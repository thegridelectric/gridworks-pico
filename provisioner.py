import machine
import ujson
from utils import get_hw_uid

APP_CONFIG_FILE = "app_config.json"

ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27
ADC2_PIN_NUMBER = 28
TOTAL_REPORTS = 200
SAMPLES = 1000

PIN_0_OFFSET = 2.4
PIN_1_OFFSET = -2.4

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
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()
        print("HW UID, Pin 0 mV, Pin 1 mV, Pin 2 mV (OFFSETS DONE ON PIN 0 and 1)")
        while self.num_recorded < TOTAL_REPORTS:
            self.print_sample()


class Prov_flow:
    def __init__(self):
        self.hw_uid = get_hw_uid()
    
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
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()
        print("Done. You can now close this file.")

if __name__ == "__main__":

    got_type = False
    while not got_type:
        type = input("Is this Pico associated to a tank (enter '0') or a flow (enter '1'): ")
        if type not in {'0','1'}:
            print('Please enter 0 or 1')
        else:
            got_type = True

    if type == '0':
        p = Prov()
        p.start()
    elif type == '1':
        p = Prov_flow()
        p.start()