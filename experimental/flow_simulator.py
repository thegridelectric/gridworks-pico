# import machine, utime
# out = machine.Pin(22, machine.Pin.OUT, value=0)
# SLEEP_US = LOW_US = 10000 # 50Hz
# #SLEEP_US = LOW_US = 33333  # ~15 Hz, 50%
# #HIGH_US = LOW_US = 2_000_000 # 0.5 Hz


# while True:
#     out.value(1)               # drive high
#     utime.sleep_us(SLEEP_US)
#     out.value(0)               # drive low
#     utime.sleep_us(SLEEP_US)

import machine, utime
out = machine.Pin(22, machine.Pin.OUT, value=0)

# Half-periods for 50 Hz and 15 Hz (microseconds)
PERIODS_US = {
    50: int(1_000_000 / (2 * 50)),   # 10_000 µs
    15: int(1_000_000 / (2 * 15)),   # 33_333 µs
}

# Duration to stay at each frequency (seconds)
MODE_DURATION_S = 10

while True:
    for freq in (50, 15):
        half_period = PERIODS_US[freq]
        start = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), start) < MODE_DURATION_S * 1000:
            out.value(1)
            utime.sleep_us(half_period)
            out.value(0)
            utime.sleep_us(half_period)