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
DEFAULT_ACTOR_NAME = "pico-flow-slow"
DEFAULT_FLOW_NODE_NAME = "primary-flow"
DEFAULT_DEADBAND_MILLISECONDS = 300
DEFAULT_INACTIVITY_TIMEOUT_S = 60
DEFAULT_NO_FLOW_MILLISECONDS = 30_000

PULSE_PIN = 1



# *********************************************
# CONNECT TO WIFI
# *********************************************

class PicoFlowSlow:
    def __init__(self):
        self.hw_uid = get_hw_uid()
        self.load_comms_config()
        self.load_app_config()
        self.latest_timestamp_ms = None
        self.latest_hb_ms = None
        self.hb = 0
        # Define the pin 
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        # Set up interrupt
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)
        self.heartbeat_timer = machine.Timer(-1)
                                                                 
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
        self.deadband_milliseconds = app_config.get("DeadbandMilliseconds", DEFAULT_DEADBAND_MILLISECONDS)
        self.inactivity_timeout_s = app_config.get("InactivityTimeoutS", DEFAULT_INACTIVITY_TIMEOUT_S)
        self.no_flow_milliseconds = app_config.get("NoFlowMilliseconds", DEFAULT_NO_FLOW_MILLISECONDS)


    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "DeadbandMilliseconds": self.deadband_milliseconds,
            "InactivityTimeoutS": self.inactivity_timeout_s,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        url = self.base_url + "/flow_slow_params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "DeadbandMilliseconds": self.deadband_milliseconds,
            "InactivityTimeoutS": self.inactivity_timeout_s,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            "TypeName": "flow.slow.params",
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
                self.deadband_milliseconds = updated_config.get("DeadbandMilliseconds", self.deadband_milliseconds)
                self.inactivity_timeout_s = updated_config.get("InactivityTimeoutS", self.inactivity_timeout_s)
                self.no_flow_milliseconds = updated_config.get("NoFlowMilliseconds", self.no_flow_milliseconds)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error posting tick delta: {e}")

    def start_heartbeat_timer(self):
        # Initialize the timer to call self.check_hb periodically
        self.heartbeat_timer.init(
            period=3000, 
            mode=machine.Timer.PERIODIC,
            callback=self.check_hb
        )

    def start(self):
        self.connect_to_wifi()
        self.update_app_config()
        self.start_heartbeat_timer()
    
    def post_tick_delta(self, milliseconds: int):
        url = self.base_url + f"/{self.actor_node_name}/tick-delta"
        payload = {
            "AboutNodeName": self.flow_node_name,
            "Milliseconds": milliseconds, 
            "TypeName": "tick.delta", 
            "Version": "000"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting tick delta: {e}")
        gc.collect()
    
    def pulse_callback(self, pin):
        """
        Callback function to record the time interval in milliseconds between two 
        ticks of a reed-style flow meter. Ignores false positives due to jitter 
        occurring within the deadband threshold.
        """
        # Get the current timestamp in integer milliseconds
        current_timestamp_ms = utime.time_ns() // 1_000_000

        if self.latest_timestamp_ms is None:
            # Initialize the timestamp if this is the first pulse for this pin
            self.latest_timestamp_ms = current_timestamp_ms
            return

        # Calculate the time difference since the last pulse
        delta_ms = current_timestamp_ms - self.latest_timestamp_ms
        if delta_ms > self.deadband_milliseconds:
            # Update the latest timestamp
            self.latest_timestamp_ms = current_timestamp_ms
            if delta_ms < self.no_flow_milliseconds:
                # Post the tick delta if it exceeds the deadband threshold AND is less than the no flow milliseconds
                self.post_tick_delta(milliseconds=delta_ms)

    def post_hb(self):
        url = self.base_url + f"/{self.actor_node_name}/hb"
        self.hb = (self.hb + 1) % 16
        hbstr = "{:x}".format(self.hb)
        payload =  {"MyHex": hbstr, "TypeName": "hb", "Version": "000"}
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting hb {e}")
        gc.collect()
    
    def check_hb(self, timer):
        """
        Publish a heartbeat, assuming no other messages sent within inactivity timeout
        """
        latest_ms = max((value for value in [self.latest_timestamp_ms, self.latest_hb_ms] if value is not None), default=0)
        current_timestamp_ms = utime.time_ns() // 1_000_000
        if (current_timestamp_ms - latest_ms) / 10**3 > self.inactivity_timeout_s:
            self.post_hb()
            self.latest_hb_ms = current_timestamp_ms


if __name__ == "main":
    p = PicoFlowSlow()
    p.start()