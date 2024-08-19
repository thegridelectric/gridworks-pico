# Use this for sending the identifier of the pico W Component
import machine
import ubinascii


def get_hw_uid():
    pico_unique_id = ubinascii.hexlify(machine.unique_id()).decode()
    return f"pico_{pico_unique_id[-6:]}"

