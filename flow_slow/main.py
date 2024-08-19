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
DEFAULT_DEADBAND_MILLISECONDS = 300
DEFAULT_INACTIVITY_TIMEOUT_S = 60

PULSE_0_PIN = 0
PULSE_1_PIN = 1
PULSE_2_PIN = 2

NAME_BY_PIN = {
    PULSE_0_PIN: "dist-flow",
    PULSE_1_PIN: "primary-flow",
    PULSE_2_PIN: "store-flow"
}

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
        self.actor_node_name = app_config.get("ActorNodeName", "default")
        self.deadband_milliseconds = app_config.get("DeadbandMilliseconds", DEFAULT_DEADBAND_MILLISECONDS)
        self.inactivity_timeout_s = app_config.get("InactivityTimeoutS", DEFAULT_INACTIVITY_TIMEOUT_S)

    def save_app_config(self):
        config = {
            'ActorNodeName': self.actor_node_name,
            'DeadbandMilliseconds': self.deadband_milliseconds,
            'InactivityTimeoutS': self.inactivity_timeout_s,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        url = self.base_url + "/pico_flow_slow_params"
        payload = {
            'HwUid': self.hw_uid, 
            'ActorNodeName': self.actor_node_name,
            'DeadbandMilliseconds': self.deadband_milliseconds,
            'InactivityTimeoutS': self.inactivity_timeout_s,
            'TypeName': 'pico.flow.slow.params',
            'Version': '000'
        }
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                # Update configuration with the server response
                updated_config = response.json()
                self.actor_node_name = updated_config.get('ActorNodeName', self.actor_node_name)
                self.deadband_milliseconds = updated_config.get('DeadbandMilliseconds', self.deadband_milliseconds)
                self.inactivity_timeout_s = updated_config.get('InactivityTimeoutS', self.inactivity_timeout_s)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error posting tick delta: {e}")

    def start_heartbeat_timer(self):
        # Initialize the timer to call self.post_hb periodically
        self.heartbeat_timer.init(
            period=self.inactivity_timeout_s * 1000,  # Convert seconds to milliseconds
            mode=machine.Timer.PERIODIC,
            callback=self.post_hb
        )

    def start(self):
        self.connect_to_wifi()
        self.update_app_config()
        self.start_heartbeat_timer()
    
    def post_tick_delta(self, node_name: str, milliseconds: int):
        url = self.base_url + f"/{self.actor_node_name}/tick-delta"
        payload = {
            'AboutNodeName': node_name,
            'Milliseconds': milliseconds, 
            "TypeName": "tick.delta", 
            "Version": "000"
        }
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting tick delta: {e}")
        finally:
            response.close()
            gc.collect()
    
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
            # Post the tick delta if it exceeds the deadband threshold
            self.post_tick_delta(node_name=NAME_BY_PIN[pin_number], milliseconds=delta_ms)
            # Update the latest timestamp
            self.latest_timestamps_ms[pin_number] = current_timestamp_ms
    
    def pulse_0_callback(self, pin):
        self.pulse_callback(0)

    def pulse_1_callback(self, pin):
        self.pulse_callback(1)

    def pulse_2_callback(self, pin):
        self.pulse_callback(2)

    def post_hb(self, timer):
        print("HB triggered")
        url = self.base_url + f"/{self.actor_node_name}/hb"
        self.hb = (self.hb + 1) % 16
        hbstr = "{:x}".format(self.hb)
        payload =  {'MyHex': hbstr, 'TypeName': 'hb', 'Version': '000'}
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
        except Exception as e:
            print(f"Error posting hb {e}")
        finally:
            response.close()
            gc.collect()
    
    def check_hb(self, timer):
        """
        Publish a heartbeat, assuming no other messages sent within inactivity timeout
        """
        print("Checking HB")
        latest_ms = max((value for value in self.latest_timestamps_ms.values() if value is not None), default=0)
        current_timestamp_ms = utime.time_ns() // 1_000_000
        if (current_timestamp_ms - latest_ms) / 10**3 > self.inactivity_timeout_s:
            self.post_hb()
            self.latest_timestamps_ms["hb"] = current_timestamp_ms
