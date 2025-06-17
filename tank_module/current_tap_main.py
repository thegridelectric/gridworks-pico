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
DEFAULT_ACTOR_NAME = "current_tap"
DEFAULT_SYNC_READING_STEP_MICROSECONDS = 10
DEFAULT_CAPTURE_PERIOD_S = 10

# Other constants
ADC0_PIN_NUMBER = 26

# ---------------------------------
# Main class
# ---------------------------------

class CurrentTap:

    def __init__(self):
        # Unique ID
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
        # Pins
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        # Load configuration files
        self.load_comms_config()
        self.load_app_config()
        # Measuring and repoting voltages
        self.prev_mv0 = -1
        self.mv0 = None
        self.mv0_list = []
        self.timestamp_list = []
        # Synchronous reporting on the minute
        self.sync_report_timer = machine.Timer(-1)
        self.actively_posting = False

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
        self.sync_reading_step_microseconds = app_config.get("SyncReadingStepMicroseconds", DEFAULT_SYNC_READING_STEP_MICROSECONDS)
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)

    def save_app_config(self):
        config = {
            "ActorNodeName": self.actor_node_name,
            "CapturePeriodS": self.capture_period_s,
            "SyncReadingStepMicroseconds": self.sync_reading_step_microseconds,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        url = self.base_url + f"/{self.actor_node_name}/current-tap-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "CapturePeriodS": self.capture_period_s,
            "SyncReadingStepMicroseconds": self.sync_reading_step_microseconds,
            "TypeName": "current.tap.params",
            "Version": "100"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                updated_config = response.json()
                self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
                self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)
                self.sync_reading_step_microseconds = updated_config.get("SyncReadingStepMicroseconds", self.sync_reading_step_microseconds)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error sending current tap params: {e}")

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

    def read_adc0_micros(self):
        voltage = int(self.adc0.read_u16() * 3.3 / 65535 * 10**6)
        self.mv0_list.append(voltage)
        self.timestamp_list.append(utime.time_ns())
    
    # ---------------------------------
    # Posting microvolts
    # ---------------------------------

    def post_microvolts(self):
        url = self.base_url + f"/{self.actor_node_name}/current-tap-microvolts"
        payload = {
            "HwUid": self.hw_uid,
            "MicroVoltsList": self.mv0_list, 
            "TimestampList": self.timestamp_list,
            "TypeName": "current.tap.microvolts", 
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
        self.mv0_list = []
        self.timestamp_list = []
        
    def sync_report(self, timer):
        self.post_microvolts()

    def start_sync_report_timer(self):
        '''Initialize the timer to call self.keep_alive periodically'''
        self.sync_report_timer.init(
            period=int(self.capture_period_s * 1000), 
            mode=machine.Timer.PERIODIC,
            callback=self.sync_report
        )

    def main_loop(self):
        while True:
            while len(self.mv0_list) < 500 and not self.actively_posting:
                self.read_adc0_micros()
                utime.sleep_us(int(self.sync_reading_step_microseconds))

    def start(self):
        self.connect_to_wifi()
        self.update_code()
        self.update_app_config()
        self.read_adc0_micros()
        self.start_sync_report_timer()
        self.main_loop()

if __name__ == "__main__":
    t = CurrentTap()
    t.start()

