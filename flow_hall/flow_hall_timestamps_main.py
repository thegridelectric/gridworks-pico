import machine
import utime
import network
import ujson
import urequests
import time
import gc
from utils import get_hw_uid

# *********************************************
# CONFIG FILE AND DEFAULT PARAMS
# *********************************************

COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"

# *********************************************
# CONSTANTS
# *********************************************

DEFAULT_ACTOR_NAME = "pico-flow-hall"
DEFAULT_FLOW_NODE_NAME = "primary-flow"
DEFAULT_ALPHA_TIMES_100 = 10
DEFAULT_ASYNC_CAPTURE_DELTA_HZ = 3
DEFAULT_PUBLISH_STAMPS_PERIOD_S = 10
DEFAULT_INACTIVITY_TIMEOUT_S = 60
DEFAULT_EXP_WEIGHTING_MS = 40

PULSE_PIN = 28 # 7 pins down on the hot side
CODE_UPDATE_PERIOD_S = 60*5
KEEPALIVE_TIMER_PERIOD_S = 3
NO_FLOW_MILLISECONDS = 1000
ACTIVELY_PUBLISHING_AFTER_POST_MILLISECONDS = 200
MAIN_LOOP_MILLISECONDS = 100

# *********************************************
# CONNECT TO WIFI
# *********************************************

class PicoFlowHall:
    def __init__(self):
        # Define the pin 
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self.hw_uid = get_hw_uid()
        self.load_comms_config()
        self.load_app_config()
        # variables for tracking async reports of simple exponential weighted frequency
        self.timestamps = []
        self.exp_hz = 0
        self.prev_hz = None
        self.hz_posted_time = utime.time()
        # variables for tracking tick list
        self.last_ticks_sent = utime.time()
        # there is a time lag between posting the ticks and starting off capturing ticks
        # this is the microseconds of the first tick in a batch
        self.latest_ts = None
        self.actively_publishing = False
        self.keepalive_timer = machine.Timer(-1)
        self.update_code_timer = machine.Timer(-1)
                                                                 
    def load_comms_config(self):
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
    
    def load_app_config(self):
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
    
    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncCaptureDeltaHz": self.async_capture_delta_hz,
            "PublishStampsPeriodS": self.publish_stamps_period_s,
            "InactivityTimeoutS": self.inactivity_timeout_s,
            "ExpWeightingMs": self.exp_weighting_ms,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
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
            "TypeName": "flow.hall.params",
            "Version": "000"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                # Update configuration with the server response
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.flow_node_name = updated_config.get("FlowNodeName", self.flow_node_name)
                self.alpha = updated_config.get("AlphaTimes100", self.alpha * 100) / 100
                self.async_capture_delta_hz = updated_config.get("AsyncCaptureDeltaHz", self.async_capture_delta_hz)
                self.publish_stamps_period_s = updated_config.get("PublishStampsPeriodS", self.publish_stamps_period_s)
                self.inactivity_timeout_s = updated_config.get("InactivityTimeoutS", self.inactivity_timeout_s)
                self.exp_weighting_ms = updated_config.get("ExpWeightingMs", self.exp_weighting_ms)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error posting tick delta: {e}")

    def post_ticklist(self):
        url = self.base_url + f"/{self.actor_node_name}/ticklist000"
        payload = {
            "AboutNodeName": self.flow_node_name,
            "TimestampNsList": self.timestamps,
            "TypeName": "ticklist", 
            "Version": "000"
            }
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting ticklist000: {e}")
        gc.collect()
        self.relative_us_list = []
        self.first_tick_us = None
        self.timestamps = []


    def pulse_callback(self, pin):
        # Only add ticks when not actively publishing; otherwise adds too much noise
        if not self.actively_publishing:
            current_timestamp_us = utime.time_ns()
            if self.latest_ts is None:
                 # Initialize the timestamp if this is the first pulse for this pin
                self.latest_ts = current_timestamp_us
                self.timestamps.append(current_timestamp_us)
                return
            self.timestamps.append(current_timestamp_us)
            self.latest_ts = current_timestamp_us

    
    def update_code(self, timer):
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
    
    def start_code_update_timer(self):
        # start the periodic check for code updates
        self.update_code_timer.init(
            period=CODE_UPDATE_PERIOD_S * 1000,
            mode=machine.Timer.PERIODIC,
            callback=self.update_code
        )

    def main_loop(self):
        while True:
            utime.sleep_ms(MAIN_LOOP_MILLISECONDS)
            if utime.time() - self.last_ticks_sent > self.publish_stamps_period_s:
                # Only post if there is some flow
                if len(self.timestamps) > 0:
                    self.actively_publishing = True
                    self.post_ticklist()
                    self.last_ticks_sent = utime.time()
                    # utime.sleep_ms(ACTIVELY_PUBLISHING_AFTER_POST_MILLISECONDS)
                    self.actively_publishing = False

    def start(self):
        self.connect_to_wifi()
        self.update_app_config()
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)
        self.start_code_update_timer()
        self.main_loop()

if __name__ == "__main__":
    p = PicoFlowHall()
    p.start()