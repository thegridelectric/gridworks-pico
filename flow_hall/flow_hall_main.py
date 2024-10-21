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
DEFAULT_PUBLISH_STAMPS_PERIOD_S = 10
DEFAULT_PUBLISH_EMPTY_STAMPS_AFTER_S = 60

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
        # Creating relative ticklists
        self.first_tick_us = None
        self.relative_us_list = []
        # Posting ticklists
        self.last_ticks_sent = utime.time()
        self.actively_publishing = False
        # Synchronous reporting on the minute
        self.capture_offset_seconds = 0

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
        self.publish_stamps_period_s = app_config.get("PublishStampsPeriodS", DEFAULT_PUBLISH_STAMPS_PERIOD_S)
        self.publish_empty_stamps_after_s = app_config.get("PublishEmptyStampsAfterS", DEFAULT_PUBLISH_EMPTY_STAMPS_AFTER_S)
    
    def save_app_config(self):
        '''Save the parameters to the app_config file'''
        config = {
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "PublishStampsPeriodS": self.publish_stamps_period_s,
            "PublishEmptyStampsAfterS": self.publish_empty_stamps_after_s,
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
            "PublishStampsPeriodS": self.publish_stamps_period_s,
            "PublishEmptyStampsAfterS": self.publish_empty_stamps_after_s,
            "TypeName": "flow.hall.params",
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
                self.publish_stamps_period_s = updated_config.get("PublishStampsPeriodS", self.publish_stamps_period_s)
                self.publish_empty_stamps_after_s = updated_config.get("PublishEmptyStampsAfterS", self.publish_empty_stamps_after_s)
                self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
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
    # Receive and publish ticklists periodically
    # ---------------------------------
            
    def pulse_callback(self, pin):
        '''Compute the relative timestamp and add it to a list'''
        if not self.actively_publishing:
            current_timestamp_us = utime.ticks_us()
            # Initialize the timestamp if this is the first pulse
            if self.first_tick_us is None:
                self.first_tick_us = current_timestamp_us
                self.time_at_first_tick_ns = utime.time_ns()
                self.relative_us_list.append(0)
            else:
                relative_us = current_timestamp_us - self.first_tick_us
                if relative_us - self.relative_us_list[-1] > 1e3:
                    self.relative_us_list.append(relative_us)

    def post_ticklist(self):
        url = self.base_url + f"/{self.actor_node_name}/ticklist-hall"
        payload = {
            "HwUid": self.hw_uid,
            "FirstTickTimestampNanoSecond": self.time_at_first_tick_ns,
            "RelativeMicrosecondList": self.relative_us_list,
            "PicoBeforePostTimestampNanoSecond": utime.time_ns(),
            "TypeName": "ticklist.hall", 
            "Version": "101"
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

    def main_loop(self):
        '''Post the relative timestamps list periodically'''
        while True:
            utime.sleep_ms(MAIN_LOOP_MILLISECONDS)
            if ((self.relative_us_list and utime.time()-self.last_ticks_sent > self.publish_stamps_period_s) 
                or 
                (not self.relative_us_list and utime.time()-self.last_ticks_sent > self.publish_empty_stamps_after_s)):
                self.actively_publishing = True
                self.post_ticklist()
                self.last_ticks_sent = utime.time()
                self.actively_publishing = False

    def start(self):
        self.connect_to_wifi()
        self.update_code()
        self.update_app_config()
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)
        self.main_loop()

if __name__ == "__main__":
    p = PicoFlowHall()
    p.start()