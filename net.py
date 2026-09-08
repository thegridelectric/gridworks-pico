import network
import utime
import urequests
import ujson
import gc


def connect_to_wifi(name, password):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(name, password)
        while not wlan.isconnected():
            utime.sleep_ms(500)


def connect_to_ethernet():
    nic = network.WIZNET5K()
    for _ in range(3):
        try:
            nic.active(True)
            break
        except:
            utime.sleep_ms(500)

    if not nic.isconnected():
        nic.ifconfig('dhcp')
        start = utime.time()
        while not nic.isconnected():
            if utime.time() - start > 10:
                raise RuntimeError("Ethernet timeout")
            utime.sleep_ms(500)


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