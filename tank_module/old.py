import gc
import time

import machine
import network
import ujson
import urequests
import utime


class TmPico:
    def __init__(self):
        # Parameters that are updated on boot
        self.samples = 1000
        self.adc0 = machine.ADC(26)
        self.adc1 = machine.ADC(27)
        self.node_by_adc = {
            self.adc0:  "tank1-depth1",
            self.adc1:  "tank1-depth2",
        }
        # parameters that need to be set ahead of time
        self.wifi_name = "OurKatahdin"
        self.wifi_password =  "classyraven882"
        self.base_url =  "http://192.168.0.165:8000"
        self.micro_volts_by_adc = {
            self.adc0: 0,
            self.adc1: 0,
        }

    def connect_to_wifi(self):
        # Connect to wifi
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            print("Connecting to wifi...")
            wlan.connect(self.wifi_name, self.wifi_password)
            while not wlan.isconnected():
                time.sleep(1)
        print(f"Connected to wifi {self.wifi_name}")

    def publish_microvolts(self, adc):
        url = self.base_url + f"/{self.node_by_adc[adc]}/microvolts"
        payload = {'MicroVolts': self.micro_volts_by_adc[adc], "TypeName": "microvolts", "Version": "000"}
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting hz: {e}")
    
    def adc0_micros(self):
        readings = []
        for _ in range(self.samples):
            # Read the raw ADC value (0-65535)
            readings.append(self.adc0.read_u16())
        voltages = list(map(lambda x: x * 3.3 / 65535, readings))
        return int(10**6 * sum(voltages) / self.samples)
    
    def adc1_micros(self):
        readings = []
        for _ in range(self.samples):
            # Read the raw ADC value (0-65535)
            readings.append(self.adc1.read_u16())
        voltages = list(map(lambda x: x * 3.3 / 65535, readings))
        return int(10**6 * sum(voltages) / self.samples)

    def get_params(self):
        ...
        # TODO: send a post that gets back the sample size
        # and the names of the channels
    
    def start(self):
        while True:
            self.micro_volts_by_adc[self.adc0] = self.adc0_micros()
            self.publish_microvolts(self.adc0)
            self.micro_volts_by_adc[self.adc1] = self.adc1_micros()
            self.publish_microvolts(self.adc1)
            gc.collect()







