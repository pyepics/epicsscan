"""
convert scan definitions from scan database dictioary to Stepscans

"""
import time
import json
import numpy as np

from .utils import asciikeys
from .detectors import get_detector
from .positioner import Positioner
from .scan import StepScan
from .xafs_scan import XAFS_Scan, QXAFS_Scan
from .debugtime import debugtime

def create_scan(filename='scan.dat', comments=None, type='linear',
                detmode=None, rois=None, nscans=1, positioners=None,
                detectors=None, counters=None, extra_pvs=None, inner=None,
                outer=None, dwelltime=1.0, pos_settle_time=0.01,
                det_settle_time=0.01, scantime=None, elem=None,
                e0=None, dimension=1, regions=None,
                energy_drive=None, energy_read=None, is_qxafs=False,
                time_kw=0, max_time=0, is_relative=False, **kws):
    """
    return a StepScan object, built from function arguments

    Arguments
    ---------
    filename (string): name for datafile ['scan.dat']
    type (string):  type of scan, for building positions ('linear',
                   'xafs', 'mesh', 'fastmap', ...)  ['linear']
    detmode (string):  detector mode, for configuring detector and counters,
                   one of 'scaler', 'roi', 'ndarray' [None: guess from scan type]
    dwelltime (float or array):  dwelltime per point
    pos_settle_time (float):  positioner settling time
    det_settle_time (float):  detector settling time
    positioners (list or None):  list of list of Positioners values for step scan
    inner  (list or None):  Positioners values for inner loop of mesh / fastmap scan
    outer  (list or None):  Positioners values for outer loop of mesh / fastmap scan
    detectors (list or None):  list of Detectors
    counters (list or None):  list of Counters
    extra_pvs (list or None):  list of Extra PVs
    e0 (float or None):  e0 for XAFS scan
    regions (list or None): regions for segmented XAFS scan
    energy_drive (string or None): energy drive pv for XAFS scan
    energy_read (string or None): energy read pv for XAFS scan
    is_qxafs (bool):  to use QXAFS mode for XAFS scn
    time_kw (int): time kweight for XAFS scan
    max_time (float): max dwelltime for XAFS scan
    is_relative (bool): use relative for XAFS scan (ONLY!)

    Notes
    ------

    need to doc positions, inner, outer, regions, detectors, counters

    """
    scantype = type
    # create different scan types
    if scantype == 'xafs':
        min_dtime = dwelltime
        if isinstance(min_dtime, np.ndarray):
            min_dtime = min(dtime)
        kwargs = dict(filename=filename, comments=comments,
                      energy_pv=energy_drive, read_pv=energy_read, e0=e0)
        if is_qxafs or min_dtime < 0.45:
            scan = QXAFS_Scan(**kwargs)
        else:
            scan = XAFS_Scan(**kwargs)
        nregions  = len(regions)
        for ireg, det in enumerate(regions):
            start, stop, npts, dt, units = det
            kws  = {'relative': is_relative}
            kws['dtime'] =  dt
            kws['use_k'] =  units.lower() !='ev'
            if ireg == nregions-1: # final reg
                if max_time > dt and time_kw>0 and kws['use_k']:
                    kws['dtime_final'] = max_time
                    kws['dtime_wt'] = time_kw
            scan.add_region(start, stop, npts=npts, e0=e0, **kws)
    else:
        scan = StepScan(filename=filename, comments=comments)
        if scantype == 'linear' and positioners is not None:
            for pos in positioners:
                label, pvs, start, stop, npts = pos
                p = Positioner(pvs[0], label=label)
                p.array = np.linspace(start, stop, npts)
                scan.add_positioner(p)
                if len(pvs) > 0:
                    scan.add_counter(pvs[1], label="%s_read" % label)
        elif scantype in ('mesh', 'slew', 'slowmap', 'fastmap'):
            scan.scantype = scantype
            if inner is None and positioners is not None:
                inner = positioners
            label1, pvs1, start1, stop1, npts1 = inner
            p1 = Positioner(pvs1[0], label=label1)
            p2 = None
            npts2 = 1
            if dimension > 2 or outer is not None:
                label2, pvs2, start2, stop2, npts2 = outer
                p2 = Positioner(pvs2[0], label=label2)
                x2  = [[i]*npts1 for i in np.linspace(start2, stop2, npts2)]
                p2.array = np.array(x2).flatten()

            x1 = npts2*[np.linspace(start1, stop1, npts1)]
            p1.array = np.array(x1).flatten()
            scan.add_positioner(p1)
            if len(pvs1) > 0:
                scan.add_counter(pvs1[1], label="%s_read" % label1)
            if p2 is not None:
                scan.add_positioner(p2)
                if len(pvs2) > 0:
                    scan.add_counter(pvs2[1], label="%s_read" % label2)

            if scantype in ('slew', 'fastmap'):
                scan.detmode = 'ndarray'
    # detectors, with ROIs and det mode
    scan.rois = rois
    for dpars in detectors:
        dpars['rois'] = scan.rois
        dpars['mode'] = scan.detmode
        scan.add_detector(get_detector(**dpars))


    # extra counters (not-triggered things to count)
    if counters is not None:
        for label, pvname in counters:
            scan.add_counter(pvname, label=label)
    # other bits
    if extra_pvs is not None:
        scan.add_extra_pvs(extra_pvs)
    if scan.scantype is None and type is not None:
        scan.scantype = type
    scan.filename = filename
    scan.scantime = scantime
    scan.nscans = nscans
    scan.pos_settle_time = pos_settle_time
    scan.det_settle_time = det_settle_time
    if scan.dwelltime is None:
        scan.set_dwelltime(dwelltime)

    return scan
