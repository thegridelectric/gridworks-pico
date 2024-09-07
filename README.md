# gridworks-pico

GridWorks micropython code for sensors/actuators running on a Raspberry Pi Pico W.

## Setting up a Pico

- Plug in the Pico to a computer. Open Thonny, and close all open files. Finally, a good practice is to hit the red 'Stop' button before going any further.

- Add `boot.py` and `utils.py` to the Pico.

- Add `comms_config.json` to the Pico, and update the `WifiPassword` (in 1Password) and `BaseURL` (replace "fir2" with the correct path).

- Add `app_config.json` to the Pico *(careful to keep the quotation marks when updating this file!)*
  - Update the `ActorNodeName`. The name choice does not matter, but all Picos in the same house must have a different ActorNodeName (as long as we are using remote code download). Some examples from fir: 
    - Reed flowmeter, primary: `pico-flow-reed`
    - Hall flowmeter, distribution: `pico-flow-hall`
    - Hall flowmeter, storage: `pico-flow-hall-store`
    - Top two layers of buffer: `buffer-a`
    - Bottom two layers of buffer: `buffer-b`
    - Top two layers of tank1: `tank1-a`
    - Bottom two layers of tank1: `tank1-b`
  - Update `FlowNodeName` if the Pico is measuring flow:
    - Primary: `primary-flow`
    - Distribution: `dist-flow`
    - Storage: `store-flow`
  - Update `PicoAB` if the Pico is measuring temperatures in a tank:
    - Top two layers: `a`
    - Bottom two layers: `b`
  - *Note: It does not matter what `FlowNodeName` is set to for tank modules, and what `PicoAB` is set to for flowmeters.*
  
- Depending on the sensor connected to the Pico, add `..._main.py` as `main.py` to the Pico:
  - Reed flowmeter: `flow_reed_main.py`
  - Hall flowmeter: `flow_hall_main.py`
  - Tank temperatures: `tank_module_main.py`
  - Omega flowmeter: `omega_main.py`

- Plug the Pico to power (or run `main.py` in Thonny).
  - The Pico should show up in the `api` tmux session. 
  - As soon as connected, it will communicate its parameters, of which: ```HwUid: pico_xxxxxx```, where `xxxxxx` is its unique ID. 
- Add this Pico to the [device registry](https://docs.google.com/spreadsheets/d/1ciNYkqTFreuF7spXqfPVz5j4dWS9rPG2Zydkkh57mLI/edit?pli=1&gid=167548878#gid=167548878).