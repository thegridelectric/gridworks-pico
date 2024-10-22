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
DEFAULT_PUBLISH_TICKLIST_LENGTH = 10
DEFAULT_PUBLISH_ANY_TICKLIST_AFTER_S = 180
DEFAULT_DEADBAND_MILLISECONDS = 10

# Other constants
PULSE_PIN = 28 # 7 pins down on the hot side

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
        # Reporting relative ticklists
        self.relative_ms_list = []
        self.first_tick_ms = None
        self.time_at_first_tick_ns = None
        # Posting ticklists
        self.last_ticks_sent = utime.time()
        self.actively_publishing_ticklist = False

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

            # If still on oak2.local, write 'false'
            if 'has_new_host.txt' not in os.listdir():
                with open('has_new_host.txt', 'w') as f:
                    f.write('False')

            # Check if it says True of False
            with open('has_new_host.txt', 'r') as f:
                content = f.read().strip()
                has_new_host = content == 'True'

            # If it says False, then update to oak.local
            if not has_new_host:
                # Edit the base URL and save to comms_config
                comms_config["BaseUrl"] = 'http://oak.local:8000'

                with open('has_new_host.txt', 'w') as f:
                    f.write('True')

                with open(COMMS_CONFIG_FILE, "w") as f:
                    ujson.dump(comms_config, f)
                
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
        self.publish_ticklist_length = app_config.get("PublishTicklistLength", DEFAULT_PUBLISH_TICKLIST_LENGTH)
        self.publish_any_ticklist_after_s = app_config.get("PublishAnyTicklistAfterS", DEFAULT_PUBLISH_ANY_TICKLIST_AFTER_S)
        self.deadband_milliseconds = app_config.get("DeadbandMilliseconds", DEFAULT_DEADBAND_MILLISECONDS)

    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "PublishTicklistLength": self.publish_ticklist_length,
            "PublishAnyTicklistAfterS": self.publish_any_ticklist_after_s,
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
            "PublishTicklistLength": self.publish_ticklist_length,
            "PublishAnyTicklistAfterS": self.publish_any_ticklist_after_s,
            "DeadbandMilliseconds": self.deadband_milliseconds,
            "TypeName": "flow.reed.params",
            "Version": "101"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.flow_node_name = updated_config.get("FlowNodeName", self.flow_node_name)
                self.publish_ticklist_length = updated_config.get("PublishTicklistLength", self.publish_ticklist_length)
                self.publish_any_ticklist_after_s = updated_config.get("PublishAnyTicklistAfterS", self.publish_any_ticklist_after_s)
                self.deadband_milliseconds = updated_config.get("DeadbandMilliseconds", self.deadband_milliseconds)
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
    # Posting relative timestamps
    # ---------------------------------
    
    def post_ticklist(self):
        url = self.base_url + f"/{self.actor_node_name}/ticklist-reed"
        payload = {
            "HwUid": self.hw_uid,
            "FirstTickTimestampNanoSecond": self.time_at_first_tick_ns,
            "RelativeMillisecondList": self.relative_ms_list, 
            "PicoBeforePostTimestampNanoSecond": utime.time_ns(),
            "TypeName": "ticklist.reed", 
            "Version": "101"
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
        self.time_at_first_tick_ns = None

    # ---------------------------------
    # Receive and publish ticks
    # ---------------------------------

    def main_loop(self):

        time_since_0 = utime.ticks_ms()
        time_since_1 = utime.ticks_ms()
        self.first_tick_ms = None

        while(True):  

            # Publish ticklist when it reaches a certain length, or after some time
            if (len(self.relative_ms_list) >= self.publish_ticklist_length or
                utime.time() - self.last_ticks_sent > self.publish_any_ticklist_after_s):
                if not self.actively_publishing_ticklist:
                    self.actively_publishing_ticklist = True
                    self.post_ticklist()
                    self.last_ticks_sent = utime.time()
                    self.actively_publishing_ticklist = False

            # States: down -> going up -> up -> going down -> down
            current_reading = self.pulse_pin.value()
            current_time_ms = utime.ticks_ms()
        
            # down -> going up
            if self.pin_state == PinState.DOWN and current_reading == 1:
                self.pin_state = PinState.GOING_UP
                time_since_1 = current_time_ms
                # This is the state change we track for tick deltas
                if self.first_tick_ms is None:
                    self.first_tick_ms = current_time_ms
                    self.time_at_first_tick_ns = utime.time_ns()
                    self.relative_ms_list.append(0)
                else:
                    relative_ms = current_time_ms - self.first_tick_ms
                    if relative_ms - self.relative_ms_list[-1] > 1:
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
                
    def start(self):
        self.connect_to_wifi()
        self.update_code()
        self.update_app_config()
        self.state_init()
        print("Initialized")
        self.main_loop()

if __name__ == "__main__":
    p = PicoFlowReed()
    p.start()