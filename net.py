import network
import utime
import urequests
import ujson
import gc

CONNECT_TIMEOUT_S = 10

HEADERS = {"Content-Type": "application/json"}
BASE_URL_ATTEMPTS = 2
BASE_URL_RETRY_S = 300
POST_TIMEOUT_S = 3
BACKUP_POST_TIMEOUT_S = 5
PING_TIMEOUT_S = 3

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
    '''POST to scada, failing over from base_url to backup_url.

    base_url is the primary (an IP address in the field) and backup_url is
    the DNS name. Once base_url stops answering its /ping we post to
    backup_url instead, and only re-test base_url every BASE_URL_RETRY_S.
    Failing over also posts a baseurl.failure.alert over backup_url, which
    needs actor_node_name: the caller keeps that attribute up to date.
    '''

    def __init__(self, base_url, backup_url=None, hw_uid=None, actor_node_name=None):
        self.hw_uid = hw_uid
        self.actor_node_name = actor_node_name
        self.base_url = base_url.rstrip("/")
        self.backup_url = None if not backup_url else backup_url.rstrip("/")
        self.base_url_failed = False
        self.last_base_url_retry = utime.time()

    def post(self, path, payload, mode=0):
        '''POST payload to path, on base_url or backup_url.

        mode: 0=ignore body, 1=json, 2=bytes
        Returns (status, body). A status of None means no url gave any HTTP
        response, which is how the caller knows the link may be down. Any
        status at all, 404 and 500 included, means scada answered.
        '''
        body = ujson.dumps(payload)
        self._retry_base_url_if_due()

        if self.base_url_failed:
            return self._post_to(self.backup_url, path, body, mode, 1, BACKUP_POST_TIMEOUT_S)

        status, result = self._post_to(
            self.base_url, path, body, mode, BASE_URL_ATTEMPTS, POST_TIMEOUT_S
        )
        if status is not None:
            return status, result

        if self.is_reachable(self.base_url):
            print(f"{self.base_url} is reachable but the request failed")
            return None, None

        return self._fail_over_to_backup(path, body, mode)

    def post_fire_and_forget(self, path, payload):
        status, _ = self.post(path, payload)
        return status

    def is_reachable(self, url):
        r = None
        try:
            r = urequests.get(url + "/ping", timeout=PING_TIMEOUT_S)
            return r.status_code == 200
        except:
            return False
        finally:
            self._close(r)
            gc.collect()

    def _close(self, r):
        if r:
            try:
                r.close()
            except:
                pass

    def _post_to(self, url, path, body, mode, attempts, timeout_s):
        for attempt in range(attempts):
            if attempt > 0:
                print(f"Retry {attempt} for {url}{path}")
            r = None
            raw = None
            try:
                r = urequests.post(url + path, data=body, headers=HEADERS, timeout=timeout_s)
                status = r.status_code
                if status == 200:
                    raw = r.content if mode == 2 else (r.text if mode == 1 else None)
                elif status == 404:
                    print(f"{path} not found (404) on {url}")
                else:
                    print(f"{url}{path} returned status {status}")
                    if status >= 500 and attempt < attempts - 1:
                        continue
            except Exception as e:
                print(f"Attempt {attempt+1} for {url}{path} failed: {e}")
                if attempt < attempts - 1:
                    utime.sleep_ms(50)
                    continue
                return None, None
            finally:
                self._close(r)
                gc.collect()

            if mode == 1 and raw:
                try:
                    return status, ujson.loads(raw)
                except:
                    return status, None
            return status, raw

        return None, None

    def _retry_base_url_if_due(self):
        if not self.base_url_failed:
            return
        waited = utime.time() - self.last_base_url_retry
        if waited <= BASE_URL_RETRY_S:
            return
        print(f"Retrying {self.base_url} after {waited}s")
        self.last_base_url_retry = utime.time()
        if self.is_reachable(self.base_url):
            print(f"{self.base_url} is back online")
            self.base_url_failed = False

    def _fail_over_to_backup(self, path, body, mode):
        if not self.backup_url:
            return None, None
        message = f"switching to backup url {self.backup_url}"
        print(message)
        self.base_url_failed = True
        self.last_base_url_retry = utime.time()
        self._alert_base_url_failure(message)
        return self._post_to(self.backup_url, path, body, mode, 1, BACKUP_POST_TIMEOUT_S)

    def _alert_base_url_failure(self, message):
        if self.actor_node_name is None:
            return
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "BaseUrl": self.base_url,
            "Message": message,
            "TypeName": "baseurl.failure.alert",
            "Version": "100"
        }
        r = None
        try:
            r = urequests.post(
                self.backup_url + f"/{self.actor_node_name}/baseurl-failure-alert",
                data=ujson.dumps(payload),
                headers=HEADERS,
                timeout=POST_TIMEOUT_S
            )
        except Exception as e:
            print(f"Could not post baseurl failure alert ({e})")
        finally:
            self._close(r)
            gc.collect()