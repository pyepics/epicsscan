from lib.gui import ScanApp

from scan_credentials import conn
ScanApp(**conn).MainLoop()
