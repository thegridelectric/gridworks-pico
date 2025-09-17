import machine


def measure_chip_temperature(self):
        temp_sensor_pin = machine.ADC(4)
        reading = temp_sensor_pin.read_u16()
        voltage = reading * 3.3 / 65535
        temperature_c = 27 - (voltage - 0.706) / 0.001721
        return temperature_c * 9/5 + 32
        