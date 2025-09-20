
import machine
import utime
import network
import ujson
import urequests
import ubinascii
import utime
import gc

# ---------------------------------
# Constants
# ---------------------------------

# Configuration files
COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"

BASE_URL_RETRY_SECONDS = 300  # 5 minutes
# Default parameters
DEFAULT_ACTOR_NAME = "tank"
DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS = 500
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_SAMPLES = 1000
DEFAULT_NUM_SAMPLE_AVERAGES = 10

# Other constants
ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27
ADC2_PIN_NUMBER = 28

# ---------------------------------
# Main class
# ---------------------------------

class TankModule3:

    def __init__(self):
        # Unique ID
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
        self.hw_uid = f"pico_{pico_unique_id}"
        # Pins
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        self.adc2 = machine.ADC(ADC2_PIN_NUMBER)
        # Load configuration files
        self.base_url_failed = False
        self.load_comms_config()
        self.load_app_config()
        # Measuring and repoting voltages
        self.prev_mv0 = -1
        self.prev_mv1 = -1
        self.prev_mv2 = -1
        self.mv0 = None
        self.mv1 = None
        self.mv2 = None
        self.node_names = []
        self.microvolts_posted_time = utime.time()
        # Synchronous reporting on the minute
        self.capture_offset_seconds = 0
        self.sync_report_timer = machine.Timer(-1)

    def set_names(self):
        if self.actor_node_name is None:
            raise Exception("Needs actor node name or pico number to run. Reboot!")
        self.node_names = [
            f"{self.actor_node_name}-depth1", 
            f"{self.actor_node_name}-depth2",
            f"{self.actor_node_name}-depth3"
        ]

    # ---------------------------------
    # Communication
    # ---------------------------------
                                                                 
    def connect_to_wifi(self):
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            print("Connecting to wifi...")
            wlan.connect(self.wifi_name, self.wifi_password)
            while not wlan.isconnected():
                utime.sleep_ms(500)
        print(f"Connected to wifi {self.wifi_name}")

    def connect_to_ethernet(self):
        nic = network.WIZNET5K()
        for attempt in range(3):
            try:
                nic.active(True)
                break
            except Exception as e:
                print(f"Retrying NIC activation due to: {e}")
                utime.sleep(0.5)
        if not nic.isconnected():
            print("Connecting to Ethernet...")
            nic.ifconfig('dhcp')
            timeout = 10
            start = utime.time()
            while not nic.isconnected():
                if utime.time() - start > timeout:
                    raise RuntimeError("Failed to connect to Ethernet (timeout)")
                utime.sleep(0.5)
        print("Connected to Ethernet")

    def post_with_fallback(self, endpoint, payload):
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)

        # Check if it's time to retry base_url
        if self.base_url_failed:
            time_since_last_retry = utime.time() - self.last_base_url_retry
            if time_since_last_retry > BASE_URL_RETRY_SECONDS:
                self.last_base_url_retry = utime.time()
                # Quick test of base_url
                if self._test_url(self.base_url):
                    self.base_url_failed = False

        url = self.backup_url if self.base_url_failed else self.base_url

        try:
            response = urequests.post(url+endpoint, data=json_payload, headers=headers, timeout=5)
            if response.status_code == 200:
                return response
            response.close()
        except Exception as e:
            if url == self.base_url:
                if not self._test_url(self.base_url):
                    self.base_url_failed = True
                    self.last_base_url_retry = utime.time()
                    try:
                        self.send_baseurl_failure_alert()
                    except Exception:
                        pass
                print(f"{url} not reachable!")
                if self.backup_url:
                    try:
                        return  urequests.post(self.backup_url+endpoint, data=json_payload, headers=headers, timeout=5)
                    except Exception:
                        return None

        return None

    def send_baseurl_failure_alert(self, message):
        alert_payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "BaseUrl": self.base_url,
            "Message": message,
            "TypeName": "baseurl.failure.alert",
            "Version": "100"
        }

        if self.backup_url:
            try:
                url = self.backup_url + f"/{self.actor_node_name}/baseurl-failure-alert"
                headers = {'Content-Type': 'application/json'}
                response = urequests.post(url, data=ujson.dumps(alert_payload), headers=headers, timeout=3)
                response.close()
            except:
                pass

    def update_code(self):
        endpoint = f"/{self.actor_node_name}/code-update"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "TypeName": "new.code",
            "Version": "100"
        }
        response = self.post_with_fallback(endpoint, payload)
        if response and response.status_code == 200:
            try:
                ujson.loads(response.content.decode('utf-8'))
            except:
                python_code = response.content
                with open('main_update.py', 'wb') as file:
                    file.write(python_code)
                machine.reset()

    def load_comms_config(self):
        try:
            with open(COMMS_CONFIG_FILE, "r") as f:
                comms_config = ujson.load(f)
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Error loading comms_config file: {e}")
        self.wifi_or_ethernet = comms_config.get("WifiOrEthernet", 'wifi')
        self.wifi_name = comms_config.get("WifiName", None)
        self.wifi_password = comms_config.get("WifiPassword", None)
        self.base_url = comms_config.get("BaseUrl", None)
        self.backup_url = comms_config.get("BackupUrl", None)
        if self.wifi_or_ethernet=='wifi':
            if self.wifi_name is None:
                raise KeyError("WifiName not found in comms_config.json")
            if self.wifi_password is None:
                raise KeyError("WifiPassword not found in comms_config.json")
        elif self.wifi_or_ethernet=='ethernet':
            pass
        else:
            raise KeyError("WifiOrEthernet must exost amd be either 'wifi' or 'ethernet' in comms_config.json")
        if self.base_url is None:
            raise KeyError("BaseUrl not found in comms_config.json")

    def _test_url(self, url):
        #Test if a URL is reachable#
        try:
            test = url + "/ping"
            response = urequests.get(test, timeout=3)
            success = response.status_code == 200
            response.close()
            return success
        except:
            return False

    def update_comms_config(self):
        endpoint = f"/{self.actor_node_name}/pico-comms-params"
        payload = {
            "HwUid": self.hw_uid,
            "BaseUrl": self.base_url,
            "BackupUrl": self.backup_url,
            "TypeName": "pico.comms.params",
            "Version": "000"
        }
        response = None
        try:
            response = self.post_with_fallback(endpoint, payload)
            print(f"response in update_comms_config is {response}")
            if response and response.status_code == 200:
                new_config = response.json()
                 #Track if we made changes
                config_changed = False
                # Only update if the new URLs actually work
                new_base = new_config.get("BaseUrl", self.base_url)
                if new_base != self.base_url and self._test_url(new_base):
                    self.base_url = new_base
                    config_changed = True

                # Only update BackupUrl if different and working
                new_backup = new_config.get("BackupUrl", self.backup_url)
                if new_backup != self.backup_url and self._test_url(new_backup):
                    old_backup = self.backup_url
                    self.backup_url = new_backup
                    config_changed = True

                if config_changed:
                    self.save_comms_config()

        except Exception as e:
            print(f"Config update error: {e}")
        finally:
            if response and response.status_code == 200:
                response.close()

    def save_comms_config(self):
        config = {
            "WifiOrEthernet": self.wifi_or_ethernet,
            "BaseUrl": self.base_url,
            "BackupUrl": self.backup_url,
            "TypeName": "pico.comms.config",
            "Version": "000"
        }
        if self.wifi_or_ethernet == "wifi":
            config["WifiName"] = self.wifi_name
            config["WifiPassword"] = self.wifi_password

        with open(COMMS_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)


    # ---------------------------------
    # Parameters
    # ---------------------------------
    
    def load_app_config(self):
        '''
        Set parameters to their value in the app_config file if it is specified
        Otherwise set them to their default value
        '''
        try:
            with open(APP_CONFIG_FILE, "r") as f:
                app_config = ujson.load(f)
        except:
            app_config = {}
        self.actor_node_name = app_config.get("ActorNodeName", DEFAULT_ACTOR_NAME)
        self.async_capture_delta_micro_volts = app_config.get("AsyncCaptureDeltaMicroVolts", DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS)
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        self.samples = app_config.get("Samples", DEFAULT_SAMPLES)
        self.num_sample_averages = app_config.get("NumSampleAverages", DEFAULT_NUM_SAMPLE_AVERAGES)

    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "CapturePeriodS": self.capture_period_s,
            "Samples": self.samples,
            "NumSampleAverages":self.num_sample_averages,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        endpoint = f"/{self.actor_node_name}/tank-module-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "CapturePeriodS": self.capture_period_s,
            "Samples": self.samples,
            "NumSampleAverages": self.num_sample_averages,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
            "TypeName": "tank.module.params",
            "Version": "110"
        }
        response = self.post_with_fallback(endpoint, payload)
        if response and response.status_code == 200:
            updated_config = response.json()
            self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
            self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)
            self.samples = updated_config.get("Samples", self.samples)
            self.num_sample_averages = updated_config.get("NumSampleAverages", self.num_sample_averages)
            self.async_capture_delta_micro_volts = updated_config.get("AsyncCaptureDeltaMicroVolts", self.async_capture_delta_micro_volts)
            self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
            self.save_app_config()

    # ---------------------------------
    # Measuring microvolts
    # ---------------------------------

    def adc0_micros(self):
        sample_averages = []
        for _ in range(self.num_sample_averages):
            readings = []
            for _ in range(self.samples):
                # Read the raw ADC value (0-65535)
                readings.append(self.adc0.read_u16())
            voltages = list(map(lambda x: x * 3.3 / 65535, readings))
            mean_1000 = int(10**6 * sum(voltages) / self.samples)
            sample_averages.append(mean_1000)
        return int(sum(sample_averages)/self.num_sample_averages)
    
    def adc1_micros(self):
        sample_averages = []
        for _ in range(self.num_sample_averages):
            readings = []
            for _ in range(self.samples):
                # Read the raw ADC value (0-65535)
                readings.append(self.adc1.read_u16())
            voltages = list(map(lambda x: x * 3.3 / 65535, readings))
            mean_1000 = int(10**6 * sum(voltages) / self.samples)
            sample_averages.append(mean_1000)
        return int(sum(sample_averages)/self.num_sample_averages)
    
    def adc2_micros(self):
        sample_averages = []
        for _ in range(self.num_sample_averages):
            readings = []
            for _ in range(self.samples):
                # Read the raw ADC value (0-65535)
                readings.append(self.adc2.read_u16())
            voltages = list(map(lambda x: x * 3.3 / 65535, readings))
            mean_1000 = int(10**6 * sum(voltages) / self.samples)
            sample_averages.append(mean_1000)
        return int(sum(sample_averages)/self.num_sample_averages)  
    
    # ---------------------------------
    # Posting microvolts
    # ---------------------------------

    def post_microvolts(self, idx=3):
        endpoint = f"/{self.actor_node_name}/microvolts"
        if idx==0:
            mv_list = [self.mv0]
        elif idx==1:
            mv_list = [self.mv1]
        elif idx==2:
            mv_list = [self.mv2]
        else:
            mv_list = [self.mv0, self.mv1, self.mv2]
        payload = {
            "HwUid": self.hw_uid,
            "AboutNodeNameList": [self.node_names[idx]] if idx<=2 else self.node_names,
            "MicroVoltsList": mv_list, 
            "TypeName": "microvolts", 
            "Version": "100"
        }

        try:
            response = self.post_with_fallback(endpoint, payload)
        except Exception as e:
            print(f"Error posting microvolts: {e}")

        gc.collect()
        self.microvolts_posted_time = utime.time()
        
    def sync_report(self, timer):
        self.post_microvolts()

    def start_sync_report_timer(self):
        '''Initialize the timer to call self.keep_alive periodically'''
        self.sync_report_timer.init(
            period=self.capture_period_s * 1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.sync_report
        )

    def main_loop(self):
        self.mv0 = self.adc0_micros()
        self.mv1 = self.adc1_micros()
        self.mv2 = self.adc2_micros()
        while True:
            self.mv0 = self.adc0_micros()
            self.mv1 = self.adc1_micros()
            self.mv2 = self.adc2_micros()
            if abs(self.mv0 - self.prev_mv0) > self.async_capture_delta_micro_volts:
                self.post_microvolts(idx=0)
                self.prev_mv0 = self.mv0
            if abs(self.mv1 - self.prev_mv1) > self.async_capture_delta_micro_volts:
                self.post_microvolts(idx=1)
                self.prev_mv1 = self.mv1
            if abs(self.mv2 - self.prev_mv2) > self.async_capture_delta_micro_volts:
                self.post_microvolts(idx=2)
                self.prev_mv2 = self.mv2
            utime.sleep_ms(100)

    def start(self):
        if self.wifi_or_ethernet=='wifi':
            self.connect_to_wifi()
        elif self.wifi_or_ethernet=='ethernet':
            self.connect_to_ethernet()

        # Update configurations
        self.update_comms_config()
        self.update_app_config()
        self.update_code()

        self.set_names()
        self.mv0 = self.adc0_micros()
        self.mv1 = self.adc1_micros()
        self.mv2 = self.adc2_micros()
        self.post_microvolts()
        utime.sleep(self.capture_offset_seconds)
        self.start_sync_report_timer()
        self.main_loop()

if __name__ == "__main__":
    t = TankModule3()
    t.start()
    
