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
DEFAULT_DEADBAND_MILLISECONDS = 300
DEFAULT_INACTIVITY_TIMEOUT_S = 60
DEFAULT_NO_FLOW_MILLISECONDS = 30_000
DEFAULT_PUBLISH_HZ = True
DEFAULT_PUBLISH_TICK_DELTAS = False

# EKM Meter gives a tick every 1/100th of a cubic foot, or every 0.0748 gallons
DEFAULT_GALLONS_PER_TICK_0_TIMES_10000 = 748
DEFAULT_GALLONS_PER_TICK_1_TIMES_10000 = 748
DEFAULT_GALLONS_PER_TICK_2_TIMES_10000 = 748

DEFAULT_ALPHA_TIMES_100 = 10
DEFAULT_ASYNC_DELTA_GPM_TIMES_100 = 10

PULSE_0_PIN = 0
PULSE_1_PIN = 1
PULSE_2_PIN = 2

NAME_BY_PIN = {
    PULSE_0_PIN: "dist-flow",
    PULSE_1_PIN: "primary-flow",
    PULSE_2_PIN: "store-flow"
}

TIME_WEIGHTING_MS = 800
# *********************************************
# CONNECT TO WIFI
# *********************************************

class PicoFlowSlow:
    def __init__(self):
        self.hw_uid = get_hw_uid()
        self.load_comms_config()
        self.load_app_config()
        self.latest_timestamps_ms = {PULSE_0_PIN: None, PULSE_1_PIN: None, PULSE_2_PIN: None, "hb": None}
        self.hb = 0
        self.exp_gpm = {PULSE_0_PIN: 0, PULSE_1_PIN: 0, PULSE_2_PIN: 0}
        self.prev_gpm = {PULSE_0_PIN: None, PULSE_1_PIN: None, PULSE_2_PIN: None}

        # Define the pin objects
        self.pulse_0_pin = machine.Pin(PULSE_0_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self.pulse_1_pin = machine.Pin(PULSE_1_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self.pulse_2_pin = machine.Pin(PULSE_2_PIN, machine.Pin.IN, machine.Pin.PULL_UP)

        # Set up interrupts for each pin
        self.pulse_0_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_0_callback)
        self.pulse_1_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_1_callback)
        self.pulse_2_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_2_callback)
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
        self.deadband_milliseconds = app_config.get("DeadbandMilliseconds", DEFAULT_DEADBAND_MILLISECONDS)
        self.inactivity_timeout_s = app_config.get("InactivityTimeoutS", DEFAULT_INACTIVITY_TIMEOUT_S)
        self.no_flow_milliseconds = app_config.get("NoFlowMilliseconds", DEFAULT_NO_FLOW_MILLISECONDS)
        self.publish_gpm = app_config.get("PublishGpm", DEFAULT_PUBLISH_HZ)
        self.publish_tick_deltas = app_config.get("PublishTickDeltas", DEFAULT_PUBLISH_TICK_DELTAS)
        self.gallons_per_tick = {}
        gallons_per_tick_0_times_10000 = app_config.get("GallonsPerTick0Times10000", DEFAULT_GALLONS_PER_TICK_0_TIMES_10000)
        gallons_per_tick_1_times_10000 = app_config.get("GallonsPerTick1Times10000", DEFAULT_GALLONS_PER_TICK_1_TIMES_10000)
        gallons_per_tick_2_times_10000 = app_config.get("GallonsPerTick2Times10000", DEFAULT_GALLONS_PER_TICK_2_TIMES_10000)
        self.gallons_per_tick[0] = gallons_per_tick_0_times_10000 / 10_000
        self.gallons_per_tick[1] = gallons_per_tick_1_times_10000 / 10_000
        self.gallons_per_tick[2] = gallons_per_tick_2_times_10000 / 10_000
        alpha_times_100 = app_config.get("AlphaTimes100", DEFAULT_ALPHA_TIMES_100)
        self.alpha = alpha_times_100 / 100
        async_delta_gpm_times_100 = app_config.get("AsyncDeltaGpmTimes100", DEFAULT_ASYNC_DELTA_GPM_TIMES_100)
        self.async_delta_gpm = async_delta_gpm_times_100 / 100

    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "DeadbandMilliseconds": self.deadband_milliseconds,
            "InactivityTimeoutS": self.inactivity_timeout_s,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            "PublishGpm": self.publish_gpm,
            "PublishTickDeltas": self.publish_tick_deltas,
            "GallonsPerTick0Times10000": int(self.gallons_per_tick[0] * 10_000),
            "GallonsPerTick1Times10000": int(self.gallons_per_tick[1] * 10_000),
            "GallonsPerTick2Times10000": int(self.gallons_per_tick[2] * 10_000),
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncDeltaGpmTimes100": int(self.async_delta_gpm * 100),
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        url = self.base_url + "/pico_flow_slow_params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "DeadbandMilliseconds": self.deadband_milliseconds,
            "InactivityTimeoutS": self.inactivity_timeout_s,
            "NoFlowMilliseconds": self.no_flow_milliseconds,
            "PublishGpm": self.publish_gpm,
            "PublishTickDeltas": self.publish_tick_deltas,
            "GallonsPerTick0Times10000": int(self.gallons_per_tick[0] * 10_000),
            "GallonsPerTick1Times10000": int(self.gallons_per_tick[1] * 10_000),
            "GallonsPerTick2Times10000": int(self.gallons_per_tick[2] * 10_000),
            "AlphaTimes100": int(self.alpha * 100),
            "AsyncDeltaGpmTimes100": int(self.async_delta_gpm * 100),
            "TypeName": "pico.flow.slow.params",
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
                self.deadband_milliseconds = updated_config.get("DeadbandMilliseconds", self.deadband_milliseconds)
                self.inactivity_timeout_s = updated_config.get("InactivityTimeoutS", self.inactivity_timeout_s)
                self.no_flow_milliseconds = updated_config.get("NoFlowMilliseconds", self.no_flow_milliseconds)
                self.publish_gpm = updated_config.get("PublishGpm", self.publish_gpm)
                self.publish_tick_deltas = updated_config.get("PublishTickDeltas", self.publish_tick_deltas)
                gallons_per_tick_0_times_10000 = updated_config.get("GallonsPerTick0Times10000", int(self.gallons_per_tick[0]*10_000))
                self.gallons_per_tick[0] = gallons_per_tick_0_times_10000 / 10_000
                gallons_per_tick_1_times_10000 = updated_config.get("GallonsPerTick1Times10000", int(self.gallons_per_tick[1]*10_000))
                self.gallons_per_tick[1] = gallons_per_tick_1_times_10000 / 10_000
                gallons_per_tick_2_times_10000 = updated_config.get("GallonsPerTick2Times10000", int(self.gallons_per_tick[2]*10_000))
                self.gallons_per_tick[2] = gallons_per_tick_2_times_10000 / 10_000
                alpha_times_100 = updated_config.get("AlphaTImes100", int(self.alpha * 100))
                self.alpha = alpha_times_100 / 100
                async_delta_gpm_times_100 = updated_config.get("AsyncDeltaGpmTimes100", int(self.async_delta_gpm * 100))
                self.async_delta_gpm = async_delta_gpm_times_100 / 100
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
    
    def post_gpm(self, pin_number: int):
        if not self.publish_gpm:
            return
        node_name = NAME_BY_PIN[pin_number]
        url = self.base_url +  f"/{self.actor_node_name}/gpm"
        payload = {
            "AboutNodeName": node_name,
            "ValueTimes100": int(100 * self.exp_gpm[pin_number]),
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
        self.prev_gpm[pin_number] = self.exp_gpm[pin_number]
        
    def post_tick_delta(self, pin_number: int, milliseconds: int):
        if not self.publish_tick_deltas:
            return
        node_name = NAME_BY_PIN[pin_number]
        url = self.base_url + f"/{self.actor_node_name}/tick-delta"
        payload = {
            "AboutNodeName": node_name,
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
    
    def update_gpm(self, pin_number: int, delta_ms: int):
        hz = 1000 / delta_ms
        gpm = self.gallons_per_tick[pin_number] * 60 * hz
        # If enough milliseconds have gone by, we assume the flow has stopped and reset flow to 0
        if delta_ms > self.no_flow_milliseconds:
            self.exp_gpm[pin_number] = 0
        elif self.exp_gpm[pin_number] == 0:
            self.exp_gpm[pin_number] = gpm
        else:
            tw_alpha = min(1, (delta_ms / TIME_WEIGHTING_MS) * self.alpha)
            self.exp_gpm[pin_number] = tw_alpha * gpm + (1 - tw_alpha) * self.exp_gpm[pin_number]
    
    def pulse_callback(self, pin_number: int):
        """
        Callback function to record the time interval in milliseconds between two 
        ticks of a reed-style flow meter. Ignores false positives due to jitter 
        occurring within the deadband threshold.
        """
        # Get the current timestamp in integer milliseconds
        current_timestamp_ms = utime.time_ns() // 1_000_000

        if self.latest_timestamps_ms[pin_number] is None:
            # Initialize the timestamp if this is the first pulse for this pin
            self.latest_timestamps_ms[pin_number] = current_timestamp_ms
            return

        # Calculate the time difference since the last pulse
        delta_ms = current_timestamp_ms - self.latest_timestamps_ms[pin_number]
        if delta_ms > self.deadband_milliseconds:
            # Update the latest timestamp and the exponential weighted avg gpm
            self.latest_timestamps_ms[pin_number] = current_timestamp_ms
            self.update_gpm(pin_number=pin_number, delta_ms=delta_ms)
            if  (self.prev_gpm[pin_number] is None) or \
                abs(self.exp_gpm[pin_number] - self.prev_gpm[pin_number]) > self.async_delta_gpm:
                self.post_gpm(pin_number)
            if delta_ms < self.no_flow_milliseconds:
                # Post the tick delta if it exceeds the deadband threshold AND is less than the no flow milliseconds
                self.post_tick_delta(pin_number=pin_number, milliseconds=delta_ms)
            
    
    def pulse_0_callback(self, pin):
        self.pulse_callback(0)

    def pulse_1_callback(self, pin):
        self.pulse_callback(1)

    def pulse_2_callback(self, pin):
        self.pulse_callback(2)

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
        latest_ms = max((value for value in self.latest_timestamps_ms.values() if value is not None), default=0)
        current_timestamp_ms = utime.time_ns() // 1_000_000
        if (current_timestamp_ms - latest_ms) / 10**3 > self.inactivity_timeout_s:
            self.post_hb()
            self.latest_timestamps_ms["hb"] = current_timestamp_ms


if __name__ == "main":
    p = PicoFlowSlow()
    p.start()