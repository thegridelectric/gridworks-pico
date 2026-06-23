import machine
import utime
import network
import ujson
import urequests
import ubinascii
import gc

# ---------------------------------
# Constants
# ---------------------------------

COMMS_CONFIG_FILE = "comms_config.json"
PULSE_PIN_NUMBER = 21  # Adjust as needed
DEFAULT_ACTOR_NAME = "vortex-profile"
CAPTURE_DURATION_S = 10
POST_PAUSE_MS = 300

# ---------------------------------
# Main class
# ---------------------------------

class PulseProfile:
    
    def __init__(self):
        # Unique ID
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
        self.hw_uid = f"pico_{pico_unique_id}"
        
        # Hardware setup
        self.pulse_pin = machine.Pin(PULSE_PIN_NUMBER, machine.Pin.IN, machine.Pin.PULL_UP)
        
        # Configuration
        self.actor_name = DEFAULT_ACTOR_NAME
        self.load_comms_config()
        
        # Edge capture data
        self.first_edge_us = None
        self.rising_edges_us = []
        self.falling_edges_us = []
        self.last_pin_state = None
        self.capturing = False
        self.capture_start_s = None
        
    def load_comms_config(self):
        '''Load the communication configuration file'''
        try:
            with open(COMMS_CONFIG_FILE, "r") as f:
                comms_config = ujson.load(f)
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Error loading comms_config file: {e}")
            
        self.wifi_or_ethernet = comms_config.get("WifiOrEthernet", 'wifi')
        self.wifi_name = comms_config.get("WifiName", None)
        self.wifi_password = comms_config.get("WifiPassword", None)
        self.base_url = comms_config.get("BaseUrl")
        
        if self.wifi_or_ethernet == 'wifi':
            if self.wifi_name is None:
                raise KeyError("WifiName not found in comms_config.json")
            if self.wifi_password is None:
                raise KeyError("WifiPassword not found in comms_config.json")
        elif self.wifi_or_ethernet != 'ethernet':
            raise KeyError("WifiOrEthernet must be either 'wifi' or 'ethernet' in comms_config.json")
            
        if self.base_url is None:
            raise KeyError("BaseUrl not found in comms_config.json")
    
    def connect_to_wifi(self):
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            print("Connecting to wifi...")
            wlan.connect(self.wifi_name, self.wifi_password)
            while not wlan.isconnected():
                utime.sleep_ms(500)
        print(f"Connected to wifi {self.wifi_name}")
    
    def connect_to_ethernet(self):
        nic = network.WIZNET5K()
        for attempt in range(3):
            try:
                nic.active(True)
                break
            except Exception as e:
                print(f"Retrying NIC activation due to: {e}")
                utime.sleep(0.5)
        if not nic.isconnected():
            print("Connecting to Ethernet...")
            nic.ifconfig('dhcp')
            timeout = 10
            start = utime.time()
            while not nic.isconnected():
                if utime.time() - start > timeout:
                    raise RuntimeError("Failed to connect to Ethernet (timeout)")
                utime.sleep(0.5)
        print("Connected to Ethernet")
    
    def edge_callback(self, pin):
        '''Interrupt handler for both rising and falling edges'''
        if not self.capturing:
            return
            
        # Get timestamp in microseconds
        now_us = utime.ticks_us()
        
        # Read current pin state
        pin_state = pin.value()
        
        # Skip if state hasn't changed (debounce)
        if pin_state == self.last_pin_state:
            return
            
        if self.first_edge_us is None:
            # First edge - store absolute time in microseconds
            self.first_edge_us = now_us
            self.last_pin_state = pin_state
            edge_type = "rising" if pin_state else "falling"
            print(f"First edge captured ({edge_type})")
        else:
            # Calculate relative microseconds from first edge
            rel_us = utime.ticks_diff(now_us, self.first_edge_us)
            
            # Store in appropriate list based on edge type
            if pin_state == 1:  # Rising edge (went from 0 to 1)
                self.rising_edges_us.append(rel_us)
            else:  # Falling edge (went from 1 to 0)
                self.falling_edges_us.append(rel_us)
            
            self.last_pin_state = pin_state
    
    def capture_profile(self):
        '''Capture edges for CAPTURE_DURATION_S seconds'''
        print(f"\nStarting {CAPTURE_DURATION_S} second capture...")
        
        # Reset data
        self.first_edge_us = None
        self.rising_edges_us = []
        self.falling_edges_us = []
        self.last_pin_state = self.pulse_pin.value()
        
        # Enable interrupt for both edges
        self.capturing = True
        self.capture_start_s = utime.time()
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_RISING | machine.Pin.IRQ_FALLING, 
                          handler=self.edge_callback)
        
        # Wait for capture duration
        while utime.time() - self.capture_start_s < CAPTURE_DURATION_S:
            # Show progress
            elapsed = utime.time() - self.capture_start_s
            total_edges = len(self.rising_edges_us) + len(self.falling_edges_us) + (1 if self.first_edge_us else 0)
            print(f"  {elapsed:.1f}s: {total_edges} edges ({len(self.rising_edges_us)} rising, {len(self.falling_edges_us)} falling)", end="\r")
            utime.sleep_ms(100)
        
        # Disable interrupt
        self.capturing = False
        self.pulse_pin.irq(handler=None)
        
        # Final count
        total_edges = len(self.rising_edges_us) + len(self.falling_edges_us) + (1 if self.first_edge_us else 0)
        print(f"\nCapture complete: {total_edges} edges in {CAPTURE_DURATION_S} seconds")
        print(f"  Rising edges: {len(self.rising_edges_us)}")
        print(f"  Falling edges: {len(self.falling_edges_us)}")
        
        # Estimate frequency if we have enough edges
        if len(self.rising_edges_us) > 1:
            # Calculate average period between rising edges
            periods = []
            for i in range(1, len(self.rising_edges_us)):
                period_us = self.rising_edges_us[i] - self.rising_edges_us[i-1]
                periods.append(period_us)
            if periods:
                avg_period_us = sum(periods) / len(periods)
                freq_hz = 1_000_000 / avg_period_us
                print(f"  Estimated frequency: {freq_hz:.2f} Hz")
    
    def post_profile(self):
        '''Post pulse profile data to FastAPI endpoint'''
        url = self.base_url + f"/{self.actor_name}/pulse-profile"
        
        payload = {
            "HwUid": self.hw_uid,
            "FirstEdgeUs": self.first_edge_us,
            "RisingEdgesUs": self.rising_edges_us,
            "FallingEdgesUs": self.falling_edges_us,
            "PicoSentMs": int(utime.time() * 1000),
            "TypeName": "pulse.profile"
        }
        
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                result = response.json()
                print(f"Profile posted successfully")
                if "frequency_hz" in result:
                    print(f"Server calculated: {result['frequency_hz']:.2f} Hz")
                if "duty_cycle" in result:
                    print(f"Duty cycle: {result['duty_cycle']:.1f}%")
            else:
                print(f"Failed to post profile. Status: {response.status_code}")
            response.close()
        except Exception as e:
            print(f"Error posting profile: {e}")
        finally:
            gc.collect()
    
    def main_loop(self):
        '''Main capture and posting loop'''
        while True:
            # Capture profile
            self.capture_profile()
            self.post_profile()
            
            # Pause before next capture
            print(f"Pausing {POST_PAUSE_MS} ms before next capture...")
            utime.sleep_ms(POST_PAUSE_MS)
    
    def start(self):
        '''Initialize and start the pulse profile capture'''
        # Connect to network
        if self.wifi_or_ethernet == 'wifi':
            self.connect_to_wifi()
        elif self.wifi_or_ethernet == 'ethernet':
            self.connect_to_ethernet()
        
        print(f"Starting pulse profile capture on pin {PULSE_PIN_NUMBER}")
        print(f"Will capture both rising and falling edges for {CAPTURE_DURATION_S} seconds per batch")
        
        # Start main loop
        self.main_loop()


if __name__ == "__main__":
    profiler = PulseProfile()
    profiler.start()
