import machine
import utime
import network
import ujson
import urequests
import ubinascii
import time
import gc
import os

# ---------------------------------
# Constants
# ---------------------------------

# Configuration files
COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"

# Pins
ADC0_PIN_NUMBER = 26   # (COLD)
ADC1_PIN_NUMBER = 27  #(HOT)
PULSE_PIN = 28

# Default parameters
DEFAULT_ACTOR_NAME = "pico-btu"
DEFAULT_FLOW_NODE_NAME = "hp-flow"
DEFAULT_ALPHA_TIMES_100 = 10
DEFAULT_ASYNC_CAPTURE_DELTA_HZ = 1
DEFAULT_EXP_WEIGHTING_MS = 40
DEFAULT_PUBLISH_STAMPS_PERIOD_S = 10
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_NO_FLOW_MILLISECONDS = 1000
ACTIVELY_PUBLISHING_AFTER_POST_MILLISECONDS = 200
MAIN_LOOP_MILLISECONDS = 100
DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS = 500
DEFAULT_SAMPLES = 1000
DEFAULT_NUM_SAMPLE_AVERAGES = 10

# ---------------------------------
# Main class
# ---------------------------------

class PicoBTU:

    def __init__(self):

        # [BOTH]
        # Unique ID
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        # Pins
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        # Load configuration files
        self.load_comms_config()
        self.load_app_config()
        # Synchronous reporting on the second
        self.capture_offset_seconds = 0
        self.keepalive_timer = machine.Timer(-1)

        # [FLOW] 
        # Reporting exp weighted average Hz
        self.exp_hz = 0
        self.prev_hz = None
        self.hz_posted_time = utime.time()
        # Reporting relative ticklists
        self.first_tick_us = None
        self.relative_us_list = []
        self.last_ticks_sent = utime.time()
        self.actively_publishing = False

        # [TEMP] 
        self.prev_mv0 = -1
        self.prev_mv1 = -1
        self.mv0 = None
        self.mv1 = None
        self.node_names = []
        self.microvolts_posted_time = utime.time()

    def set_names(self):
        if self.actor_node_name is None:
            raise Exception("Needs an actor node name to run.")
        self.node_names = [
            f"{self.flow_node_name}-cold", 
            f"{self.flow_node_name}-hot"
        ]

    # ---------------------------------
    # Communication
    # ---------------------------------

    def load_comms_config(self):
        '''Load the communication configuration file (WiFi and API base URL)'''
        try:
            with open(COMMS_CONFIG_FILE, "r") as f:
                comms_config = ujson.load(f)
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Error loading comms_config file: {e}")
        self.wifi_name = comms_config.get("WifiName")
        self.wifi_password = comms_config.get("WifiPassword")
        self.base_url = comms_config.get("BaseUrl")
        if self.wifi_name is None:
            raise KeyError("WifiName not found in comms_config.json")
        if self.wifi_password is None:
            raise KeyError("WifiPassword not found in comms_config.json")
        if self.base_url is None:
            raise KeyError("BaseUrl not found in comms_config.json")
        
    def connect_to_wifi(self):
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            print("Connecting to wifi...")
            wlan.connect(self.wifi_name, self.wifi_password)
            while not wlan.isconnected():
                time.sleep(1)
        print(f"Connected to wifi {self.wifi_name}")

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
        # Both
        self.actor_node_name = app_config.get("ActorNodeName", DEFAULT_ACTOR_NAME)
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        # Flow
        self.flow_node_name = app_config.get("FlowNodeName", DEFAULT_FLOW_NODE_NAME)
        self.alpha = app_config.get("AlphaTimes100", DEFAULT_ALPHA_TIMES_100) / 100
        self.async_capture_delta_hz = app_config.get("AsyncCaptureDeltaHz", DEFAULT_ASYNC_CAPTURE_DELTA_HZ)
        self.exp_weighting_ms = app_config.get("ExpWeightingMs", DEFAULT_EXP_WEIGHTING_MS)
        self.publish_stamps_period_s = app_config.get("PublishStampsPeriodS", DEFAULT_PUBLISH_STAMPS_PERIOD_S)
        self.no_flow_milliseconds = app_config.get("NoFlowMilliseconds", DEFAULT_NO_FLOW_MILLISECONDS)
        # Temp
        self.async_capture_delta_micro_volts = app_config.get("AsyncCaptureDeltaMicroVolts", DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS)
        self.samples = app_config.get("Samples", DEFAULT_SAMPLES)
        self.num_sample_averages = app_config.get("NumSampleAverages", DEFAULT_NUM_SAMPLE_AVERAGES)

    def save_app_config(self):
        '''Save the parameters to the app_config file'''
        config = {
            # Both
            "ActorNodeName": self.actor_node_name,
            "CapturePeriodS": self.capture_period_s,
            # Flow
            "FlowNodeName": self.flow_node_name,
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncCaptureDeltaHz": self.async_capture_delta_hz,
            "ExpWeightingMs": self.exp_weighting_ms,
            "PublishStampsPeriodS": self.publish_stamps_period_s,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            # Temp
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
            "Samples": self.samples,
            "NumSampleAverages":self.num_sample_averages,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        '''Post current parameters, and update parameters based on the server response'''
        url = self.base_url + f"/{self.actor_node_name}/btu-params"
        payload = {
            # Both
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "CapturePeriodS": self.capture_period_s,
            "TypeName": "btu.params",
            "Version": "100",
            # Flow
            "FlowNodeName": self.flow_node_name,
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncCaptureDeltaHz": self.async_capture_delta_hz,
            "ExpWeightingMs": self.exp_weighting_ms,
            "PublishStampsPeriodS": self.publish_stamps_period_s,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            # Tank
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
            "Samples": self.samples,
            "NumSampleAverages": self.num_sample_averages,
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                updated_config = response.json()
                # Both
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)
                self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
                # Flow
                self.flow_node_name = updated_config.get("FlowNodeName", self.flow_node_name)
                self.alpha = updated_config.get("AlphaTimes100", self.alpha * 100) / 100
                self.async_capture_delta_hz = updated_config.get("AsyncCaptureDeltaHz", self.async_capture_delta_hz)
                self.exp_weighting_ms = updated_config.get("ExpWeightingMs", self.exp_weighting_ms)
                self.publish_stamps_period_s = updated_config.get("PublishStampsPeriodS", self.publish_stamps_period_s)
                self.no_flow_milliseconds = updated_config.get("NoFlowMilliseconds", self.no_flow_milliseconds)
                # Tank
                self.async_capture_delta_micro_volts = updated_config.get("AsyncCaptureDeltaMicroVolts", self.async_capture_delta_micro_volts)
                self.samples = updated_config.get("Samples", self.samples)
                self.num_sample_averages = updated_config.get("NumSampleAverages", self.num_sample_averages)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error posting flow.hall.params: {e}")

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

    # ---------------------------------
    # Posting mV and Hz
    # ---------------------------------

    def post_microvolts(self, idx=2):
        url = self.base_url + f"/{self.actor_node_name}/microvolts"
        if idx==0:
            mv_list = [self.mv0]
        elif idx==1:
            mv_list = [self.mv1]
        else:
            mv_list = [self.mv0, self.mv1]
        payload = {
            "HwUid": self.hw_uid,
            "AboutNodeNameList": [self.node_names[idx]] if idx<=1 else self.node_names,
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

    def post_hz(self):
        url = self.base_url + f"/{self.actor_node_name}/hz"
        payload = {
            "FlowNodeName": self.flow_node_name,
            "MilliHz": int(self.exp_hz * 1e3), 
            "TypeName": "hz",
            "Version": "100"
            }
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting hz: {e}")
        self.prev_hz = self.exp_hz
        self.hz_posted_time = utime.time()
        
    def keep_alive(self, timer):
        '''Post Hz and mV if none were posted within the last minute'''
        if utime.time() - self.hz_posted_time > 55:
            self.post_hz()
        if utime.time() - self.microvolts_posted_time > 55:
            self.post_microvolts()

    def start_keepalive_timer(self):
        '''Initialize the timer to call self.keep_alive periodically'''
        self.keepalive_timer.init(
            period=self.capture_period_s * 1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.keep_alive
        )
    
    def update_hz(self, delta_us):
        '''Compute the exponential weighted average and post on change'''
        delta_ms = delta_us / 1e3
        hz = 1e6 / delta_us
        if delta_ms > self.no_flow_milliseconds:
            self.exp_hz = 0
        elif self.exp_hz == 0:
            self.exp_hz = hz
        else:
            tw_alpha = min(1, (delta_ms / self.exp_weighting_ms) * self.alpha)
            self.exp_hz = tw_alpha * hz + (1 - tw_alpha) * self.exp_hz
        if (self.prev_hz is None) or (abs(self.exp_hz - self.prev_hz) > self.async_capture_delta_hz):
            self.post_hz()
            
    def post_ticklist(self):
        url = self.base_url + f"/{self.actor_node_name}/ticklist-hall"
        payload = {
            "FlowNodeName": self.flow_node_name,
            "PicoStartMillisecond": self.first_tick_us // 1000,
            "RelativeMicrosecondList": self.relative_us_list,
            "TypeName": "ticklist.hall", 
            "Version": "100"
            }
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting relative timestamps: {e}")
        gc.collect()
        self.relative_us_list = []
        self.first_tick_us = None

    def pulse_callback(self, pin):
        '''When not actively publishing, compute the relative timestamp and add it to a list'''
        if not self.actively_publishing:
            current_timestamp_us = utime.ticks_us()
            # Initialize the timestamp if this is the first pulse
            if self.first_tick_us is None:
                self.first_tick_us = current_timestamp_us
                self.relative_us_list.append(0)
                return
            relative_us = current_timestamp_us - self.first_tick_us
            delta_us = relative_us - self.relative_us_list[-1]
            self.update_hz(delta_us)
            self.relative_us_list.append(relative_us)

    # ---------------------------------
    # Main loop
    # ---------------------------------

    def main_loop(self):
        
        self.mv0 = self.adc0_micros()
        self.mv1 = self.adc1_micros()
        
        while True:

            # Temperatures
            self.mv0 = self.adc0_micros()
            self.mv1 = self.adc1_micros()
            if abs(self.mv0 - self.prev_mv0) > self.async_capture_delta_micro_volts:
                self.post_microvolts(idx=0)
                self.prev_mv0 = self.mv0
            if abs(self.mv1 - self.prev_mv1) > self.async_capture_delta_micro_volts:
                self.post_microvolts(idx=1)
                self.prev_mv1 = self.mv1
                    
            utime.sleep_ms(MAIN_LOOP_MILLISECONDS)
            
            # Flow
            if (utime.time()-self.last_ticks_sent > self.publish_stamps_period_s) and (len(self.relative_us_list) > 0):
                self.actively_publishing = True
                self.post_ticklist()
                self.last_ticks_sent = utime.time()
                # Wait after the post before starting to track ticks to let the time disturbances reduce
                utime.sleep_ms(ACTIVELY_PUBLISHING_AFTER_POST_MILLISECONDS)
                self.actively_publishing = False
            # If there have been no ticks in the last second, flow is 0
            if (utime.time()-self.last_ticks_sent > 1) and (len(self.relative_us_list)==0):
                self.update_hz(1e9)

    def start(self):
        self.connect_to_wifi()
        self.update_app_config()
        self.set_names()
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)
        utime.sleep(self.capture_offset_seconds)
        self.start_keepalive_timer()
        self.main_loop()

if __name__ == "__main__":
    p = PicoBTU()
    p.start()