import network
import utime
import urequests
import ujson
import gc

CONNECT_TIMEOUT_S = 10

_wlan = None
_ethernet_nic = None


def connect_to_wifi(name, password, timeout_s=CONNECT_TIMEOUT_S):
    global _wlan
    if _wlan is None:
        _wlan = network.WLAN(network.STA_IF)
    _wlan.active(True)
    if not _wlan.isconnected():
        print("Connecting to wifi...")
        _wlan.connect(name, password)
        start = utime.time()
        while not _wlan.isconnected():
            if utime.time() - start > timeout_s:
                raise RuntimeError("Failed to connect to WiFi (timeout)")
            utime.sleep_ms(500)
    print(f"Connected to wifi {name}")


def is_wifi_connected():
    global _wlan
    if _wlan is None:
        _wlan = network.WLAN(network.STA_IF)
    return _wlan.isconnected()


def connect_to_ethernet(timeout_s=CONNECT_TIMEOUT_S):
    global _ethernet_nic
    if _ethernet_nic is None:
        _ethernet_nic = network.WIZNET5K()
    for _ in range(3):
        try:
            _ethernet_nic.active(True)
            break
        except:
            utime.sleep_ms(500)

    if not _ethernet_nic.isconnected():
        print("Connecting to Ethernet...")
        _ethernet_nic.ifconfig('dhcp')
        start = utime.time()
        while not _ethernet_nic.isconnected():
            if utime.time() - start > timeout_s:
                raise RuntimeError("Failed to connect to Ethernet (timeout)")
            utime.sleep_ms(500)
    print("Connected to Ethernet")


def is_ethernet_connected():
    global _ethernet_nic
    if _ethernet_nic is None:
        return False
    return _ethernet_nic.isconnected()


class HttpClient:

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def _close(self, r):
        if r:
            try:
                r.close()
            except:
                pass

    def post(self, path, payload, mode=0):
        # mode: 0=ignore body, 1=json, 2=bytes

        url = self.base_url + path
        headers = {"Content-Type": "application/json"}
        body = ujson.dumps(payload)

        r = None
        status = None
        text = None
        content = None

        try:
            r = urequests.post(url, data=body, headers=headers)
            status = r.status_code
    
            if status == 200:
                if mode == 2:
                    content = r.content
                elif mode == 1:
                    text = r.text
        except:
            return None, None
        finally:
            self._close(r)

        if mode == 1 and text:
            try:
                result = ujson.loads(text)
            except:
                result = None
            gc.collect()
            return status, result

        if mode == 2:
            gc.collect()
            return status, content

        gc.collect()
        return status, None

    def post_fire_and_forget(self, path, payload):
        url = self.base_url + path
        headers = {"Content-Type": "application/json"}
        body = ujson.dumps(payload)

        r = None
        try:
            r = urequests.post(url, data=body, headers=headers)
            return r.status_code
        except:
            return None
        finally:
            self._close(r)
            gc.collect()