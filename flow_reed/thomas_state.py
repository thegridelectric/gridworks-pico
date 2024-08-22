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
DEFAULT_ACTOR_NAME = "pico-flow-reed"
DEFAULT_FLOW_NODE_NAME = "primary-flow"
DEFAULT_DEADBAND_MILLISECONDS = 10
DEFAULT_INACTIVITY_TIMEOUT_S = 60
DEFAULT_NO_FLOW_MILLISECONDS = 30_000


DEFAULT_PUBLISH_GPM = True
DEFAULT_PUBLISH_TICK_DELTAS = False

DEFAULT_GALLONS_PER_TICK_TIMES_10000 = 748
DEFAULT_ALPHA_TIMES_100 = 10
DEFAULT_ASYNC_DELTA_GPM_TIMES_100 = 10

PULSE_PIN = 0 # This is pin 1
TIME_WEIGHTING_MS = 800

class PinState:
    GOING_UP = 0
    UP = 1
    GOING_DOWN = 2
    DOWN = 3

# *********************************************
# CONNECT TO WIFI
# *********************************************

class PicoFlowReed:
    def __init__(self):
        self.hw_uid = get_hw_uid()
        self.load_comms_config()
        self.load_app_config()
        self.latest_timestamp_ms = None
        self.latest_hb_ms = None
        self.hb = 0
        self.pin_state = PinState.UP
        self.exp_gpm = 0
        self.prev_gpm = None
        # Define the pin 
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
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
        self.publish_gpm = app_config.get("PublishGpm", DEFAULT_PUBLISH_GPM)
        self.publish_tick_deltas = app_config.get("PublishTickDeltas", DEFAULT_PUBLISH_TICK_DELTAS)
        alpha_times_100 = app_config.get("AlphaTimes100", DEFAULT_ALPHA_TIMES_100)
        gallons_per_tick_times_10000 = app_config.get("GallonsPerTickTimes10000", DEFAULT_GALLONS_PER_TICK_TIMES_10000)
        self.gallons_per_tick = gallons_per_tick_times_10000 / 10_000
        self.alpha = alpha_times_100 / 100
        async_delta_gpm_times_100 = app_config.get("AsyncDeltaGpmTimes100", DEFAULT_ASYNC_DELTA_GPM_TIMES_100)
        self.async_delta_gpm = async_delta_gpm_times_100 / 100

    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "DeadbandMilliseconds": self.deadband_milliseconds,
            "InactivityTimeoutS": self.inactivity_timeout_s,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            "PublishGpm": self.publish_gpm,
            "PublishTickDeltas": self.publish_tick_deltas,
            "GallonsPerTickTimes10000": int(self.gallons_per_tick * 10_000),
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncDeltaGpmTimes100": int(self.async_delta_gpm * 100),
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
            "PublishGpm": self.publish_gpm,
            "PublishTickDeltas": self.publish_tick_deltas,
            "GallonsPerTickTimes10000": int(self.gallons_per_tick * 10_000),
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncDeltaGpmTimes100": int(self.async_delta_gpm * 100),
            "TypeName": "flow.reed.params",
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
                self.publish_gpm = updated_config.get("PublishGpm", self.publish_gpm)
                self.publish_tick_deltas = updated_config.get("PublishTickDeltas", self.publish_tick_deltas)
                gallons_per_tick_times_10000 = updated_config.get("GallonsPerTickTimes10000", int(self.gallons_per_tick*10_000))
                self.gallons_per_tick = gallons_per_tick_times_10000 / 10_000
                alpha_times_100 = updated_config.get("AlphaTimes100", int(self.alpha * 100))
                self.alpha = alpha_times_100 / 100
                async_delta_gpm_times_100 = updated_config.get("AsyncDeltaGpmTimes100", int(self.async_delta_gpm * 100))
                self.async_delta_gpm = async_delta_gpm_times_100 / 100
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error posting flow.reed.params: {e}")
    
    def post_gpm(self):
        if not self.publish_gpm:
            return
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
            print(f"Error posting hz: {e}")
        gc.collect()
        self.prev_gpm = self.exp_gpm

    def update_gpm(self, delta_ms: int):
        hz = 1000 / delta_ms
        gpm = self.gallons_per_tick * 60 * hz
        # If enough milliseconds have gone by, we assume the flow has stopped and reset flow to 0
        if delta_ms > self.no_flow_milliseconds:
            self.exp_gpm= 0
        elif self.exp_gpm == 0:
            self.exp_gpm = gpm
        else:
            tw_alpha = min(1, (delta_ms / TIME_WEIGHTING_MS) * self.alpha)
            self.exp_gpm= tw_alpha * gpm + (1 - tw_alpha) * self.exp_gpm
    
    def post_tick_delta(self, milliseconds: int):
        if not self.publish_tick_deltas:
            return
        url = self.base_url + f"/{self.actor_node_name}/tick-delta"
        payload = {
            "AboutNodeName": self.flow_node_name,
            "Milliseconds": int(milliseconds), 
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

    def start_heartbeat_timer(self):
        # Initialize the timer to call self.check_hb periodically
        self.heartbeat_timer.init(
            period=3000, 
            mode=machine.Timer.PERIODIC,
            callback=self.check_hb
        )

    def check_state(self):
        ms_since_0 = utime.ticks_ms()
        ms_since_1 = utime.ticks_ms()

        while(True):  
            # States: going up -> up -> going down -> down
            current_reading = self.pulse_pin.value()
            current_time_ms = utime.ticks_ms()
                        
            # Down -> going up
            if self.pin_state == PinState.DOWN and current_reading == 1:
                # This is the tick we track for tick deltas
                #use the delta we need for calculating gpm and/or tick deltas
                delta_ms = current_time_ms - self.latest_timestamp_ms
                self.latest_timestamp_ms = current_time_ms
                self.update_gpm(delta_ms)
                if  (self.prev_gpm is None) or \
                    abs(self.exp_gpm - self.prev_gpm) > self.async_delta_gpm:
                    self.post_gpm()
                if delta_ms < self.no_flow_milliseconds:
                    self.post_tick_delta(delta_ms)
                ms_since_1 = current_time_ms

            # Still in going up phase
            elif self.pin_state == PinState.GOING_UP  and current_reading == 0:
                ms_since_1 = current_time_ms

            # Going up -> up
            elif self.pin_state == PinState.GOING_UP and current_reading == 1:
                if (current_time_ms - ms_since_1) > self.deadband_milliseconds: # if there has been more than 10ms of 1s
                    self.pin_state = PinState.UP
            
            # Up -> going down
            elif self.pin_state == PinState.UP and current_reading == 0:
                self.pin_state = PinState.GOING_DOWN

            # Still in going down phase
            elif self.pin_state == PinState.GOING_DOWN  and current_reading == 1:
                ms_since_0 = current_time_ms
                
            # Going down -> down
            elif self.pin_state == PinState.GOING_DOWN and current_reading == 0:
                if (current_time_ms - ms_since_0) > self.deadband_milliseconds: # if there has been more than 10ms of 0s
                    self.pin_state = PinState.DOWN
            
            #print(f"State is {self.pin_state}")
            

    def start(self):
        self.connect_to_wifi()
        self.update_app_config()
        #self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)
        self.start_heartbeat_timer()
        self.check_state()

    

if __name__ == "__main__":
    p = PicoFlowReed()
    p.start()