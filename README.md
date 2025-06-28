# gridworks-pico

GridWorks micropython code for sensors/actuators running on a Raspberry Pi Pico W.

## Configuring a new Pico

- Plug in the Pico to a computer and open Thonny
- Click the bottom right menu bar, and click "Install Micropython..."
- For a Pico communicating Wifi select "Pico W", for a Pico communicating Ethernet select "Wiznet 5500"
- Create a new file
- Copy and paste the content of the provided `provisioner.py` in that new file
- Run the file and answer the prompts in Thonny's shell
- Add this Pico to the [device registry](https://docs.google.com/spreadsheets/d/1ciNYkqTFreuF7spXqfPVz5j4dWS9rPG2Zydkkh57mLI/edit?pli=1&gid=167548878#gid=167548878)

## Testing the code
- Option 1: 
  - Unplug the Pico from the computer
  - Plug the Pico to a new power source
- Option 2:
  - Hit the stop button
  - Close all open windows
  - Open `main.py` and run it
- In both cases, the Pico should show up in the `api` tmux session and communicate its parameters
