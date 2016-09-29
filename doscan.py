import sys
from lib import scandb
from lib.larch_interface import LarchScanDBServer
import json
from scan_credentials import conn

sdb = scandb.ScanDB(**conn)

def asciikeys(adict):
    """ensure a dictionary has ASCII keys (and so can be an **kwargs)"""
    return dict((k.encode('ascii'), v) for k, v in adict.items())

def list_scans(stype='slew'):
    cls, table = sdb.get_table('scandefs')
    all = table.select(whereclause="type='%s'" % stype).execute().fetchall()
    for s in all:
        print(s.name)


larchserver = LarchScanDBServer(sdb, fileroot='/cars5/Data/xas_user')
larchserver.load_macros()

# list_scans('linear')
# scan = sdb.make_scan('line1', larch=larchserver.larch)

scan = sdb.make_scan('bmap', larch=larchserver.larch)

# print("Scan:: ", scan, scan.scantype, scan.detmode)  #, scan.dimension)

## print("======================================")


# scan = sdb.make_scan('Fe_QXAFS')
# print("Scan:: ", scan, scan.scantype, scan.detmode)  #, scan.dimension)


# print 'Mode = ', scan.detmode
# print 'Larch = ', scan.larch
# scan.larch.run('show(_sys)')

# for p in scan.positioners:
#    print("== Pos: ", p)
    # print(dir(p))
    # oprint(p.array)


# print scan.xps.traj_group,

# for d in scan.detectors:
#     print("== Det: ", d, d.mode)
#

# print sdb.get_info('server_fileroot')
# print sdb.get_info('user_folder')


# scan.prepare_scan()
#scan.pre_scan()
scan.run(npts=25, debug=False)



print("___DONE")



# scan.run(filename='foo.dat', debug=False)


# _larch = LarchScanDBServer(sdb)
# _larch.load_plugins()
# _larch.load_modules()

# from lib.station_config import StationConfig

# from lib.server import run_scan

#
# from lib.detectors import get_detector
#
# ##from lib.larch_interface import LarchScanDBServer
# # import epics
# # p = epics.PV('13IDE:SIS1:mca1')
# # print p.get()
#
#
# import json
# ;
