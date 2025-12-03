import cProfile
import sys
import os

# Zorg dat het script-directory in sys.path staat
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

import portefeuille_viewer_0_11

def run():
    portefeuille_viewer_0_11.main()

cProfile.run("run()", "startup.prof")