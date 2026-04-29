import sys

from backend.settings import CAH_PUBLIC_KEY_STORAGE_PATH
import subprocess
from pathlib import Path



class ElevatedOperations:

    @staticmethod
    def add_home_user(home_id: int, username: str, public_key: str):
        public_key_filename = f'{username}{home_id}_public_key'
        public_key_filepath = Path(CAH_PUBLIC_KEY_STORAGE_PATH) / Path(public_key_filename)

        with open(public_key_filepath, 'w') as f:
            f.write(public_key)

        subprocess.run(['sudo', 'manage_tunnel.py', 'add', username, str(home_id), '-p', public_key_filename], check=True)
        subprocess.run(['sudo', 'manage_tunnel.py', 'reload'], check=True)

    @staticmethod
    def remove_home_user(home_id: int, username: str):
        subprocess.run(['sudo', 'manage_tunnel.py', 'remove', username, str(home_id)], check=True)
        subprocess.run(['sudo', 'manage_tunnel.py', 'reload'], check=True)

    @staticmethod
    def reload_tunnel_users():
        subprocess.run(['sudo', 'manage_tunnel.py', 'reload'], check=True)



