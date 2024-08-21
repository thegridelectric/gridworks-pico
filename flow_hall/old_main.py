import gc
import time

import machine
import network
import ujson
import urequests
import utime

# *********************************************
# PARAMETERS
# *********************************************
wifi_name = "ARRIS-3007"
wifi_password = "PASS"

base_url = "http://192.168.0.175:8000"

HB_FREQUENCY_S = 3
PULSE_PIN = 28
ALPHA = .1
HZ_THRESHOLD = 1
PUBLISH_STAMPS_PERIOD_S = 10

# Connect to wifi
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
if not wlan.isconnected():
    print("Connecting to wifi...")
    wlan.connect(wifi_name, wifi_password)
    while not wlan.isconnected():
        time.sleep(1)
print(f"Connected to wifi {wifi_name}")


# *********************************************
# Catch pulses
# *********************************************
latest_ts = None
exp_hz = None
prev_published_hz = 0
publish_new = False
timestamps = []
publishing_list = False
last_tick = utime.time_ns()

def pulse_callback(pin):
    global publishing_list, latest_ts, exp_hz, publish_new, prev_published_hz, timestamps, last_tick
    if not publishing_list:
        if latest_ts is None:
            latest_ts = utime.time_ns()
            timestamps.append(timestamp)
        else:
            timestamp = utime.time_ns()
            timestamps.append(timestamp)
            hz = 1e9/(timestamp-latest_ts)
            if exp_hz is None:
                exp_hz = hz
            else:
                exp_hz = ALPHA * hz + (1 - ALPHA) * exp_hz
            
            latest_ts = timestamp
            last_tick = timestamp
            if abs(exp_hz  - prev_published_hz) >= HZ_THRESHOLD:
                # print(f"prev_published was {prev_published_hz}")
                # print(f"now is {exp_hz}")
                publish_new = True
    

pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_DOWN)
pulse_pin.irq(trigger=machine.Pin.IRQ_RISING, handler=pulse_callback)

def publish_hz():
    global exp_hz
    global prev_published_hz
    global publish_new
    url = base_url + "/dist-flow/hz"
    payload = {'MilliHz': int(exp_hz * 1e3), "TypeName": "hz", "Version": "000"}
    headers = {'Content-Type': 'application/json'}
    json_payload = ujson.dumps(payload)
    try:
        response = urequests.post(url, data=json_payload, headers=headers)
        response.close()
    except Exception as e:
        print(f"Error posting hz: {e}")
    gc.collect()
    publish_new = False
    prev_published_hz = exp_hz


def publish_ticklist():
    global timestamps
    url = base_url + "/dist-flow/ticklist"
    payload = {'TimestampNsList': timestamps, "TypeName": "ticklist", "Version": "000"}
    headers = {'Content-Type': 'application/json'}
    json_payload = ujson.dumps(payload)
    try:
        response = urequests.post(url, data=json_payload, headers=headers)
        response.close()
    except Exception as e:
        print(f"Error posting hz: {e}")
    gc.collect()
    timestamps = []
# *********************************************
# Publish Heartbeat
# *********************************************
hb = 0


def publish_heartbeat(timer):
    """
    Publish a heartbeat, assuming no omega tick in the last 5 minutes.
    Acts as a keepalive
    """
    global hb
    global last_tick
    hb = (hb + 1) % 16
    hbstr = "{:x}".format(hb)
    payload =  {'MyHex': hbstr, 'TypeName': 'hb', 'Version': '000'}
    headers = {'Content-Type': 'application/json'}
    json_payload = ujson.dumps(payload)
    url = base_url + "/dist-flow/hb"
    timestamp = utime.time_ns()
    if (timestamp - last_tick) / 10**9 > HB_FREQUENCY_S:
        try:
            response = urequests.post(url, data=json_payload, headers=headers)
            response.close()
        except Exception as e:
            print(f"Error posting hb: {e}")
        gc.collect()

# Create a timer to publish heartbeat every 3 seconds
heartbeat_timer = machine.Timer(-1)
heartbeat_timer.init(period=3000, mode=machine.Timer.PERIODIC, callback=publish_heartbeat)

last_ticks_sent = utime.time()
try:
    while True:
        utime.sleep(.2)
        if publish_new:
            publish_hz()
        if utime.time() - last_ticks_sent > PUBLISH_STAMPS_PERIOD_S:
            publishing_list = True
            publish_ticklist()
            latest_ts = None
            publishing_list = False
            last_ticks_sent = utime.time()
except KeyboardInterrupt:
    print("Program interrupted by user")