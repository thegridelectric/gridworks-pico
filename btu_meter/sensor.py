"""
Raspberry Pi Pico W - Sensor reader with JSON comunication template
"""

from machine import Pin, ADC
import utime
import math
import json


# ========== THERMISTOR READER CLASS ==========
class ThermistorReader:
    def __init__(self, adc_pin, r1=10000, r2_nominal=10000, 
                 t_nominal=25, b_coefficient=3977, vref=3.3):
        self.adc = ADC(Pin(adc_pin))
        self.r1 = r1
        self.r2_nominal = r2_nominal
        self.t_nominal = t_nominal
        self.b_coefficient = b_coefficient
        self.vref = vref
        self.adc_max = 4095
        
    def read_voltage(self):
        adc_value = self.adc.read_u16() >> 4
        voltage = (adc_value / self.adc_max) * self.vref
        return voltage
    
    def read_resistance(self):
        voltage = self.read_voltage()
        if voltage >= self.vref:
            return float('inf')
        if voltage <= 0:
            return 0
        resistance = self.r1 * voltage / (self.vref - voltage)
        return resistance
    
    def read_temperature_celsius(self, samples=5):
        total_resistance = 0
        for _ in range(samples):
            total_resistance += self.read_resistance()
        avg_resistance = total_resistance / samples
        
        try:
            t_nominal_k = self.t_nominal + 273.15
            inv_t = (1.0 / t_nominal_k) + (1.0 / self.b_coefficient) * math.log(avg_resistance / self.r2_nominal)
            temp_k = 1.0 / inv_t
            temp_c = temp_k - 273.15
            return temp_c
        except (ValueError, ZeroDivisionError):
            return float('nan')


# ========== FREQUENCY READER CLASS ==========
class FrequencyReader:
    def __init__(self, pin_num=22):
        self.pin = Pin(pin_num, Pin.IN, Pin.PULL_DOWN)
        self.pulse_count = 0
        self.last_measurement_time = utime.ticks_us()
        self.pin.irq(trigger=Pin.IRQ_RISING, handler=self._pulse_handler)
        
    def _pulse_handler(self, pin):
        self.pulse_count += 1
    
    def get_frequency(self, reset=True):
        current_time = utime.ticks_us()
        elapsed_us = utime.ticks_diff(current_time, self.last_measurement_time)
        elapsed_sec = elapsed_us / 1_000_000.0
        
        if elapsed_sec == 0:
            return 0.0
        
        frequency = self.pulse_count / elapsed_sec
        
        if reset:
            self.pulse_count = 0
            self.last_measurement_time = current_time
        
        return frequency


# ========== JSON PACKET BUILDER ==========
class SensorDataPacket:
    def __init__(self, device_id="PICO_01", k_ff=0.15):
        """
        Initialize JSON packet builder
        
        Args:
            device_id: Unique identifier for this device
            k_ff: Flow meter calibration constant
        """
        self.device_id = device_id
        self.k_ff = k_ff
        self.packet_sequence = 0
        
    def build_packet(self, frequency, temp1_c, temp1_v, temp2_c, temp2_v):
        """
        Build a JSON data packet from sensor readings
        
        Args:
            frequency: Flow meter frequency in Hz
            temp1_c: Temperature 1 in Celsius
            temp1_v: Voltage 1 in volts
            temp2_c: Temperature 2 in Celsius
            temp2_v: Voltage 2 in volts
            
        Returns:
            Dictionary (can be serialized to JSON)
        """
        self.packet_sequence += 1
        
        packet = {
            "device_id": self.device_id,
            "timestamp": utime.time(),
            "sequence": self.packet_sequence,
            "flow": {
                "frequency_hz": round(frequency, 2),
                "flow_rate_lpm": round(self.k_ff * frequency, 2)
            },
            "temperature": {
                "sensor_1": {
                    "temp_c": round(temp1_c, 2),
                    "voltage_v": round(temp1_v, 3)
                },
                "sensor_2": {
                    "temp_c": round(temp2_c, 2),
                    "voltage_v": round(temp2_v, 3)
                }
            }
        }
        
        return packet
    
    def build_packet_compact(self, frequency, temp1_c, temp1_v, temp2_c, temp2_v):
        """
        Build a compact JSON packet (shorter field names for bandwidth savings)
        
        Returns:
            Dictionary with abbreviated keys
        """
        self.packet_sequence += 1
        
        packet = {
            "id": self.device_id,
            "ts": utime.time(),
            "seq": self.packet_sequence,
            "f": round(frequency, 2),           # frequency (Hz)
            "fr": round(self.k_ff * frequency, 2),  # flow rate (LPM)
            "t1": round(temp1_c, 2),            # temp 1 (°C)
            "v1": round(temp1_v, 3),            # voltage 1 (V)
            "t2": round(temp2_c, 2),            # temp 2 (°C)
            "v2": round(temp2_v, 3)             # voltage 2 (V)
        }
        
        return packet
    
    def to_json_string(self, packet):
        """
        Convert packet dictionary to JSON string
        
        Args:
            packet: Dictionary from build_packet() or build_packet_compact()
            
        Returns:
            JSON string
        """
        return json.dumps(packet)


# ========== INTEGRATED SENSOR SYSTEM WITH JSON ==========
class SensorSystemWithJSON:
    def __init__(self, device_id="PICO_01", freq_pin=22, temp1_pin=26, temp2_pin=27, k_ff=0.15):
        """Initialize sensor system with JSON packet builder"""
        self.freq_reader = FrequencyReader(pin_num=freq_pin)
        self.thermistor_1 = ThermistorReader(adc_pin=temp1_pin)
        self.thermistor_2 = ThermistorReader(adc_pin=temp2_pin)
        self.packet_builder = SensorDataPacket(device_id=device_id, k_ff=k_ff)
        
    def read_and_build_packet(self, compact=False):
        """
        Read all sensors and build JSON packet
        
        Args:
            compact: If True, use compact packet format
            
        Returns:
            Dictionary ready to serialize as JSON
        """
        # Read all sensors
        frequency = self.freq_reader.get_frequency(reset=True)
        temp1_c = self.thermistor_1.read_temperature_celsius()
        temp1_v = self.thermistor_1.read_voltage()
        temp2_c = self.thermistor_2.read_temperature_celsius()
        temp2_v = self.thermistor_2.read_voltage()
        
        # Build packet
        if compact:
            return self.packet_builder.build_packet_compact(frequency, temp1_c, temp1_v, temp2_c, temp2_v)
        else:
            return self.packet_builder.build_packet(frequency, temp1_c, temp1_v, temp2_c, temp2_v)
    
    def read_and_send_json(self, compact=False):
        """
        Read sensors and return JSON string
        
        Args:
            compact: If True, use compact packet format
            
        Returns:
            JSON string
        """
        packet = self.read_and_build_packet(compact=compact)
        return self.packet_builder.to_json_string(packet)


def main():
    """Demonstration of JSON packet generation"""
    
    DEVICE_ID = "PICO_01"
    FREQ_PIN = 22
    TEMP1_PIN = 26
    TEMP2_PIN = 27
    K_FF = 0.15
    MEASUREMENT_INTERVAL = 1.0
    USE_COMPACT_FORMAT = False  # Set to True for compact packets
    
    print("=" * 80)
    print("JSON Communication Protocol Demo - Raspberry Pi Pico W")
    print("=" * 80)
    print(f"Device ID: {DEVICE_ID}")
    print(f"Packet Format: {'Compact' if USE_COMPACT_FORMAT else 'Standard'}")
    print("=" * 80)
    print()
    
    # Initialize sensor system
    sensors = SensorSystemWithJSON(
        device_id=DEVICE_ID,
        freq_pin=FREQ_PIN,
        temp1_pin=TEMP1_PIN,
        temp2_pin=TEMP2_PIN,
        k_ff=K_FF
    )
    
    print("Generating JSON packets...")
    print("Press Ctrl+C to stop")
    print()
    
    try:
        while True:
            utime.sleep(MEASUREMENT_INTERVAL)
            
            # Get JSON string
            json_string = sensors.read_and_send_json(compact=USE_COMPACT_FORMAT)
            
            # Print JSON packet (this would be sent over MQTT/serial)
            print(json_string)
            
    except KeyboardInterrupt:
        print("\n" + "=" * 80)
        print("Stopped")
        print("=" * 80)


if __name__ == "__main__":
    main()
