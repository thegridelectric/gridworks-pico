import machine
import utime
import network
import ujson
import urequests
import utime
import gc
import os
from utils import get_hw_uid

# *********************************************
# CONFIG FILE AND DEFAULT PARAMS
# *********************************************
COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"

# *********************************************
# CONSTANTS
# *********************************************
ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27
CODE_UPDATE_PERIOD_S = 60
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_CAPTURE_OFFSET_S = 0
DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS = 500
DEFAULT_SAMPLES = 1000
DEFAULT_NUM_SAMPLE_AVERAGES = 10

# *********************************************
# CONNECT TO WIFI
# *********************************************

class TankModule:
    def __init__(self):
        self.update_code_timer = machine.Timer(-1)
        self.hw_uid = get_hw_uid()
        self.load_comms_config()
        self.load_app_config()
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        self.prev_mv0 = -1
        self.prev_mv1 = -1
        self.mv0 = None
        self.mv1 = None
        self.node_names = []
        self.sync_report_timer = machine.Timer(-1)
        
                                                                 
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
                utime.sleep_ms(500)
        print(f"Connected to wifi {self.wifi_name}")
    
    def load_app_config(self):
        try:
            with open(APP_CONFIG_FILE, "r") as f:
                app_config = ujson.load(f)
        except:
            app_config = {}
        self.actor_node_name = app_config.get("ActorNodeName")
        self.pico_a_b = app_config.get("PicoAB")
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        self.samples = app_config.get("Samples", DEFAULT_SAMPLES)
        self.num_sample_averages = app_config.get("NumSampleAverages", DEFAULT_NUM_SAMPLE_AVERAGES)
        self.capture_offset_milliseconds = app_config.get("CaptureOffsetS", DEFAULT_CAPTURE_OFFSET_S)
        self.async_capture_delta_micro_volts = app_config.get("AsyncCaptureDeltaMicroVolts", DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS)

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
        url = self.base_url + "/tank-module-params"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "PicoAB": self.pico_a_b,
            "CapturePeriodS": self.capture_period_s,
            "Samples": self.samples,
            "NumSampleAverages": self.num_sample_averages,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
            "CaptureOffsetMilliseconds": self.capture_offset_milliseconds,
            "TypeName": "tank.module.params",
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
                self.pico_a_b = updated_config.get("PicoAB", self.pico_a_b)
                self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)
                self.samples = updated_config.get("Samples", self.samples)
                self.num_sample_averages = updated_config.get("NumSampleAverages", self.num_sample_averages)
                self.async_capture_delta_micro_volts = updated_config.get("AsyncCaptureDeltaMicroVolts", self.async_capture_delta_micro_volts)
                self.capture_offset_milliseconds = updated_config.get("CaptureOffsetMilliseconds", self.capture_offset_milliseconds)
                self.save_app_config()
            response.close()
        except Exception as e:
            print(f"Error sending/receiving parameters to/from server: {e}")
            if 'main_previous.py' in os.listdir():
                # Reverting to previous code
                os.rename('main_previous.py', 'main_revert.py')
                machine.reset()

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

    def async_post_microvolts(self, idx: int):
        url = self.base_url + f"/{self.actor_node_name}/microvolts"
        if idx == 0:
            val_list = [self.mv0]
        else:
            val_list = [self.mv1]
        payload = {
            "AboutNodeNameList": [self.node_names[idx]],
            "MicroVoltsList": val_list, 
            "TypeName": "microvolts", 
            "Version": "001"
        }
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting hz: {e}")

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
        return sum(sample_averages)/self.num_sample_averages
    
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
        return sum(sample_averages)/self.num_sample_averages
    
    def sync_post_microvolts(self, timer):
        print("In timer")
        url = self.base_url + f"/{self.actor_node_name}/microvolts"
        payload = {
            "AboutNodeNameList": self.node_names,
            "MicroVoltsList": [self.mv0, self.mv1], 
            "TypeName": "microvolts", 
            "Version": "001"
        }
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting hz: {e}")
    
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
    
    def start_sync_report_timer(self):
         # start the synchronous reporting
        self.sync_report_timer.init(
            period=self.capture_period_s * 1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.sync_post_microvolts
        )

    def start_code_update_timer(self):
        # start the periodic check for code updates
        self.update_code_timer.init(
            period=CODE_UPDATE_PERIOD_S * 1000,
            mode=machine.Timer.PERIODIC,
            callback=self.update_code
        )
    
    def main_loop(self):
        self.mv0 = self.adc0_micros()
        self.mv1 = self.adc1_micros()
        while True:
            self.mv0 = self.adc0_micros()
            self.mv1 = self.adc1_micros()
            if abs(self.mv0 - self.prev_mv0) > self.async_capture_delta_micro_volts:
                self.async_post_microvolts(idx = 0)
                self.prev_mv0 = self.mv0
            if abs(self.mv1 - self.prev_mv1) > self.async_capture_delta_micro_volts:
                self.async_post_microvolts(idx = 1)
                self.prev_mv1 = self.mv1
            utime.sleep_ms(100)

    def start(self):
        self.connect_to_wifi()
        self.update_app_config()
        self.set_names()
        print(f"sleeping for {self.capture_offset_milliseconds}")
        utime.sleep_ms(self.capture_offset_milliseconds)
        self.start_sync_report_timer()
        self.start_code_update_timer()
        self.main_loop()


if __name__ == "__main__":
    t = TankModule()
    t.start()