# gridworks-pico

GridWorks micropython code for sensors/actuators running on a Raspberry Pi Pico W.

## Setting up a Pico

- Plug in the Pico to a computer. Open Thonny, and close all open files. Finally, a good practice is to hit the red 'Stop' button just to make sure.

- Add `boot.py` and `utils.py` to the Pico.

- Add `comms_config.json` to the Pico, and update the WifiPassword (in 1password) and BaseURL (replace "fir2" with the correct path).

- Add `app_config.json` to the Pico, and update the `ActorNodeName` accordingly. The exact name does not matter, but all Picos in the same house must have a different ActorNodeName. Some examples from `fir2`: 
  - Top two layers of buffer: `buffer-a`
  - Bottom two layers of buffer: `buffer-b`
  - Top two layers of tank1: `tank1-a`
  - Bottom two layers of tank1: `tank1-b`
  - Reed flowmeter: `pico-flow-reed`
  - Hall flowmeter, distribution: `pico-flow-hall`
  - Hall flowmeter, storage`pico-flow-hall-store`
  
- Depending on the sensor connected to the Pico, add `flow_hall_main.py`, `flow_reed_main.py`, `omega_main.py` or `tank_module_main.py` as `main.py` to the Pico.

- When running `main.py` or by plugging the Pico to power, it should show up in the API (look for it in the `api` tmux session). As soon as connected, it will communicate its parameters, of which: ```HwUid: pico_xxxxxx```, where `xxxxxx` is its unique ID. Add this Pico to the [device registry](https://docs.google.com/spreadsheets/d/1ciNYkqTFreuF7spXqfPVz5j4dWS9rPG2Zydkkh57mLI/edit?pli=1&gid=167548878#gid=167548878).