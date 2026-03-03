"""
Raspberry Pi Pico W - Square Wave Transmitter
Generates a square wave with configurable base frequency and per-pulse deviation
Each pulse has a slightly different period based on the deviation setting
"""

from machine import Pin
import utime
import random
import _thread

class SquareWaveGenerator:
    def __init__(self, pin_num=2, base_freq=50, deviation=2, base_duty_cycle=50, duty_deviation=5):
        """
        Initialize the square wave generator
        
        Args:
            pin_num: GPIO pin number for output
            base_freq: Base frequency in Hz
            deviation: Maximum frequency deviation in Hz (+/-)
                      Each pulse period is randomly varied within this range
            base_duty_cycle: Base duty cycle as percentage (0-100)
                            50 = 50% high, 50% low
            duty_deviation: Maximum duty cycle deviation in percentage (+/-)
                           e.g., 5 means duty can vary ±5% from base
        """
        self.pin = Pin(pin_num, Pin.OUT)
        self.base_freq = base_freq
        self.deviation = deviation
        self.base_duty_cycle = base_duty_cycle
        self.duty_deviation = duty_deviation
        self.running = False
        self.pulse_count = 0
        
    def set_base_freq(self, freq):
        """Set the base frequency in Hz"""
        self.base_freq = freq
        
    def set_deviation(self, dev):
        """Set the frequency deviation in Hz"""
        self.deviation = dev
        
    def set_base_duty_cycle(self, duty):
        """Set the base duty cycle as percentage (0-100)"""
        self.base_duty_cycle = max(0, min(100, duty))
        
    def set_duty_deviation(self, dev):
        """Set the duty cycle deviation in percentage"""
        self.duty_deviation = dev
        
    def _generate_wave(self):
        """Main wave generation loop - runs in separate thread"""
        # Initialize timing - use absolute target times to compensate for loop overhead
        next_edge_time = utime.ticks_us()
        
        while self.running:
            # Calculate this pulse's frequency with random deviation
            deviation_amount = random.uniform(-self.deviation, self.deviation)
            pulse_freq = self.base_freq + deviation_amount
            
            # Ensure frequency is positive
            if pulse_freq <= 0:
                pulse_freq = 1
            
            # Calculate this pulse's duty cycle with random deviation
            duty_deviation_amount = random.uniform(-self.duty_deviation, self.duty_deviation)
            pulse_duty_cycle = self.base_duty_cycle + duty_deviation_amount
            
            # Clamp duty cycle to valid range (5% to 95% to avoid extreme cases)
            pulse_duty_cycle = max(5, min(95, pulse_duty_cycle))
            
            # Calculate full period in microseconds (use float for precision)
            period_us = 1000000.0 / pulse_freq
            
            # Calculate high and low times based on duty cycle
            high_time_us = period_us * pulse_duty_cycle / 100.0
            low_time_us = period_us - high_time_us
            
            # Calculate absolute target times for this pulse
            high_end_time = next_edge_time + int(high_time_us)
            low_end_time = high_end_time + int(low_time_us)
            
            # High phase - wait until target time
            self.pin.value(1)
            while utime.ticks_diff(high_end_time, utime.ticks_us()) > 0:
                pass
            
            # Low phase - wait until target time
            self.pin.value(0)
            while utime.ticks_diff(low_end_time, utime.ticks_us()) > 0:
                pass
            
            # Set next edge time (this compensates for any timing drift)
            next_edge_time = low_end_time
            
            self.pulse_count += 1
        
    def start(self):
        """Start generating the square wave with per-pulse deviation"""
        if self.running:
            print("Generator already running")
            return
            
        self.running = True
        self.pulse_count = 0
        
        # Start wave generation in a separate thread
        _thread.start_new_thread(self._generate_wave, ())
        
    def stop(self):
        """Stop generating the square wave"""
        self.running = False
        utime.sleep_ms(100)  # Give thread time to finish
        self.pin.value(0)
        
    def get_pulse_count(self):
        """Return the number of pulses generated"""
        return self.pulse_count
    
    def get_config(self):
        """Return current configuration"""
        return {
            'base_freq': self.base_freq,
            'deviation': self.deviation,
            'base_duty_cycle': self.base_duty_cycle,
            'duty_deviation': self.duty_deviation,
            'running': self.running,
            'pulse_count': self.pulse_count
        }


def main():
    """Main program - demonstrates the square wave generator"""
    
    # Configuration
    OUTPUT_PIN = 2           # GPIO pin for square wave output
    BASE_FREQUENCY = 50      # Base frequency in Hz (50 Hz)
    DEVIATION = 2            # Deviation in Hz (+/- 2 Hz)
    BASE_DUTY_CYCLE = 50     # Base duty cycle (50% high, 50% low)
    DUTY_DEVIATION = 5       # Duty cycle deviation (+/- 5%)
    
    print("=" * 50)
    print("Square Wave Generator - Raspberry Pi Pico W")
    print("=" * 50)
    print(f"Output Pin: GPIO{OUTPUT_PIN}")
    print(f"Base Frequency: {BASE_FREQUENCY} Hz")
    print(f"Frequency Deviation: +/- {DEVIATION} Hz (per pulse)")
    print(f"Base Duty Cycle: {BASE_DUTY_CYCLE}%")
    print(f"Duty Cycle Deviation: +/- {DUTY_DEVIATION}%")
    print("=" * 50)
    
    # Create generator instance
    generator = SquareWaveGenerator(
        pin_num=OUTPUT_PIN,
        base_freq=BASE_FREQUENCY,
        deviation=DEVIATION,
        base_duty_cycle=BASE_DUTY_CYCLE,
        duty_deviation=DUTY_DEVIATION
    )
    
    # Start generating with per-pulse deviation
    generator.start()
    
    print("Square wave generation started!")
    print("Each pulse has random frequency and duty cycle deviation")
    print("Press Ctrl+C to stop")
    print()
    
    try:
        # Monitor pulse count
        last_count = 0
        last_time = utime.ticks_ms()
        
        while True:
            utime.sleep(1)
            
            current_count = generator.get_pulse_count()
            current_time = utime.ticks_ms()
            
            # Calculate actual frequency from pulse count
            pulses = current_count - last_count
            time_diff = utime.ticks_diff(current_time, last_time) / 1000.0
            measured_freq = pulses / time_diff if time_diff > 0 else 0
            
            print(f"Pulses: {current_count:6d} | Last second: {measured_freq:.2f} Hz")
            
            last_count = current_count
            last_time = current_time
            
    except KeyboardInterrupt:
        print("\nStopping square wave generation...")
        generator.stop()
        print("Stopped.")
        print(f"Total pulses generated: {generator.get_pulse_count()}")


if __name__ == "__main__":
    main()
