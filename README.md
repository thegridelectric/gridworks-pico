# gridworks-pico

GridWorks micropython code for sensors/actuators running on some variant of the Raspberry Pi RP2040 (Pico) or RP2350 (Pico2) MicroController Units.

## Configuring a new Pico

### 1. Loading Micropython and packages

**Load Micropython**
- **Wiznet W5500-EVB-Pico2** (built on RP2350)
  - Follow instructions at [firmware/W5500-EVB-Pico2/README.md](firmware/W5500-EVB-Pico2/README.md)
- **Wiznet W5500-EVB-Pico** 
  - Press and hold the bootsel button (**closest to edge of board**)
  - Click the bottom right menu bar, and click "Install Micropython..."
  - Plug in the Pico to a computer and open Thonny
  - Select RPi 2040 and the variant of  W5500-EVB-Pico with RP2040
- **Wifi Pico** 
  - Plug in the Pico to a computer and open Thonny
  - Select from the Thonny dropdown menus: "Raspberry Pi - Pico W / Pico WH"




**Add urequests** 
In Thonny, click on `Tools/Manage Packages`. Search and load the urequests package


### 2. Loading GridWorks firmware
- Create a new file
- Copy and paste the content of the provided `provisioner.py` in that new file
- Run the file and answer the prompts in Thonny's shell
- Add this Pico to the [device registry](https://docs.google.com/spreadsheets/d/1ciNYkqTFreuF7spXqfPVz5j4dWS9rPG2Zydkkh57mLI/edit?pli=1&gid=167548878#gid=167548878)

### Testing the code
- Option 1: 
  - Unplug the Pico from the computer
  - Plug the Pico to a new power source
- Option 2:
  - Hit the stop button
  - Close all open windows
  - Open `main.py` and run it
- In both cases, the Pico should show up in the `api` tmux session and communicate its parameters

