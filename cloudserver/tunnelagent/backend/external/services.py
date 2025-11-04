from backend.settings import CAH_PUBLIC_KEY_STORAGE_PATH
import subprocess
from pathlib import Path



class ElevatedOperations:

    @staticmethod
    def add_home_user(home_id: int, username: str, public_key: str) -> int:
        """returns the process exit status of the external script run"""

        # determine public key filename and path
        public_key_filename = f'{username}{home_id}_public_key'
        public_key_filepath = Path(CAH_PUBLIC_KEY_STORAGE_PATH) / Path(public_key_filename)

        # write pyblic key to file
        f = open(public_key_filepath, 'w')
        f.write(public_key)
        f.close()

        # subprocess.run(['sudo','manage_tunnel.py'])
        result = subprocess.run(['sudo', 'manage_tunnel.py', 'add', username, str(home_id), '-p', public_key_filename])
        print('manage_tunnel.py returned: ', result.returncode)

        #

        return result.returncode



