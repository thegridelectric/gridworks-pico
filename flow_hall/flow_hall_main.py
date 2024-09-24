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
DEFAULT_ACTOR_NAME = "pico-flow-hall"
DEFAULT_FLOW_NODE_NAME = "primary-flow"
DEFAULT_ALPHA_TIMES_100 = 10
DEFAULT_ASYNC_CAPTURE_DELTA_HZ = 1
DEFAULT_EXP_WEIGHTING_MS = 40
DEFAULT_PUBLISH_STAMPS_PERIOD_S = 10
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_REPORT_HZ = True
DEFAULT_NO_FLOW_MILLISECONDS = 1000

# Other constants
PULSE_PIN = 28 # 7 pins down on the hot side
ACTIVELY_PUBLISHING_AFTER_POST_MILLISECONDS = 200
MAIN_LOOP_MILLISECONDS = 100

# ---------------------------------
# Main class
# ---------------------------------

class PicoFlowHall:

    def __init__(self):
        # Unique ID
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        # Pins
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        # Load configuration files
        self.load_comms_config()
        self.load_app_config()
        # Reporting exp weighted average Hz
        self.exp_hz = 0
        self.prev_hz = None
        self.hz_posted_time = utime.time()
        # Reporting relative ticklists
        self.first_tick_us = None
        self.relative_us_list = []
        self.last_ticks_sent = utime.time()
        self.actively_publishing = False
        # Synchronous reporting on the minute
        self.capture_offset_seconds = 0
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
        self.alpha = app_config.get("AlphaTimes100", DEFAULT_ALPHA_TIMES_100) / 100
        self.async_capture_delta_hz = app_config.get("AsyncCaptureDeltaHz", DEFAULT_ASYNC_CAPTURE_DELTA_HZ)
        self.exp_weighting_ms = app_config.get("ExpWeightingMs", DEFAULT_EXP_WEIGHTING_MS)
        self.publish_stamps_period_s = app_config.get("PublishStampsPeriodS", DEFAULT_PUBLISH_STAMPS_PERIOD_S)
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        self.report_hz = app_config.get("ReportHz", DEFAULT_REPORT_HZ)
        self.no_flow_milliseconds = app_config.get("NoFlowMilliseconds", DEFAULT_NO_FLOW_MILLISECONDS)
    
    def save_app_config(self):
        '''Save the parameters to the app_config file'''
        config = {
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncCaptureDeltaHz": self.async_capture_delta_hz,
            "ExpWeightingMs": self.exp_weighting_ms,
            "PublishStampsPeriodS": self.publish_stamps_period_s,
            "CapturePeriodS": self.capture_period_s,
            "ReportHz": self.report_hz,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        '''Post current parameters, and update parameters based on the server response'''
        url = self.base_url + f"/{self.actor_node_name}/flow-hall-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncCaptureDeltaHz": self.async_capture_delta_hz,
            "ExpWeightingMs": self.exp_weighting_ms,
            "PublishStampsPeriodS": self.publish_stamps_period_s,
            "CapturePeriodS": self.capture_period_s,
            "ReportHz": self.report_hz,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            "TypeName": "flow.hall.params",
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
                self.alpha = updated_config.get("AlphaTimes100", self.alpha * 100) / 100
                self.async_capture_delta_hz = updated_config.get("AsyncCaptureDeltaHz", self.async_capture_delta_hz)
                self.exp_weighting_ms = updated_config.get("ExpWeightingMs", self.exp_weighting_ms)
                self.publish_stamps_period_s = updated_config.get("PublishStampsPeriodS", self.publish_stamps_period_s)
                self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)
                self.report_hz = updated_config.get("ReportHz", self.report_hz)
                self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
                self.no_flow_milliseconds = updated_config.get("NoFlowMilliseconds", self.no_flow_milliseconds)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error posting flow.hall.params: {e}")
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
    # Posting Hz
    # ---------------------------------

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
        '''Post Hz if none were posted within the last minute'''
        if utime.time() - self.hz_posted_time > 55 and self.report_hz:
            self.post_hz()

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

    # ---------------------------------
    # Posting relative timestamps
    # ---------------------------------
            
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
        self.update_code()
        self.update_app_config()
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)
        utime.sleep(self.capture_offset_seconds)
        self.start_keepalive_timer()
        self.main_loop()

if __name__ == "__main__":
    p = PicoFlowHall()
    p.start()