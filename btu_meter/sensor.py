"""
Raspberry Pi Pico W - JSON Communication Protocol
Template for sending sensor data as JSON packets over serial or MQTT
"""

from machine import Pin, ADC
import utime
import math
import json
import os


# ========== CONFIGURATION LOADER ==========
class ConfigLoader:
    def __init__(self, ConfigFilePath="config.json"):
        """
        Load configuration from JSON file
        
        Args:
            ConfigFilePath: Path to configuration JSON file
        """
        self.ConfigFilePath = ConfigFilePath
        self.Config = self.LoadConfig()
        
    def LoadConfig(self):
        """
        Load configuration from JSON file
        
        Returns:
            Configuration dictionary
        """
        try:
            with open(self.ConfigFilePath, 'r') as f:
                Config = json.load(f)
                print(f"✓ Configuration loaded from {self.ConfigFilePath}")
                return Config
        except OSError:
            print(f"✗ Config file not found: {self.ConfigFilePath}")
            print("  Using default configuration")
            return self.GetDefaultConfig()
        except ValueError as e:
            print(f"✗ Invalid JSON in config file: {e}")
            print("  Using default configuration")
            return self.GetDefaultConfig()
    
    def GetDefaultConfig(self):
        """
        Return default configuration if file not found or invalid
        
        Returns:
            Default configuration dictionary
        """
        return {
            "DeviceIdentity": {
                "DeviceId": "btuMeter_01",
                "Location": "Unknown"
            },
            "HardwareCalibration": {
                "KFlowFactor": 0.15,
                "ThermistorR1": 10000,
                "ThermistorR2Nominal": 10000,
                "ThermistorBCoefficient": 3977,
                "ThermistorTNominal": 25
            },
            "FluidProperties": {
                "SpecificHeat": 4.186,
                "Density": 1000
            },
            "MeasurementTiming": {
                "MeasurementInterval": 1.0,
                "TransmissionInterval": 10.0
            },
            "ChangeDetection": {
                "EnableChangeDetection": True,
                "DeltaTThreshold": 1.0,
                "FlowThreshold": 1.0
            },
            "GpioPins": {
                "FreqPin": 22,
                "Temp1Pin": 26,
                "Temp2Pin": 27
            },
            "MqttSettings": {
                "Enabled": False,
                "Broker": "mqtt.example.com",
                "Port": 1883,
                "Topic": "sensors/btu_meter",
                "Username": "",
                "Password": ""
            }
        }
    
    def SaveConfig(self, Config):
        """
        Save configuration to JSON file
        
        Args:
            Config: Configuration dictionary to save
        """
        try:
            with open(self.ConfigFilePath, 'w') as f:
                # MicroPython json.dump doesn't support indent
                json.dump(Config, f)
            print(f"✓ Configuration saved to {self.ConfigFilePath}")
            return True
        except Exception as e:
            print(f"✗ Failed to save config: {e}")
            return False
    
    def PrintConfig(self):
        """Print current configuration in readable format"""
        print("\n" + "=" * 60)
        print("CURRENT CONFIGURATION")
        print("=" * 60)
        
        # MicroPython json.dumps doesn't support indent parameter
        # Print sections manually for readability
        print("Device Identity:")
        for key, value in self.Config["DeviceIdentity"].items():
            print(f"  {key}: {value}")
        
        print("\nHardware Calibration:")
        for key, value in self.Config["HardwareCalibration"].items():
            print(f"  {key}: {value}")
        
        print("\nFluid Properties:")
        for key, value in self.Config["FluidProperties"].items():
            print(f"  {key}: {value}")
        
        print("\nMeasurement Timing:")
        for key, value in self.Config["MeasurementTiming"].items():
            print(f"  {key}: {value}")
        
        print("\nChange Detection:")
        for key, value in self.Config["ChangeDetection"].items():
            print(f"  {key}: {value}")
        
        print("\nGPIO Pins:")
        for key, value in self.Config["GpioPins"].items():
            print(f"  {key}: {value}")
        
        print("\nMQTT Settings:")
        for key, value in self.Config["MqttSettings"].items():
            print(f"  {key}: {value}")
        
        print("=" * 60 + "\n")


# ========== THERMISTOR READER CLASS ==========
class ThermistorReader:
    def __init__(self, AdcPin, R1=10000, R2Nominal=10000, 
                 TNominal=25, BCoefficient=3977, VRef=3.3):
        self.Adc = ADC(Pin(AdcPin))
        self.R1 = R1
        self.R2Nominal = R2Nominal
        self.TNominal = TNominal
        self.BCoefficient = BCoefficient
        self.VRef = VRef
        self.AdcMax = 4095
        
    def ReadVoltage(self):
        AdcValue = self.Adc.read_u16() >> 4
        Voltage = (AdcValue / self.AdcMax) * self.VRef
        return Voltage
    
    def ReadResistance(self):
        Voltage = self.ReadVoltage()
        if Voltage >= self.VRef:
            return float('inf')
        if Voltage <= 0:
            return 0
        Resistance = self.R1 * Voltage / (self.VRef - Voltage)
        return Resistance
    
    def ReadTemperatureCelsius(self, Samples=5):
        TotalResistance = 0
        for _ in range(Samples):
            TotalResistance += self.ReadResistance()
        AvgResistance = TotalResistance / Samples
        
        try:
            TNominalK = self.TNominal + 273.15
            InvT = (1.0 / TNominalK) + (1.0 / self.BCoefficient) * math.log(AvgResistance / self.R2Nominal)
            TempK = 1.0 / InvT
            TempC = TempK - 273.15
            return TempC
        except (ValueError, ZeroDivisionError):
            return float('nan')


# ========== FREQUENCY READER CLASS ==========
class FrequencyReader:
    def __init__(self, PinNum=22):
        self.Pin = Pin(PinNum, Pin.IN, Pin.PULL_DOWN)
        self.PulseCount = 0
        self.LastMeasurementTime = utime.ticks_us()
        self.Pin.irq(trigger=Pin.IRQ_RISING, handler=self._PulseHandler)
        
    def _PulseHandler(self, pin):
        self.PulseCount += 1
    
    def GetFrequency(self, Reset=True):
        CurrentTime = utime.ticks_us()
        ElapsedUs = utime.ticks_diff(CurrentTime, self.LastMeasurementTime)
        ElapsedSec = ElapsedUs / 1_000_000.0
        
        if ElapsedSec == 0:
            return 0.0
        
        Frequency = self.PulseCount / ElapsedSec
        
        if Reset:
            self.PulseCount = 0
            self.LastMeasurementTime = CurrentTime
        
        return Frequency


# ========== JSON PACKET BUILDER ==========
class SensorDataPacket:
    def __init__(self, DeviceId="btuMeter", Location="Unknown", KFlowFactor=0.15, Cp=4.186):
        """
        Initialize JSON packet builder
        
        Args:
            DeviceId: Unique identifier for this device
            Location: Device location description
            KFlowFactor: Flow meter calibration constant (LPM/Hz)
            Cp: Specific heat capacity of water in J/g°C
        """
        self.DeviceId = DeviceId
        self.Location = Location
        self.KFlowFactor = KFlowFactor
        self.Cp = Cp
        
    def BuildPacket(self, Frequency, Temp1C, Temp2C):
        """
        Build a JSON data packet from sensor readings
        
        Args:
            Frequency: Flow meter frequency in Hz
            Temp1C: Temperature 1 in Celsius (inlet)
            Temp2C: Temperature 2 in Celsius (outlet)
            
        Returns:
            Dictionary (can be serialized to JSON)
        """
        FlowRate = self.KFlowFactor * Frequency  # Flow rate in LPM
        
        # Calculate instantaneous power in watts
        MassFlowRateGPerSec = FlowRate * 1000.0 / 60.0
        DeltaT = Temp1C - Temp2C
        Watts = MassFlowRateGPerSec * self.Cp * DeltaT

        Packet = {
            "DeviceId": self.DeviceId,
            "Location": self.Location,
            "Timestamp": utime.time(),
            "Flow": {
                "FrequencyHz": round(Frequency, 2),
                "FlowRateLPM": round(FlowRate, 2)
            },
            "Temperature": {
                "Sensor1": {
                    "TempC": round(Temp1C, 2),
                },
                "Sensor2": {
                    "TempC": round(Temp2C, 2),
                },
                "DeltaT": round(DeltaT, 2)
            },
            "Energy": {
                "InstantaneousWatts": round(Watts, 2)
            }
        }
        
        return Packet
    
    def ToJsonString(self, Packet):
        """Convert packet dictionary to JSON string"""
        return json.dumps(Packet)


# ========== INTEGRATED BTU METER SYSTEM ==========
class BTUMeterSystem:
    def __init__(self, Config):
        """
        Initialize BTU meter system from configuration
        
        Args:
            Config: Configuration dictionary
        """
        # Extract configuration
        self.Config = Config
        DeviceId = Config["DeviceIdentity"]["DeviceId"]
        Location = Config["DeviceIdentity"]["Location"]
        
        HwCal = Config["HardwareCalibration"]
        FluidProps = Config["FluidProperties"]
        Pins = Config["GpioPins"]
        
        # Initialize hardware
        self.FreqReader = FrequencyReader(PinNum=Pins["FreqPin"])
        
        self.Thermistor1 = ThermistorReader(
            AdcPin=Pins["Temp1Pin"],
            R1=HwCal["ThermistorR1"],
            R2Nominal=HwCal["ThermistorR2Nominal"],
            TNominal=HwCal["ThermistorTNominal"],
            BCoefficient=HwCal["ThermistorBCoefficient"]
        )
        
        self.Thermistor2 = ThermistorReader(
            AdcPin=Pins["Temp2Pin"],
            R1=HwCal["ThermistorR1"],
            R2Nominal=HwCal["ThermistorR2Nominal"],
            TNominal=HwCal["ThermistorTNominal"],
            BCoefficient=HwCal["ThermistorBCoefficient"]
        )
        
        self.PacketBuilder = SensorDataPacket(
            DeviceId=DeviceId,
            Location=Location,
            KFlowFactor=HwCal["KFlowFactor"],
            Cp=FluidProps["SpecificHeat"]
        )
        
        self.KFlowFactor = HwCal["KFlowFactor"]
        
        # Change detection
        self.LastTransmittedDeltaT = 0.0
        self.LastTransmittedFlowRate = 0.0
        
    def MeasureAll(self):
        """
        Measure all sensors
        
        Returns:
            Tuple of (Frequency, Temp1C, Temp2C)
        """
        Frequency = self.FreqReader.GetFrequency(Reset=True)
        Temp1C = self.Thermistor1.ReadTemperatureCelsius()
        Temp2C = self.Thermistor2.ReadTemperatureCelsius()
        return Frequency, Temp1C, Temp2C
    
    def CheckSignificantChange(self, DeltaTThreshold, FlowThreshold):
        """
        Check if temperature delta or flow rate has changed significantly
        
        Args:
            DeltaTThreshold: Minimum change in delta_T (°C)
            FlowThreshold: Minimum change in flow rate (LPM)
            
        Returns:
            True if significant change detected
        """
        Frequency = self.FreqReader.GetFrequency(Reset=False)
        Temp1C = self.Thermistor1.ReadTemperatureCelsius()
        Temp2C = self.Thermistor2.ReadTemperatureCelsius()
        
        CurrentDeltaT = Temp1C - Temp2C
        CurrentFlowRate = self.KFlowFactor * Frequency
        
        DeltaTChange = abs(CurrentDeltaT - self.LastTransmittedDeltaT)
        FlowChange = abs(CurrentFlowRate - self.LastTransmittedFlowRate)
        
        if DeltaTChange >= DeltaTThreshold or FlowChange >= FlowThreshold:
            self.LastTransmittedDeltaT = CurrentDeltaT
            self.LastTransmittedFlowRate = CurrentFlowRate
            return True
        
        return False
    
    def GetJsonString(self, Frequency, Temp1C, Temp2C):
        """Get JSON string from sensor readings"""
        Packet = self.PacketBuilder.BuildPacket(Frequency, Temp1C, Temp2C)
        return self.PacketBuilder.ToJsonString(Packet)


def main():
    """Main program with configuration file"""
    
    print("\n" + "=" * 80)
    print("BTU METER - Raspberry Pi Pico W")
    print("=" * 80 + "\n")
    
    # Load configuration
    ConfigLoader_obj = ConfigLoader("config.json")
    Config = ConfigLoader_obj.Config
    
    # Print configuration
    ConfigLoader_obj.PrintConfig()
    
    # Extract timing settings
    MeasurementInterval = Config["MeasurementTiming"]["MeasurementInterval"]
    TransmissionInterval = Config["MeasurementTiming"]["TransmissionInterval"]
    
    # Extract change detection settings
    ChangeDetection = Config["ChangeDetection"]
    EnableChangeDetection = ChangeDetection["EnableChangeDetection"]
    DeltaTThreshold = ChangeDetection["DeltaTThreshold"]
    FlowThreshold = ChangeDetection["FlowThreshold"]
    
    # Initialize BTU meter
    print("Initializing BTU meter...")
    BtuMeter = BTUMeterSystem(Config)
    print("✓ BTU meter initialized\n")
    
    print("Configuration Summary:")
    print(f"  Device ID: {Config['DeviceIdentity']['DeviceId']}")
    print(f"  Location: {Config['DeviceIdentity']['Location']}")
    print(f"  Measurement Interval: {MeasurementInterval} sec")
    print(f"  Transmission Interval: {TransmissionInterval} sec")
    print(f"  Change Detection: {'Enabled' if EnableChangeDetection else 'Disabled'}")
    if EnableChangeDetection:
        print(f"    - Delta-T Threshold: ±{DeltaTThreshold}°C")
        print(f"    - Flow Threshold: ±{FlowThreshold} LPM")
    print("\n" + "=" * 80)
    print("Starting measurements...")
    print("Press Ctrl+C to stop")
    print("=" * 80 + "\n")
    
    # Timing variables
    LastTransmissionTime = utime.time()
    MeasurementCounter = 0
    TransmissionCounter = 0
    
    try:
        while True:
            # Measure sensors
            Frequency, Temp1C, Temp2C = BtuMeter.MeasureAll()
            MeasurementCounter += 1
            
            # Check transmission conditions
            CurrentTime = utime.time()
            TimeSinceTransmission = CurrentTime - LastTransmissionTime
            
            # Condition 1: Regular interval exceeded
            TimeBasedTrigger = TimeSinceTransmission >= TransmissionInterval
            
            # Condition 2: Significant change detected (if enabled)
            ChangeBasedTrigger = False
            if EnableChangeDetection:
                ChangeBasedTrigger = BtuMeter.CheckSignificantChange(
                    DeltaTThreshold=DeltaTThreshold,
                    FlowThreshold=FlowThreshold
                )
            
            # Transmit if either condition is met
            if TimeBasedTrigger or ChangeBasedTrigger:
                JsonString = BtuMeter.GetJsonString(Frequency, Temp1C, Temp2C)
                
                # Indicate why we transmitted
                TriggerReason = []
                if TimeBasedTrigger:
                    TriggerReason.append("TIMER")
                if ChangeBasedTrigger:
                    TriggerReason.append("CHANGE")
                
                print(f"[{'/'.join(TriggerReason)}] {JsonString}")
                
                LastTransmissionTime = CurrentTime
                TransmissionCounter += 1
            
            # Wait until next measurement
            utime.sleep(MeasurementInterval)
            
    except KeyboardInterrupt:
        print("\n" + "=" * 80)
        print("BTU Meter stopped")
        print(f"Total measurements: {MeasurementCounter}")
        print(f"Total transmissions: {TransmissionCounter}")
        print("=" * 80)


if __name__ == "__main__":
    main()

