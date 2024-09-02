# gridworks-pico
GridWorks micro python code for sensors/actuators running on a Raspberry Pi Pico W


## Provision TankModule

**1. Load code: cut and paste the following to same-named files on pico**
  - utils.py
  - comms_config.json
  - [FOR NOW]boot.py
  - tank_module/tank_module_main.py (as main.py)
  - tank_module/provisioner.py (as provisioner.py)

**2. Update Wifi Password and  BaseUrl**
 Open comms_config.json:
   - update the wifi password (in 1password)
   - update BaseUrl (replace fir2 with correct plant)

**3. Run the provisioner script**

**4. Backoffice and label**
- Label the pico with the XXXXXX from pico_XXXXXX of step 3
- Add the pico to the [device registry](https://docs.google.com/spreadsheets/d/1ciNYkqTFreuF7spXqfPVz5j4dWS9rPG2Zydkkh57mLI/edit?gid=167548878#gid=167548878)