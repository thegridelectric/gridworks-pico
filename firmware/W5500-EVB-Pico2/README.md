# W5500-EVB-Pico2 MicroPython Firmware

Custom MicroPython firmware for the Wiznet W5500-EVB-Pico2 board (RP2350-based) with integrated Ethernet support.


## Quick Start


**Steps 0 - 4 ALL are on a terminal window**

 0. `brew install picotool` (only need to do this once)

 1. Navigate to this directory (after making sure this repository is local and up to date):
   `cd $path/gridworks-pico/firmware/W5500-EVB-Pico2/`
and then

 2. Hold BOOTSEL button while connecting the Pico2 to USB

 3. Confirm the RP2350 drive exists: `ls /Volumes`
 4. load code:

 ```
 picotool load 	Wiz-Pico2_2aaf30.uf2
 ```
Unplug and then plug back in the pico, and then open Thonny and in the lower right corner select the new micropython OS. In Thonny:
 1. Verify at the top of the Shell window that the OS is for a Pico2 (grey text ends with `W5500-EVB-Pico2 with RP2350`)
 2. In Thonny go to Tools -> manage packages -> 
 3. Type `urequests` into the search prompt
 4. Click on `urequests` when it comes up and then click on `install`. The `urequests` package will now be installed on the pico (in thonny, you should see `lib` in the drop-down window with a carrot; urequests is installed under that)

After this you should be able to run the standard `provisioner.py` (after plugging into Ethernet and re-powering)
 ## Features

 - MicroPython v1.27.0-preview.83
 - Network module with WIZNET5K support
 - Pre-configured for W5500-EVB-Pico2 hardware
 - 20MHz SPI for optimal Ethernet performance

## Usage

```
import network
import urequests
from machine import Pin, SPI

# Option 1: Use default pins (if board detection works)
nic = network.WIZNET5K()

# Option 2: Explicit configuration
spi = SPI(0, baudrate=20_000_000, sck=Pin(18), mosi=Pin(19), miso=Pin(16))
nic = network.WIZNET5K(spi, Pin(17), Pin(20))  # spi, cs, rst

# Activate and configure
nic.active(True)
nic.ifconfig('dhcp')  
```

## Building From Source

### Prerequisites
ARM GNU Toolchain, CMake 3.13+, Python 3.8+, Git

For a mac:
1. Command line tools (for make, etc)
```
xcode-select --install
```
2. CMake + ARM embedded compiler

```
brew install cmake
brew install --cask gcc-arm-embedded
```

Verify:
```
cmake --version   # if this errors, do: brew install cmake
arm-none-eabi-gcc --version  # if this errors, do: brew install arm-none-eabi-gcc
make --version
python --version
picotool version
```
### Build Instructions

1. Clone MicroPython and prepare environment

```
git clone --recurse-submodules https://github.com/micropython/micropython.git
cd micropython
make -C mpy-cross
make -C ports/rp2 submodules BOARD=RPI_PICO2
```

2. Create board configuration

```
cd ports/rp2/boards
cp RPI_PICO2 W5500_EVB_PICO2
```

Replace the following files with the versions in this `board_config` folder:
1. `ports/rp2/boards/W5500_EVB_PICO2/mpconfigboard.cmake`
2. `ports/rp2/boards/W5500_EVB_PICO2/mpconfigboard.h`
3. `extmod/network_wiznet5k.c`
4. `ports/rp2/CMakeLists.txt`

3. Build the firmware

Go to the `ports/rp2/boards` directory

```
rm -rf build-W5500_EVB_PICO2
make BOARD=W5500_EVB_PICO2 clean
make BOARD=W5500_EVB_PICO2 submodules
make BOARD=W5500_EVB_PICO2 -j8
```
The firmware will be at `build-W5500_EVB_PICO2/firmware.uf2`

### Differences from Standard Pico2 Build
 - Network module enabled
 - WIZNET5K driver included
 - Default pins for W5500
 - Optimized SPI speed (20 MHz)
