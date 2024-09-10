import machine
import ujson
import network
import utime
import urequests
import ubinascii
import os

# Constants
ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27
ADC2_PIN_NUMBER = 28
TOTAL_REPORTS = 200
SAMPLES = 1000
PIN_0_OFFSET = 2.4
PIN_1_OFFSET = -2.4

# Remove existing files
if 'boot.py' in os.listdir():
    os.remove('boot.py')
if 'app_config.json' in os.listdir():
    os.remove('app_config.json')
if 'comms_config.json' in os.listdir():
    os.remove('comms_config.json')
if 'main.py' in os.listdir():
    os.remove('main.py')

# *************************
# 1/3 - MAIN.PY PROVISION
# *************************

def write_flow_hall_main():
    main_code = """import machine
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

# Default parameters
DEFAULT_ACTOR_NAME = "pico-flow-hall"
DEFAULT_FLOW_NODE_NAME = "primary-flow"
DEFAULT_ALPHA_TIMES_100 = 10
DEFAULT_ASYNC_CAPTURE_DELTA_HZ = 1
DEFAULT_PUBLISH_STAMPS_PERIOD_S = 10
DEFAULT_INACTIVITY_TIMEOUT_S = 60
DEFAULT_EXP_WEIGHTING_MS = 40
DEFAULT_REPORT_HZ = True

# Other constants
PULSE_PIN = 28 # 7 pins down on the hot side
CODE_UPDATE_PERIOD_S = 60
KEEPALIVE_TIMER_PERIOD_S = 3
NO_FLOW_MILLISECONDS = 1000
ACTIVELY_PUBLISHING_AFTER_POST_MILLISECONDS = 200
MAIN_LOOP_MILLISECONDS = 100

# ---------------------------------
# Main class
# ---------------------------------

class PicoFlowHall:

    def __init__(self):
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        self.load_comms_config()
        self.load_app_config()
        # For tracking async reports of exponential weighted frequency
        self.exp_hz = 0
        self.prev_hz = None
        self.hz_posted_time = utime.time()
        # For tracking tick list
        self.last_ticks_sent = utime.time()
        # There is a time lag between posting the ticks and starting off capturing ticks
        # and this is the microseconds of the first tick in a batch
        self.first_tick_us = None
        self.relative_us_list = []
        self.actively_publishing = False
        self.keepalive_timer = machine.Timer(-1)

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
        self.actor_node_name = app_config.get("ActorNodeName", DEFAULT_ACTOR_NAME)
        self.flow_node_name = app_config.get("FlowNodeName", DEFAULT_FLOW_NODE_NAME)
        alpha_times_100 = app_config.get("AlphaTimes100", DEFAULT_ALPHA_TIMES_100)
        self.alpha = alpha_times_100 / 100
        self.async_capture_delta_hz = app_config.get("AsyncCaptureDeltaHz", DEFAULT_ASYNC_CAPTURE_DELTA_HZ)
        self.publish_stamps_period_s = app_config.get("PublishStampsPeriodS", DEFAULT_PUBLISH_STAMPS_PERIOD_S)
        self.inactivity_timeout_s = app_config.get("InactivityTimeoutS", DEFAULT_INACTIVITY_TIMEOUT_S)
        self.exp_weighting_ms = app_config.get("ExpWeightingMs", DEFAULT_EXP_WEIGHTING_MS)
        self.report_hz = app_config.get("ReportHz", DEFAULT_REPORT_HZ)
    
    def save_app_config(self):
        '''Save the parameters to the app_config file'''
        config = {
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncCaptureDeltaHz": self.async_capture_delta_hz,
            "PublishStampsPeriodS": self.publish_stamps_period_s,
            "InactivityTimeoutS": self.inactivity_timeout_s,
            "ExpWeightingMs": self.exp_weighting_ms,
            "ReportHz": self.report_hz,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        '''Post current parameters, and update parameters based on the server response'''
        url = self.base_url + "/flow-hall-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncCaptureDeltaHz": self.async_capture_delta_hz,
            "PublishStampsPeriodS": self.publish_stamps_period_s,
            "InactivityTimeoutS": self.inactivity_timeout_s,
            "ExpWeightingMs": self.exp_weighting_ms,
            "ReportHz": self.report_hz,
            "TypeName": "flow.hall.params",
            "Version": "001"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.flow_node_name = updated_config.get("FlowNodeName", self.flow_node_name)
                self.alpha = updated_config.get("AlphaTimes100", self.alpha * 100) / 100
                self.async_capture_delta_hz = updated_config.get("AsyncCaptureDeltaHz", self.async_capture_delta_hz)
                self.publish_stamps_period_s = updated_config.get("PublishStampsPeriodS", self.publish_stamps_period_s)
                self.inactivity_timeout_s = updated_config.get("InactivityTimeoutS", self.inactivity_timeout_s)
                self.exp_weighting_ms = updated_config.get("ExpWeightingMs", self.exp_weighting_ms)
                self.report_hz = updated_config.get("ReportHz", self.report_hz)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error posting flow.hall.params: {e}")
            # Try reverting to previous code (will only try once)
            if 'main_previous.py' in os.listdir():
                os.rename('main_previous.py', 'main_revert.py')
                machine.reset()

    # ---------------------------------
    # Code updates
    # ---------------------------------

    def update_code(self):
        url = self.base_url + "/code-update"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "TypeName": "new.code",
            "Version": "000"
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
    # Posting Hz
    # ---------------------------------

    def post_hz(self):
        if self.report_hz:
            url = self.base_url + f"/{self.actor_node_name}/hz"
            payload = {
                "AboutNodeName": self.flow_node_name,
                "MilliHz": int(self.exp_hz * 1e3), 
                "TypeName": "hz",
                "Version": "001"
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
        else:
            return

    def keep_alive(self, timer):
        '''Post Hz, assuming no other messages sent within inactivity timeout'''
        if utime.time() - self.hz_posted_time > self.inactivity_timeout_s:
            self.post_hz()

    def start_keepalive_timer(self):
        '''Initialize the timer to call self.keep_alive periodically'''
        self.keepalive_timer.init(
            period=KEEPALIVE_TIMER_PERIOD_S * 1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.keep_alive
        )
    
    def update_hz(self, delta_us):
        delta_ms = delta_us / 1e3
        hz = 1e6 / delta_us
        if delta_ms > NO_FLOW_MILLISECONDS:
            self.exp_hz = 0
        elif self.exp_hz == 0:
            self.exp_hz = hz
        else:
            tw_alpha = min(1, (delta_ms / self.exp_weighting_ms) * self.alpha)
            self.exp_hz = tw_alpha * hz + (1 - tw_alpha) * self.exp_hz
        
        if self.prev_hz is None:
            self.post_hz()
        elif abs(self.exp_hz - self.prev_hz) > self.async_capture_delta_hz:
            self.post_hz()

    # ---------------------------------
    # Posting relative timestamps
    # ---------------------------------
            
    def post_timestamp_list(self):
        url = self.base_url + f"/{self.actor_node_name}/ticklist"
        payload = {
            "AboutNodeName": self.flow_node_name,
            "PicoStartMillisecond": self.first_tick_us // 1000,
            "RelativeMicrosecondList": self.relative_us_list,
            "TypeName": "ticklist", 
            "Version": "002"
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

    # ---------------------------------
    # Receive and publish ticks
    # ---------------------------------

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

    def main_loop(self):
        '''Post the relative timestamps list periodically if there has been flow'''
        while True:
            utime.sleep_ms(MAIN_LOOP_MILLISECONDS)
            if (utime.time()-self.last_ticks_sent > self.publish_stamps_period_s) and (len(self.relative_us_list) > 0):
                self.actively_publishing = True
                self.post_timestamp_list()
                self.last_ticks_sent = utime.time()
                # Wait longer after the post before starting to track ticks
                # to let the time disturbances reduce
                utime.sleep_ms(ACTIVELY_PUBLISHING_AFTER_POST_MILLISECONDS)
                self.actively_publishing = False

    def start(self):
        self.connect_to_wifi()
        self.update_code()
        self.update_app_config()
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)
        # report 0 hz every self.inactivity_timeout_s (default 60)
        self.start_keepalive_timer()
        self.main_loop()

if __name__ == "__main__":
    p = PicoFlowHall()
    p.start()"""
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_flow_reed_main():
    main_code = """import machine
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

# Default parameters
DEFAULT_ACTOR_NAME = "pico-flow-reed"
DEFAULT_FLOW_NODE_NAME = "primary-flow"
DEFAULT_DEADBAND_MILLISECONDS = 10
DEFAULT_INACTIVITY_TIMEOUT_S = 60
DEFAULT_NO_FLOW_MILLISECONDS = 3_000
DEFAULT_GALLONS_PER_TICK_TIMES_10000 = 748
DEFAULT_ALPHA_TIMES_100 = 10
DEFAULT_ASYNC_DELTA_GPM_TIMES_100 = 10
DEFAULT_REPORT_GPM = True

# Other constants
PULSE_PIN = 0 # This is pin 1
TIME_WEIGHTING_MS = 800
POST_LIST_LENGTH = 100
CODE_UPDATE_PERIOD_S = 60
KEEPALIVE_TIMER_PERIOD_S = 3

# Available pin states
class PinState:
    GOING_UP = 0
    UP = 1
    GOING_DOWN = 2
    DOWN = 3

# ---------------------------------
# Main class
# ---------------------------------

class PicoFlowReed:

    def __init__(self):
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        self.hw_uid = get_hw_uid()
        self.load_comms_config()
        self.load_app_config()
        # For tracking async reports of exponential weighted GPM
        self.exp_gpm = 0
        self.prev_gpm = None
        self.gpm_posted_time = utime.time()
        self.posting_ticklist = False
        # For tracking tick list
        self.last_ticks_sent = utime.time()
        self.latest_timestamp_ms = None
        self.first_tick_ms = None
        self.relative_ms_list = []
        # Will be initialized as PinState.DOWN
        self.pin_state = None 
        self.keepalive_timer = machine.Timer(-1)

    def state_init(self):
        in_down_state = False
        reading = self.pulse_pin.value()
        while not in_down_state:
            utime.sleep_ms(self.deadband_milliseconds)
            prev_reading = reading
            reading = self.pulse_pin.value()
            if prev_reading == 0 and reading == 0:
                in_down_state = True
        self.pin_state = PinState.DOWN

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
        self.actor_node_name = app_config.get("ActorNodeName", DEFAULT_ACTOR_NAME)
        self.flow_node_name = app_config.get("FlowNodeName", DEFAULT_FLOW_NODE_NAME)
        self.deadband_milliseconds = app_config.get("DeadbandMilliseconds", DEFAULT_DEADBAND_MILLISECONDS)
        self.inactivity_timeout_s = app_config.get("InactivityTimeoutS", DEFAULT_INACTIVITY_TIMEOUT_S)
        self.no_flow_milliseconds = app_config.get("NoFlowMilliseconds", DEFAULT_NO_FLOW_MILLISECONDS)
        alpha_times_100 = app_config.get("AlphaTimes100", DEFAULT_ALPHA_TIMES_100)
        gallons_per_tick_times_10000 = app_config.get("GallonsPerTickTimes10000", DEFAULT_GALLONS_PER_TICK_TIMES_10000)
        self.gallons_per_tick = gallons_per_tick_times_10000 / 10_000
        self.alpha = alpha_times_100 / 100
        async_delta_gpm_times_100 = app_config.get("AsyncDeltaGpmTimes100", DEFAULT_ASYNC_DELTA_GPM_TIMES_100)
        self.async_delta_gpm = async_delta_gpm_times_100 / 100
        self.report_gpm = app_config.get("ReportGpm", DEFAULT_REPORT_GPM)

    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "DeadbandMilliseconds": self.deadband_milliseconds,
            "InactivityTimeoutS": self.inactivity_timeout_s,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            "GallonsPerTickTimes10000": int(self.gallons_per_tick * 10_000),
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncDeltaGpmTimes100": int(self.async_delta_gpm * 100),
            "ReportGpm": self.report_gpm,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        url = self.base_url + "/flow-reed-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "DeadbandMilliseconds": self.deadband_milliseconds,
            "InactivityTimeoutS": self.inactivity_timeout_s,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            "GallonsPerTickTimes10000": int(self.gallons_per_tick * 10_000),
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncDeltaGpmTimes100": int(self.async_delta_gpm * 100),
            "ReportGpm": self.report_gpm,
            "TypeName": "flow.reed.params",
            "Version": "003"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.flow_node_name = updated_config.get("FlowNodeName", self.flow_node_name)
                self.deadband_milliseconds = updated_config.get("DeadbandMilliseconds", self.deadband_milliseconds)
                self.inactivity_timeout_s = updated_config.get("InactivityTimeoutS", self.inactivity_timeout_s)
                self.no_flow_milliseconds = updated_config.get("NoFlowMilliseconds", self.no_flow_milliseconds)
                gallons_per_tick_times_10000 = updated_config.get("GallonsPerTickTimes10000", int(self.gallons_per_tick*10_000))
                self.gallons_per_tick = gallons_per_tick_times_10000 / 10_000
                alpha_times_100 = updated_config.get("AlphaTimes100", int(self.alpha * 100))
                self.alpha = alpha_times_100 / 100
                async_delta_gpm_times_100 = updated_config.get("AsyncDeltaGpmTimes100", int(self.async_delta_gpm * 100))
                self.async_delta_gpm = async_delta_gpm_times_100 / 100
                self.report_gpm = updated_config.get("ReportGpm", self.report_gpm)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error posting flow.reed.params: {e}")
            # Try reverting to previous code (will only try once)
            if 'main_previous.py' in os.listdir():
                os.rename('main_previous.py', 'main_revert.py')
                machine.reset()

    # ---------------------------------
    # Code updates
    # ---------------------------------

    def update_code(self):
        url = self.base_url + "/code-update"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "TypeName": "new.code",
            "Version": "000"
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
    # Posting GPM
    # ---------------------------------

    def post_gpm(self):
        if self.report_gpm:
            url = self.base_url +  f"/{self.actor_node_name}/gpm"
            payload = {
                "AboutNodeName": self.flow_node_name,
                "ValueTimes100": int(100 * self.exp_gpm),
                "TypeName": "gpm", 
                "Version": "000"
            }
            headers = {"Content-Type": "application/json"}
            json_payload = ujson.dumps(payload)
            try:
                response = urequests.post(url, data=json_payload, headers=headers)
                response.close()
            except Exception as e:
                print(f"Error posting gpm: {e}")
            gc.collect()
            self.prev_gpm = self.exp_gpm
            self.gpm_posted_time = utime.time()
        else:
            return

    def keep_alive(self, timer):
        '''Post gpm, assuming no other messages sent within inactivity timeout'''
        if utime.time() - self.gpm_posted_time > self.inactivity_timeout_s:
            self.post_gpm()

    def start_keepalive_timer(self):
        '''Initialize the timer to call self.keep_alive periodically'''
        self.keepalive_timer.init(
            period=KEEPALIVE_TIMER_PERIOD_S * 1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.keep_alive
        )

    def update_gpm(self, delta_ms: int):
        hz = 1000 / delta_ms
        gpm = self.gallons_per_tick * 60 * hz
        # If enough milliseconds have gone by, we assume the flow has stopped and reset flow to 0
        if delta_ms > self.no_flow_milliseconds:
            self.exp_gpm = 0
        elif self.exp_gpm == 0:
            self.exp_gpm = gpm
        else:
            tw_alpha = min(1, (delta_ms / TIME_WEIGHTING_MS) * self.alpha)
            self.exp_gpm= tw_alpha * gpm + (1 - tw_alpha) * self.exp_gpm
        
        if  self.prev_gpm is None:
            self.post_gpm()
        elif abs(self.exp_gpm - self.prev_gpm) > self.async_delta_gpm:
            self.post_gpm()

    # ---------------------------------
    # Posting relative timestamps
    # ---------------------------------
    
    def post_timestamp_list(self):
        if self.first_tick_ms is None:
            return
        url = self.base_url + f"/{self.actor_node_name}/ticklist-reed"
        payload = {
            "AboutNodeName": self.flow_node_name,
            "PicoStartMillisecond": self.first_tick_ms,
            "RelativeMillisecondList": self.relative_ms_list, 
            "TypeName": "ticklist.reed", 
            "Version": "000"
        }

        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting relative timestamps: {e}")
        gc.collect()
        self.relative_ms_list = []
        self.first_tick_ms = None

    # ---------------------------------
    # Receive and publish ticks
    # ---------------------------------

    def main_loop(self):

        time_since_0 = utime.ticks_ms()
        time_since_1 = utime.ticks_ms()
        self.first_tick_ms = None
        self.published_0_gpm = False

        while(True):  

            # Publish the list of relative ticks when it reaches a certain length
            if len(self.relative_ms_list) >= POST_LIST_LENGTH and not (self.posting_ticklist):
                self.posting_ticklist = True
                self.post_timestamp_list()
                self.posting_ticklist = False

            # States: down -> going up -> up -> going down -> down
            current_reading = self.pulse_pin.value()
            current_time_ms = utime.ticks_ms()
        
            # down -> going up
            if self.pin_state == PinState.DOWN and current_reading == 1:
                self.pin_state = PinState.GOING_UP
                time_since_1 = current_time_ms
                self.published_0_gpm = False
                # This is the state change we track for tick deltas
                if self.first_tick_ms is None:
                    self.first_tick_ms = current_time_ms
                    self.relative_ms_list.append(0)
                else:
                    relative_ms = current_time_ms - self.first_tick_ms
                    delta_ms = relative_ms - self.relative_ms_list[-1]
                    self.update_gpm(delta_ms)
                    self.relative_ms_list.append(relative_ms)
                    
            # going up -> going up
            elif self.pin_state == PinState.GOING_UP  and current_reading == 0:
                time_since_1 = current_time_ms

            # going up -> up
            elif self.pin_state == PinState.GOING_UP and current_reading == 1:
                if (current_time_ms - time_since_1) > self.deadband_milliseconds:
                    self.pin_state = PinState.UP
            
            # up -> going down
            elif self.pin_state == PinState.UP and current_reading == 0:
                self.pin_state = PinState.GOING_DOWN
                time_since_0 = current_time_ms

            # going down -> going down
            elif self.pin_state == PinState.GOING_DOWN  and current_reading == 1:
                time_since_0 = current_time_ms
                
            # going down -> down
            elif self.pin_state == PinState.GOING_DOWN and current_reading == 0:
                if (current_time_ms - time_since_0) > self.deadband_milliseconds:
                    self.pin_state = PinState.DOWN

            # Reporting 0 gpm
            if self.first_tick_ms is not None:
                time_since_last_tick = current_time_ms - self.first_tick_ms - self.relative_ms_list[-1]
                if time_since_last_tick > self.no_flow_milliseconds and not self.published_0_gpm:
                    self.update_gpm(1e9)
                    self.published_0_gpm = True
                
    def start(self):
        self.connect_to_wifi()
        self.update_code()
        self.update_app_config()
        self.start_keepalive_timer()
        self.state_init()
        print("Initialized")
        self.main_loop()

if __name__ == "__main__":
    p = PicoFlowReed()
    p.start()"""
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_tank_module_main():
    main_code = """import machine
import utime
import network
import ujson
import urequests
import ubinascii
import utime
import gc
import os

# ---------------------------------
# Constants
# ---------------------------------

# Configuration files
COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"

# Default parameters
DEFAULT_ACTOR_NAME = "tank"
DEFAULT_PICO_AB = "a"
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_CAPTURE_OFFSET_S = 0
DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS = 500
DEFAULT_SAMPLES = 1000
DEFAULT_NUM_SAMPLE_AVERAGES = 10
DEFAULT_REPORT_MICROVOLTS = True

# Other constants
ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27
CODE_UPDATE_PERIOD_S = 60

# ---------------------------------
# Main class
# ---------------------------------

class TankModule:

    def __init__(self):
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        self.load_comms_config()
        self.load_app_config()
        self.prev_mv0 = -1
        self.prev_mv1 = -1
        self.mv0 = None
        self.mv1 = None
        self.node_names = []
        self.keepalive_timer = machine.Timer(-1)

    def set_names(self):
        if self.actor_node_name is None:
            raise Exception("Needs actor node name or pico number to run. Reboot!")
        
        if self.pico_a_b == "a":
            self.node_names = [
                f"{self.actor_node_name}-depth1", 
                f"{self.actor_node_name}-depth2"
            ]
        elif self.pico_a_b == "b":
            self.node_names = [
                f"{self.actor_node_name}-depth3", 
                f"{self.actor_node_name}-depth4"
            ]
        else:
            raise Exception("PicoAB must be a or b")

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
                utime.sleep_ms(500)
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
        self.actor_node_name = app_config.get("ActorNodeName", DEFAULT_ACTOR_NAME)
        self.pico_a_b = app_config.get("PicoAB", DEFAULT_PICO_AB)
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        self.samples = app_config.get("Samples", DEFAULT_SAMPLES)
        self.num_sample_averages = app_config.get("NumSampleAverages", DEFAULT_NUM_SAMPLE_AVERAGES)
        self.capture_offset_milliseconds = app_config.get("CaptureOffsetS", DEFAULT_CAPTURE_OFFSET_S)
        self.async_capture_delta_micro_volts = app_config.get("AsyncCaptureDeltaMicroVolts", DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS)
        self.report_micro_volts = app_config.get("ReportMicroVolts", DEFAULT_REPORT_MICROVOLTS)

    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "PicoAB": self.pico_a_b,
            "CapturePeriodS": self.capture_period_s,
            "Samples": self.samples,
            "NumSampleAverages":self.num_sample_averages,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
            "ReportMicroVolts": self.report_micro_volts,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        url = self.base_url + "/tank-module-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "PicoAB": self.pico_a_b,
            "CapturePeriodS": self.capture_period_s,
            "Samples": self.samples,
            "NumSampleAverages": self.num_sample_averages,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
            "CaptureOffsetMilliseconds": self.capture_offset_milliseconds,
            "ReportMicroVolts": self.report_micro_volts,
            "TypeName": "tank.module.params",
            "Version": "000"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.pico_a_b = updated_config.get("PicoAB", self.pico_a_b)
                self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)
                self.samples = updated_config.get("Samples", self.samples)
                self.num_sample_averages = updated_config.get("NumSampleAverages", self.num_sample_averages)
                self.async_capture_delta_micro_volts = updated_config.get("AsyncCaptureDeltaMicroVolts", self.async_capture_delta_micro_volts)
                self.capture_offset_milliseconds = updated_config.get("CaptureOffsetMilliseconds", self.capture_offset_milliseconds)
                self.report_micro_volts = updated_config.get("ReportMicroVolts", self.report_micro_volts)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error sending tank module params: {e}")
            if 'main_previous.py' in os.listdir():
            # Try reverting to previous code (will only try once)
                os.rename('main_previous.py', 'main_revert.py')
                machine.reset()

    # ---------------------------------
    # Code updates
    # ---------------------------------

    def update_code(self):
        url = self.base_url + "/code-update"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "TypeName": "new.code",
            "Version": "000"
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
    
    # ---------------------------------
    # Posting microvolts
    # ---------------------------------

    def post_microvolts(self):
        if self.report_micro_volts:
            url = self.base_url + f"/{self.actor_node_name}/microvolts"
            payload = {
                "AboutNodeNameList": self.node_names,
                "MicroVoltsList": [self.mv0, self.mv1], 
                "TypeName": "microvolts", 
                "Version": "001"
            }
            headers = {'Content-Type': 'application/json'}
            json_payload = ujson.dumps(payload)
            try:
                response = urequests.post(url, data=json_payload, headers=headers)
                response.close()
            except Exception as e:
                print(f"Error posting microvolts: {e}")
        else:
            return
        
    def keep_alive(self, timer):
        '''Post microvolts'''
        self.post_microvolts()
    
    def start_keepalive_timer(self):
        '''Initialize the timer to post microvolts periodically'''
        self.keepalive_timer.init(
            period=self.capture_period_s * 1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.keep_alive
        )

    def main_loop(self):
        self.mv0 = self.adc0_micros()
        self.mv1 = self.adc1_micros()
        while True:
            self.mv0 = self.adc0_micros()
            self.mv1 = self.adc1_micros()
            if abs(self.mv0 - self.prev_mv0) > self.async_capture_delta_micro_volts:
                self.post_microvolts()
                self.prev_mv0 = self.mv0
            if abs(self.mv1 - self.prev_mv1) > self.async_capture_delta_micro_volts:
                self.post_microvolts()
                self.prev_mv1 = self.mv1
            utime.sleep_ms(100)

    def start(self):
        self.connect_to_wifi()
        self.update_code()
        self.update_app_config()
        self.set_names()
        #utime.sleep_ms(self.capture_offset_milliseconds)
        self.start_keepalive_timer()
        self.main_loop()

if __name__ == "__main__":
    t = TankModule()
    t.start()"""
    with open('main.py', 'w') as file:
        file.write(main_code)

# *************************
# 2/3 - APP_CONFIG PROVISION
# *************************

# -------------------------
# Tank module
# -------------------------

class tankmodule_provision:

    def __init__(self):
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        self.adc2 = machine.ADC(ADC2_PIN_NUMBER)
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        self.samples = SAMPLES
        self.total_reports = TOTAL_REPORTS
        self.num_recorded = 0

    def mv0(self):
        readings = []
        for _ in range(self.samples):
            # Read the raw ADC value (0-65535)
            readings.append(self.adc0.read_u16())
        voltages = list(map(lambda x: x * 3.3 / 65535, readings))
        return int(10**4 * sum(voltages) / self.samples) / 10
    
    def mv1(self):
        readings = []
        for _ in range(self.samples):
            # Read the raw ADC value (0-65535)
            readings.append(self.adc1.read_u16())
        voltages = list(map(lambda x: x * 3.3 / 65535, readings))
        return int(10**4 * sum(voltages) / self.samples) / 10

    def mv2(self):
        readings = []
        for _ in range(self.samples):
            # Read the raw ADC value (0-65535)
            readings.append(self.adc2.read_u16())
        voltages = list(map(lambda x: x * 3.3 / 65535, readings))
        return int(10**4 * sum(voltages) / self.samples) / 10
        
    def print_sample(self):
            report = f"{self.hw_uid}, {self.mv0() - PIN_0_OFFSET}, {self.mv1() - PIN_1_OFFSET}, {self.mv2()}"
            print(report)
            self.num_recorded += 1
    
    def set_name(self):
        got_a_or_b = False
        while not got_a_or_b:
            a_or_b = input("Tank Module pico a or b? Type 'a' or 'b': ")
            self.pico_a_b = a_or_b
            if a_or_b not in {'a', 'b'}:
                print("please enter a or b!")
            else:
                got_a_or_b = True
        
        got_tank_name = False
        while not got_tank_name:
            name = input(f"Tank Name: 'buffer', 'tank1', tank2', 'tank3': ")
            self.name = name
            if name not in {'buffer', 'tank1', 'tank2', 'tank3'}:
                print("bad tank name")
            else:
                got_tank_name = True
        self.actor_node_name = name
        config = {
            "ActorNodeName": self.actor_node_name,
            "PicoAB": self.pico_a_b,
        }
        with open("app_config.json", "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()
        # print("HW UID, Pin 0 mV, Pin 1 mV, Pin 2 mV (OFFSETS DONE ON PIN 0 and 1)")
        # while self.num_recorded < TOTAL_REPORTS:
        #     self.print_sample()

# -------------------------
# Flowmeter
# -------------------------

class flowmeter_provision:
    
    def set_name(self):

        # Get ActorNodeName
        got_actor_name = False
        while not got_actor_name:
            self.actor_name = input("Enter Actor name (e.g. 'pico-flow-reed', 'pico-flow-hall', 'pico-flow-hall-store'): ")
            if 'flow' not in self.actor_name:
                print("please include 'flow' in the actor name")
            else:
                got_actor_name = True
        
        # Get FlowNodeName
        got_flow_name = False
        while not got_flow_name:
            self.flow_name = input(f"Enter Flow name ('primary-flow', 'dist-flow', 'store-flow'): ")
            if self.flow_name not in {'primary-flow', 'dist-flow', 'store-flow'}:
                print("invalid flow name")
            else:
                got_flow_name = True

        # Save in app_config.json
        config = {
            "ActorNodeName": self.actor_name,
            "FlowNodeName": self.flow_name,
        }
        with open("app_config.json", "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()

# *************************
# 3/3 - MAIN CODE
# *************************

if __name__ == "__main__":

    # Get hardware ID
    pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
    hw_uid = f"pico_{pico_unique_id[-6:]}"
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

    # Connect to wifi

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    wlan.disconnect()
    while wlan.isconnected():
        utime.sleep(0.1)
    
    while not wlan.isconnected():

        wifi_name = input("Enter wifi name: ")
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

    # Connect to API

    connected_to_api = False
    while not connected_to_api:

        hostname = input("Enter hostname (e.g., 'fir2.local'): ")
        base_url = f"http://{hostname}:8000"
        url = base_url + "/new-pico"
        payload = {
            "HwUid": hw_uid,
            "TypeName": "new.pico",
            "Version": "000"
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
            print("There was an error connecting to the API: {e}. Please check the hostname and try again.")

    print(f"Connected to the API hosted in '{base_url}'.")

    # Write the parameters to comms_config.json

    comms_config_content = {
        "WifiName": wifi_name,
        "WifiPassword": wifi_pass, 
        "BaseUrl": base_url
    }
    with open('comms_config.json', 'w') as file:
        ujson.dump(comms_config_content, file)

    print(f"\n{'-'*40}\n[2/4] Success! Wrote 'comms_config.json' on the Pico.\n{'-'*40}\n")

    # -------------------------
    # Write app_config.json
    # -------------------------

    got_type = False
    while not got_type:
        type = input("Is this Pico associated to a tank module (enter '0') or a flowmeter (enter '1'): ")
        if type not in {'0','1'}:
            print('Please enter 0 or 1.')
        else:
            got_type = True

    if type == '0':
        p = tankmodule_provision()
        p.start()
    elif type == '1':
        p = flowmeter_provision()
        p.start()

    print(f"\n{'-'*40}\n[3/4] Success! Wrote 'app_config.json' on the Pico.\n{'-'*40}\n")

    # -------------------------
    # Write main.py
    # -------------------------

    # Read the actor node name
    with open('app_config.json', 'r') as file:
        config_content = ujson.load(file)
    name = config_content['ActorNodeName']

    if 'flow' in name:
        if 'hall' in name:
            print("This is a hall meter.")
            write_flow_hall_main()
        if 'reed' in name:
            print("This is a reed meter.")
            write_flow_reed_main()
    else:
        print("This is a tank module.")
        write_tank_module_main()

    print(f"\n{'-'*40}\n[4/4] Success! Wrote 'main.py' on the Pico.\n{'-'*40}\n")

    print("The Pico is set up. It is now ready to use.\nNote: you can delete this file from the Pico to save up space.")