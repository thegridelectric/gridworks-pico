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

# Default parameters
DEFAULT_ACTOR_NAME = "pico-flow-reed"
DEFAULT_FLOW_NODE_NAME = "primary-flow"
DEFAULT_ALPHA_TIMES_100 = 10
DEFAULT_ASYNC_DELTA_GPM_TIMES_100 = 10
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_REPORT_GPM = True
DEFAULT_NO_FLOW_MILLISECONDS = 3_000
DEFAULT_GALLONS_PER_TICK_TIMES_10000 = 748
DEFAULT_DEADBAND_MILLISECONDS = 10

# Other constants
PULSE_PIN = 28 # 7 pins down on the hot side
TIME_WEIGHTING_MS = 800
POST_LIST_LENGTH = 100

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
        # Unique ID
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        # Pins
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self.pin_state = None # will be initialized as PinState.DOWN
        # Load configuration files
        self.load_comms_config()
        self.load_app_config()
        # Reporting exp weighted average Hz
        self.exp_gpm = 0
        self.prev_gpm = None
        self.gpm_posted_time = utime.time()
        # Reporting relative ticklists
        self.first_tick_ms = None
        self.relative_ms_list = []
        self.last_ticks_sent = utime.time()
        self.posting_ticklist = False
        # Synchronous reporting on the minute
        self.capture_offset_seconds = 0
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
        self.alpha = app_config.get("AlphaTimes100", DEFAULT_ALPHA_TIMES_100) / 100
        self.async_delta_gpm = app_config.get("AsyncDeltaGpmTimes100", DEFAULT_ASYNC_DELTA_GPM_TIMES_100) / 100        
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        self.report_gpm = app_config.get("ReportGpm", DEFAULT_REPORT_GPM)
        self.no_flow_milliseconds = app_config.get("NoFlowMilliseconds", DEFAULT_NO_FLOW_MILLISECONDS)
        self.gallons_per_tick = app_config.get("GallonsPerTickTimes10000", DEFAULT_GALLONS_PER_TICK_TIMES_10000) / 10_000
        self.deadband_milliseconds = app_config.get("DeadbandMilliseconds", DEFAULT_DEADBAND_MILLISECONDS)

    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncDeltaGpmTimes100": int(self.async_delta_gpm * 100),
            "CapturePeriodS": self.capture_period_s,
            "ReportGpm": self.report_gpm,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            "GallonsPerTickTimes10000": int(self.gallons_per_tick * 10_000),
            "DeadbandMilliseconds": self.deadband_milliseconds,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        url = self.base_url + f"/{self.actor_node_name}/flow-reed-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncDeltaGpmTimes100": int(self.async_delta_gpm * 100),
            "CapturePeriodS": self.capture_period_s,
            "ReportGpm": self.report_gpm,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            "GallonsPerTickTimes10000": int(self.gallons_per_tick * 10_000),
            "DeadbandMilliseconds": self.deadband_milliseconds,
            "TypeName": "flow.reed.params",
            "Version": "100"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.flow_node_name = updated_config.get("FlowNodeName", self.flow_node_name)
                self.alpha = updated_config.get("AlphaTimes100", int(self.alpha * 100)) / 100
                self.async_delta_gpm = updated_config.get("AsyncDeltaGpmTimes100", int(self.async_delta_gpm * 100)) / 100
                self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)
                self.deadband_milliseconds = updated_config.get("DeadbandMilliseconds", self.deadband_milliseconds)
                self.no_flow_milliseconds = updated_config.get("NoFlowMilliseconds", self.no_flow_milliseconds)
                self.gallons_per_tick = updated_config.get("GallonsPerTickTimes10000", int(self.gallons_per_tick*10_000)) / 10_000
                self.report_gpm = updated_config.get("ReportGpm", self.report_gpm)
                self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error posting flow.reed.params: {e}")
            if 'main_previous.py' in os.listdir():
                print("Reverting to previous code.")
                os.rename('main_previous.py', 'main_revert.py')
                machine.reset()

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
    # Posting GPM
    # ---------------------------------

    def post_gpm(self):
        url = self.base_url +  f"/{self.actor_node_name}/gpm"
        payload = {
            "FlowNodeName": self.flow_node_name,
            "ValueTimes100": int(100 * self.exp_gpm),
            "TypeName": "gpm", 
            "Version": "100"
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

    def keep_alive(self, timer):
        '''Post GPM if none were posted within the last minute'''
        if utime.time() - self.gpm_posted_time > 55 and self.report_gpm:
            self.post_gpm()

    def start_keepalive_timer(self):
        '''Initialize the timer to call self.keep_alive periodically'''
        self.keepalive_timer.init(
            period=self.capture_period_s * 1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.keep_alive
        )

    def update_gpm(self, delta_ms: int):
        hz = 1e3 / delta_ms
        gpm = hz * self.gallons_per_tick * 60
        if delta_ms > self.no_flow_milliseconds:
            self.exp_gpm = 0
        elif self.exp_gpm == 0:
            self.exp_gpm = gpm
        else:
            tw_alpha = min(1, (delta_ms / TIME_WEIGHTING_MS) * self.alpha)
            self.exp_gpm= tw_alpha * gpm + (1 - tw_alpha) * self.exp_gpm
        if  (self.prev_gpm is None) or abs(self.exp_gpm - self.prev_gpm) > self.async_delta_gpm:
            self.post_gpm()

    # ---------------------------------
    # Posting relative timestamps
    # ---------------------------------
    
    def post_ticklist(self):
        if self.first_tick_ms is None:
            return
        url = self.base_url + f"/{self.actor_node_name}/ticklist-reed"
        payload = {
            "FlowNodeName": self.flow_node_name,
            "PicoStartMillisecond": self.time_at_first_tick_ms,
            "RelativeMillisecondList": self.relative_ms_list, 
            "TypeName": "ticklist.reed", 
            "Version": "100"
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

        self.time_at_first_tick_ms = utime.time()*1000
        time_since_0 = utime.ticks_ms()
        time_since_1 = utime.ticks_ms()
        self.first_tick_ms = None
        self.published_0_gpm = False

        while(True):  

            # Publish the list of relative ticks when it reaches a certain length
            if len(self.relative_ms_list) >= POST_LIST_LENGTH and not (self.posting_ticklist):
                self.posting_ticklist = True
                self.post_ticklist()
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
                    self.time_at_first_tick_ms += utime.ticks_ms()
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
        utime.sleep(self.capture_offset_seconds)
        self.start_keepalive_timer()
        self.state_init()
        print("Initialized")
        self.main_loop()

if __name__ == "__main__":
    p = PicoFlowReed()
    p.start()