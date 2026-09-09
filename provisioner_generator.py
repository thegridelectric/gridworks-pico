# ----------------------------------------------------
# 1 - Beginning of provisioner
# ----------------------------------------------------

step1 = """import machine
import ujson
import network
import utime
import urequests
import ubinascii
import os

PRIMARY_SCADA_IP = "192.168.2.200"

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
if 'net.py' in os.listdir():
    os.remove('net.py')

# *************************
# 1/3 - MAIN.PY PROVISION
# *************************
"""

# ----------------------------------------------------
# 2 - beginning of net.py
# ----------------------------------------------------

step2 = """
def write_net_py():
    net_code = \"\"\"
"""

# ----------------------------------------------------
# 3 - End of net.py, beginning of tank3 main
# ----------------------------------------------------

step3 = """
    \"\"\"
    with open('net.py', 'w') as file:
        file.write(net_code)

def write_tank_module_3_main():
    main_code = \"\"\"
"""

# ----------------------------------------------------
# 4 - End of tank3 main, beggining of btu main
# ----------------------------------------------------

step4 = """
    \"\"\"
    with open('main.py', 'w') as file:
        file.write(main_code)

def write_btu_meter_main():
    main_code = \"\"\"
"""



# ----------------------------------------------------
# 5 - End of btu main, end of provisioner
# ----------------------------------------------------

step5 = """
    \"\"\"
    with open('main.py', 'w') as file:
        file.write(main_code)


# *************************
# 2/3 - APP_CONFIG PROVISION
# *************************

# -------------------------
# Tank module
# -------------------------

def determine_pico_board_variant(wifi_or_ethernet):
    machine_str = os.uname().machine
    print(f"os.uname().machine = {machine_str!r}")
    if "RP2350" in machine_str:
        return "PicoWiznetEth2350"
    if "RP2040" in machine_str:
        if wifi_or_ethernet == 'ethernet':
            return "PicoWiznetEth2040"
        if wifi_or_ethernet == 'wifi':
            return "PicoRaspberryWifi2040"
    return "Unknown"


def provision_tank_module():
    \"\"\"Configure tank module app_config.json\"\"\"
    # Get tank name
    while True:
        tank_name = input("Tank Name: 'buffer', 'tank1', 'tank2', 'tank3': ")
        if tank_name in {'buffer', 'tank1', 'tank2', 'tank3'}:
            break
        print("Invalid tank name")

    config = {
            "ActorNodeName": tank_name,
        }

    # Save config
    with open("app_config.json", "w") as f:
        ujson.dump(config, f)

    return tank_name


# -------------------------
# BTU meter
# -------------------------

def provision_btu_meter():
    \"\"\"Configure BTU meter app_config\"\"\"
    while True:
        btu_name = input("BTU Name: 'dist-btu', 'store-btu', 'primary-btu', 'sieg-btu': ")
        if btu_name in {'primary-btu', 'store-btu', 'dist-btu', 'sieg-btu'}:
            break
        print("Invalid BTU name")

    config = {
        "ActorNodeName": btu_name,
    }

    # Save config
    with open("app_config.json", "w") as f:
        ujson.dump(config, f)

    return btu_name


# *************************
# 3/3 - MAIN CODE
# *************************

if __name__ == "__main__":

    # Get hardware ID
    pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
    hw_uid = f"pico_{pico_unique_id}"
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
    
    print(f"\\n{'-'*40}\\n[1/3] Success! Found hardware ID and wrote 'boot.py'.\\n{'-'*40}\\n")

    # -------------------------
    # Write comms_config.json
    # -------------------------

    have_wifi_or_ethernet = False
    while not have_wifi_or_ethernet:
        transport_choice = input("Does this Pico use WiFi (enter 'w') or Ethernet (enter 'e'): ")
        if transport_choice not in {'w', 'e'}:
            print("Invalid entry. Please enter either 'w' or 'e'.")
        else:
            have_wifi_or_ethernet = True

    if transport_choice == 'w':
        wifi_or_ethernet = 'wifi'
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
            wlan.disconnect()
            while wlan.isconnected():
                utime.sleep(0.1)
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

    elif transport_choice == 'e':
        wifi_or_ethernet = 'ethernet'
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

    pico_board_variant = determine_pico_board_variant(wifi_or_ethernet)
    print(f"PicoBoardVariant = {pico_board_variant}")

    # Connect to API

    connected_to_api = False
    while not connected_to_api:

        ip_address = input("Enter IP address (return for default): ").strip()
        if ip_address == '':
            ip_address = PRIMARY_SCADA_IP

        base_url = f"http://{ip_address}:8000"

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

    print(f"Connected to the API hosted at '{base_url}'.")
    hostname = input("Enter hostname for backup (e.g., 'beech'): ").strip()
    backup_url = f"http://{hostname}.local:8000"

    # Write the parameters to comms_config.json
    if wifi_or_ethernet == 'wifi':
        comms_config_content = {
            "WifiOrEthernet": 'wifi',
            "WifiName": wifi_name,
            "WifiPassword": wifi_pass,
            "PicoBoardVariant": pico_board_variant,
            "BaseUrl": base_url,
            "BackupUrl": backup_url
        }
    elif wifi_or_ethernet == 'ethernet':
        comms_config_content = {
            "WifiOrEthernet": 'ethernet',
            "PicoBoardVariant": pico_board_variant,
            "BaseUrl": base_url,
            "BackupUrl": backup_url
        }
    with open('comms_config.json', 'w') as file:
        ujson.dump(comms_config_content, file)

    print(f"\\n{'-'*40}\\n[2/3] Success! Wrote 'comms_config.json' on the Pico.\\n{'-'*40}\\n")

    # -------------------------
    # Write app_config.json and main code
    # -------------------------
    while True:
        device_type = input("Is this Pico associated to a TankModule3 (enter '0') or an AsyncBtuMeter (enter '1'): ")
        if device_type in {'0', '1'}:
            break
        print('Please enter 0 or 1.')

    if device_type == '0':
        actor_name = provision_tank_module()
        print("This is a tank module")
        write_net_py()
        write_tank_module_3_main()
    elif device_type == '1':
        actor_name = provision_btu_meter()
        print("This is a BTU meter.")
        write_btu_meter_main()

    print(f"\\n{'-'*40}\\n[3/3] Success! Wrote 'main.py' on the Pico.\\n{'-'*40}\\n")

    print("The Pico is set up. It is now ready to use.")"""

# ----------------------------------------------------
# Write provisioner.py
# ----------------------------------------------------


with open('tank_module/tank_module_3_main.py', 'r') as file:
    tank_module_3_main = file.read()
with open('net.py', 'r') as file:
    net_py = file.read()
with open('btu_meter/async_btu_main.py', 'r') as file:
    async_btu_main = file.read()

if __name__ == "__main__":
    with open('provisioner.py', 'w') as file:
        file.write(step1)
        file.write(step2)
        file.write(net_py)
        file.write(step3)
        file.write(tank_module_3_main)
        file.write(step4)
        file.write(async_btu_main)
        file.write(step5)
