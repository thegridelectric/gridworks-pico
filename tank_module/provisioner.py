import machine
import ujson
from utils import get_hw_uid

APP_CONFIG_FILE = "app_config.json"

ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27
ADC2_PIN_NUMBER = 28
TOTAL_REPORTS = 5
SAMPLES = 1000

class Prov:
    def __init__(self):
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        self.adc2 = machine.ADC(ADC2_PIN_NUMBER)
        self.hw_uid = get_hw_uid()
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
            report = f"{self.hw_uid}, {self.mv0()}, {self.mv1()}, {self.mv2()}"
            print(report)
            self.num_recorded += 1
    
    def set_name(self):
        got_a_or_b = False
        while not got_a_or_b:
            a_or_b = input("Tank Module pico a or b? Type 'a' or 'b'")
            self.pico_a_b = a_or_b
            if a_or_b not in {'a', 'b'}:
                print("please enter a or b!")
            else:
                got_a_or_b = True
        
        got_tank_name = False
        while not got_tank_name:
            name = input(f"Tank Name: 'buffer', 'tank1', tank2', 'tank3'")
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
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()
        while self.num_recorded < self.samples:
            self.print_sample()

if __name__ == "__main__":
    p = Prov()
    p.start()
