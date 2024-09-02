import machine
import utime
import utime
from utils import get_hw_uid

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
        return int(10**3 * sum(voltages) / self.samples)
    
    def mv1(self):
        readings = []
        for _ in range(self.samples):
            # Read the raw ADC value (0-65535)
            readings.append(self.adc1.read_u16())
        voltages = list(map(lambda x: x * 3.3 / 65535, readings))
        return int(10**3 * sum(voltages) / self.samples)

    def mv2(self):
        readings = []
        for _ in range(self.samples):
            # Read the raw ADC value (0-65535)
            readings.append(self.adc2.read_u16())
        voltages = list(map(lambda x: x * 3.3 / 65535, readings))
        return int(10**3 * sum(voltages) / self.samples)
        
    def print_sample(self):
            report = f"{self.hw_uid}, {self.mv0()}, {self.mv1()}, {self.mv2()}"
            print(report)
            self.num_recorded += 1

    def start(self):
        while self.num_recorded < self.samples:
            self.print_sample()

if __name__ == "__main__":
    p = Prov()
    p.start()
