import machine
import ujson
import network
import utime
import urequests
import ubinascii
import os

# Constants
ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27
ADC2_PIN_NUMBER = 28
TOTAL_REPORTS = 200
SAMPLES = 1000
PIN_0_OFFSET = 2.4
PIN_1_OFFSET = -2.4

# Remove existing files
if 'boot.py' in os.listdir():
    os.remove('boot.py')
if 'app_config.json' in os.listdir():
    os.remove('app_config.json')
if 'comms_config.json' in os.listdir():
    os.remove('comms_config.json')
if 'main.py' in os.listdir():
    os.remove('main.py')
if 'main_previous.py' in os.listdir():
    os.remove('main_previous.py')

# *************************
# 1/3 - MAIN.PY PROVISION
# *************************

def write_flow_hall_main():
    main_code = """
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
DEFAULT_PUBLISH_TICKLIST_PERIOD_S = 10
DEFAULT_PUBLISH_EMPTY_TICKLIST_AFTER_S = 60

# Other constants
PULSE_PIN = 28 # 7 pins down on the hot side
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
        self.relative_us_list = []
        self.first_tick_us = None
        self.time_at_first_tick_ns = None
        # Posting ticklists
        self.last_ticks_sent = utime.time()
        self.actively_publishing_ticklist = False

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
        self.publish_ticklist_period_s = app_config.get("PublishTicklistPeriodS", DEFAULT_PUBLISH_TICKLIST_PERIOD_S)
        self.publish_empty_ticklist_after_s = app_config.get("PublishEmptyTicklistAfterS", DEFAULT_PUBLISH_EMPTY_TICKLIST_AFTER_S)
    
    def save_app_config(self):
        '''Save the parameters to the app_config file'''
        config = {
            "ActorNodeName": self.actor_node_name,
            "FlowNodeName": self.flow_node_name,
            "PublishTicklistPeriodS": self.publish_ticklist_period_s,
            "PublishEmptyTicklistAfterS": self.publish_empty_ticklist_after_s,
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
            "PublishTicklistPeriodS": self.publish_ticklist_period_s,
            "PublishEmptyTicklistAfterS": self.publish_empty_ticklist_after_s,
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
                self.publish_ticklist_period_s = updated_config.get("PublishTicklistPeriodS", self.publish_ticklist_period_s)
                self.publish_empty_ticklist_after_s = updated_config.get("PublishEmptyTicklistAfterS", self.publish_empty_ticklist_after_s)
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
        if not self.actively_publishing_ticklist:
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
        self.time_at_first_tick_ns = None

    def main_loop(self):
        '''Post the relative timestamps list periodically'''
        while True:
            utime.sleep_ms(MAIN_LOOP_MILLISECONDS)
            if ((self.relative_us_list and utime.time()-self.last_ticks_sent > self.publish_ticklist_period_s) 
                or 
                (not self.relative_us_list and utime.time()-self.last_ticks_sent > self.publish_empty_ticklist_after_s)):
                self.actively_publishing_ticklist = True
                self.post_ticklist()
                self.last_ticks_sent = utime.time()
                self.actively_publishing_ticklist = False

    def start(self):
        self.connect_to_wifi()
        self.update_code()
        self.update_app_config()
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)
        self.main_loop()

if __name__ == "__main__":
    p = PicoFlowHall()
    p.start()
    """
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_flow_reed_main():
    main_code = """
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
    """
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_tank_module_main():
    main_code = """
import machine
import utime
import network
import ujson
import urequests
import ubinascii
import utime
import gc
import os

# ---------------------------------
# Constants
# ---------------------------------

# Configuration files
COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"

# Default parameters
DEFAULT_ACTOR_NAME = "tank"
DEFAULT_PICO_AB = "a"
DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS = 500
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_SAMPLES = 1000
DEFAULT_NUM_SAMPLE_AVERAGES = 10

# Other constants
ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27

# ---------------------------------
# Main class
# ---------------------------------

class TankModule:

    def __init__(self):
        # Unique ID
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        # Pins
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        # Load configuration files
        self.load_comms_config()
        self.load_app_config()
        # Measuring and repoting voltages
        self.prev_mv0 = -1
        self.prev_mv1 = -1
        self.mv0 = None
        self.mv1 = None
        self.node_names = []
        self.microvolts_posted_time = utime.time()
        # Synchronous reporting on the minute
        self.capture_offset_seconds = 0
        self.keepalive_timer = machine.Timer(-1)

    def set_names(self):
        if self.actor_node_name is None:
            raise Exception("Needs actor node name or pico number to run. Reboot!")
        if self.pico_a_b == "a":
            self.node_names = [
                f"{self.actor_node_name}-depth1", 
                f"{self.actor_node_name}-depth2"
            ]
        elif self.pico_a_b == "b":
            self.node_names = [
                f"{self.actor_node_name}-depth3", 
                f"{self.actor_node_name}-depth4"
            ]
        else:
            raise Exception("PicoAB must be a or b")

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
                utime.sleep_ms(500)
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
        self.pico_a_b = app_config.get("PicoAB", DEFAULT_PICO_AB)
        self.async_capture_delta_micro_volts = app_config.get("AsyncCaptureDeltaMicroVolts", DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS)
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        self.samples = app_config.get("Samples", DEFAULT_SAMPLES)
        self.num_sample_averages = app_config.get("NumSampleAverages", DEFAULT_NUM_SAMPLE_AVERAGES)

    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "PicoAB": self.pico_a_b,
            "CapturePeriodS": self.capture_period_s,
            "Samples": self.samples,
            "NumSampleAverages":self.num_sample_averages,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        url = self.base_url + f"/{self.actor_node_name}/tank-module-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "PicoAB": self.pico_a_b,
            "CapturePeriodS": self.capture_period_s,
            "Samples": self.samples,
            "NumSampleAverages": self.num_sample_averages,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
            "TypeName": "tank.module.params",
            "Version": "100"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.pico_a_b = updated_config.get("PicoAB", self.pico_a_b)
                self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)
                self.samples = updated_config.get("Samples", self.samples)
                self.num_sample_averages = updated_config.get("NumSampleAverages", self.num_sample_averages)
                self.async_capture_delta_micro_volts = updated_config.get("AsyncCaptureDeltaMicroVolts", self.async_capture_delta_micro_volts)
                self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error sending tank module params: {e}")
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
    # Measuring microvolts
    # ---------------------------------

    def adc0_micros(self):
        sample_averages = []
        for _ in range(self.num_sample_averages):
            readings = []
            for _ in range(self.samples):
                # Read the raw ADC value (0-65535)
                readings.append(self.adc0.read_u16())
            voltages = list(map(lambda x: x * 3.3 / 65535, readings))
            mean_1000 = int(10**6 * sum(voltages) / self.samples)
            sample_averages.append(mean_1000)
        return int(sum(sample_averages)/self.num_sample_averages)
    
    def adc1_micros(self):
        sample_averages = []
        for _ in range(self.num_sample_averages):
            readings = []
            for _ in range(self.samples):
                # Read the raw ADC value (0-65535)
                readings.append(self.adc1.read_u16())
            voltages = list(map(lambda x: x * 3.3 / 65535, readings))
            mean_1000 = int(10**6 * sum(voltages) / self.samples)
            sample_averages.append(mean_1000)
        return int(sum(sample_averages)/self.num_sample_averages)
    
    # ---------------------------------
    # Posting microvolts
    # ---------------------------------

    def post_microvolts(self, idx=2):
        url = self.base_url + f"/{self.actor_node_name}/microvolts"
        if idx==0:
            mv_list = [self.mv0]
        elif idx==1:
            mv_list = [self.mv1]
        else:
            mv_list = [self.mv0, self.mv1]
        payload = {
            "HwUid": self.hw_uid,
            "AboutNodeNameList": [self.node_names[idx]] if idx<=1 else self.node_names,
            "MicroVoltsList": mv_list, 
            "TypeName": "microvolts", 
            "Version": "100"
        }
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting microvolts: {e}")
        gc.collect()
        self.microvolts_posted_time = utime.time()
        
    def keep_alive(self, timer):
        '''Post microvolts if none were posted within the last minute'''
        if utime.time() - self.microvolts_posted_time > 55:
            self.post_microvolts()
    
    def start_keepalive_timer(self):
        '''Initialize the timer to call self.keep_alive periodically'''
        self.keepalive_timer.init(
            period=self.capture_period_s * 1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.keep_alive
        )

    def main_loop(self):
        self.mv0 = self.adc0_micros()
        self.mv1 = self.adc1_micros()
        while True:
            self.mv0 = self.adc0_micros()
            self.mv1 = self.adc1_micros()
            if abs(self.mv0 - self.prev_mv0) > self.async_capture_delta_micro_volts:
                self.post_microvolts(idx=0)
                self.prev_mv0 = self.mv0
            if abs(self.mv1 - self.prev_mv1) > self.async_capture_delta_micro_volts:
                self.post_microvolts(idx=1)
                self.prev_mv1 = self.mv1
            utime.sleep_ms(100)

    def start(self):
        self.connect_to_wifi()
        self.update_code()
        self.update_app_config()
        self.set_names()
        utime.sleep(self.capture_offset_seconds)
        self.start_keepalive_timer()
        self.main_loop()

if __name__ == "__main__":
    t = TankModule()
    t.start()
    """
    with open('main.py', 'w') as file:
        file.write(main_code)

# *************************
# 2/3 - APP_CONFIG PROVISION
# *************************

# -------------------------
# Tank module
# -------------------------

class tankmodule_provision:

    def __init__(self):
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        self.adc2 = machine.ADC(ADC2_PIN_NUMBER)
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        self.samples = SAMPLES
        self.total_reports = TOTAL_REPORTS
        self.num_recorded = 0

    def mv0(self):
        readings = []
        for _ in range(self.samples):
            # Read the raw ADC value (0-65535)
            readings.append(self.adc0.read_u16())
        voltages = list(map(lambda x: x * 3.3 / 65535, readings))
        return int(10**4 * sum(voltages) / self.samples) / 10
    
    def mv1(self):
        readings = []
        for _ in range(self.samples):
            # Read the raw ADC value (0-65535)
            readings.append(self.adc1.read_u16())
        voltages = list(map(lambda x: x * 3.3 / 65535, readings))
        return int(10**4 * sum(voltages) / self.samples) / 10

    def mv2(self):
        readings = []
        for _ in range(self.samples):
            # Read the raw ADC value (0-65535)
            readings.append(self.adc2.read_u16())
        voltages = list(map(lambda x: x * 3.3 / 65535, readings))
        return int(10**4 * sum(voltages) / self.samples) / 10
        
    def print_sample(self):
            report = f"{self.hw_uid}, {self.mv0() - PIN_0_OFFSET}, {self.mv1() - PIN_1_OFFSET}, {self.mv2()}"
            print(report)
            self.num_recorded += 1
    
    def set_name(self):
        got_a_or_b = False
        while not got_a_or_b:
            a_or_b = input("Tank Module pico a or b? Type 'a' or 'b': ")
            self.pico_a_b = a_or_b
            if a_or_b not in {'a', 'b'}:
                print("please enter a or b!")
            else:
                got_a_or_b = True
        
        got_tank_name = False
        while not got_tank_name:
            name = input(f"Tank Name: 'buffer', 'tank1', tank2', 'tank3': ")
            self.name = name
            if name not in {'buffer', 'tank1', 'tank2', 'tank3'}:
                print("bad tank name")
            else:
                got_tank_name = True
        self.actor_node_name = name
        config = {
            "ActorNodeName": self.actor_node_name,
            "PicoAB": self.pico_a_b,
        }
        with open("app_config.json", "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()
        # print("HW UID, Pin 0 mV, Pin 1 mV, Pin 2 mV (OFFSETS DONE ON PIN 0 and 1)")
        # while self.num_recorded < TOTAL_REPORTS:
        #     self.print_sample()

# -------------------------
# Flowmeter
# -------------------------

class flowmeter_provision:
    
    def set_name(self):

        # Get ActorNodeName
        got_actor_name = False
        while not got_actor_name:
            self.actor_name = input("Enter Actor name (e.g. 'pico-flow-reed', 'pico-flow-hall', 'pico-flow-hall-store'): ")
            if 'flow' not in self.actor_name:
                print("please include 'flow' in the actor name")
            else:
                got_actor_name = True
        
        # Get FlowNodeName
        got_flow_name = False
        while not got_flow_name:
            self.flow_name = input(f"Enter Flow name ('primary-flow', 'dist-flow', 'store-flow'): ")
            if self.flow_name not in {'primary-flow', 'dist-flow', 'store-flow'}:
                print("invalid flow name")
            else:
                got_flow_name = True

        # Save in app_config.json
        config = {
            "ActorNodeName": self.actor_name,
            "FlowNodeName": self.flow_name,
        }
        with open("app_config.json", "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()

# *************************
# 3/3 - MAIN CODE
# *************************

if __name__ == "__main__":

    # Get hardware ID
    pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
    hw_uid = f"pico_{pico_unique_id[-6:]}"
    print(f"\nThis Pico's unique hardware ID is {hw_uid}.")

    # -------------------------
    # Write boot.py
    # -------------------------

    bootpy_code = """import os

if 'main_update.py' in os.listdir():
    
    if 'main_previous.py' in os.listdir():
        os.remove('main_previous.py')

    if 'main.py' in os.listdir():
        os.rename('main.py', 'main_previous.py')

    os.rename('main_update.py', 'main.py')

elif 'main_revert.py' in os.listdir():

    if 'main.py' in os.listdir():
        os.remove('main.py')

    os.rename('main_revert.py', 'main.py')
    """

    with open('boot.py', 'w') as file:
        file.write(bootpy_code)
    print(f"Wrote 'boot.py' on the Pico.")
    
    print(f"\n{'-'*40}\n[1/4] Success! Found hardware ID and wrote 'boot.py'.\n{'-'*40}\n")

    # -------------------------
    # Write comms_config.json
    # -------------------------

    # Connect to wifi

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    wlan.disconnect()
    while wlan.isconnected():
        utime.sleep(0.1)
    
    while not wlan.isconnected():

        wifi_name = input("Enter wifi name: ")
        wifi_pass = input("Enter wifi password: ")

        time_waiting_connection = 0
        wlan.connect(wifi_name, wifi_pass)
        while not wlan.isconnected():
            if time_waiting_connection>0 and time_waiting_connection%2==0:
                print(f"Trying to connect ({int(time_waiting_connection/2)}/5)...")
            utime.sleep(0.5)
            time_waiting_connection += 0.5
            if time_waiting_connection > 10:
                print("Failed to connect to wifi, please try again.\n")
                break

    print(f"Connected to wifi '{wifi_name}'.\n")

    # Connect to API

    connected_to_api = False
    while not connected_to_api:

        hostname = input("Enter hostname (e.g., 'fir2' or an IP address): ")
        base_url = f"http://{hostname}.local:8000"
        url = base_url + "/new-pico"
        payload = {
            "HwUid": hw_uid,
            "TypeName": "new.pico",
            "Version": "100"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                connected_to_api = True
            else:
                print(f"Connected to the API, but it returned a status code {response.status_code}, indicating an issue.")
            response.close()
        except Exception:
            # If the hostname is an IP address
            base_url = f"http://{hostname}:8000"
            url = base_url + "/new-pico"
            payload = {
                "HwUid": hw_uid,
                "TypeName": "new.pico",
                "Version": "100"
            }
            headers = {"Content-Type": "application/json"}
            json_payload = ujson.dumps(payload)
            try:
                response = urequests.post(url, data=json_payload, headers=headers)
                if response.status_code == 200:
                    connected_to_api = True
                else:
                    print(f"Connected to the API, but it returned a status code {response.status_code}, indicating an issue.")
                response.close()
            except Exception as e:
                print(f"There was an error connecting to the API: {e}. Please check the hostname and try again.")

    print(f"Connected to the API hosted in '{base_url}'.")

    # Write the parameters to comms_config.json

    base_url = input('Enter the TRUE base URL: ')
    wifi_name = 'GridWorks'
    wifi_pass = input('Enter the TRUE password (for GridWorks wifi): ')

    comms_config_content = {
        "WifiName": wifi_name,
        "WifiPassword": wifi_pass, 
        "BaseUrl": base_url
    }
    with open('comms_config.json', 'w') as file:
        ujson.dump(comms_config_content, file)

    print(f"\n{'-'*40}\n[2/4] Success! Wrote 'comms_config.json' on the Pico.\n{'-'*40}\n")

    # -------------------------
    # Write app_config.json
    # -------------------------

    got_type = False
    while not got_type:
        type = input("Is this Pico associated to a tank module (enter '0') or a flowmeter (enter '1'): ")
        if type not in {'0','1'}:
            print('Please enter 0 or 1.')
        else:
            got_type = True

    if type == '0':
        p = tankmodule_provision()
        p.start()
    elif type == '1':
        p = flowmeter_provision()
        p.start()

    print(f"\n{'-'*40}\n[3/4] Success! Wrote 'app_config.json' on the Pico.\n{'-'*40}\n")

    # -------------------------
    # Write main.py
    # -------------------------

    # Read the actor node name
    with open('app_config.json', 'r') as file:
        config_content = ujson.load(file)
    name = config_content['ActorNodeName']

    if 'flow' in name:
        if 'hall' in name:
            print("This is a hall meter.")
            write_flow_hall_main()
        if 'reed' in name:
            print("This is a reed meter.")
            write_flow_reed_main()
    else:
        print("This is a tank module.")
        write_tank_module_main()

    print(f"\n{'-'*40}\n[4/4] Success! Wrote 'main.py' on the Pico.\n{'-'*40}\n")

    print("The Pico is set up. It is now ready to use.")