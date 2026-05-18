import os
import sys

PROJ = "/Users/romanhoyos94/Documents/Desarrollos-claude/Detector-anomailias-claude"
os.chdir(PROJ)

port = os.environ.get("PORT", "8501")
sys.argv = ["streamlit", "run", os.path.join(PROJ, "app.py"),
            "--server.port", port, "--server.headless", "true"]

from streamlit.web import cli as stcli
stcli.main()
