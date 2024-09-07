# gridworks-pico

GridWorks micropython code for sensors/actuators running on a Raspberry Pi Pico W.

## First steps

- Plug in the Pico to a computer and open Thonny
- Close all open files and hit the red 'Stop' button
- Add the provided `boot.py` to the Pico
- Add the provided `utils.py` to the Pico

## Adding `comms_config.json`

- Add the provided `comms_config.json` to the Pico
- Update the `WifiPassword` (in 1Password)
- Update the `BaseURL` (replace "fir2" with the correct path)

## Adding `app_config.json`

- Add the provided `app_config.json` to the Pico

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

### Examples:

Hall meter, store flow:
```
{"ActorNodeName": "pico-flow-hall-store", "FlowNodeName": "store-flow", "PicoAB": "no-ab"}
```
Tank module, upper two layers:
```
{"ActorNodeName": "tank1-a", "FlowNodeName": "no-name", "PicoAB": "a"}
```

## Adding a `main.py`

Depending on the sensor connected to the Pico, save the content of `..._main.py` as `main.py` to the Pico:
- Reed flowmeter: `flow_reed_main.py`
- Hall flowmeter: `flow_hall_main.py`
- Tank temperatures: `tank_module_main.py`
- Omega flowmeter: `omega_main.py`

## Final steps
- Make sure all files are saved on the Pico
- To test the code, you can either:
  - Unplug the Pico from the computer and plug the Pico to a new power source
  - Or run `main.py` directly in Thonny
- The Pico should show up in the `api` tmux session
- It will immediately communicate its parameters, of which ```HwUid: pico_xxxxxx```, where `xxxxxx` is its unique ID. 
- Add this Pico to the [device registry](https://docs.google.com/spreadsheets/d/1ciNYkqTFreuF7spXqfPVz5j4dWS9rPG2Zydkkh57mLI/edit?pli=1&gid=167548878#gid=167548878).