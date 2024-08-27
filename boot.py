import os

if 'main_update.py' in os.listdir():
    
    # Check all is well
    
    # Replace the current main.py
    if 'main.py' in os.listdir():
        os.remove('main.py')
    os.rename('main_update.py', 'main.py')