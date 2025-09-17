# cmake file for Raspberry Pi Pico2 (ports/rp2/boards/RPI_PICO2_WIZNET/mconfigboard.cmake)
set(PICO_BOARD "pico2")

# To change the gpio count for QFN-80
# set(PICO_NUM_GPIOS 48)

# Enable the Wiznet5k NIC (W5500)
set(MICROPY_PY_NETWORK 1)
set(MICROPY_PY_NETWORK_WIZNET5K 5500)
