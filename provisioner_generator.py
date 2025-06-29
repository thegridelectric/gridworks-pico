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
# 4 - End of tank main, beggining of btu main
# ----------------------------------------------------

step4 = """
    \"\"\"
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_btu_meter_main():
    main_code = \"\"\"
"""

# ----------------------------------------------------
# 5 - End of btu main, beggining of current tap
# ----------------------------------------------------

step5 = """
    \"\"\"
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_current_tap_main():
    main_code = \"\"\"
"""

# ----------------------------------------------------
# 5 - End of current tap main, beggining of tank module 3
# ----------------------------------------------------

step6 = """
    \"\"\"
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_tank_module_3_main():
    main_code = \"\"\"
"""

# ----------------------------------------------------
# 6 - End of tank module 3, end of provisioner
# ----------------------------------------------------

step7 = """
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
        have_three_layer_pico = False
        while not have_three_layer_pico:
            three_layer_pico = input("How many temperatures is this Pico measuring (enter '2' or '3'): ")
            if three_layer_pico not in {'2','3'}:
                print("Invalid number of temerpatures")
            else:
                have_three_layer_pico = True
                three_layer_pico = True if three_layer_pico=='3' else False
                self.three_layers = three_layer_pico

        if not three_layer_pico:
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
        else:
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
            self.actor_name = input("Enter Actor name ('dist-flow', 'store-flow', 'primary-flow): ")
            if self.actor_name not in {'dist-flow', 'store-flow', 'primary-flow'}:
                print("Invalid actor name")
            else:
                got_actor_name = True
        
        # Save in app_config.json
        config = {
            "ActorNodeName": self.actor_name,
            "FlowNodeName": self.actor_name,
        }
        with open("app_config.json", "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()

# -------------------------
# BTU meter
# -------------------------

class btu_provision:  
    def set_name(self):
        got_tank_name = False
        while not got_tank_name:
            name = input(f"BTU Name: 'dist-btu', 'store-btu', 'primary-btu', 'sieg-btu': ")
            self.name = name
            if name not in {'primary-btu', 'store-btu', 'dist-btu', 'sieg-btu'}:
                print("Invalid btu name")
            else:
                got_tank_name = True
        self.actor_node_name = name
        config = {
            "ActorNodeName": self.actor_node_name,
        }
        with open("app_config.json", "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()

# -------------------------
# CurrentTap
# -------------------------

class current_tap_provision:  
    def set_name(self):
        got_ct_name = False
        while not got_ct_name:
            name = input(f"CurrentTap Name: ")
            self.name = name
            if name:
                got_ct_name = True
        self.actor_node_name = name
        config = {
            "ActorNodeName": self.actor_node_name,
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

    have_wifi_or_ethernet = False
    while not have_wifi_or_ethernet:
        wifi_or_ethernet = input("Does this Pico use WiFi (enter 'w') or Ethernet (enter 'e'): ")
        if wifi_or_ethernet not in {'w','e'}:
            print("Invalid entry. Please enter either 'w' or 'e'.")
        else:
            have_wifi_or_ethernet = True
    
    # Connect to wifi
    if wifi_or_ethernet == 'w':
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

    # Connect to ethernet
    elif wifi_or_ethernet == 'e':
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

    # Connect to API

    connected_to_api = False
    while not connected_to_api:

        hostname = input("Enter hostname (e.g., 'beech' or an IP address): ")
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
    if wifi_or_ethernet=='w':
        comms_config_content = {
            "WifiOrEthernet": 'wifi',
            "WifiName": wifi_name,
            "WifiPassword": wifi_pass, 
            "BaseUrl": base_url
        }
    elif wifi_or_ethernet=='e':
        comms_config_content = {
            "WifiOrEthernet": 'ethernet',
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
        type = input("Is this Pico associated to a tank module (enter '0'), a flowmeter (enter '1'), a BTU-meter (enter '2'), a CurrentTap (enter '3'): ")
        if type not in {'0','1','2','3'}:
            print('Please enter 0, 1, 2, or 3.')
        else:
            got_type = True

    if type == '0':
        p = tankmodule_provision()
        p.start()
        three_layers = True if p.three_layers else False
    elif type == '1':
        p = flowmeter_provision()
        p.start()
        got_subtype = False
        while not got_subtype:
            subtype = input("Is this FlowModule Hall (enter '0') or Reed (enter '1'): ")
            if subtype not in {'0','1'}:
                print('Please enter 0 or 1.')
            else:
                got_subtype = True
        if subtype == '0':
            flow_type = "Hall"
        else:
            flow_type = "Reed"
    elif type == '2':
        p = btu_provision()
        p.start()
    elif type == '3':
        p = current_tap_provision()
        p.start()

    print(f"\\n{'-'*40}\\n[3/4] Success! Wrote 'app_config.json' on the Pico.\\n{'-'*40}\\n")

    # -------------------------
    # Write main.py
    # -------------------------

    # Read the actor node name
    with open('app_config.json', 'r') as file:
        config_content = ujson.load(file)
    name = config_content['ActorNodeName']

    if type=='0':
        if three_layers:
            print("This is a 3-layer tank module")
            write_tank_module_3_main()
        else:
            print("This is a 2-layer tank module")
            write_tank_module_main()
        
    elif type == '1':
        if flow_type == "Hall":
            print("This is a hall meter.")
            write_flow_hall_main()
        else:
            print("This is a reed meter.")
            write_flow_reed_main()
    
    elif type=='2':
        print("This is a BTU meter.")
        write_btu_meter_main()

    elif type=='3':
        print("This is a CurrentTap.")
        write_current_tap_main()

    print(f"\\n{'-'*40}\\n[4/4] Success! Wrote 'main.py' on the Pico.\\n{'-'*40}\\n")

    print("The Pico is set up. It is now ready to use.")"""

# ----------------------------------------------------
# Write provisioner.py
# ----------------------------------------------------

with open('flow_hall/flow_hall_main.py', 'r') as file:
    flow_hall_main = file.read()
with open('flow_reed/flow_reed_main.py', 'r') as file:
    flow_reed_main = file.read()
with open('tank_module/tank_module_main.py', 'r') as file:
    tank_module_main = file.read()
with open('tank_module/tank_module_3_main.py', 'r') as file:
    tank_module_3_main = file.read()
with open('btu_meter/btu_main.py', 'r') as file:
    btu_meter_main = file.read()
with open('current_tap/current_tap_main.py', 'r') as file:
    current_tap_main = file.read()

if __name__ == "__main__":
    with open('provisioner.py', 'w') as file:
        file.write(step1)
        file.write(flow_hall_main)
        file.write(step2)
        file.write(flow_reed_main)
        file.write(step3)
        file.write(tank_module_main)
        file.write(step4)
        file.write(btu_meter_main)
        file.write(step5)
        file.write(current_tap_main)
        file.write(step6)
        file.write(tank_module_3_main)
        file.write(step7)