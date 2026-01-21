import machine
import ujson
import network
import utime
import urequests
import ubinascii
import os

PRIMARY_SCADA_IP = "192.168.2.200"

# Remove existing files
if 'boot.py' in os.listdir():
    os.remove('boot.py')
if 'app_config.json' in os.listdir():
    os.remove('app_config.json')
if 'comms_config.json' in os.listdir():
    os.remove('comms_config.json')
if 'main.py' in os.listdir():
    os.remove('main.py')
if 'main_previous.py' in os.listdir():
    os.remove('main_previous.py')

# *************************
# 1/3 - MAIN.PY PROVISION
# *************************

def write_tank_module_3_main():
    main_code = """

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
                                                                 
    def load_comms_config(self):
        '''Load the communication configuration file (WiFi/Ethernet and API base URL)'''
        try:
            with open(COMMS_CONFIG_FILE, "r") as f:
                comms_config = ujson.load(f)
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Error loading comms_config file: {e}")
        self.wifi_or_ethernet = comms_config.get("WifiOrEthernet", 'wifi')
        self.wifi_name = comms_config.get("WifiName", None)
        self.wifi_password = comms_config.get("WifiPassword", None)
        self.base_url = comms_config.get("BaseUrl")
        if self.wifi_or_ethernet=='wifi':
            if self.wifi_name is None:
                raise KeyError("WifiName not found in comms_config.json")
            if self.wifi_password is None:
                raise KeyError("WifiPassword not found in comms_config.json")
        elif self.wifi_or_ethernet=='ethernet':
            pass
        else:
            raise KeyError("WifiOrEthernet must be either 'wifi' or 'ethernet' in comms_config.json")
        if self.base_url is None:
            raise KeyError("BaseUrl not found in comms_config.json")
        
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
        url = self.base_url + f"/{self.actor_node_name}/tank-module-params"
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
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)
                self.samples = updated_config.get("Samples", self.samples)
                self.num_sample_averages = updated_config.get("NumSampleAverages", self.num_sample_averages)
                self.async_capture_delta_micro_volts = updated_config.get("AsyncCaptureDeltaMicroVolts", self.async_capture_delta_micro_volts)
                self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error sending tank module params: {e}")

    # ---------------------------------
    # Code updates
    # ---------------------------------

    def update_code(self):
        url = self.base_url + f"/{self.actor_node_name}/code-update"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "TypeName": "new.code",
            "Version": "100"
        }
        json_payload = ujson.dumps(payload)
        headers = {"Content-Type": "application/json"}
        response = urequests.post(url, data=json_payload, headers=headers)
        if response.status_code == 200:
            # If there is a pending code update then the response is a python file, otherwise json
            try:
                ujson.loads(response.content.decode('utf-8'))
            except:
                python_code = response.content
                with open('main_update.py', 'wb') as file:
                    file.write(python_code)
                machine.reset()

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
        url = self.base_url + f"/{self.actor_node_name}/microvolts"
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
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
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
        self.update_code()
        self.update_app_config()
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
    

    """
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_btu_meter_main():
    main_code = """
import machine
import utime
import math
import network
import ujson
import urequests
import ubinascii


COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"
DEFAULT_ACTOR_NAME = "primary-btu"

BASE_URL_RETRY_SECONDS = 300  # 5 minutes
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_GALLONS_PER_PULSE = 0.0009
DEFAULT_ASYNC_CAPTURE_DELTA_GPM_X_100 = 10
DEFAULT_ASYNC_CAPTURE_DELTA_CELSIUS_X_100 = 20
DEFAULT_ASYNC_CAPTURE_DELTA_CT_VOLTS_X_100 = 20
DEFAULT_THERMISTOR_BETA = 3977
SAMPLES = 1000
NUM_SAMPLE_AVERAGES = 1

class AsyncBtuMeter:
    # BTU meter with coordinated measure of flow, temp and pump power.
    # Designed for async reporting on change for all 3 and also
    # synchronous reporting happening at a default of 60 seconds

    # Flow meter expected range: 15-150 Hz (67ms - 6.7ms periods)
    # Jitter threshold: > 400 Hz (< 2.5ms period) indicates physical bounce
    #
    # self.read_ct is True iff CtNodeName is not None

    PULSE_PIN = 21
    ADC0_PIN = 26 # Hot Temp
    ADC1_PIN = 27 # Cold Temp
    ADC2_PIN = 28 # Current Transformer

    FLOW_TIMEOUT_MS = 100

    R_FIXED_KOHMS = 5.6
    THERMISTOR_R0_KOHMS = 10
    THERMISTOR_T0 = 298

    def __init__(self):
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
        self.hw_uid = f"pico_{pico_unique_id}"
        self.load_comms_config()
        self.use_ip_failed = False
        self.last_base_url_retry = utime.time()
        self.load_app_config()

        # Hardware setup
        self.pulse_pin = machine.Pin(self.PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self.adc_hot = machine.ADC(self.ADC0_PIN)
        self.adc_cold = machine.ADC(self.ADC1_PIN)
        self.adc_ct = machine.ADC(self.ADC2_PIN)

        # Flow measurement state
        self._tick_count = 0 # Only modified by pulse_callback (ISR)
        
        self.ready_for_new_measurement = True
        self.last_tick_ms = utime.ticks_ms()
        self.measurement_start_ms = None  # this signals no flow
        self.completed_elapsed_ms = None
        self.completed_tick_count = 0

        self.flow_data_ready = False # set True by pulse_callback, False by flow_timer 

        # Measurements

        self.gpm = None
        self.hz = None
        self.hot = None
        self.cold = None
        self.pump_ct_voltage = None

        # Initialize last_sent values to force first send
        self.last_sent_gpm = -999
        self.last_sent_hot = -999
        self.last_sent_cold = -999
        self.last_sent_pump_ct_voltage = -999

        #Timers
        self.last_sync_report_s = 0
        self.capture_offset_seconds = 0 
        self.temp_timer = machine.Timer(-1)
        self.flow_timer = machine.Timer(-1)

        # main loop variables
        self.last_flow_calc_ms = None
        self.pending_async_check = False

        # Debt tracking for disruption recovery
        self.period_us_3 = None
        self.period_us_2 = None
        self.period_us_1 = None
        self.period_us_0 = None
        self.disruption_recovery = 0
        self.double_debt_us = 0
        self.avg_double = 20000
        self.last_pulse_us = None
        self.toss_measurement = False
                                                                 
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
        # POST to SCADA with IP/DNS fallback.
        # Tries IP twice with short timeout, then falls back to DNS if needed.

        # Returns:
        #      - Response object if successful (200 status)
        #      - None if endpoint doesn't exist (404) or other non-critical failure
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        
        # Check if it's time to retry IP address
        if self.use_ip_failed:
            time_since_last_retry = utime.time() - self.last_ip_retry
            if time_since_last_retry > BASE_URL_RETRY_SECONDS:
                print(f"Retrying IP address after {time_since_last_retry}s")
                self.last_ip_retry = utime.time()
                # Quick test of IP connectivity
                if self._test_url(self.ip_url):
                    print("IP address is back online")
                    self.use_ip_failed = False
        
        # Select URL: use DNS if IP has failed, otherwise use IP
        url = self.dns_url if self.use_ip_failed else self.ip_url

        max_attempts = 2 if url == self.ip_url else 1

        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    print(f"Retry {attempt} for {url}")

                response = urequests.post(url+endpoint, data=json_payload, headers=headers, timeout=3)
                if response.status_code == 200:
                    return response
                elif response.status_code == 404:
                    # Server is reachable but endpoint doesn't exist
                    # This is NOT a connectivity failure, so don't mark IP as failed
                    print(f"Endpoint {endpoint} not found (404) - server IS reachable")
                    response.close()
                    return None
                else:
                    print(f"Status: {response.status_code}")
                    response.close()
                    if response.status_code >= 500 and attempt < max_attempts - 1:
                        continue  # Retry on server errors
                    return None
                
            except Exception as e:
                print(f"Attempt {attempt+1} failed: {e}")

                if attempt < max_attempts - 1:
                    utime.sleep_ms(50)  # Brief pause before retry
                    continue

                # Only handle failover if we were using IP address
                if url == self.ip_url:
                    # Test if IP is truly unreachable (not just this endpoint)
                    if not self._test_url(self.ip_url):
                        msg = f"switching to DNS {self.dns_url}"
                        print(msg)
                        self.use_ip_failed = True
                        self.last_ip_retry = utime.time()

                        # Send alert about IP failure
                        try:
                            self.send_baseurl_failure_alert(msg)
                        except Exception:
                            pass

                        # Try DNS URL as fallback
                        if self.dns_url:
                            print(f"Trying DNS fallback {self.dns_url}")
                            try:
                                response = urequests.post(self.dns_url+endpoint,
                                                        data=json_payload,
                                                        headers=headers,
                                                        timeout=5)
                                print(f"DNS responded with status: {response.status_code}")

                                if response.status_code == 200:
                                    print("DNS fallback successful")
                                    return response
                                elif response.status_code == 404:
                                    print(f"Endpoint {endpoint} not found via DNS (404)")
                                    response.close()
                                    return None
                                else:
                                    print(f"DNS returned status: {response.status_code}")
                                    response.close()
                                    return None

                            except Exception as dns_e:
                                print(f"DNS also failed: {dns_e}")
                                return None
                    else:
                        # IP is reachable but this specific request failed
                        # Could be timeout, connection reset, etc.
                        print(f"IP is reachable but request failed: {e}")
                        return None
                else:
                    # We were already using DNS and it failed
                    print(f"DNS request failed: {e}")
                    return None

            # Shouldn't get here, but just in case
            return None

    def send_baseurl_failure_alert(self, message):
        alert_payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "BaseUrl": self.ip_url,
            "Message": message,
            "TypeName": "baseurl.failure.alert",
            "Version": "100"
        }

        if self.dns_url:
            try:
                url = self.dns_url + f"/{self.actor_node_name}/baseurl-failure-alert"
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
        if response:
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
        self.ip_url = comms_config.get("BaseUrl", None)
        self.dns_url = comms_config.get("BackupUrl", None)
        print(f"After loading - ip_url: {self.ip_url}, dns_url: {self.dns_url}")
        if self.wifi_or_ethernet=='wifi':
            if self.wifi_name is None:
                raise KeyError("WifiName not found in comms_config.json")
            if self.wifi_password is None:
                raise KeyError("WifiPassword not found in comms_config.json")
        elif self.wifi_or_ethernet=='ethernet':
            pass
        else:
            raise KeyError("WifiOrEthernet must exost amd be either 'wifi' or 'ethernet' in comms_config.json")
        if self.ip_url is None:
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
            "BaseUrl": self.ip_url,
            "BackupUrl": self.dns_url,
            "TypeName": "pico.comms.params",
            "Version": "000"
        }
        try:
            response = self.post_with_fallback(endpoint, payload)
            if response and response.status_code == 200:
                new_config = response.json()
                 #Track if we made changes
                config_changed = False
                # Only update if the new URLs actually work
                new_base = new_config.get("BaseUrl", self.ip_url)
                if new_base != self.ip_url and self._test_url(new_base):
                    self.ip_url = new_base
                    config_changed = True

                # Only update BackupUrl if different and working  
                new_backup = new_config.get("BackupUrl", self.dns_url)
                if new_backup != self.dns_url and self._test_url(new_backup):
                    self.dns_url = new_backup
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
            "BaseUrl": self.ip_url,
            "BackupUrl": self.dns_url,
            "TypeName": "pico.comms.config",
            "Version": "000"
        }
        if self.wifi_or_ethernet == "wifi":
            config["WifiName"] = self.wifi_name
            config["WifiPassword"] = self.wifi_password

        with open(COMMS_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)

    def load_app_config(self):
        #Load the app config file. If PumpPowerName is None, do not read power
        try:
            with open(APP_CONFIG_FILE, "r") as f:
                app_config = ujson.load(f)
        except:
            app_config = {}
        self.actor_node_name = app_config.get("ActorNodeName", DEFAULT_ACTOR_NAME)
        prefix = self.actor_node_name.replace("-btu", "")
        self.flow_channel_name = app_config.get("FlowChannelName", f"{prefix}-flow")
        self.hot_channel_name = app_config.get("HotChannelName", f"{prefix}-hot-temp")
        self.cold_channel_name = app_config.get("ColdChannelName", f"{prefix}-cold-temp")
        self.ct_channel_name = app_config.get("CtChannelName", None)

        self.send_hz = app_config.get("SendHz", False)
        self.read_ct_voltage = self.ct_channel_name is not None
        self.thermistor_beta = app_config.get("ThermistorBeta", DEFAULT_THERMISTOR_BETA)
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        self.gallons_per_pulse = app_config.get("GallonsPerPulse", DEFAULT_GALLONS_PER_PULSE)
        self.async_capture_delta_gpm_x_100 = app_config.get("AsyncCaptureDeltaGpmX100", DEFAULT_ASYNC_CAPTURE_DELTA_GPM_X_100)
        self.async_capture_delta_celsius_x_100 = app_config.get("AsyncCaptureDeltaCelsiusX100", DEFAULT_ASYNC_CAPTURE_DELTA_CELSIUS_X_100)
        self.async_capture_delta_ct_volts_x_100 = app_config.get("AsyncCaptureDeltaCtVoltsX100",DEFAULT_ASYNC_CAPTURE_DELTA_CT_VOLTS_X_100)

    def save_app_config(self):

        config = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "FlowChannelName": self.flow_channel_name,
            "SendHz": self.send_hz,
            "ReadCtVoltage": self.read_ct_voltage,
            "HotChannelName": self.hot_channel_name,
            "ColdChannelName": self.cold_channel_name,
            "CtChannelName": self.ct_channel_name,
            "ThermistorBeta": self.thermistor_beta,
            "CapturePeriodS": self.capture_period_s,
            "GallonsPerPulse": self.gallons_per_pulse,
            "AsyncCaptureDeltaGpmX100": self.async_capture_delta_gpm_x_100,
            "AsyncCaptureDeltaCelsiusX100": self.async_capture_delta_celsius_x_100,
            "AsyncCaptureDeltaCtVoltsX100": self.async_capture_delta_ct_volts_x_100,
            "TypeName": "async.btu.params",
            "Version": "000"
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        endpoint = f"/{self.actor_node_name}/async-btu-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "FlowChannelName": self.flow_channel_name,
            "SendHz": self.send_hz,
            "ReadCtVoltage": self.read_ct_voltage,
            "HotChannelName": self.hot_channel_name,
            "ColdChannelName": self.cold_channel_name,
            "CtChannelName": self.ct_channel_name,
            "ThermistorBeta": self.thermistor_beta,
            "CapturePeriodS": self.capture_period_s,
            "GallonsPerPulse": self.gallons_per_pulse,
            "AsyncCaptureDeltaGpmX100": self.async_capture_delta_gpm_x_100,
            "AsyncCaptureDeltaCelsiusX100": self.async_capture_delta_celsius_x_100,
            "AsyncCaptureDeltaCtVoltsX100": self.async_capture_delta_ct_volts_x_100,
            "TypeName": "async.btu.params",
            "Version": "000"
        }
        response = self.post_with_fallback(endpoint, payload)
        if response:
            try:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.hot_channel_name = updated_config.get("HotChannelName", self.hot_channel_name)
                self.cold_channel_name = updated_config.get("ColdChannelName", self.cold_channel_name)
                self.flow_channel_name = updated_config.get("FlowChannelName", self.flow_channel_name)
                self.send_hz = updated_config.get("SendHz", self.send_hz)
                self.read_ct_voltage = updated_config.get("ReadCtVoltage", self.read_ct_voltage)
                # None will signal not reading power
                self.ct_channel_name = updated_config.get("CtChannelName")
                
                self.read_ct_voltage = self.ct_channel_name is not None
                self.thermistor_beta = updated_config.get("ThermistorBeta", self.thermistor_beta)
                if self.thermistor_beta is None:
                    self.thermistor_beta = DEFAULT_THERMISTOR_BETA
                self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
                if self.capture_offset_seconds is None:
                    self.capture_offset_seconds = 0
                self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)

                self.gallons_per_pulse = updated_config.get("GallonsPerPulse", self.gallons_per_pulse)
                self.async_capture_delta_gpm_x_100 = updated_config.get("AsyncCaptureDeltaGpmX100", self.async_capture_delta_gpm_x_100)

                self.async_capture_delta_celsius_x_100 = updated_config.get("AsyncCaptureDeltaCelsiusX100", self.async_capture_delta_celsius_x_100)

                self.async_capture_delta_ct_volts_x_100 = updated_config.get("AsyncCaptureDeltaCtVoltsX100", self.async_capture_delta_ct_volts_x_100)
                self.save_app_config()
            except:
                pass
            finally:
                response.close()

    def celsius_from_volts(self, volts):
        #  Uses Beta formula with THERMISTOR_BETA of 3977
        # TODO: consider adding thermistor_beta to app_config?
        if volts <= 0.001 or volts >= 3.299:
            return None
        # Use Beta Formula
        r_therm = 1 / ((3.3 / volts - 1) / self.R_FIXED_KOHMS)
        thermistor_beta = self.thermistor_beta
        if thermistor_beta is None or thermistor_beta == 0:
            thermistor_beta = DEFAULT_THERMISTOR_BETA
        return 1 / ((1 / self.THERMISTOR_T0) + (math.log(r_therm / self.THERMISTOR_R0_KOHMS) / thermistor_beta)) - 273

    def measure_temp(self, adc_channel, n_samples=100):
        # Measure voltage in microvolts (for temp) Takes ~1.7ms for 100 samples.
        try:
            reading_sum = 0
            for _ in range(n_samples):
                reading_sum += adc_channel.read_u16()
            avg_reading = reading_sum / n_samples
            avg_voltage =  avg_reading * 3.3 / 65535
            return self.celsius_from_volts(avg_voltage)
        except Exception as e:
            print(f"Temp measurement failed: {e}")
            return None

    def measure_ct_voltage(self):
        #Sample the current transformer (CT) ADC channel.
        #
        #Collects 200 successive ADC readings as quickly as possible,
        #timestamping each sample. A typical loop iteration takes ~95 µs
        #without explicit delays, so 200 samples span ~19 ms. This
        #comfortably covers at least one full 60 Hz AC cycle
        #(period ≈ 16.7 ms).

        # Notes:
        #    - At 60 Hz, 200 samples correspond to ~83 µs/sample if perfectly
        #    distributed; in practice this function achieves ~95 µs/sample.
        #    - The function reduces the collected data to just the peak ADC
        #    value and its first timestamp.
        if not self.read_ct_voltage:
            return
        try:
            readings = []
            while len(readings) < 200:
                readings.append(self.adc_ct.read_u16())
            
            max_reading = max(readings)
            max_voltage = (max_reading * 3.3 / 65535)
            return max_voltage
        except Exception as e:
            print(f"CT measurement failed: {e}")
            return None

    def pulse_callback(self, pin):
        # Flow pulse interrupt handler. Implements debt tracking to handle
        # timing disruptions where pulses queue up during CPU-intensive operations.
        #
        # Debt mechanism: When a disruption causes a LONG period followed by
        # SHORT catch-up pulses, we track the "debt" (missed time) and adjust
        # the final measurement accordingly.
        #
        # Also we delay the start if there is active debt
        now_ms = utime.ticks_ms()
        now_us = utime.ticks_us()

        # Update period history
        if not self.last_pulse_us:
            self.last_pulse_us = now_us
        else:
            # Shift history
            self.period_us_3 = self.period_us_2
            self.period_us_2 = self.period_us_1
            self.period_us_1 = self.period_us_0
            self.period_us_0 = now_us - self.last_pulse_us

            self.last_pulse_us = now_us
            if self.toss_measurement:
                return

            # Handle jitter and/or the LONG/SHORT/SHORT..
            if (self.double_debt_us == 0 and 
                self.period_us_1 and self.period_us_2 and self.period_us_3):

                if self.disruption_recovery > 0:
                    self.disruption_recovery -= 1

                else:
                    # Average (times 2 to avoid float)
                    avg_double = self.period_us_3 + self.period_us_2

                    # Check if current period is SHORT (>1ms shorter than expected)
                    if avg_double - 2 * self.period_us_0 > 2000:
                        # print(f"SHORT TICK: {self.period_us_0}, tick count {self._tick_count}")
                        debt_floor_double = avg_double - 2 * self.period_us_0

                        # Check if previous period was LONG enough to create multi-tick debt
                        if 2 * self.period_us_1 > avg_double + debt_floor_double + 500:
                            # Multi-tick debt detected
                            double_debt_us = 2 * self.period_us_1 - avg_double
                            self.avg_double = avg_double
                            self.disruption_recovery = 2 # Skip next 2 pattern checks 

                            # Bail if 4 catch-up ticks at ~1000us each can recover: 4*avg_double - 8000
                            max_recoverable = min(4 * avg_double - 8000, 800_000)
                            if double_debt_us > max_recoverable:
                                self.toss_measurement = True
                                self.double_debt_us = 0
                            else:
                                # set ready_for_new_measurement flag to trigger a reset
                                # IF _tick_count happens to be 0. This is so that the LONG
                                # is included along with the shorts....
                                self.double_debt_us = double_debt_us
                                if self._tick_count == 0:
                                    # print(f"RESET - should trigger new tick 0 after debt clears")
                                    self.flow_data_ready = False
                                    self.ready_for_new_measurement = True

                        # "bookend" debt detected - clears immediately
                        elif 2 * self.period_us_1 > avg_double + 500:
                            self.disruption_recovery = 1
                            # ... unless the long tick happened before 0
                            if self._tick_count == 0:
                                self.flow_data_ready = False
                                self.ready_for_new_measurement = True

                        elif self.period_us_0 < 2500: # < 2.5ms = > 400 Hz
                            # JITTER! Physical switch bounce/oscillation - don't count it
                            # print(f"JITTER detected: {self.period_us_0} us with no preceding long")
                            return

            elif self.double_debt_us > 0:
                # paying off debt
                # print("PAYING OFF DEBT")
                payoff = self.avg_double - 2 * self.period_us_0
                if payoff > 1000:
                    new_debt = self.double_debt_us - payoff
                    if new_debt < 1000:
                        self.double_debt_us = 0
                    else:
                        self.double_debt_us = new_debt
                else:
                    if self.double_debt_us > 1000:
                        self.toss_measurement = True
                        self.double_debt_us = 0
                        return
                    else:
                        self.double_debt_us = 0
                        self.avg_double = None

        # Handle start of a new measurement period
        if self.ready_for_new_measurement:
            if self.double_debt_us > 0: # still working off debt ... delay
                return

            # Start measurement cycle debt-free
            self.measurement_start_ms = now_ms
            self._tick_count = 0
            self.ready_for_new_measurement = False
            return

        # Normal case!
        if self.measurement_start_ms is not None:
            self._tick_count += 1
            elapsed_ms = now_ms - self.measurement_start_ms

            # Don't overwrite if not processed yet
            if elapsed_ms >= 800 and not self.flow_data_ready:

                self.completed_tick_count = self._tick_count
                self.completed_elapsed_ms = elapsed_ms
                self.flow_data_ready = True

    def adjust_for_debt(self):
        if self.avg_double is None or self.avg_double == 0:
            return
        if self.double_debt_us > 0:
            # Calculate how many ticks were compressed into catch-up bursts
            debt_ticks = int( (self.double_debt_us // self.avg_double) + 0.5) # round
            adjusted_tick_count = self.completed_tick_count + debt_ticks
            adjusted_elapsed_ms = self.completed_elapsed_ms + (self.double_debt_us // 2000)

            self.completed_tick_count = adjusted_tick_count
            self.completed_elapsed_ms = adjusted_elapsed_ms

            # Clear debt since we've accounted for it
            self.double_debt_us = 0

    def calculate_flow(self):
        # Calculate gpm, unless self.send_hz in which case calculate hz
        if self.completed_elapsed_ms is None or self.completed_elapsed_ms == 0:
            return

        elapsed_s = self.completed_elapsed_ms / 1000.0
        self.hz = self.completed_tick_count / elapsed_s

        gallons = self.completed_tick_count * self.gallons_per_pulse
        minutes = elapsed_s / 60.0
        self.gpm = gallons / minutes if minutes > 0 else 0.0


    def measure_temps_and_ct(self, timer):
        # Timer callback: Runs at t=850ms, 1850ms, 2850ms...
        # Intentionally offset from flow measurement window (0-800ms)
        # to avoid interference with pulse counting
        #
        # blocks for 3.5 ms, 3.5 ms, then 20 ms

        # print(f"Measuring temps and CT at tick {self._tick_count}")
        self.hot = self.measure_temp(self.adc_hot) # ~3.5 ms
        self.cold = self.measure_temp(self.adc_cold) # ~ 3.5 ms

        if self.read_ct_voltage:
            self.pump_ct_voltage = self.measure_ct_voltage() # ~ 20 ms

    def reset_flow_measurement(self):
        # resets all flow measurement state for next cycle
        self.flow_data_ready = False
        self.measurement_start_ms = None
        self.ready_for_new_measurement = True
        # Let main loop know its time send an async report ...
        self.pending_async_check = True
        self.disruption_recovery = 0

    def manage_flow(self, timer):

        if self.toss_measurement:
            print("Tossing corrupted measurement")
            self.toss_measurement = False
            # NOT updating gpm with corrupted measurement
            self.reset_flow_measurement()
            return

        # No ticks this last second <-> measurement_start_ms is None
        if self.measurement_start_ms is None:
            self.gpm = 0
            if self.send_hz:
                self.hz = 0
            self.completed_tick_count = 0
            self.completed_elapsed_ms = 1000
            self.reset_flow_measurement()
            return

        # active measurement, but haven't gotten all our ticks
        if not self.flow_data_ready:
            self.completed_tick_count = self._tick_count
            self.completed_elapsed_ms = utime.ticks_ms() - self.measurement_start_ms

        # Calculate gpm (either from ISR data or from what we captured above)
        self.adjust_for_debt()
        self.calculate_flow()

        # ready for new measurement
        self.reset_flow_measurement()

    def report(self):
        now_s = utime.time()
        time_since_sync = now_s  - self.last_sync_report_s
        send_sync = time_since_sync >= self.capture_period_s

        flow_val = self.gpm
        flow_unit = "GpmTimes100"
        if self.send_hz:
            flow_val = self.hz
            flow_unit = "HzTimes100"
        if send_sync:
            if flow_val is not None and self.hot is not None and self.cold is not None:

                about_nodes = [self.flow_channel_name, self.hot_channel_name, self.cold_channel_name]
                measurements = [
                    round(flow_val * 100),
                    round(self.hot * 100),
                    round(self.cold * 100),
                ]
                units = [flow_unit, "CelsiusTimes100", "CelsiusTimes100"]
                
                if self.read_ct_voltage and self.pump_ct_voltage is not None:
                    about_nodes.append(self.ct_channel_name)
                    measurements.append(round(self.pump_ct_voltage * 100))
                    units.append("VoltsTimes100")
                
                self.post_btu_data(about_nodes, measurements, units)
                self.last_sync_report_s = now_s
                print(f"JUST RESET last_sync_report_s")
        else:
            about_nodes = []
            measurements = []
            units = []
            if flow_val is None or self.hot is None or self.cold is None:
                print(f"Skipping async - missing data: flow: {flow_val}{flow_unit}, hot={self.hot}, cold={self.cold}")
                return
            if 100 * abs(self.gpm - self.last_sent_gpm) > self.async_capture_delta_gpm_x_100:
                about_nodes.append(self.flow_channel_name)
                measurements.append(round(flow_val * 100))
                units.append(flow_unit)
                print(f"Flow changed: {self.last_sent_gpm:.3f} -> {self.gpm:.3f} GPM")
            
            if self.hot is not None:
                if 100 * abs(self.hot - self.last_sent_hot) > self.async_capture_delta_celsius_x_100:
                    about_nodes.append(self.hot_channel_name)
                    measurements.append(round(self.hot * 100)) # Send as centi-Celsius
                    units.append("CelsiusTimes100")
                    print(f"hot temp changed: {self.last_sent_hot:.3f} -> {self.hot:.3f} deg C")
            
            if self.cold is not None:
                if 100 * abs(self.cold - self.last_sent_cold) > self.async_capture_delta_celsius_x_100:
                    about_nodes.append(self.cold_channel_name)
                    measurements.append(round(self.cold * 100)) # Send as centi-Celsius
                    units.append("CelsiusTimes100")
                    print(f"cold temp changed: {self.last_sent_cold:.3f} -> {self.cold:.3f} deg C")
            
            if self.read_ct_voltage and self.pump_ct_voltage is not None:
                if 100 * abs(self.pump_ct_voltage - self.last_sent_pump_ct_voltage) > self.async_capture_delta_ct_volts_x_100:
                    about_nodes.append(self.ct_channel_name)
                    measurements.append(round(self.pump_ct_voltage * 100)) # Send as centi-volts
                    units.append("VoltsTimes100")

            if about_nodes:
                self.post_btu_data(about_nodes, measurements, units)

    def sync_report(self, timer):
        if self.gpm is None or self.hot is None or self.cold is None:
            return
        about_nodes = [self.flow_channel_name, self.hot_channel_name, self.cold_channel_name]
        measurements = [
            round(self.gpm * 100),  # GpmTimes100
            round(self.hot * 100),  # CelsiusTimes100
            round(self.cold * 100), # CelsiusTImes100
        ]
        units = ["GpmTimes100", "CelsiusTimes100", "CelsiusTimes100"]

        # add ct voltage if configured
        if self.read_ct_voltage and self.pump_ct_voltage is not None:
            about_nodes.append(self.ct_channel_name)
            measurements.append(round(self.pump_ct_voltage * 100))
            units.append("VoltsTimes100")

        self.post_btu_data(about_nodes, measurements, units)

    def post_btu_data(self, about_nodes, measurements, units):
        endpoint = f"/{self.actor_node_name}/multichannel-snapshot"
        payload = {
                "HwUid": self.hw_uid,
                "ChannelNameList": about_nodes,
                "MeasurementList": measurements,
                "UnitList": units,
                "TypeName": "multichannel.snapshot",
                "Version": "000"
            }
        response = self.post_with_fallback(endpoint, payload)

        if response:
            response.close()
            if self.flow_channel_name in about_nodes:
                self.last_sent_gpm = self.gpm
            if self.hot_channel_name in about_nodes:
                self.last_sent_hot = self.hot
            if self.cold_channel_name in about_nodes:
                self.last_sent_cold = self.cold
            if self.read_ct_voltage and self.ct_channel_name in about_nodes:
                self.last_sent_pump_ct_voltage = self.pump_ct_voltage
            return True

        return False

    def start_timers(self):
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)

        utime.sleep_ms(850)
        self.temp_timer.init(
            period=1000, # every second
            mode=machine.Timer.PERIODIC,
            callback=self.measure_temps_and_ct
        )

        utime.sleep_ms(150)
        self.flow_timer.init(
            period=1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.manage_flow
        )
        
    def main_loop(self):

        try:
            offset = round(self.capture_offset_seconds)
            if offset > 1:
                offset -= 1
            self.last_sync_report_s = utime.time() + offset - self.capture_period_s
        except Exception as e:
            self.last_sync_report_s = utime.time()
        while True:
            if self.pending_async_check:
                # Give pulse callback the chance to cleanly catch its first
                # timestamp. Slowest ~ 15 Hz / 67 ms
                utime.sleep_ms(100)
                print(f"{self.gpm:.2f} gpm [{self.completed_tick_count} ticks in {self.completed_elapsed_ms} ms]")
                self.report()
                self.pending_async_check = False

            utime.sleep_ms(1) 

    def start(self):
        if self.wifi_or_ethernet=='wifi':
            self.connect_to_wifi()
        elif self.wifi_or_ethernet=='ethernet':
            self.connect_to_ethernet()

        # Update configurations 
        self.update_comms_config()
        self.update_app_config()
        self.update_code()

        self.start_timers()
        self.report() 
        self.main_loop()


if __name__ == "__main__":
    b = AsyncBtuMeter()
    b.start()

    """
    with open('main.py', 'w') as file:
        file.write(main_code)


# *************************
# 2/3 - APP_CONFIG PROVISION
# *************************

# -------------------------
# Tank module
# -------------------------

def provision_tank_module():
    """Configure tank module app_config.json"""
    # Get tank name
    while True:
        tank_name = input("Tank Name: 'buffer', 'tank1', 'tank2', 'tank3': ")
        if tank_name in {'buffer', 'tank1', 'tank2', 'tank3'}:
            break
        print("Invalid tank name")

    config = {
            "ActorNodeName": tank_name,
        }

    # Save config
    with open("app_config.json", "w") as f:
        ujson.dump(config, f)

    return tank_name


# -------------------------
# BTU meter
# -------------------------

def provision_btu_meter():
    """Configure BTU meter app_config"""
    while True:
        btu_name = input("BTU Name: 'dist-btu', 'store-btu', 'primary-btu', 'sieg-btu': ")
        if btu_name in {'primary-btu', 'store-btu', 'dist-btu', 'sieg-btu'}:
            break
        print("Invalid BTU name")

    config = {
        "ActorNodeName": btu_name,
    }

    # Save config
    with open("app_config.json", "w") as f:
        ujson.dump(config, f)

    return btu_name


# *************************
# 3/3 - MAIN CODE
# *************************

if __name__ == "__main__":

    # Get hardware ID
    pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
    hw_uid = f"pico_{pico_unique_id}"
    print(f"\nThis Pico's unique hardware ID is {hw_uid}.")

    # -------------------------
    # Write boot.py
    # -------------------------

    bootpy_code = """import os

if 'main_update.py' in os.listdir():
    
    if 'main_previous.py' in os.listdir():
        os.remove('main_previous.py')

    if 'main.py' in os.listdir():
        os.rename('main.py', 'main_previous.py')

    os.rename('main_update.py', 'main.py')

elif 'main_revert.py' in os.listdir():

    if 'main.py' in os.listdir():
        os.remove('main.py')

    os.rename('main_revert.py', 'main.py')
    """

    with open('boot.py', 'w') as file:
        file.write(bootpy_code)
    print(f"Wrote 'boot.py' on the Pico.")
    
    print(f"\n{'-'*40}\n[1/4] Success! Found hardware ID and wrote 'boot.py'.\n{'-'*40}\n")

    # -------------------------
    # Write comms_config.json
    # -------------------------

    have_wifi_or_ethernet = False
    while not have_wifi_or_ethernet:
        wifi_or_ethernet = input("Does this Pico use WiFi (enter 'w') or Ethernet (enter 'e'): ")
        if wifi_or_ethernet not in {'w','e'}:
            print("Invalid entry. Please enter either 'w' or 'e'.")
        else:
            have_wifi_or_ethernet = True
    
    # Connect to wifi
    if wifi_or_ethernet == 'w':
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        wlan.disconnect()
        while wlan.isconnected():
            utime.sleep(0.1)
        
        while not wlan.isconnected():
            wifi_name = input("Enter wifi name (leave blank for 'GridWorks'): ")
            if wifi_name == "":
                wifi_name = "GridWorks"
            wifi_pass = input("Enter wifi password: ")
            time_waiting_connection = 0
            wlan.connect(wifi_name, wifi_pass)
            while not wlan.isconnected():
                if time_waiting_connection>0 and time_waiting_connection%2==0:
                    print(f"Trying to connect ({int(time_waiting_connection/2)}/5)...")
                utime.sleep(0.5)
                time_waiting_connection += 0.5
                if time_waiting_connection > 10:
                    print("Failed to connect to wifi, please try again.\n")
                    break
        print(f"Connected to wifi '{wifi_name}'.\n")

    # Connect to ethernet
    elif wifi_or_ethernet == 'e':
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

    # Connect to API

    connected_to_api = False
    while not connected_to_api:

        ip_address = input("Enter IP address (return for default): ").strip()
        if ip_address == '':
            ip_address = PRIMARY_SCADA_IP

        base_url = f"http://{ip_address}:8000"

        url = base_url + "/new-pico"
        payload = {
            "HwUid": hw_uid,
            "TypeName": "new.pico",
            "Version": "100"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                connected_to_api = True
            else:
                print(f"Connected to the API, but it returned a status code {response.status_code}, indicating an issue.")
            response.close()
        except Exception as e:
            print(f"There was an error connecting to the API: {e}. Please check the hostname and try again.")

    print(f"Connected to the API hosted at '{base_url}'.")
    hostname = input("Enter hostname for backup (e.g., 'beech'): ").strip()
    backup_url = f"http://{hostname}.local:8000"

    # Write the parameters to comms_config.json
    if wifi_or_ethernet=='w':
        comms_config_content = {
            "WifiOrEthernet": 'wifi',
            "WifiName": wifi_name,
            "WifiPassword": wifi_pass, 
            "BaseUrl": f"http://{ip_address}:8000",
            "BackupUrl": backup_url
        }
    elif wifi_or_ethernet=='e':
        comms_config_content = {
            "WifiOrEthernet": 'ethernet',
            "BaseUrl": f"http://{ip_address}:8000",
            "BackupUrl": backup_url
        }
    with open('comms_config.json', 'w') as file:
        ujson.dump(comms_config_content, file)

    print(f"\n{'-'*40}\n[2/4] Success! Wrote 'comms_config.json' on the Pico.\n{'-'*40}\n")

    # -------------------------
    # Write app_config.json and main code
    # -------------------------
    while True:
        device_type = input("Is this Pico associated to a TankModule3 (enter '0') or an AsyncBtuMeter (enter '1'): ")
        if device_type in {'0', '1'}:
            break
        print('Please enter 0 or 1.')

    if device_type == '0':
        actor_name = provision_tank_module()
        print("This is a tank module")
        write_tank_module_3_main()
    elif device_type == '1':
        actor_name = provision_btu_meter()
        print("This is a BTU meter.")
        write_btu_meter_main()
        

    print(f"\n{'-'*40}\n[4/4] Success! Wrote 'main.py' on the Pico.\n{'-'*40}\n")

    print("The Pico is set up. It is now ready to use.")