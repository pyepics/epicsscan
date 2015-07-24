from lib import scandb
# from lib.station_config import StationConfig
# from lib.server import run_scan
# from lib.detectors import get_detector


from lib.larch_interface import LarchScanDBServer



import epics
p = epics.PV('13IDE:SIS1:mca1')
print p.get()

             
import json

from scan_credentials import conn
sdb = scandb.ScanDB(**conn)

_larch = LarchScanDBServer(sdb)
_larch.load_plugins()
_larch.load_modules()

scandef = sdb.get_scandef('testmap')
print scandef




