import machine, utime
out = machine.Pin(22, machine.Pin.OUT, value=0)
HIGH_US = LOW_US = 10000 # 50Hz
#HIGH_US = LOW_US = 33333  # ~15 Hz, 50%
#HIGH_US = LOW_US = 2_000_000 # 0.5 Hz


while True:
    out.value(1)               # drive high
    utime.sleep_us(HIGH_US)
    out.value(0)               # drive low
    utime.sleep_us(LOW_US)