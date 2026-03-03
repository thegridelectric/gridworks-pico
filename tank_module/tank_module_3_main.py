import os
import machine
from machine import Pin
import utime
import ujson
import ubinascii

import net

# ---------------------------------
# Constants
# ---------------------------------

# Configuration files
COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"

# Default parameters
DEFAULT_ACTOR_NAME = "tank"
DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS = 500
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_SAMPLES = 1000
DEFAULT_NUM_SAMPLE_AVERAGES = 10

ADC_REF_UV = 3_300_000

# Other constants
ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27
ADC2_PIN_NUMBER = 28

# ---------------------------------
# Main class
# ---------------------------------

class TankModule3:

    def __init__(self):
        # Unique ID
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
        self.hw_uid = f"pico_{pico_unique_id}"
        # Release any ADC pull-down/pull-up resistors
        Pin(26, Pin.IN)
        Pin(27, Pin.IN)
        Pin(28, Pin.IN)
        # Set Pin as ADC
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        self.adc2 = machine.ADC(ADC2_PIN_NUMBER)
        self.load_comms_config()
        self.http = net.HttpClient(base_url=self.base_url)
        try:
            with open(APP_CONFIG_FILE, "r") as f:
                app_config = ujson.load(f)
        except:
            app_config = {}
        self.load_app_config(app_config)
        # Measuring and repoting voltages
        self.prev_mv0 = -1
        self.prev_mv1 = -1
        self.prev_mv2 = -1
        self.mv0 = None
        self.mv1 = None
        self.mv2 = None
        self.node_names = []
        self.microvolts_posted_time = utime.time()
        # Synchronous reporting on the minute
        self.capture_offset_seconds = 0
        self.sync_flag = False
        self.sync_report_timer = machine.Timer(-1)

    def set_names(self):
        if self.actor_node_name is None:
            raise Exception("Needs actor node name or pico number to run. Reboot!")
        self.node_names = [
            f"{self.actor_node_name}-depth1", 
            f"{self.actor_node_name}-depth2",
            f"{self.actor_node_name}-depth3"
        ]

    # ---------------------------------
    # Communication
    # ---------------------------------
                                                                 
    def load_comms_config(self):
        '''Load the communication configuration file (WiFi/Ethernet and API base URL)'''
        try:
            with open(COMMS_CONFIG_FILE, "r") as f:
                comms_config = ujson.load(f)
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Error loading comms_config file: {e}")
        self.wifi_or_ethernet = comms_config.get("WifiOrEthernet", 'wifi')
        self.wifi_name = comms_config.get("WifiName", None)
        self.wifi_password = comms_config.get("WifiPassword", None)
        self.base_url = comms_config.get("BaseUrl")
        if self.wifi_or_ethernet=='wifi':
            if self.wifi_name is None:
                raise KeyError("WifiName not found in comms_config.json")
            if self.wifi_password is None:
                raise KeyError("WifiPassword not found in comms_config.json")
        elif self.wifi_or_ethernet=='ethernet':
            pass
        else:
            raise KeyError("WifiOrEthernet must be either 'wifi' or 'ethernet' in comms_config.json")
        if self.base_url is None:
            raise KeyError("BaseUrl not found in comms_config.json")

    # ---------------------------------
    # Parameters
    # ---------------------------------
    
    def load_app_config(self, app_config):
        '''
        Set parameters to their value in the app_config file if it is specified
        Otherwise set them to their default value
        '''
        self.actor_node_name = app_config.get("ActorNodeName", DEFAULT_ACTOR_NAME)
        self.async_capture_delta_micro_volts = app_config.get("AsyncCaptureDeltaMicroVolts", DEFAULT_ASYNC_CAPTURE_DELTA_MICRO_VOLTS)
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        self.samples = app_config.get("Samples", DEFAULT_SAMPLES)
        self.num_sample_averages = app_config.get("NumSampleAverages", DEFAULT_NUM_SAMPLE_AVERAGES)

    def save_app_config(self, config_dict):
        temp_file = APP_CONFIG_FILE + ".tmp"
        try:
            with open(temp_file, "w") as f:
                ujson.dump(config_dict, f)
                f.flush()
            os.sync()
            os.rename(temp_file, APP_CONFIG_FILE)
            os.sync()
        except Exception as e:
            print(f"Error saving app config: {e}")

    def current_tank_module_params(self):
        return {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "CapturePeriodS": self.capture_period_s,
            "Samples": self.samples,
            "NumSampleAverages": self.num_sample_averages,
            "AsyncCaptureDeltaMicroVolts": self.async_capture_delta_micro_volts,
            "TypeName": "tank.module.params",
            "Version": "110"
        }

    def update_app_config(self):
        current = self.current_tank_module_params()
        status, updated_config = self.http.post(
            f"/{self.actor_node_name}/tank-module-params",
            current,
            mode=1
        )

        if status != 200 or not updated_config:
            return

        PARAM_KEYS = (
            "ActorNodeName",
            "CapturePeriodS",
            "Samples",
            "NumSampleAverages",
            "AsyncCaptureDeltaMicroVolts",
        )

        changed = any(
            k in updated_config and updated_config[k] != current[k]
            for k in PARAM_KEYS
        )

        if not changed:
            return

        new_config = {
            k: updated_config.get(k, current[k])
            for k in PARAM_KEYS
        }

        self.save_app_config(new_config)
        self.load_app_config(new_config)

        offset = updated_config.get("CaptureOffsetS")
        if isinstance(offset, int) and 0 <= offset < self.capture_period_s:
            self.capture_offset_seconds = offset

    # ---------------------------------
    # Code updates
    # ---------------------------------

    def update_code(self):
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "TypeName": "new.code",
            "Version": "100"
        }
        status, content = self.http.post(
            f"/{self.actor_node_name}/code-update",
            payload,
            mode=2  # raw bytes
        )
        if status != 200 or not content:
            return

        # JSON response → no update pending
        if content.startswith(b"{"):
            return

        try:
            with open("main_update.py.tmp", "wb") as f:
                f.write(content)
                f.flush()

            os.sync()
            os.rename("main_update.py.tmp", "main_update.py")
            os.sync()

            machine.reset()

        except Exception as e:
            print("Code update failed:", e)

    # ---------------------------------
    # Measuring microvolts
    # ---------------------------------

    def adc_micros(self, adc):
        samples = self.samples
        averages = self.num_sample_averages
        total_microvolts = 0
        denom = 65535 * samples
        read = adc.read_u16

        for _ in range(averages):
            total = 0
            for _ in range(samples):
                total += read()

            microvolts = total * ADC_REF_UV // denom
            total_microvolts += microvolts

        return total_microvolts // averages
    
    # ---------------------------------
    # Posting microvolts
    # ---------------------------------

    def post_microvolts(self, idx=3):
        if idx==0:
            mv_list = [self.mv0]
        elif idx==1:
            mv_list = [self.mv1]
        elif idx==2:
            mv_list = [self.mv2]
        else:
            mv_list = [self.mv0, self.mv1, self.mv2]
        payload = {
            "HwUid": self.hw_uid,
            "AboutNodeNameList": [self.node_names[idx]] if idx<=2 else self.node_names,
            "MicroVoltsList": mv_list, 
            "TypeName": "microvolts", 
            "Version": "100"
        }
        
        self.http.post_fire_and_forget(
            f"/{self.actor_node_name}/microvolts",
            payload
        )
        self.microvolts_posted_time = utime.time()
        
    def sync_report(self, timer):
        self.sync_flag = True

    def start_sync_report_timer(self):
        '''Initialize the timer to call self.keep_alive periodically'''
        self.sync_report_timer.init(
            period=self.capture_period_s * 1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.sync_report
        )

    def main_loop(self):
        while True:
            self.mv0 = self.adc_micros(self.adc0)
            self.mv1 = self.adc_micros(self.adc1)
            self.mv2 = self.adc_micros(self.adc2)
            if abs(self.mv0 - self.prev_mv0) > self.async_capture_delta_micro_volts:
                self.post_microvolts(idx=0)
                self.prev_mv0 = self.mv0
            if abs(self.mv1 - self.prev_mv1) > self.async_capture_delta_micro_volts:
                self.post_microvolts(idx=1)
                self.prev_mv1 = self.mv1
            if abs(self.mv2 - self.prev_mv2) > self.async_capture_delta_micro_volts:
                self.post_microvolts(idx=2)
                self.prev_mv2 = self.mv2
            if self.sync_flag:
                self.sync_flag = False
                self.post_microvolts()
            utime.sleep_ms(100)

    def start(self):
        if self.wifi_or_ethernet=='wifi':
            net.connect_to_wifi(self.wifi_name, self.wifi_password)
        elif self.wifi_or_ethernet=='ethernet':
            net.connect_to_ethernet()
        self.update_code()
        self.update_app_config()
        self.set_names()
        self.mv0 = self.adc_micros(self.adc0)
        self.mv1 = self.adc_micros(self.adc1)
        self.mv2 = self.adc_micros(self.adc2)
        self.post_microvolts()
        utime.sleep(self.capture_offset_seconds)
        self.start_sync_report_timer()
        self.main_loop()

if __name__ == "__main__":
    t = TankModule3()
    t.start()
    
