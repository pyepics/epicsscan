"""
convert scan definitions from scan database dictioary to Stepscans

"""
import time
import json
import numpy as np

from .detectors import get_detector, ScalerDetector
from .positioner import Positioner
from .scan import StepScan
from .xafs_scan import XAFS_Scan, QXAFS_Scan
from .slew_scan import Slew_Scan
from .slew_scan1d import Slew_Scan1D

def get_axesdict(axes):
    """normalize inner/outer axes to dictionary (yaml-saveable)"""
    out = {}
    if isinstance(axes, dict):
        out.update(axes)
    if isinstance(axes, (list, tuple)):
        if len(axes) == 6:
            label, pvdrive, pvread, start, stop, npts = axes
        if len(axes) == 5:
            label, pvnames, start, stop, npts = axes
            pvdrive, pvread = pvnames
        out = {'label': label, 'pvdrive': pvdrive, 'pvread': pvread,
               'start': start, 'stop': stop, 'npts': npts}
    return out


def create_scan(filename='scan.dat', comments=None, type='linear',
                scanmode=None, detmode=None, rois=None, nscans=1,
                positioners=None, detectors=None, counters=None,
                extra_pvs=None, inner=None, outer=None, dwelltime=1.0,
                pos_settle_time=0.01, det_settle_time=0.01, scantime=None,
                elem=None, edge=None, e0=None, dimension=1, regions=None,
                energy_drive=None, energy_read=None, time_kw=0, max_time=0,
                is_relative=False, scandb=None, mkernel=None,
                data_callback=None, **kws):
    """
    return a StepScan object, built from function arguments

    Arguments
    ---------
    filename (string): name for datafile ['scan.dat']
    type (string):  type of scan, for building positions ('linear',
                   'xafs', 'mesh', 'slew',  ...)  ['linear']
    scanmode (string or None): scan-specific mode info,
         typically 'step' or 'slew', as for step/continuous XAFS scans
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
    time_kw (int): time kweight for XAFS scan
    max_time (float): max dwelltime for XAFS scan
    is_relative (bool): use relative for XAFS scan (ONLY!)
    scandb (ScanDB instance or None): scandb instance

    Notes
    ------

    need to doc positions, inner, outer, regions, detectors, counters

    """
    scantype = type
    if positioners is not None:
        positioners = get_axesdict(positioners)
    if inner is not None:
        inner = get_axesdict(inner)
    if outer is not None:
        outer = get_axesdict(outer)
    # create different scan types
    if scantype in ('xafs', 'qxafs'):
        min_dtime = dwelltime
        if isinstance(min_dtime, np.ndarray):
            min_dtime = min(dtime)
        kwargs = dict(filename=filename, comments=comments, scandb=scandb,
                      energy_pv=energy_drive, read_pv=energy_read, e0=e0,
                      elem=elem, edge=edge)

        # print("Create XAFS Scan ", scanmode, scantype, kwargs, kws)
        if scantype == 'qxafs' or scanmode=='slew':
            scan = QXAFS_Scan(**kwargs)
            scan.detmode = 'roi'
        else:
            scan = XAFS_Scan(**kwargs)
            scan.detmode = 'scaler'
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
        scan.detmode = 'scaler'
        if scantype == 'linear' and positioners is not None:
            for pos in positioners:
                p = Positioner(pos['pvdrive'], label=pos['label'])
                p.array = np.linspace(pos['start'], pos['stop'], pos['npts'])
                scan.add_positioner(p)
                scan.add_counter(pos['pvread'], label=f"{pos['label']}_read")
        elif scantype == 'mesh':
            if inner is None and positioners is not None:
                inner = positioners
            p1 = Positioner(inner['pvdrive'], label=inner['label'])
            p1vals = np.linspace(inner['start'], inner['stop'], inner['npts'])
            p2 = None
            npts2 = 1
            if outer is not None:
                p2 = Positioner(outer['pvdrive'], label=outer['label'])
                p2vals = np.linspace(outer['start'], outer['stop'], outer['npts'])
                x2  = [[i]*npts1 for i in p2vals]
                p2.array = np.array(x2).flatten()

            x1 = outer['npts']*[p1vals]
            p1.array = np.array(x1).flatten()
            scan.add_positioner(p1)
            scan.add_counter(inner['pvread'], label="f{inner['label']}_read")
            if p2 is not None:
                scan.add_positioner(p2)
                scan.add_counter(outer['pvread'], label="f{outer['label']}_read")

        elif scantype == 'slew1d' or scantype == 'slew' and dimension == 1:
            scan = Slew_Scan1D(filename=filename, comments=comments)
            scan.inner = inner
            scan.detmode = 'roi'
            pos = Positioner(inner['pvdrive'], label=inner['label'])
            pos.array = np.linspace(inner['start'], inner['stop'], inner['npts'])
            scan.add_positioner(pos)

        elif scantype == 'slew':
            scan = Slew_Scan(filename=filename, comments=comments)
            scan.inner = inner
            scan.detmode = 'ndarray'
            scan.outer = outer
            pos = Positioner(outer['pvdrive'], label=outer['label'])
            pos.array = np.linspace(outer['start'], outer['stop'], outer['npts'])
            scan.add_positioner(pos)


    # data callback
    if data_callback is not None:
        scan.data_callback = data_callback
    # detectors, with ROIs and det mode
    # also, note this hack:
    # a scan may have specified a 'scaler' detector, but
    # if it is a slew scan or qxafs scan, this should really
    # be the corresponding MCS (Struck/USBCTR) detector
    scaler_shim = None
    if scan.detmode in ('roi', 'ndarray') and scandb is not None:
        scaler_pvname = '_no_scaler_available_'
        alldets = scandb.get_detectors()
        for d in detectors:
            if d['kind'] == 'scaler':
                scaler_pvname = d['prefix']
        for a in alldets:
            if scaler_pvname == json.loads(a.options).get('scaler', None):
                scaler_shim = {'kind': 'mcs', # a.kind,
                               'prefix': a.pvname,
                               'label': a.name,
                               'scaler': scaler_pvname}
    # ... or if this is a step scan, and an MCS (Struck/ USBCTR) is give,
    # replace it with the corresponding Scaler Detector:
    elif scan.detmode == 'scaler':
        newdets = []
        for d in detectors:
            if d.get('scaler', None) is not None:
                newdets.append({'kind': 'scaler', 'prefix': d['scaler'],
                                'nchan': d['nchan'], 'label': 'scaler'})
            else:
                newdets.append(d)
        detectors = newdets

    scan.rois = rois
    for dpars in detectors:
        dpars['rois'] = scan.rois
        dpars['mode'] = scan.detmode
        # dpars['scandb'] = scandb
        dkind = dpars['kind'].lower()
        if dkind == 'scaler' and scaler_shim is not None:
            dpars.update(scaler_shim)
        if 'label' not in dpars:
            dpars['label'] = dpars['kind']
        scan.add_detector(get_detector(**dpars))

    # extra counters (not-triggered things to count)
    if counters is not None:
        for label, pvname in counters:
            scan.add_counter(pvname, label=label)
    # other bits
    if extra_pvs is not None:
        scan.add_extra_pvs(extra_pvs)

    scan.rois = rois
    # scan.scandb = scandb
    # scan.mkernel = mkernel
    scan.scantype = scantype
    scan.filename = filename
    scan.scantime = scantime
    scan.nscans = nscans
    scan.pos_settle_time = pos_settle_time
    scan.det_settle_time = det_settle_time
    if scan.dwelltime is None:
        scan.set_dwelltime(dwelltime)
    return scan
