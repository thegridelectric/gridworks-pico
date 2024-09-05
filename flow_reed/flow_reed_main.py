import machine
import utime
import network
import ujson
import urequests
import time
import gc
import os
from utils import get_hw_uid

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
DEFAULT_SYNC_REPORT_GPM = True

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
        self.sync_report_gpm = app_config.get("SyncReportGpm", DEFAULT_SYNC_REPORT_GPM)

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
            "SyncReportGpm": self.sync_report_gpm,
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
            "SyncReportGpm": self.sync_report_gpm,
            "TypeName": "flow.reed.params",
            "Version": "002"
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
                self.sync_report_gpm = updated_config.get("SyncReportGpm", self.sync_report_gpm)
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
        if self.sync_report_gpm:
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
    p.start()