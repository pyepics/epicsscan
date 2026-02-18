#!/usr/bin/python
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from epicsscan import ScanServer
from epicsscan.gui import ScanApp


def check_escan_credentials():
    cred_file = os.environ.get('ESCAN_CREDENTIALS', None)
    if cred_file is None:
        raise ValueError("need to set ESCAN_CREDENTIALS environment variable")
    if not Path(cred_file).exists():
        raise ValueError(f"ESCAN_CREDENTIALS='{cred_file}' file does not exist.")

def run_epicsscan_gui():
    "run the epicsscan client gui"
    check_escan_credentials()
    ScanApp().MainLoop()

def run_epicsscan_server():
    "run the epicsscan server"
    check_escan_credentials()
    server = ScanServer()
    server.scandb.check_hostpid()

    row = server.scandb.get_info('heartbeat', full_row=True, default=None)
    if row is None:
        raise ValueError("ScanServer database not setup.")
    if row.modify_time > datetime.now()-timedelta(seconds=15):
        raise ValueError("ScanServer appears to be running")

    server.mainloop()
