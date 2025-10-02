import machine
import utime
import network
import ujson
import urequests
import ubinascii
import gc

COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"
DEFAULT_ACTOR_NAME = "primary-btu"

BASE_URL_RETRY_SECONDS = 300  # 5 minutes

# FLOW
DEFAULT_PUBLISH_TICKLIST_PERIOD_S = 10
DEFAULT_PUBLISH_EMPTY_TICKLIST_AFTER_S = 5
PULSE_PIN = 0

# TEMP
DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS = 500

SAMPLES = 1000
NUM_SAMPLE_AVERAGES = 1

ADC0_PIN_NUMBER = 26 # Hot Temp
ADC1_PIN_NUMBER = 27 # Cold Temp
ADC2_PIN_NUMBER = 28 # CT



class BtuMeter:
    def __init__(self):
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
        self.hw_uid = f"pico_{pico_unique_id}"
        self.load_comms_config()
        self.base_url_failed = False
        self.last_base_url_retry = utime.time()
        self.load_app_config()

        # FLOW
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self.relative_us_list = []
        self.first_tick_us = None
        self.time_at_first_tick_ns = utime.time_ns()
        self.last_ticks_sent = utime.time()
        self.last_empty_ticks_sent = utime.time()
        self.actively_publishing = False
        self.measuring_flow = False
        self.first_tick_timestamp_ns_list = []
        self.relative_us_list_list = []
        
        # TEMP
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        self.hot_list = []
        self.cold_list = []
        self.hot_ts_list = []
        self.cold_ts_list = []
        self.prev_hot = -1
        self.prev_cold = -1
        self.hot = None
        self.cold = None
        self.pump_pwr = None
        self.ct_timer = machine.Timer(-1)
        self.capture_offset_seconds = 0
        self.flow_timer = machine.Timer(-1)
        self.temp_timer = machine.Timer(-1)
        self.samples = SAMPLES
        self.num_sample_averages = NUM_SAMPLE_AVERAGES

        self.adc2 = machine.ADC(ADC2_PIN_NUMBER) # reads optional pump power
        

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
        #Post to BaseUrl if working, otherwise BackupUrl.
        #Periodically retry BaseUrl if it had failed
        #
        #Args:
        #    endpoint: The API endpoint (e.g., "/primary-btu/btu-params")
        #    payload: Dictionary to send as JSON
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
            # Only consider BaseUrl "failed" if it's truly unreachable per _test_url
            if url == self.base_url:
                if not self._test_url(self.base_url):
                    self.base_url_failed = True
                    self.last_base_url_retry = utime.time()
                    try:
                        self.send_baseurl_failure_alert()
                    except Exception:
                        pass
                print(f"{url} not reachable!")
                # For this request, try backup regardless
                if self.backup_url:
                    try:
                        return  urequests.post(self.backup_url+endpoint, data=json_payload, headers=headers, timeout=5)
                    except Exception:
                        return None
                
        # If exception occurred while already on backup, just give up
        return None

    def send_baseurl_failure_alert(self, message):
        #Send a single alert when BaseUrl first fails
        alert_payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "BaseUrl": self.base_url,
            "Message": message,
            "TypeName": "baseurl.failure.alert",
            "Version": "100"
        }
        # Try to send alert via backup URL
        if self.backup_url:
            try:
                url = self.backup_url + f"/{self.actor_node_name}/baseurl-failure-alert"
                headers = {'Content-Type': 'application/json'}
                response = urequests.post(url, data=ujson.dumps(alert_payload), headers=headers, timeout=3)
                response.close()
            except:
                pass  # Alert failed, but we tried

    # ---------------------------------
    # Code updates
    # ---------------------------------

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
            # If there is a pending code update then the response is a python file, otherwise json
            try:
                ujson.loads(response.content.decode('utf-8'))
            except:
                python_code = response.content
                with open('main_update.py', 'wb') as file:
                    file.write(python_code)
                machine.reset()
            
    # ---------------------------------
    # Parameters
    # ---------------------------------

            
    # ---------------------------------
    # Comms Parameters
    # ---------------------------------

    def load_comms_config(self):
        #Load the communication configuration file (WiFi/Ethernet and API base URL)
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
        #Try to update comms config from new-pico endpoint

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
        #Save the parameters to the comm_config file
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
    # App Parameters
    # ---------------------------------
    
    def load_app_config(self):
        #Load the app config file. If PumpPowerName is None, do not read power
        try:
            with open(APP_CONFIG_FILE, "r") as f:
                app_config = ujson.load(f)
        except:
            app_config = {}
        self.actor_node_name = app_config.get("ActorNodeName", DEFAULT_ACTOR_NAME)
        # Dynamic node naming with sensible defaults
        prefix = self.actor_node_name.replace("-btu", "")
        self.hot_temp_name = app_config.get("HotTempName", f"{prefix}-hot-temp")
        self.cold_temp_name = app_config.get("ColdTempName", f"{prefix}-cold-temp")
        self.pump_pwr_name = app_config.get("PumpPwrName", f"{prefix}-pump-pwr")

        # Check if we should read power
        self.read_power = self.pump_pwr_name is not None
        
        # Build node_names list based on what we're actually reading
        if self.read_power:
            self.pump_pwr_mv_list = []
            self.pump_pwr_timestamp_list = []
            self.prev_pump_pwr = -1
        else:
            self.pump_pwr_mv_list = None
            self.pump_pwr_timestamp_list = None
            self.prev_pump_pwr = None


        # FLOW
        self.publish_ticklist_period_s = app_config.get("PublishTicklistPeriodS", DEFAULT_PUBLISH_TICKLIST_PERIOD_S)
        self.publish_empty_ticklist_after_s = app_config.get("PublishEmptyTicklistAfterS", DEFAULT_PUBLISH_EMPTY_TICKLIST_AFTER_S)
        # TEMP
        self.async_capture_delta_micro_volts = app_config.get("AsyncCaptureDeltaMicroVolts", DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS)
    
    def save_app_config(self):
        #Save the parameters to the app_config file
        config = {
            "ActorNodeName": self.actor_node_name,
            "HotTempName": self.hot_temp_name,
            "ColdTempName": self.cold_temp_name,
            "PumpPwrName": self.pump_pwr_name,
            # FLOW
            "PublishTicklistPeriodS": self.publish_ticklist_period_s,
            "PublishEmptyTicklistAfterS": self.publish_empty_ticklist_after_s,
            # TEMP
            "Samples": self.samples,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,

            "TypeName": "ticklist.btu.params",
            "Version": "100"
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        #Post current parameters, and update parameters based on the server response
        endpoint = f"/{self.actor_node_name}/ticklist-btu-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "HotTempName": self.hot_temp_name,
            "ColdTempName": self.cold_temp_name,
            "PumpPwrName": self.pump_pwr_name,
            # FLOW
            "PublishTicklistPeriodS": self.publish_ticklist_period_s,
            "PublishEmptyTicklistAfterS": self.publish_empty_ticklist_after_s,
            # TEMP
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
            "TypeName": "ticklist.btu.params",
            "Version": "000"
        }

        response = self.post_with_fallback(endpoint, payload)
        if response:
            try:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.hot_temp_name = updated_config.get("HotTempName", self.hot_temp_name)
                self.cold_temp_name = updated_config.get("ColdTempName", self.cold_temp_name)

                # None will signal not reading power
                self.pump_pwr_name = updated_config.get("PumpPwrName")
                # Update read_power flag based on pump_pwr_name
                old_read_power = self.read_power
                self.read_power = self.pump_pwr_name is not None
                # Update node_names list if power reading changed
                if old_read_power != self.read_power:
                    if self.read_power:
                        self.pump_pwr_mv_list = []
                        self.pump_pwr_timestamp_list = []
                        self.prev_pump_pwr = -1
                    else:
                        self.pump_pwr_mv_list = None
                        self.pump_pwr_timestamp_list = None
                        self.prev_pump_pwr = None
                

                # FLOW
                self.publish_ticklist_period_s = updated_config.get("PublishTicklistPeriodS", self.publish_ticklist_period_s)
                self.publish_empty_ticklist_after_s = updated_config.get("PublishEmptyTicklistAfterS", self.publish_empty_ticklist_after_s)
                # TEMP
                self.async_capture_delta_micro_volts = updated_config.get("AsyncCaptureDeltaMicroVolts", self.async_capture_delta_micro_volts)
                self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
                # CT
                self.save_app_config()
            except:
                pass
            finally:
                response.close()

    # ---------------------------------
    # Receiving ticklists
    # ---------------------------------
            
    def pulse_callback(self, pin):
        #Compute the relative timestamp and add it to a list
        if not self.measuring_flow or self.actively_publishing:
            return
        current_timestamp_us = utime.ticks_us()
        # Initialize the timestamp if this is the first pulse
        if self.first_tick_us is None:
            self.first_tick_us = current_timestamp_us
            self.time_at_first_tick_ns = utime.time_ns()
            self.relative_us_list = [0]
        else:
            relative_us = current_timestamp_us - self.first_tick_us
            if relative_us - self.relative_us_list[-1] > 1e3:
                self.relative_us_list.append(relative_us)

    # ---------------------------------
    # Posting data
    # ---------------------------------

    def post_btu_data(self):
        # Build lists based on what we're measuring
        if self.read_power:
            node_names = [self.cold_temp_name, self.hot_temp_name, self.pump_pwr_name]
            mv_lists = [self.cold_list, self.hot_list, self.pump_pwr_mv_list]
            ts_lists = [self.cold_ts_list, self.hot_ts_list, self.pump_pwr_timestamp_list]
        else:
            node_names = [self.cold_temp_name, self.hot_temp_name]
            mv_lists = [self.cold_list, self.hot_list]
            ts_lists = [self.cold_ts_list, self.hot_ts_list]
        endpoint =  f"/{self.actor_node_name}/ticklist-btu-data"
        if len(self.relative_us_list_list)>1:
            if len(self.relative_us_list_list[0])<2 and len(self.relative_us_list_list[1])>0:
                self.relative_us_list_list = self.relative_us_list_list[1:]
                self.first_tick_timestamp_ns_list = self.first_tick_timestamp_ns_list[1:]
        payload = {
            "HwUid": self.hw_uid,
            "FirstTickTimestampNanoSecondList": self.first_tick_timestamp_ns_list,
            "RelativeMicrosecondListList": self.relative_us_list_list,
            "PicoBeforePostTimestampNanoSecond": utime.time_ns(),
            "AboutNodeNameList": node_names,
            "MicroVoltsLists": mv_lists,
            "MicroVoltsTimestampsLists": ts_lists,
            "TypeName": "ticklist.btu.data", 
            "Version": "100"
            }
        
        response = self.post_with_fallback(endpoint, payload)

        if response:
            response.close()
            # Clear lists after successful post
            self.first_tick_us = None
            self.relative_us_list = []
            self.first_tick_timestamp_ns_list = []
            self.relative_us_list_list = []
            self.hot_list = []
            self.cold_list = []
            self.hot_ts_list = []
            self.cold_ts_list = []

            if self.read_power:
                self.pump_pwr_timestamp_list = []
                self.pump_pwr_mv_list = []
            gc.collect()

    # ---------------------------------
    # Measuring microvolts
    # ---------------------------------

    def measure_hot(self):
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
    
    def measure_cold(self):
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

    def save_temp_readings(self, idx=2):
        # 0: save hot_temp microvolts, 1: save cold_temp microvolts, 2: save both
        time_ns = utime.time_ns()
        if idx==0:
            self.hot_list.append(self.hot)
            self.hot_ts_list.append(time_ns)
        elif idx==1:
            self.cold_list.append(self.cold)
            self.cold_ts_list.append(time_ns)
        else:
            self.hot_list.append(self.hot)
            self.cold_list.append(self.cold)
            self.hot_ts_list.append(time_ns)
            self.cold_ts_list.append(time_ns)
        
    def measure_flow(self, timer):
        #Measure flow in ticklists and record the data
        # Save the flow data
        self.first_tick_timestamp_ns_list.append(self.time_at_first_tick_ns)
        self.relative_us_list_list.append(self.relative_us_list)
        # Reset the flow variables
        self.first_tick_us = None
        self.relative_us_list = []
        self.time_at_first_tick_ns = utime.time_ns()
        # Start measuring flow again
        self.measuring_flow = True

    def measure_temp(self, timer):
        #Measure temp and record on change
        self.measuring_flow = False
        # time_at_start_temp = utime.time_ns()
        # print("Stopped measuring flow to measure temp")
        self.hot = self.measure_hot()
        self.cold = self.measure_cold()
        if abs(self.hot - self.prev_hot) > self.async_capture_delta_micro_volts:
            self.save_temp_readings(idx=0)
            self.prev_hot = self.hot
        if abs(self.cold - self.prev_cold) > self.async_capture_delta_micro_volts:
            self.save_temp_readings(idx=1)
            self.prev_cold = self.cold
        # timediff = utime.time_ns()-time_at_start_temp
        # timediff = round(float(timediff)/1e9,2)
        # print(f"Took {timediff}s to measure temp")
        # print("Done measuring temp")

    def measure_ct(self, timer):
        #Sample the current transformer (CT) ADC channel.
        #
        #Collects 200 successive ADC readings as quickly as possible,
        #timestamping each sample. A typical loop iteration takes ~95 µs
        #without explicit delays, so 200 samples span ~19 ms. This
        #comfortably covers at least one full 60 Hz AC cycle
        #(period ≈ 16.7 ms).

        #Notes:
        #    - At 60 Hz, 200 samples correspond to ~83 µs/sample if perfectly 
        #    distributed; in practice this function achieves ~95 µs/sample.
        #    - The function reduces the collected data to just the peak ADC
        #    value and its first timestamp.
        if not self.read_power:
            return
        
        if self.actively_publishing:
            print("Not measuring ct ... actively publishing")
            return
        
        pump_pwr_list = []
        while len(pump_pwr_list) < 200:
            voltage = int(self.adc2.read_u16() * 3.3 / 65535 * 10**6)
            pump_pwr_list.append(voltage)
            #utime.sleep_us(10)
        print(f"length of pump_pwr_mv_list is {len(self.pump_pwr_mv_list)}")
        print(f"self.read_power is {self.read_power}")
        pump_pwr = max(pump_pwr_list)
        self.pump_pwr_mv_list.append(pump_pwr)
        self.pump_pwr_timestamp_list.append(utime.time_ns())

    def start_flow_timer(self):
        #Initialize the timer to measure flow every second
        self.flow_timer.init(
            period=1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.measure_flow
        )
    
    def start_temp_timer(self):
        #Initialize the timer to measure temp every second
        self.temp_timer.init(
            period=1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.measure_temp
        )
    
    def start_ct_timer(self):
        #Initialize the timer to measure CT every second
        self.ct_timer.init(
            period=1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.measure_ct
        )

    def main_loop(self):
        while True:
            recorded_ticks = any(self.relative_us_list_list)
            time_since_last_ticks_sent = utime.time() - self.last_ticks_sent
            if (
                (recorded_ticks and time_since_last_ticks_sent > self.publish_ticklist_period_s) 
                or 
                (not recorded_ticks and time_since_last_ticks_sent > self.publish_empty_ticklist_after_s)
                ):
                self.actively_publishing = True
                self.post_btu_data()
                self.actively_publishing = False
                self.last_ticks_sent = utime.time()

    def start(self):
        if self.wifi_or_ethernet=='wifi':
            self.connect_to_wifi()
        elif self.wifi_or_ethernet=='ethernet':
            self.connect_to_ethernet()

        # Update configurations 
        self.update_comms_config()
        self.update_app_config()
        self.update_code()

        # FLOW
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)
        # TEMP
        self.hot= self.measure_hot()
        self.cold = self.measure_cold()
        self.save_temp_readings()

        # Start measurement timers with staggered timing
        self.start_flow_timer()
        utime.sleep_ms(600)
        self.start_temp_timer()
        # Only start ct timer if we are reading power
        if self.read_power:
            utime.sleep_ms(300)
            self.start_ct_timer()

        self.main_loop()

if __name__ == "__main__":
    b = BtuMeter()
    b.start()
