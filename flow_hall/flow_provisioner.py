import machine
import ujson
from utils import get_hw_uid

APP_CONFIG_FILE = "app_config.json"

class Prov:
    def __init__(self):
        self.hw_uid = get_hw_uid()
    
    def set_name(self):

        # Get ActorNodeName
        got_actor_name = False
        while not got_actor_name:
            self.actor_name = input("Enter Actor name (e.g. 'pico-flow-reed', 'pico-flow-hall', 'pico-flow-hall-store'): ")
            if 'flow' not in self.actor_name:
                print("please include 'flow' in the actor name")
            else:
                got_actor_name = True
        
        # Get FlowNodeName
        got_flow_name = False
        while not got_flow_name:
            self.flow_name = input(f"Enter Flow name ('primary-flow', 'dist-flow', 'store-flow'): ")
            if self.flow_name not in {'primary-flow', 'dist-flow', 'store-flow'}:
                print("invalid flow name")
            else:
                got_flow_name = True

        # Save in app_config.json
        config = {
            "ActorNodeName": self.actor_name,
            "FlowNodeName": self.flow_name,
        }
        with open(APP_CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
            
    def start(self):
        self.set_name()
        print("Done. You can now close this file.")

if __name__ == "__main__":
    p = Prov()
    p.start()