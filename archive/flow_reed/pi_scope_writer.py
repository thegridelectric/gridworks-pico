import paho.mqtt.client as mqtt
import csv
import json
import time

ROUGH_SECONDS = 1
directory = '/home/pi/pico_files/'
csv_file_path = directory + f"pin_state_{int(time.time())}.csv"

# MQTT settings
mqtt_broker = '192.168.40.79'  # Replace with your MQTT broker address
mqtt_port = 1883  # Default MQTT port
mqtt_topic = 'flow-scope/pin-state-list'
mqtt_username = 'sara'  # Replace with your MQTT username
mqtt_password = 'orca2026'  # Replace with your MQTT password
batches = 0
ts_list = []
value_list = []
# Callback when the client receives a CONNACK response from the server
def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    if rc == 0:
        client.subscribe(mqtt_topic)
    else:
        print(f"Connection failed with code {rc}")


# Callback when a PUBLISH message is received from the server
def on_message(client, userdata, msg):
    global ts_list, value_list, batches
    try:
        # Parse the JSON payload
        payload = json.loads(msg.payload.decode())
        batches += 1
        print(f"batch {batches} length {len(payload.get("RelativeTsMicroList", []))}")
        ts_list = ts_list + ['new_batch'] + payload.get("RelativeTsMicroList", [])
        value_list = value_list + ['new_batch'] + payload.get("ValueList", [])       
    except Exception as e:
        print(f"Error processing message: {e}")


client = mqtt.Client()
client.username_pw_set(mqtt_username, mqtt_password)
client.on_connect = on_connect
client.on_message = on_message
client.connect(mqtt_broker, mqtt_port, 60)
client.loop_start()


try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    client.loop_stop()
    client.disconnect()
    try:
        with open(csv_file_path, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Timestamp (μs)', 'Value'])
            for ts, value in zip(ts_list, value_list):
                writer.writerow([ts, value])
        print(f"Data written to {csv_file_path}")
    except Exception as e:
        print(f"Error writing CSV file: {e}")
        

