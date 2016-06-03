"""
convert scan definitions from scan database dictioary to Stepscans
"""
import json
import numpy as np

from .detectors import get_detector
from .positioner import Positioner
from .stepscan import StepScan
from .xafs_scan import XAFS_Scan, QXAFS_Scan
from .scandb import ScanDBException, ScanDB
from .utils import asciikeys

def scan_from_db(scandb, scanname, filename='scan.00'):
    """
    return a StepScan object from a scan named in a scan database

    Arguments
    ---------
    scandb (ScanDB instance): scan database instance
    scanname (string): name of scan
    filename (string): name for datafile

    """
    if not isinstance(scandb, ScanDB):
        raise ScanDBException("scan_from_db needs a valid ScanDB object")

    thisscan = scandb.get_scandef(scanname)
    if thisscan is None:
        raise ScanDBException('scan_from_db needs a valid scan name')
    sdict = json.loads(thisscan.text, object_hook=asciikeys)

    default_rois = json.loads(scandb.get_info('rois'))

    # create different scan types
    if sdict['type'] == 'xafs':
        min_dtime = sdict['dwelltime']
        if isinstance(min_dtime, np.ndarray):
            min_dtime = min(dtime)
        kwargs = dict(energy_pv=sdict['energy_drive'],
                      read_pv=sdict['energy_read'],
                      e0=sdict['e0'])

        if sdict.get('is_qxafs', False) or min_dtime < 0.45:
            scan = QXAFS_Scan(**kwargs)
            sdict['time_kw'] = 0
            sdict['max_time'] = 0
            scan.mode = 'sca'
        else:
            scan = XAFS_Scan(**kwargs)
            scan.mode = 'step'

        t_kw  = sdict['time_kw']
        t_max = sdict['max_time']
        nreg  = len(sdict['regions'])
        for i, det in enumerate(sdict['regions']):
            start, stop, npts, dt, units = det
            kws  = {'relative': sdict['is_relative']}
            kws['dtime'] =  dt
            kws['use_k'] =  units.lower() !='ev'
            if i == nreg-1: # final reg
                if t_max > dt and t_kw>0 and kws['use_k']:
                    kws['dtime_final'] = t_max
                    kws['dtime_wt'] = t_kw
            scan.add_region(start, stop, npts=npts, **kws)
    else:
        scan = StepScan(filename=filename)
        if sdict.get('mode', None) is None:
            scan.mode = 'step'
        if sdict['type'] == 'linear':
            for pos in sdict['positioners']:
                label, pvs, start, stop, npts = pos
                p = Positioner(pvs[0], label=label)
                p.array = np.linspace(start, stop, npts)
                scan.add_positioner(p)
                if len(pvs) > 0:
                    scan.add_counter(pvs[1], label="%s_read" % label)

        elif sdict['type'] in ('mesh', 'slowmap'):
            label1, pvs1, start1, stop1, npts1 = sdict['inner']
            label2, pvs2, start2, stop2, npts2 = sdict['outer']
            p1 = Positioner(pvs1[0], label=label1)
            p2 = Positioner(pvs2[0], label=label2)

            inner = npts2* [np.linspace(start1, stop1, npts1)]
            outer = [[i]*npts1 for i in np.linspace(start2, stop2, npts2)]

            p1.array = np.array(inner).flatten()
            p2.array = np.array(outer).flatten()
            scan.add_positioner(p1)
            scan.add_positioner(p2)
            if len(pvs1) > 0:
                scan.add_counter(pvs1[1], label="%s_read" % label1)
            if len(pvs2) > 0:
                scan.add_counter(pvs2[1], label="%s_read" % label2)

        elif sdict['type'] in ('slew', 'fastmap'):
            if sdict.get('mode', None) is None:
                scan.mode = 'array'
            label1, pvs1, start1, stop1, npts1 = sdict['inner']
            p1 = Positioner(pvs1[0], label=label1)
            p1.array = np.linspace(start1, stop1, npts1)
            scan.add_positioner(p1)
            if len(pvs1) > 0:
                scan.add_counter(pvs1[1], label="%s_read" % label1)
            if sdict['dimension'] >=2:
                label2, pvs2, start2, stop2, npts2 = sdict['outer']
                p2 = Positioner(pvs2[0], label=label2)
                p2.array = np.linspace(start2, stop2, npts2)
                scan.add_positioner(p2)
                if len(pvs2) > 0:
                    scan.add_counter(pvs2[1], label="%s_read" % label2)

    # detectors, with ROIs and mode
    scan.rois = sdict.get('rois', default_rois)
    for dpars in sdict['detectors']:
        dpars['rois'] = scan.rois
        dpars['mode'] = scan.mode
        scan.add_detector(get_detector(**dpars))

    # extra counters (not-triggered things to count
    if 'counters' in sdict:
        for label, pvname  in sdict['counters']:
            scan.add_counter(pvname, label=label)

    # other bits
    scan.add_extra_pvs(sdict['extra_pvs'])
    scan.scantime = sdict.get('scantime', -1)
    scan.filename = sdict.get('filename', 'scan.dat')
    if filename is not None:
        scan.filename  = filename
    scan.pos_settle_time = sdict.get('pos_settle_time', 0.01)
    scan.det_settle_time = sdict.get('det_settle_time', 0.01)
    scan.nscans          = sdict.get('nscans', 1)
    if scan.dwelltime is None:
        scan.set_dwelltime(sdict.get('dwelltime', 1))
    return scan
