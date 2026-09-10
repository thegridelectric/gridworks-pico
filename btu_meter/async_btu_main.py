import os
import machine
from machine import Pin
import utime
import ujson
import ubinascii
import math

import net

# ---------------------------------
# Constants and helper functions
# ---------------------------------

# Configuration files
COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"

# Default parameters
DEFAULT_ACTOR_NAME = "primary-btu"
DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_GALLONS_PER_PULSE = 0.0009
DEFAULT_ASYNC_CAPTURE_DELTA_GPM_X_100 = 10
DEFAULT_ASYNC_CAPTURE_DELTA_CELSIUS_X_100 = 20
DEFAULT_ASYNC_CAPTURE_DELTA_CT_VOLTS_X_100 = 20
DEFAULT_THERMISTOR_BETA = 3977

# Pin numbers
PULSE_PIN = 22
ADC0_PIN = 26 # Hot Temp
ADC1_PIN = 27 # Cold Temp
ADC2_PIN = 28 # Current Transformer

# Other constants
SAMPLES = 1000
NUM_SAMPLE_AVERAGES = 1
RECONNECT_COOLDOWN_S = 30
ADC_REF_V = 3.3
R_FIXED_KOHMS = 5.6
THERMISTOR_R0_KOHMS = 10
THERMISTOR_T0 = 298

PICO_BOARD_VARIANTS = (
    "PicoWiznetEth2040",
    "PicoWiznetEth2350",
    "PicoRaspberryWifi2040",
    "Unknown",
)


def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
    os.sync()
    os.rename(tmp, path)
    os.sync()


# ---------------------------------
# Main class
# ---------------------------------

class AsyncBtuMeter:
    '''
    BTU meter with coordinated measure of flow, temp and pump power.
    Designed for async reporting on change for all 3 and also
    synchronous reporting happening at a default of 60 seconds
    Flow meter expected range: 15-150 Hz (67ms - 6.7ms periods)
    Jitter threshold: > 400 Hz (< 2.5ms period) indicates physical bounce
    self.read_ct is True iff CtNodeName is not None
    '''
    def __init__(self):
        # Unique ID
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
        self.hw_uid = f"pico_{pico_unique_id}"

        # Pins
        Pin(ADC0_PIN, Pin.IN)
        Pin(ADC1_PIN, Pin.IN)
        Pin(ADC2_PIN, Pin.IN)
        self.pulse_pin = machine.Pin(PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self.adc_hot = machine.ADC(ADC0_PIN)
        self.adc_cold = machine.ADC(ADC1_PIN)
        self.adc_ct = machine.ADC(ADC2_PIN)

        # Load configurations
        self.load_comms_config()
        try:
            with open(APP_CONFIG_FILE, "r") as f:
                app_config = ujson.load(f)
        except:
            app_config = {}
        self.load_app_config(app_config)
        self.http = net.HttpClient(
            base_url=self.base_url,
            backup_url=self.backup_url,
            hw_uid=self.hw_uid,
            actor_node_name=self.actor_node_name
        )

        # Flow measurement state
        self._tick_count = 0 # Only modified by pulse_callback (ISR)
        self.ready_for_new_measurement = True
        self.measurement_start_ms = None  # this signals no flow
        self.completed_elapsed_ms = None
        self.completed_tick_count = 0
        self.flow_data_ready = False # set True by pulse_callback, False by flow_timer 

        # Measurements
        self.gpm = None
        self.hz = None
        self.hot = None
        self.cold = None
        self.pump_ct_voltage = None

        # Initialize last_sent values to force first send
        self.last_sent_gpm = -999
        self.last_sent_hot = -999
        self.last_sent_cold = -999
        self.last_sent_pump_ct_voltage = -999

        # Timers
        self.last_sync_report_s = 0
        self.capture_offset_seconds = 0 
        self.temp_timer = machine.Timer(-1)
        self.flow_timer = machine.Timer(-1)

        # main loop variables
        self.last_flow_calc_ms = None
        self.pending_async_check = False

        # Debt tracking for disruption recovery
        self.period_us_3 = None
        self.period_us_2 = None
        self.period_us_1 = None
        self.period_us_0 = None
        self.disruption_recovery = 0
        self.double_debt_us = 0
        self.avg_double = 20000
        self.last_pulse_us = None
        self.toss_measurement = False

        # Reconnect
        self.needs_reconnect = False
        self.time_last_tried_to_reconnect = utime.time()

    # ---------------------------------
    # Communication
    # ---------------------------------

    def try_to_reconnect(self):
        self.time_last_tried_to_reconnect = utime.time()
        try:
            if self.wifi_or_ethernet == 'wifi':
                if not net.is_wifi_connected():
                    net.connect_to_wifi(self.wifi_name, self.wifi_password)
            elif self.wifi_or_ethernet == 'ethernet':
                if not net.is_ethernet_connected():
                    net.connect_to_ethernet()
        except Exception as e:
            print(f"Error when trying to reconnect ({e})")

    def load_comms_config(self):
        '''Load the communication configuration file (WiFi/Ethernet and API URL)'''
        try:
            with open(COMMS_CONFIG_FILE, "r") as f:
                comms_config = ujson.load(f)
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Error loading comms_config file: {e}")
        self.wifi_or_ethernet = comms_config.get("WifiOrEthernet", 'wifi')
        self.pico_board_variant = self.determine_pico_board_variant(comms_config.get("PicoBoardVariant"))
        self.wifi_name = comms_config.get("WifiName", None)
        self.wifi_password = comms_config.get("WifiPassword", None)
        self.base_url = comms_config.get("BaseUrl", None)
        self.backup_url = comms_config.get("BackupUrl", None)
        print(f"After loading - base_url: {self.base_url}, backup_url: {self.backup_url}")
        if self.wifi_or_ethernet=='wifi':
            if self.wifi_name is None:
                raise KeyError("WifiName not found in comms_config.json")
            if self.wifi_password is None:
                raise KeyError("WifiPassword not found in comms_config.json")
        elif self.wifi_or_ethernet=='ethernet':
            pass
        else:
            raise KeyError("WifiOrEthernet must exost amd be either 'wifi' or 'ethernet' in comms_config.json")
        if self.base_url is None:
            raise KeyError("BaseUrl not found in comms_config.json")

    def determine_pico_board_variant(self, configured):
        '''The physical board, as a pico.board.variant enum value.
        comms_config.json wins when the provisioner wrote one; otherwise
        derive it from os.uname().machine, with WifiOrEthernet as the
        tiebreak between the two RP2040 boards. Unknown when neither
        settles it.'''
        if configured in PICO_BOARD_VARIANTS:
            return configured
        machine_str = os.uname().machine
        if "RP2350" in machine_str:
            return "PicoWiznetEth2350"
        elif machine_str=="Raspberry Pi Pico W with RP2040":
            return "PicoRaspberryWifi2040"
        elif machine_str=="W5500-EVB-Pico with RP2040":
            return "PicoWiznetEth2040"
        return "Unknown"

    def update_comms_config(self):
        payload = {
            "HwUid": self.hw_uid,
            "BaseUrl": self.base_url,
            "BackupUrl": self.backup_url,
            "TypeName": "pico.comms.params",
            "Version": "000"
        }
        status, new_config = self.http.post(
            f"/{self.actor_node_name}/pico-comms-params",
            payload,
            mode=1
        )
        if status is None:
            self.needs_reconnect = True
        if status != 200 or not isinstance(new_config, dict):
            return

        # Only adopt urls that answer their /ping
        config_changed = False
        new_base = new_config.get("BaseUrl", self.base_url)
        if new_base and new_base != self.base_url and self.http.is_reachable(new_base):
            self.base_url = new_base
            config_changed = True

        new_backup = new_config.get("BackupUrl", self.backup_url)
        if new_backup and new_backup != self.backup_url and self.http.is_reachable(new_backup):
            self.backup_url = new_backup
            config_changed = True

        if config_changed:
            self.http.set_urls(self.base_url, self.backup_url)
            self.save_comms_config()

    def save_comms_config(self):
        config = {
            "WifiOrEthernet": self.wifi_or_ethernet,
            "BaseUrl": self.base_url,
            "BackupUrl": self.backup_url,
            "TypeName": "pico.comms.config",
            "Version": "000"
        }
        if self.wifi_or_ethernet == "wifi":
            config["WifiName"] = self.wifi_name
            config["WifiPassword"] = self.wifi_password

        try:
            _atomic_write(COMMS_CONFIG_FILE, ujson.dumps(config).encode())
        except Exception as e:
            print(f"Error saving comms config: {e}")

    # ---------------------------------
    # Parameters
    # ---------------------------------

    def load_app_config(self, app_config):
        '''
        Set parameters to their value in the app_config file if it is specified
        Otherwise set them to their default value
        '''
        self.actor_node_name = app_config.get("ActorNodeName", DEFAULT_ACTOR_NAME)
        prefix = self.actor_node_name.replace("-btu", "")
        self.flow_channel_name = app_config.get("FlowChannelName", f"{prefix}-flow")
        self.hot_channel_name = app_config.get("HotChannelName", f"{prefix}-hot-temp")
        self.cold_channel_name = app_config.get("ColdChannelName", f"{prefix}-cold-temp")
        self.ct_channel_name = app_config.get("CtChannelName", None)
        self.send_hz = app_config.get("SendHz", False)
        self.read_ct_voltage = self.ct_channel_name is not None
        self.thermistor_beta = app_config.get("ThermistorBeta", DEFAULT_THERMISTOR_BETA)
        self.capture_period_s = app_config.get("CapturePeriodS", DEFAULT_CAPTURE_PERIOD_S)
        self.gallons_per_pulse = app_config.get("GallonsPerPulse", DEFAULT_GALLONS_PER_PULSE)
        self.async_capture_delta_gpm_x_100 = app_config.get("AsyncCaptureDeltaGpmX100", DEFAULT_ASYNC_CAPTURE_DELTA_GPM_X_100)
        self.async_capture_delta_celsius_x_100 = app_config.get("AsyncCaptureDeltaCelsiusX100", DEFAULT_ASYNC_CAPTURE_DELTA_CELSIUS_X_100)
        self.async_capture_delta_ct_volts_x_100 = app_config.get("AsyncCaptureDeltaCtVoltsX100", DEFAULT_ASYNC_CAPTURE_DELTA_CT_VOLTS_X_100)

    def save_app_config(self, config_dict):
        try:
            _atomic_write(APP_CONFIG_FILE, ujson.dumps(config_dict).encode())
        except Exception as e:
            print(f"Error saving app config: {e}")

    def current_async_btu_params(self):
        return {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "FlowChannelName": self.flow_channel_name,
            "SendHz": self.send_hz,
            "ReadCtVoltage": self.read_ct_voltage,
            "HotChannelName": self.hot_channel_name,
            "ColdChannelName": self.cold_channel_name,
            "CtChannelName": self.ct_channel_name,
            "ThermistorBeta": self.thermistor_beta,
            "CapturePeriodS": self.capture_period_s,
            "GallonsPerPulse": self.gallons_per_pulse,
            "AsyncCaptureDeltaGpmX100": self.async_capture_delta_gpm_x_100,
            "AsyncCaptureDeltaCelsiusX100": self.async_capture_delta_celsius_x_100,
            "AsyncCaptureDeltaCtVoltsX100": self.async_capture_delta_ct_volts_x_100,
            "PicoBoardVariant": self.pico_board_variant,
            "MicropythonVersion": os.uname().release,
            "TypeName": "async.btu.params",
            "Version": "100"
        }

    def update_app_config(self):
        current = self.current_async_btu_params()
        status, updated_config = self.http.post(
            f"/{self.actor_node_name}/async-btu-params",
            current,
            mode=1
        )
        if status is None:
            self.needs_reconnect = True
        if status != 200 or not updated_config:
            return

        PARAM_KEYS = (
            "ActorNodeName",
            "FlowChannelName",
            "SendHz",
            "HotChannelName",
            "ColdChannelName",
            "CtChannelName",
            "ThermistorBeta",
            "CapturePeriodS",
            "GallonsPerPulse",
            "AsyncCaptureDeltaGpmX100",
            "AsyncCaptureDeltaCelsiusX100",
            "AsyncCaptureDeltaCtVoltsX100",
        )

        changed = any(
            k in updated_config and updated_config[k] != current[k]
            for k in PARAM_KEYS
        )

        if not changed:
            return

        new_config = {
            k: updated_config.get(k, current[k])
            for k in PARAM_KEYS
        }

        self.save_app_config(new_config)
        self.load_app_config(new_config)
        self.http.actor_node_name = self.actor_node_name

        offset = updated_config.get("CaptureOffsetS")
        if isinstance(offset, (int, float)) and 0 <= offset < self.capture_period_s:
            self.capture_offset_seconds = offset

    # ---------------------------------
    # Code updates
    # ---------------------------------

    def update_code(self):
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "TypeName": "new.code",
            "Version": "100"
        }
        status, content = self.http.post(
            f"/{self.actor_node_name}/code-update",
            payload,
            mode=2  # raw bytes
        )
        if status is None:
            self.needs_reconnect = True
        if status != 200 or not content:
            return

        # JSON response → no update pending
        if content.startswith(b"{"):
            return

        try:
            _atomic_write("main_update.py", content)
            machine.reset()
        except Exception as e:
            print("Code update failed:", e)

    # ---------------------------------
    # Measurements
    # ---------------------------------

    def celsius_from_volts(self, volts):
        #  Uses Beta formula with THERMISTOR_BETA of 3977
        # TODO: consider adding thermistor_beta to app_config?
        if volts <= 0.001 or volts >= 3.299:
            return None
        # Use Beta Formula
        r_therm = 1 / ((ADC_REF_V / volts - 1) / R_FIXED_KOHMS)
        thermistor_beta = self.thermistor_beta
        if thermistor_beta is None or thermistor_beta == 0:
            thermistor_beta = DEFAULT_THERMISTOR_BETA
        return 1 / ((1 / THERMISTOR_T0) + (math.log(r_therm / THERMISTOR_R0_KOHMS) / thermistor_beta)) - 273

    def measure_temp(self, adc_channel, n_samples=100):
        # Measure voltage in microvolts (for temp) Takes ~1.7ms for 100 samples.
        try:
            reading_sum = 0
            for _ in range(n_samples):
                reading_sum += adc_channel.read_u16()
            avg_reading = reading_sum / n_samples
            avg_voltage =  avg_reading * ADC_REF_V / 65535
            print(f"avg voltage is {avg_voltage}")
            return self.celsius_from_volts(avg_voltage)
        except Exception as e:
            print(f"Temp measurement failed: {e}")
            return None

    def measure_ct_voltage(self):
        #Sample the current transformer (CT) ADC channel.
        #
        #Collects 200 successive ADC readings as quickly as possible,
        #timestamping each sample. A typical loop iteration takes ~95 µs
        #without explicit delays, so 200 samples span ~19 ms. This
        #comfortably covers at least one full 60 Hz AC cycle
        #(period ≈ 16.7 ms).

        # Notes:
        #    - At 60 Hz, 200 samples correspond to ~83 µs/sample if perfectly
        #    distributed; in practice this function achieves ~95 µs/sample.
        #    - The function reduces the collected data to just the peak ADC
        #    value and its first timestamp.
        if not self.read_ct_voltage:
            return
        try:
            readings = []
            while len(readings) < 200:
                readings.append(self.adc_ct.read_u16())
            
            max_reading = max(readings)
            max_voltage = (max_reading * 3.3 / 65535)
            return max_voltage
        except Exception as e:
            print(f"CT measurement failed: {e}")
            return None

    def pulse_callback(self, pin):
        # Flow pulse interrupt handler. Implements debt tracking to handle
        # timing disruptions where pulses queue up during CPU-intensive operations.
        #
        # Debt mechanism: When a disruption causes a LONG period followed by
        # SHORT catch-up pulses, we track the "debt" (missed time) and adjust
        # the final measurement accordingly.
        #
        # Also we delay the start if there is active debt
        now_ms = utime.ticks_ms()
        now_us = utime.ticks_us()

        # Update period history
        if not self.last_pulse_us:
            self.last_pulse_us = now_us
        else:
            # Shift history
            self.period_us_3 = self.period_us_2
            self.period_us_2 = self.period_us_1
            self.period_us_1 = self.period_us_0
            self.period_us_0 = now_us - self.last_pulse_us

            self.last_pulse_us = now_us
            if self.toss_measurement:
                return

            # Handle jitter and/or the LONG/SHORT/SHORT..
            if (self.double_debt_us == 0 and 
                self.period_us_1 and self.period_us_2 and self.period_us_3):

                if self.disruption_recovery > 0:
                    self.disruption_recovery -= 1

                else:
                    # Average (times 2 to avoid float)
                    avg_double = self.period_us_3 + self.period_us_2

                    # Check if current period is SHORT (>1ms shorter than expected)
                    if avg_double - 2 * self.period_us_0 > 2000:
                        # print(f"SHORT TICK: {self.period_us_0}, tick count {self._tick_count}")
                        debt_floor_double = avg_double - 2 * self.period_us_0

                        # Check if previous period was LONG enough to create multi-tick debt
                        if 2 * self.period_us_1 > avg_double + debt_floor_double + 500:
                            # Multi-tick debt detected
                            double_debt_us = 2 * self.period_us_1 - avg_double
                            self.avg_double = avg_double
                            self.disruption_recovery = 2 # Skip next 2 pattern checks 

                            # Bail if 4 catch-up ticks at ~1000us each can recover: 4*avg_double - 8000
                            max_recoverable = min(4 * avg_double - 8000, 800_000)
                            if double_debt_us > max_recoverable:
                                self.toss_measurement = True
                                self.double_debt_us = 0
                            else:
                                # set ready_for_new_measurement flag to trigger a reset
                                # IF _tick_count happens to be 0. This is so that the LONG
                                # is included along with the shorts....
                                self.double_debt_us = double_debt_us
                                if self._tick_count == 0:
                                    # print(f"RESET - should trigger new tick 0 after debt clears")
                                    self.flow_data_ready = False
                                    self.ready_for_new_measurement = True

                        # "bookend" debt detected - clears immediately
                        elif 2 * self.period_us_1 > avg_double + 500:
                            self.disruption_recovery = 1
                            # ... unless the long tick happened before 0
                            if self._tick_count == 0:
                                self.flow_data_ready = False
                                self.ready_for_new_measurement = True

                        elif self.period_us_0 < 2500: # < 2.5ms = > 400 Hz
                            # JITTER! Physical switch bounce/oscillation - don't count it
                            # print(f"JITTER detected: {self.period_us_0} us with no preceding long")
                            return

            elif self.double_debt_us > 0:
                # paying off debt
                # print("PAYING OFF DEBT")
                payoff = self.avg_double - 2 * self.period_us_0
                if payoff > 1000:
                    new_debt = self.double_debt_us - payoff
                    if new_debt < 1000:
                        self.double_debt_us = 0
                    else:
                        self.double_debt_us = new_debt
                else:
                    if self.double_debt_us > 1000:
                        self.toss_measurement = True
                        self.double_debt_us = 0
                        return
                    else:
                        self.double_debt_us = 0
                        self.avg_double = None

        # Handle start of a new measurement period
        if self.ready_for_new_measurement:
            if self.double_debt_us > 0: # still working off debt ... delay
                return

            # Start measurement cycle debt-free
            self.measurement_start_ms = now_ms
            self._tick_count = 0
            self.ready_for_new_measurement = False
            return

        # Normal case!
        if self.measurement_start_ms is not None:
            self._tick_count += 1
            elapsed_ms = now_ms - self.measurement_start_ms

            # Don't overwrite if not processed yet
            if elapsed_ms >= 800 and not self.flow_data_ready:

                self.completed_tick_count = self._tick_count
                self.completed_elapsed_ms = elapsed_ms
                self.flow_data_ready = True

    def adjust_for_debt(self):
        if self.avg_double is None or self.avg_double == 0:
            return
        if self.double_debt_us > 0:
            # Calculate how many ticks were compressed into catch-up bursts
            debt_ticks = int( (self.double_debt_us // self.avg_double) + 0.5) # round
            adjusted_tick_count = self.completed_tick_count + debt_ticks
            adjusted_elapsed_ms = self.completed_elapsed_ms + (self.double_debt_us // 2000)

            self.completed_tick_count = adjusted_tick_count
            self.completed_elapsed_ms = adjusted_elapsed_ms

            # Clear debt since we've accounted for it
            self.double_debt_us = 0

    def calculate_flow(self):
        # Calculate gpm, unless self.send_hz in which case calculate hz
        if self.completed_elapsed_ms is None or self.completed_elapsed_ms == 0:
            return

        elapsed_s = self.completed_elapsed_ms / 1000.0
        self.hz = self.completed_tick_count / elapsed_s

        gallons = self.completed_tick_count * self.gallons_per_pulse
        minutes = elapsed_s / 60.0
        self.gpm = gallons / minutes if minutes > 0 else 0.0

    def measure_temps_and_ct(self, timer):
        # Timer callback: Runs at t=850ms, 1850ms, 2850ms...
        # Intentionally offset from flow measurement window (0-800ms)
        # to avoid interference with pulse counting
        #
        # blocks for 3.5 ms, 3.5 ms, then 20 ms

        # print(f"Measuring temps and CT at tick {self._tick_count}")
        self.hot = self.measure_temp(self.adc_hot) # ~3.5 ms
        self.cold = self.measure_temp(self.adc_cold) # ~ 3.5 ms

        if self.read_ct_voltage:
            self.pump_ct_voltage = self.measure_ct_voltage() # ~ 20 ms

    def reset_flow_measurement(self):
        # resets all flow measurement state for next cycle
        self.flow_data_ready = False
        self.measurement_start_ms = None
        self.ready_for_new_measurement = True
        # Let main loop know its time send an async report ...
        self.pending_async_check = True
        self.disruption_recovery = 0

    def manage_flow(self, timer):
        if self.toss_measurement:
            print("Tossing corrupted measurement")
            self.toss_measurement = False
            # NOT updating gpm with corrupted measurement
            self.reset_flow_measurement()
            return

        # No ticks this last second <-> measurement_start_ms is None
        if self.measurement_start_ms is None:
            self.gpm = 0
            if self.send_hz:
                self.hz = 0
            self.completed_tick_count = 0
            self.completed_elapsed_ms = 1000
            self.reset_flow_measurement()
            return

        # active measurement, but haven't gotten all our ticks
        if not self.flow_data_ready:
            self.completed_tick_count = self._tick_count
            self.completed_elapsed_ms = utime.ticks_ms() - self.measurement_start_ms

        # Calculate gpm (either from ISR data or from what we captured above)
        self.adjust_for_debt()
        self.calculate_flow()

        # ready for new measurement
        self.reset_flow_measurement()

    # ---------------------------------
    # Posting data
    # ---------------------------------

    def report(self):
        now_s = utime.time()
        time_since_sync = now_s  - self.last_sync_report_s
        send_sync = time_since_sync >= self.capture_period_s

        flow_val = self.gpm
        flow_unit = "GpmTimes100"
        if self.send_hz:
            flow_val = self.hz
            flow_unit = "HzTimes100"
        if send_sync:
            about_nodes = []
            measurements = []
            units = []

            if flow_val is not None:
                about_nodes.append(self.flow_channel_name)
                measurements.append(round(flow_val * 100))
                units.append(flow_unit)

            if self.hot is not None:
                about_nodes.append(self.hot_channel_name)
                measurements.append(round(self.hot * 100))
                units.append("CelsiusTimes100")

            if self.cold is not None:
                about_nodes.append(self.cold_channel_name)
                measurements.append(round(self.cold * 100))
                units.append("CelsiusTimes100")

            if self.read_ct_voltage and self.pump_ct_voltage is not None:
                about_nodes.append(self.ct_channel_name)
                measurements.append(round(self.pump_ct_voltage * 100))
                units.append("VoltsTimes100")

            if about_nodes:
                print(f"SYNC SEND → {about_nodes} {measurements}")
                self.post_btu_data(about_nodes, measurements, units)
                self.last_sync_report_s = now_s
        else:
            about_nodes = []
            measurements = []
            units = []
            if flow_val is None and self.hot is None and self.cold is None:
                print(f"Skipping async - missing data: flow: {flow_val}{flow_unit}, hot={self.hot}, cold={self.cold}")
                return
            if flow_val is not None and self.gpm is not None:
                if 100 * abs(self.gpm - self.last_sent_gpm) > self.async_capture_delta_gpm_x_100:
                    about_nodes.append(self.flow_channel_name)
                    measurements.append(round(flow_val * 100))
                    units.append(flow_unit)
                    print(f"Flow changed: {self.last_sent_gpm:.3f} -> {self.gpm:.3f} GPM")
            
            if self.hot is not None:
                if 100 * abs(self.hot - self.last_sent_hot) > self.async_capture_delta_celsius_x_100:
                    about_nodes.append(self.hot_channel_name)
                    measurements.append(round(self.hot * 100)) # Send as centi-Celsius
                    units.append("CelsiusTimes100")
                    print(f"hot temp changed: {self.last_sent_hot:.3f} -> {self.hot:.3f} deg C")
            
            if self.cold is not None:
                if 100 * abs(self.cold - self.last_sent_cold) > self.async_capture_delta_celsius_x_100:
                    about_nodes.append(self.cold_channel_name)
                    measurements.append(round(self.cold * 100)) # Send as centi-Celsius
                    units.append("CelsiusTimes100")
                    print(f"cold temp changed: {self.last_sent_cold:.3f} -> {self.cold:.3f} deg C")
            
            if self.read_ct_voltage and self.pump_ct_voltage is not None:
                if 100 * abs(self.pump_ct_voltage - self.last_sent_pump_ct_voltage) > self.async_capture_delta_ct_volts_x_100:
                    about_nodes.append(self.ct_channel_name)
                    measurements.append(round(self.pump_ct_voltage * 100)) # Send as centi-volts
                    units.append("VoltsTimes100")

            if about_nodes:
                self.post_btu_data(about_nodes, measurements, units)

    def post_btu_data(self, about_nodes, measurements, units):
        payload = {
                "HwUid": self.hw_uid,
                "ChannelNameList": about_nodes,
                "MeasurementList": measurements,
                "UnitList": units,
                "TypeName": "multichannel.snapshot",
                "Version": "000"
            }
        status = self.http.post_fire_and_forget(
            f"/{self.actor_node_name}/multichannel-snapshot",
            payload
        )
        if status is None:
            self.needs_reconnect = True
        if status != 200:
            return False

        if self.flow_channel_name in about_nodes:
            self.last_sent_gpm = self.gpm
        if self.hot_channel_name in about_nodes:
            self.last_sent_hot = self.hot
        if self.cold_channel_name in about_nodes:
            self.last_sent_cold = self.cold
        if self.read_ct_voltage and self.ct_channel_name in about_nodes:
            self.last_sent_pump_ct_voltage = self.pump_ct_voltage
        return True

    def start_timers(self):
        self.pulse_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.pulse_callback)

        utime.sleep_ms(850)
        self.temp_timer.init(
            period=1000, # every second
            mode=machine.Timer.PERIODIC,
            callback=self.measure_temps_and_ct
        )

        utime.sleep_ms(150)
        self.flow_timer.init(
            period=1000, 
            mode=machine.Timer.PERIODIC,
            callback=self.manage_flow
        )
        
    def main_loop(self):
        try:
            offset = round(self.capture_offset_seconds)
            if offset > 1:
                offset -= 1
            self.last_sync_report_s = utime.time() + offset - self.capture_period_s
        except Exception as e:
            self.last_sync_report_s = utime.time()
        while True:
            if self.needs_reconnect and utime.time() - self.time_last_tried_to_reconnect > RECONNECT_COOLDOWN_S:
                self.needs_reconnect = False
                self.try_to_reconnect()
            if self.pending_async_check:
                # Give pulse callback the chance to cleanly catch its first
                # timestamp. Slowest ~ 15 Hz / 67 ms
                utime.sleep_ms(100)
                gpm_str = "None" if self.gpm is None else f"{self.gpm:.2f}"
                print(f"{gpm_str} gpm [{self.completed_tick_count} ticks in {self.completed_elapsed_ms} ms]")
                self.report()
                self.pending_async_check = False
            utime.sleep_ms(1) 

    def start(self):
        try:
            if self.wifi_or_ethernet == 'wifi':
                net.connect_to_wifi(self.wifi_name, self.wifi_password)
            elif self.wifi_or_ethernet == 'ethernet':
                net.connect_to_ethernet()
        except Exception as e:
            print(f"Initial connect failed ({e})")
            self.needs_reconnect = True
            self.time_last_tried_to_reconnect = 0

        self.update_comms_config()
        self.update_app_config()
        self.update_code()

        self.start_timers()
        self.report() 
        self.main_loop()


if __name__ == "__main__":
    b = AsyncBtuMeter()
    b.start()