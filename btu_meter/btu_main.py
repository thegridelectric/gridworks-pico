import machine
import utime
import network
import ujson
import urequests
import ubinascii
import time
import gc
import os 

COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"
DEFAULT_ACTOR_NAME = "primary-btu"

# FLOW
DEFAULT_PUBLISH_TICKLIST_PERIOD_S = 10
DEFAULT_PUBLISH_EMPTY_TICKLIST_AFTER_S = 5
PULSE_PIN = 0
MAIN_LOOP_MILLISECONDS = 100

# TEMP
DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS = 500
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_SAMPLES = 1000
DEFAULT_NUM_SAMPLE_AVERAGES = 1
ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27


class BtuMeter:
    def __init__(self):
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        self.load_comms_config()
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
        self.mv0_list = []
        self.mv1_list = []
        self.mv0_timestamp_list = []
        self.mv1_timestamp_list = []
        self.prev_mv0 = -1
        self.prev_mv1 = -1
        self.mv0 = None
        self.mv1 = None
        self.node_names = ["ewt", "lwt"]
        self.capture_offset_seconds = 0
        self.flow_timer = machine.Timer(-1)
        self.temp_timer = machine.Timer(-1)

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
        # FLOW
        self.publish_ticklist_period_s = app_config.get("PublishTicklistPeriodS", DEFAULT_PUBLISH_TICKLIST_PERIOD_S)
        self.publish_empty_ticklist_after_s = app_config.get("PublishEmptyTicklistAfterS", DEFAULT_PUBLISH_EMPTY_TICKLIST_AFTER_S)
        # TEMP
        self.async_capture_delta_micro_volts = app_config.get("AsyncCaptureDeltaMicroVolts", DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS)
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        self.samples = app_config.get("Samples", DEFAULT_SAMPLES)
        self.num_sample_averages = app_config.get("NumSampleAverages", DEFAULT_NUM_SAMPLE_AVERAGES)
    
    def save_app_config(self):
        '''Save the parameters to the app_config file'''
        config = {
            "ActorNodeName": self.actor_node_name,
            # FLOW
            "PublishTicklistPeriodS": self.publish_ticklist_period_s,
            "PublishEmptyTicklistAfterS": self.publish_empty_ticklist_after_s,
            # TEMP
            "CapturePeriodS": self.capture_period_s,
            "Samples": self.samples,
            "NumSampleAverages":self.num_sample_averages,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        '''Post current parameters, and update parameters based on the server response'''
        url = self.base_url + f"/{self.actor_node_name}/btu-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            # FLOW
            "PublishTicklistPeriodS": self.publish_ticklist_period_s,
            "PublishEmptyTicklistAfterS": self.publish_empty_ticklist_after_s,
            # TEMP
            "CapturePeriodS": self.capture_period_s,
            "Samples": self.samples,
            "NumSampleAverages": self.num_sample_averages,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
            "TypeName": "btu.params",
            "Version": "100"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                # FLOW
                self.publish_ticklist_period_s = updated_config.get("PublishTicklistPeriodS", self.publish_ticklist_period_s)
                self.publish_empty_ticklist_after_s = updated_config.get("PublishEmptyTicklistAfterS", self.publish_empty_ticklist_after_s)
                # TEMP
                self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)
                self.samples = updated_config.get("Samples", self.samples)
                self.num_sample_averages = updated_config.get("NumSampleAverages", self.num_sample_averages)
                self.async_capture_delta_micro_volts = updated_config.get("AsyncCaptureDeltaMicroVolts", self.async_capture_delta_micro_volts)
                self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error posting btu.meter.params: {e}")

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
    # Receiving and publishing ticklists
    # ---------------------------------
            
    def pulse_callback(self, pin):
        '''Compute the relative timestamp and add it to a list'''
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

    def post_btu_data(self):
        url = self.base_url + f"/{self.actor_node_name}/btu-data"
        if len(self.relative_us_list_list)>1:
            if len(self.relative_us_list_list[0])<2 and len(self.relative_us_list_list[1])>0:
                self.relative_us_list_list = self.relative_us_list_list[1:]
                self.first_tick_timestamp_ns_list = self.first_tick_timestamp_ns_list[1:]
        payload = {
            "HwUid": self.hw_uid,
            "FirstTickTimestampNanoSecondList": self.first_tick_timestamp_ns_list,
            "RelativeMicrosecondListList": self.relative_us_list_list,
            "PicoBeforePostTimestampNanoSecond": utime.time_ns(),
            "AboutNodeNameList": self.node_names,
            "MicroVoltsLists": [self.mv0_list, self.mv1_list],
            "MicroVoltsTimestampsLists": [self.mv0_timestamp_list, self.mv1_timestamp_list],
            "TypeName": "btu.data", 
            "Version": "100"
            }
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting relative timestamps: {e}")
        self.first_tick_us = None
        self.relative_us_list = []
        self.first_tick_timestamp_ns_list = []
        self.relative_us_list_list = []
        self.mv0_list = []
        self.mv1_list = []
        self.mv0_timestamp_list = []
        self.mv1_timestamp_list = []
        gc.collect()

    # ---------------------------------
    # Measuring and posting microvolts
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

    def save_microvolts(self, idx=2):
        time_ns = utime.time_ns()
        if idx==0:
            self.mv0_list.append(self.mv0)
            self.mv0_timestamp_list.append(time_ns)
        elif idx==1:
            self.mv1_list.append(self.mv1)
            self.mv1_timestamp_list.append(time_ns)
        else:
            self.mv0_list.append(self.mv0)
            self.mv1_list.append(self.mv1)
            self.mv0_timestamp_list.append(time_ns)
            self.mv1_timestamp_list.append(time_ns)
        
    def measure_flow(self, timer):
        '''Measure flow in ticklists and record the data'''
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
        '''Measure temp and record on change'''
        self.measuring_flow = False
        # time_at_start_temp = utime.time_ns()
        # print("\nStopped measuring flow to measure temp")
        self.mv0 = self.adc0_micros()
        self.mv1 = self.adc1_micros()
        if abs(self.mv0 - self.prev_mv0) > self.async_capture_delta_micro_volts:
            self.save_microvolts(idx=0)
            self.prev_mv0 = self.mv0
        if abs(self.mv1 - self.prev_mv1) > self.async_capture_delta_micro_volts:
            self.save_microvolts(idx=1)
            self.prev_mv1 = self.mv1
        # timediff = utime.time_ns()-time_at_start_temp
        # timediff = round(float(timediff)/1e9,2)
        # print(f"Took {timediff}s to measure temp")
        # print("Done measuring temp")

    def start_flow_timer(self):
        '''Initialize the timer to measure data every second'''
        self.flow_timer.init(
            period=1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.measure_flow
        )
    
    def start_temp_timer(self):
        '''Initialize the timer to measure temp every second'''
        self.temp_timer.init(
            period=1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.measure_temp
        )

    def main_loop(self):
        while True:
            utime.sleep_ms(MAIN_LOOP_MILLISECONDS)
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
        self.update_code()
        self.update_app_config()
        # FLOW
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)
        # TEMP
        self.mv0 = self.adc0_micros()
        self.mv1 = self.adc1_micros()
        self.save_microvolts()
        # utime.sleep(self.capture_offset_seconds)
        self.start_flow_timer()
        utime.sleep_ms(800)
        self.start_temp_timer()
        self.main_loop()

if __name__ == "__main__":
    b = BtuMeter()
    b.start()
