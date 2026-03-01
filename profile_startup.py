import cProfile
import sys
import os

# Zorg dat het script-directory in sys.path staat
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

import portefeuille_viewer.portefeuille_viewer_AI.portefeuille_viewer_AI as portefeuille_viewer_AI

def run():
    portefeuille_viewer_AI.main()

cProfile.run("run()", "startup.prof")
