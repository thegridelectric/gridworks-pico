import gc
import machine
from machine import Pin
import utime
import math
import network
import ujson
import urequests
import ubinascii


COMMS_CONFIG_FILE = "comms_config.json"
APP_CONFIG_FILE = "app_config.json"
DEFAULT_ACTOR_NAME = "primary-btu"

DEFAULT_CAPTURE_PERIOD_S = 60
DEFAULT_GALLONS_PER_PULSE = 0.0009
DEFAULT_ASYNC_CAPTURE_DELTA_GPM_X_100 = 10
DEFAULT_ASYNC_CAPTURE_DELTA_CELSIUS_X_100 = 20
DEFAULT_ASYNC_CAPTURE_DELTA_CT_VOLTS_X_100 = 20
DEFAULT_THERMISTOR_BETA = 3977


class AsyncBtuMeter:
    # BTU meter with coordinated measure of flow, temp and pump power.
    # Designed for async reporting on change for all 3 and also
    # synchronous reporting happening at a default of 60 seconds

    # Flow meter expected range: 15-150 Hz (67ms - 6.7ms periods)
    # Jitter threshold: > 400 Hz (< 2.5ms period) indicates physical bounce
    #
    # self.read_ct is True iff CtNodeName is not None

    PULSE_PIN = 21
    ADC0_PIN = 26 # Hot Temp
    ADC1_PIN = 27 # Cold Temp
    ADC2_PIN = 28 # Current Transformer

    R_FIXED_KOHMS = 5.6
    THERMISTOR_R0_KOHMS = 10
    THERMISTOR_T0 = 298

    def __init__(self):
        pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()[-6:]
        self.hw_uid = f"pico_{pico_unique_id}"
        self.load_comms_config()
        self.load_app_config()

        # Hardware setup
        # Release any ADC pull-down/pull-up resistors
        Pin(26, Pin.IN)
        Pin(27, Pin.IN)
        Pin(28, Pin.IN)
        self.pulse_pin = machine.Pin(self.PULSE_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self.adc_hot = machine.ADC(self.ADC0_PIN)
        self.adc_cold = machine.ADC(self.ADC1_PIN)
        self.adc_ct = machine.ADC(self.ADC2_PIN)

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

        #Timers
        self.last_sync_report_s = 0
        self.capture_offset_seconds = 0 
        self.temp_timer = machine.Timer(-1)
        self.flow_timer = machine.Timer(-1)

        # main loop variables
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

        self.last_nic_restart_s = 0
        self.last_comms_success_s = utime.time()
                                                                 
    def post_json(self, endpoint: str, payload: dict):
        """POST JSON and return parsed JSON dict on 200; else None."""
        url = self.base_url + endpoint
        headers = {"Content-Type": "application/json"}
        body = ujson.dumps(payload)

        resp = None
        try:
            resp = urequests.post(url, data=body, headers=headers)
            if resp.status_code != 200:
                return None
            # Parse while still open
            self.last_comms_success_s = utime.time()
            return resp.json()
        except Exception as e:
            print(f"POST JSON failed: {e}")
            return None
        finally:
            if resp:
                resp.close()
            gc.collect()

    def post_maybe_file(self, endpoint: str, payload: dict):
        """POST JSON and return (content_bytes, is_json) on 200; else (None, False)."""
        url = self.base_url + endpoint
        headers = {"Content-Type": "application/json"}
        body = ujson.dumps(payload)

        resp = None
        try:
            resp = urequests.post(url, data=body, headers=headers)
            if resp.status_code != 200:
                return (None, False)

            data = resp.content  # capture bytes while open

            # Try JSON detection
            try:
                ujson.loads(data.decode("utf-8"))
                return (data, True)
            except Exception:
                return (data, False)
        except Exception as e:
            print(f"POST file/json failed: {e}")
            return (None, False)
        finally:
            if resp:
                resp.close()
            gc.collect()

    def update_code(self):
        endpoint = f"/{self.actor_node_name}/code-update"
        payload = {
            "HwUid": self.hw_uid,
            "ActorNodeName": self.actor_node_name,
            "TypeName": "new.code",
            "Version": "100"
        }
        content, is_json = self.post_maybe_file(endpoint, payload)
        if not content:
            return

        if is_json:
            return
        
        with open("main_update.py", "wb") as file:
            file.write(content)
        machine.reset()

    def load_comms_config(self):
        try:
            with open(COMMS_CONFIG_FILE, "r") as f:
                comms_config = ujson.load(f)
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Error loading comms_config file: {e}")
        self.wifi_or_ethernet = comms_config.get("WifiOrEthernet", "ethernet")
        self.base_url = comms_config["BaseUrl"].rstrip("/")
        if self.wifi_or_ethernet!="ethernet":
            raise KeyError("WifiOrEthernet must be 'ethernet' for Wiznet Pico")
        if self.base_url is None:
            raise KeyError("BaseUrl not found in comms_config.json")

    def load_app_config(self):
        #Load the app config file. If PumpPowerName is None, do not read power
        try:
            with open(APP_CONFIG_FILE, "r") as f:
                app_config = ujson.load(f)
        except:
            app_config = {}
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

    def save_app_config(self):

        config = {
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
            "TypeName": "async.btu.params",
            "Version": "000"
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
    
    def update_app_config(self):
        endpoint = f"/{self.actor_node_name}/async-btu-params"
        payload = {
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
            "TypeName": "async.btu.params",
            "Version": "000"
        }
        updated_config = self.post_json(endpoint, payload)
        if not updated_config:
            return False

        self.actor_node_name = updated_config.get("ActorNodeName", self.actor_node_name)
        self.hot_channel_name = updated_config.get("HotChannelName", self.hot_channel_name)
        self.cold_channel_name = updated_config.get("ColdChannelName", self.cold_channel_name)
        self.flow_channel_name = updated_config.get("FlowChannelName", self.flow_channel_name)
        self.send_hz = updated_config.get("SendHz", self.send_hz)
        self.read_ct_voltage = updated_config.get("ReadCtVoltage", self.read_ct_voltage)
        # None will signal not reading power
        self.ct_channel_name = updated_config.get("CtChannelName")
        
        self.read_ct_voltage = self.ct_channel_name is not None
        self.thermistor_beta = updated_config.get("ThermistorBeta", self.thermistor_beta)
        if self.thermistor_beta is None:
            self.thermistor_beta = DEFAULT_THERMISTOR_BETA
        self.capture_offset_seconds = updated_config.get("CaptureOffsetS", 0)
        if self.capture_offset_seconds is None:
            self.capture_offset_seconds = 0
        self.capture_period_s = updated_config.get("CapturePeriodS", self.capture_period_s)

        self.gallons_per_pulse = updated_config.get("GallonsPerPulse", self.gallons_per_pulse)
        self.async_capture_delta_gpm_x_100 = updated_config.get("AsyncCaptureDeltaGpmX100", self.async_capture_delta_gpm_x_100)

        self.async_capture_delta_celsius_x_100 = updated_config.get("AsyncCaptureDeltaCelsiusX100", self.async_capture_delta_celsius_x_100)

        self.async_capture_delta_ct_volts_x_100 = updated_config.get("AsyncCaptureDeltaCtVoltsX100", self.async_capture_delta_ct_volts_x_100)
        self.save_app_config()
        return True

    def celsius_from_volts(self, volts):
        #  Uses Beta formula with THERMISTOR_BETA of 3977
        # TODO: consider adding thermistor_beta to app_config?
        if volts <= 0.001 or volts >= 3.299:
            return None
        # Use Beta Formula
        r_therm = 1 / ((3.3 / volts - 1) / self.R_FIXED_KOHMS)
        thermistor_beta = self.thermistor_beta
        if thermistor_beta is None or thermistor_beta == 0:
            thermistor_beta = DEFAULT_THERMISTOR_BETA
        return 1 / ((1 / self.THERMISTOR_T0) + (math.log(r_therm / self.THERMISTOR_R0_KOHMS) / thermistor_beta)) - 273

    def measure_temp(self, adc_channel, n_samples=100):
        # Measure voltage in microvolts (for temp) Takes ~1.7ms for 100 samples.
        try:
            reading_sum = 0
            for _ in range(n_samples):
                reading_sum += adc_channel.read_u16()
            avg_reading = reading_sum / n_samples
            avg_voltage =  avg_reading * 3.3 / 65535
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
            if flow_val is not None and self.hot is not None and self.cold is not None:

                about_nodes = [self.flow_channel_name, self.hot_channel_name, self.cold_channel_name]
                measurements = [
                    round(flow_val * 100),
                    round(self.hot * 100),
                    round(self.cold * 100),
                ]
                units = [flow_unit, "CelsiusTimes100", "CelsiusTimes100"]
                
                if self.read_ct_voltage and self.pump_ct_voltage is not None:
                    about_nodes.append(self.ct_channel_name)
                    measurements.append(round(self.pump_ct_voltage * 100))
                    units.append("VoltsTimes100")
                
                self.post_btu_data(about_nodes, measurements, units)
                self.last_sync_report_s = now_s
                print(f"JUST RESET last_sync_report_s")
        else:
            about_nodes = []
            measurements = []
            units = []
            if flow_val is None or self.hot is None or self.cold is None:
                print(f"Skipping async - missing data: flow: {flow_val}{flow_unit}, hot={self.hot}, cold={self.cold}")
                return
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

    def sync_report(self, timer):
        if self.gpm is None or self.hot is None or self.cold is None:
            return
        about_nodes = [self.flow_channel_name, self.hot_channel_name, self.cold_channel_name]
        measurements = [
            round(self.gpm * 100),  # GpmTimes100
            round(self.hot * 100),  # CelsiusTimes100
            round(self.cold * 100), # CelsiusTImes100
        ]
        units = ["GpmTimes100", "CelsiusTimes100", "CelsiusTimes100"]

        # add ct voltage if configured
        if self.read_ct_voltage and self.pump_ct_voltage is not None:
            about_nodes.append(self.ct_channel_name)
            measurements.append(round(self.pump_ct_voltage * 100))
            units.append("VoltsTimes100")

        self.post_btu_data(about_nodes, measurements, units)

    def post_btu_data(self, about_nodes, measurements, units):
        endpoint = f"/{self.actor_node_name}/multichannel-snapshot"
        payload = {
                "HwUid": self.hw_uid,
                "ChannelNameList": about_nodes,
                "MeasurementList": measurements,
                "UnitList": units,
                "TypeName": "multichannel.snapshot",
                "Version": "000"
            }
        response = self.post_json(endpoint, payload)

        if response:
            if self.flow_channel_name in about_nodes:
                self.last_sent_gpm = self.gpm
            if self.hot_channel_name in about_nodes:
                self.last_sent_hot = self.hot
            if self.cold_channel_name in about_nodes:
                self.last_sent_cold = self.cold
            if self.read_ct_voltage and self.ct_channel_name in about_nodes:
                self.last_sent_pump_ct_voltage = self.pump_ct_voltage
            return True

        return False

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

    def restart_nic(self):
        try:
            self.nic.active(False)
            utime.sleep(1)
            self.nic.active(True)
            self.nic.ifconfig('dhcp')
        except Exception as e:
            print(f"NIC restart failed: {e}")
            machine.reset()

    def connect_to_ethernet(self):
        self.nic = network.WIZNET5K()

        for attempt in range(5):
            try:
                print(f"trying to connect, attempt {attempt}")
                self.nic.active(True)
                break
            except Exception as e:
                print(f"Retrying NIC activation due to: {e}")
                utime.sleep(0.5)

        # Always try DHCP, even if link is not ready yet
        try:
            self.nic.ifconfig('dhcp')
        except Exception as e:
            print(f"DHCP start failed: {e}")
            return False

        # Non-fatal wait for link
        start = utime.time()
        while utime.time() - start < 10:
            if self.nic.isconnected():
                print("Connected to Ethernet")
                self.last_comms_success_s = utime.time()
                return True
            utime.sleep(0.5)

        print("Ethernet not connected yet — continuing anyway")
        return False

    def main_loop(self):

        try:
            offset = round(self.capture_offset_seconds)
            if offset > 1:
                offset -= 1
            self.last_sync_report_s = utime.time() + offset - self.capture_period_s
        except Exception as e:
            self.last_sync_report_s = utime.time()
        while True:
            if self.pending_async_check:
                # Give pulse callback the chance to cleanly catch its first
                # timestamp. Slowest ~ 15 Hz / 67 ms
                utime.sleep_ms(100)
                print(f"{self.gpm:.2f} gpm [{self.completed_tick_count} ticks in {self.completed_elapsed_ms} ms]")
                self.report()
                self.pending_async_check = False

            now = utime.time()
            STALL_S = int(2.1 * self.capture_period_s)
            if (
                now - self.last_comms_success_s > STALL_S
               and now - self.last_nic_restart_s > STALL_S
            ):
                print(f"Comms stalled > {STALL_S}s - restarting NIC")
                self.last_nic_restart_s = now
                self.restart_nic()
                ok = self.update_app_config() 
                if not ok:
                    print("Probe failed after NIC restart")
            utime.sleep_ms(10) 

    def start(self):

        self.connect_to_ethernet()

        # Update configurations 
        self.update_app_config()
        self.update_code()

        self.start_timers()
        self.report() 
        self.main_loop()


if __name__ == "__main__":
    b = AsyncBtuMeter()
    b.start()
