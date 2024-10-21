# ----------------------------------------------------
# Read the desired main.py files 
# ----------------------------------------------------

with open('flow_hall/flow_hall_main.py', 'r') as file:
    flow_hall_main = file.read()
with open('flow_reed/flow_reed_main.py', 'r') as file:
    flow_reed_main = file.read()
with open('tank_module/tank_module_main.py', 'r') as file:
    tank_module_main = file.read()

# ----------------------------------------------------
# 1 - Beginning of provisioner and beginning of hall main
# ----------------------------------------------------

step1 = """import machine
import ujson
import network
import utime
import urequests
import ubinascii
import os

# Constants
ADC0_PIN_NUMBER = 26
ADC1_PIN_NUMBER = 27
ADC2_PIN_NUMBER = 28
TOTAL_REPORTS = 200
SAMPLES = 1000
PIN_0_OFFSET = 2.4
PIN_1_OFFSET = -2.4

# Remove existing files
if 'boot.py' in os.listdir():
    os.remove('boot.py')
if 'app_config.json' in os.listdir():
    os.remove('app_config.json')
if 'comms_config.json' in os.listdir():
    os.remove('comms_config.json')
if 'main.py' in os.listdir():
    os.remove('main.py')
if 'main_previous.py' in os.listdir():
    os.remove('main_previous.py')

# *************************
# 1/3 - MAIN.PY PROVISION
# *************************

def write_flow_hall_main():
    main_code = \"\"\"
"""

# ----------------------------------------------------
# 2 - End of hall main, beginning of reed main
# ----------------------------------------------------

step2 = """
    \"\"\"
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_flow_reed_main():
    main_code = \"\"\"
"""

# ----------------------------------------------------
# 3 - End of reed main, beginning of tank main
# ----------------------------------------------------

step3 = """
    \"\"\"
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_tank_module_main():
    main_code = \"\"\"
"""

# ----------------------------------------------------
# 1 - End of tank main, end of provisioner
# ----------------------------------------------------

step4 = """
    \"\"\"
    with open('main.py', 'w') as file:
        file.write(main_code)

# *************************
# 2/3 - APP_CONFIG PROVISION
# *************************

# -------------------------
# Tank module
# -------------------------

class tankmodule_provision:

    def __init__(self):
        self.adc0 = machine.ADC(ADC0_PIN_NUMBER)
        self.adc1 = machine.ADC(ADC1_PIN_NUMBER)
        self.adc2 = machine.ADC(ADC2_PIN_NUMBER)
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.hw_uid = f"pico_{pico_unique_id[-6:]}"
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
        with open("app_config.json", "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()
        # print("HW UID, Pin 0 mV, Pin 1 mV, Pin 2 mV (OFFSETS DONE ON PIN 0 and 1)")
        # while self.num_recorded < TOTAL_REPORTS:
        #     self.print_sample()

# -------------------------
# Flowmeter
# -------------------------

class flowmeter_provision:
    
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
        with open("app_config.json", "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()

# *************************
# 3/3 - MAIN CODE
# *************************

if __name__ == "__main__":

    # Get hardware ID
    pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
    hw_uid = f"pico_{pico_unique_id[-6:]}"
    print(f"\\nThis Pico's unique hardware ID is {hw_uid}.")

    # -------------------------
    # Write boot.py
    # -------------------------

    bootpy_code = \"\"\"import os

if 'main_update.py' in os.listdir():
    
    if 'main_previous.py' in os.listdir():
        os.remove('main_previous.py')

    if 'main.py' in os.listdir():
        os.rename('main.py', 'main_previous.py')

    os.rename('main_update.py', 'main.py')

elif 'main_revert.py' in os.listdir():

    if 'main.py' in os.listdir():
        os.remove('main.py')

    os.rename('main_revert.py', 'main.py')
    \"\"\"

    with open('boot.py', 'w') as file:
        file.write(bootpy_code)
    print(f"Wrote 'boot.py' on the Pico.")
    
    print(f"\\n{'-'*40}\\n[1/4] Success! Found hardware ID and wrote 'boot.py'.\\n{'-'*40}\\n")

    # -------------------------
    # Write comms_config.json
    # -------------------------

    # Connect to wifi

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    wlan.disconnect()
    while wlan.isconnected():
        utime.sleep(0.1)
    
    while not wlan.isconnected():

        wifi_name = input("Enter wifi name (leave blank for 'GridWorks'): ")
        if wifi_name == "":
            wifi_name = "GridWorks"
        wifi_pass = input("Enter wifi password: ")

        time_waiting_connection = 0
        wlan.connect(wifi_name, wifi_pass)
        while not wlan.isconnected():
            if time_waiting_connection>0 and time_waiting_connection%2==0:
                print(f"Trying to connect ({int(time_waiting_connection/2)}/5)...")
            utime.sleep(0.5)
            time_waiting_connection += 0.5
            if time_waiting_connection > 10:
                print("Failed to connect to wifi, please try again.\\n")
                break

    print(f"Connected to wifi '{wifi_name}'.\\n")

    # Connect to API

    connected_to_api = False
    while not connected_to_api:

        hostname = input("Enter hostname (e.g., 'fir' or an IP address): ")
        base_url = f"http://{hostname}.local:8000"
        url = base_url + "/new-pico"
        payload = {
            "HwUid": hw_uid,
            "TypeName": "new.pico",
            "Version": "100"
        }
        headers = {"Content-Type": "application/json"}
        json_payload = ujson.dumps(payload)
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            if response.status_code == 200:
                connected_to_api = True
            else:
                print(f"Connected to the API, but it returned a status code {response.status_code}, indicating an issue.")
            response.close()
        except Exception:
            # If the hostname is an IP address
            base_url = f"http://{hostname}:8000"
            url = base_url + "/new-pico"
            payload = {
                "HwUid": hw_uid,
                "TypeName": "new.pico",
                "Version": "100"
            }
            headers = {"Content-Type": "application/json"}
            json_payload = ujson.dumps(payload)
            try:
                response = urequests.post(url, data=json_payload, headers=headers)
                if response.status_code == 200:
                    connected_to_api = True
                else:
                    print(f"Connected to the API, but it returned a status code {response.status_code}, indicating an issue.")
                response.close()
            except Exception as e:
                print(f"There was an error connecting to the API: {e}. Please check the hostname and try again.")

    print(f"Connected to the API hosted in '{base_url}'.")

    # Write the parameters to comms_config.json

    comms_config_content = {
        "WifiName": wifi_name,
        "WifiPassword": wifi_pass, 
        "BaseUrl": base_url
    }
    with open('comms_config.json', 'w') as file:
        ujson.dump(comms_config_content, file)

    print(f"\\n{'-'*40}\\n[2/4] Success! Wrote 'comms_config.json' on the Pico.\\n{'-'*40}\\n")

    # -------------------------
    # Write app_config.json
    # -------------------------

    got_type = False
    while not got_type:
        type = input("Is this Pico associated to a tank module (enter '0') or a flowmeter (enter '1'): ")
        if type not in {'0','1'}:
            print('Please enter 0 or 1.')
        else:
            got_type = True

    if type == '0':
        p = tankmodule_provision()
        p.start()
    elif type == '1':
        p = flowmeter_provision()
        p.start()

    print(f"\\n{'-'*40}\\n[3/4] Success! Wrote 'app_config.json' on the Pico.\\n{'-'*40}\\n")

    # -------------------------
    # Write main.py
    # -------------------------

    # Read the actor node name
    with open('app_config.json', 'r') as file:
        config_content = ujson.load(file)
    name = config_content['ActorNodeName']

    if 'flow' in name:
        if 'hall' in name:
            print("This is a hall meter.")
            write_flow_hall_main()
        if 'reed' in name:
            print("This is a reed meter.")
            write_flow_reed_main()
    else:
        print("This is a tank module.")
        write_tank_module_main()

    print(f"\\n{'-'*40}\\n[4/4] Success! Wrote 'main.py' on the Pico.\\n{'-'*40}\\n")

    print("The Pico is set up. It is now ready to use.")"""

# ----------------------------------------------------
# Write provisioner.py
# ----------------------------------------------------

with open('provisioner.py', 'w') as file:
    file.write(step1)
    file.write(flow_hall_main)
    file.write(step2)
    file.write(flow_reed_main)
    file.write(step3)
    file.write(tank_module_main)
    file.write(step4)