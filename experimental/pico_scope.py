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
ADC0_PIN_NUMBER = 26
DEFAULT_ACTOR_NAME = "vortex-scope"
SAMPLES_PER_BATCH = 1000
POST_PAUSE_MS = 300

# ---------------------------------
# Main class
# ---------------------------------

class PicoScope:
    
    def __init__(self):
        # Unique ID
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
        self.hw_uid = f"pico_{pico_unique_id}"
        
        # Hardware setup
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        
        # Configuration
        self.actor_name = DEFAULT_ACTOR_NAME
        self.load_comms_config()
        
        # Data collection buffers
        self.millivolts_list = []
        self.rel_us_list = []
        
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
    
    def collect_samples(self):
        '''Collect samples as fast as possible'''
        self.millivolts_list = []
        self.rel_us_list = []
        
        # Record start time in microseconds
        start_us = utime.ticks_us()
        
        # Collect samples as fast as possible
        for _ in range(SAMPLES_PER_BATCH):
            # Get timestamp first for minimal jitter
            timestamp_us = utime.ticks_us()
            
            # Read ADC (0-65535 for 0-3.3V)
            raw_value = self.adc0.read_u16()
            
            # Convert to millivolts (3300mV full scale)
            millivolts = int(raw_value * 3300 / 65535)
            
            # Calculate relative microseconds from start
            rel_us = utime.ticks_diff(timestamp_us, start_us)
            
            # Store values
            self.millivolts_list.append(millivolts)
            self.rel_us_list.append(rel_us)
        
        # Record timestamp just before posting
        self.pico_before_post_ns = utime.time_ns() if hasattr(utime, 'time_ns') else utime.time() * 1_000_000_000
    
    def post_scope_data(self):
        '''Post collected data to FastAPI endpoint'''
        url = self.base_url + f"/{self.actor_name}/scope-data"
        
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_name,
            "MillivoltsList": self.millivolts_list,
            "RelativeMicrosecondList": self.rel_us_list,
            "PicoBeforePostTimestampNanoSecond": int(self.pico_before_post_ns),
            "TypeName": "scope.data",
            "Version": "000"
        }
        
        headers = {'Content-Type': 'application/json'}
        json_payload = ujson.dumps(payload)
        
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                result = response.json()
                print(f"Data posted successfully. Peak-to-peak: {result.get('peak_to_peak_mv', 'N/A')} mV")
            else:
                print(f"Failed to post data. Status: {response.status_code}")
            response.close()
        except Exception as e:
            print(f"Error posting scope data: {e}")
        finally:
            gc.collect()
    
    def main_loop(self):
        '''Main collection and posting loop'''
        while True:
            # Collect samples
            print(f"Collecting {SAMPLES_PER_BATCH} samples...")
            self.collect_samples()
            
            # Calculate collection stats
            duration_us = self.rel_us_list[-1] if self.rel_us_list else 0
            duration_ms = duration_us / 1000
            if duration_us > 0:
                sample_rate_khz = (SAMPLES_PER_BATCH * 1000) / duration_us
                print(f"Collected in {duration_ms:.1f} ms ({sample_rate_khz:.1f} kHz sampling rate)")
            
            # Post data
            print("Posting data...")
            self.post_scope_data()
            
            # Pause to avoid timestamp issues during transmission
            print(f"Pausing {POST_PAUSE_MS} ms...")
            utime.sleep_ms(POST_PAUSE_MS)
    
    def start(self):
        '''Initialize and start the oscilloscope'''
        # Connect to network
        if self.wifi_or_ethernet == 'wifi':
            self.connect_to_wifi()
        elif self.wifi_or_ethernet == 'ethernet':
            self.connect_to_ethernet()
        
        print(f"Starting oscilloscope on ADC0 (pin {ADC0_PIN_NUMBER})")
        print(f"Will collect {SAMPLES_PER_BATCH} samples per batch")
        
        # Start main loop
        self.main_loop()


if __name__ == "__main__":
    scope = PicoScope()
    scope.start()

