import machine
import utime
import network
from umqtt.simple import MQTTClient
import time
import gc
import ujson
from utils import get_hw_uid

# *********************************************
# CONFIG FILE AND DEFAULT PARAMS
# *********************************************
MQTT_CONFIG_FILE = "mqtt_config.json"

# *********************************************
# CONSTANTS
# *********************************************
DEFAULT_ACTOR_NAME = "flow-scope"
DEFAULT_FLOW_NODE_NAME = "primary-flow"

PULSE_PIN = 0 # This is pin 1
LIST_LENGTH = 1000
TOTAL_TIME_SECONDS = 5
MICRO_SLEEP = 1

# *********************************************
# CONNECT TO WIFI
# *********************************************

class PicoFlowScope:
    def __init__(self):
        self.hw_uid = get_hw_uid()
        self.actor_node_name = DEFAULT_ACTOR_NAME
        self.flow_node_name = DEFAULT_FLOW_NODE_NAME
        self.load_mqtt_config()
        self.mqtt_topic = f"{self.actor_node_name}/pin-state-list"
        self.ts_list = []
        self.state_list = []
        self.start_micro = None
        self.deltas = []
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
                                                                 
    def load_mqtt_config(self):
        try:
            with open(MQTT_CONFIG_FILE, "r") as f:
                mqtt_config = ujson.load(f)
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Error loading mqtt_config file: {e}")
        self.wifi_name = mqtt_config.get("WifiName")
        self.wifi_password = mqtt_config.get("WifiPassword")
        self.mqtt_broker = mqtt_config.get("MqttBroker")
        self.mqtt_username = mqtt_config.get("MqttUsername")
        self.mqtt_password = mqtt_config.get("MqttPassword")
        self.mqtt_port = mqtt_config.get("MqttPort")
        self.mqtt_client_name = self.actor_node_name
    
    def connect_to_wifi(self):
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            print("Connecting to wifi...")
            wlan.connect(self.wifi_name, self.wifi_password)
            while not wlan.isconnected():
                time.sleep(1)
        print(f"Connected to wifi {self.wifi_name}")
        
    def start_mqtt_client(self):
        self.client = MQTTClient(self.mqtt_client_name, self.mqtt_broker, user=self.mqtt_username, password=self.mqtt_password, port=self.mqtt_port)
        self.client.connect()
        print(f"Connected to mqtt broker {self.mqtt_broker} as client {self.mqtt_client_name}")

        
    def update_state(self):
        utime.sleep_us(MICRO_SLEEP)
        relative_ts_micro = utime.ticks_us() - self.start_micro
        self.ts_list.append(relative_ts_micro)
        self.state_list.append(self.pulse_pin.value())
    
    def flush_readings(self):
        self.ts_list = []
        self.state_list = []

    def publish_pin_state_list(self):
        ts_list = self.ts_list
        state_list = self.state_list
        self.flush_readings()

        payload = {
            "AboutNodeName": self.flow_node_name,
            "RelativeTsMicroList": ts_list,
            "ValueList": state_list, 
            "TypeName": "pin.state.list", 
            "Version": "001"
        }
        json_payload = ujson.dumps(payload)
        self.client.publish(self.mqtt_topic, json_payload)
    
    def capture(self, list_length: int):
        s = utime.ticks_ms()
        while len(self.ts_list) < list_length:
            self.update_state()
        e = utime.ticks_ms()
        print(f"Capture took {e-s} ms")
        s = utime.ticks_ms()
        self.publish_pin_state_list()
        e = utime.ticks_ms()
        print(f"Post took {e-s} ms")

    def start(self):
        self.connect_to_wifi()
        self.start_mqtt_client()
        self.start_micro = utime.ticks_us()
        now_micro = utime.ticks_us()
        batches = 0
        while(now_micro - self.start_micro < TOTAL_TIME_SECONDS * 10**6):
            now_micro = utime.ticks_us()
            self.update_state()
            if len(self.ts_list) > LIST_LENGTH:
                self.publish_pin_state_list()
                batches +=1
                print(f"Batch {batches}")


if __name__ == "__main__":
    p = PicoFlowScope()
    p.start()