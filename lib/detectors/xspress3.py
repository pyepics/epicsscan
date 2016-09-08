"""
Quantum Xspress3 detector
"""
import time
from ConfigParser import ConfigParser

from epics import get_pv, caput, caget, Device, poll
from epics.devices.ad_mca import ADMCA

from .trigger import Trigger
from .counter import Counter, DeviceCounter
from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE
from .areadetector import ADFileMixin
from ..debugtime import debugtime

MAX_ROIS = 32


class Xspress3(Device, ADFileMixin):
    """Epics Xspress3.20 interface (with areaDetector2)"""

    det_attrs = ('NumImages', 'NumImages_RBV', 'Acquire', 'Acquire_RBV',
                 'ArrayCounter_RBV', 'ERASE', 'UPDATE', 'AcquireTime',
                 'TriggerMode', 'StatusMessage_RBV', 'DetectorState_RBV',
                 'CTRL_DTC')

    _nonpvs = ('_prefix', '_pvs', '_delim', 'filesaver', 'fileroot',
               'pathattrs', '_nonpvs', 'nmcas', 'mcas', '_chans')

    pathattrs = ('FilePath', 'FileTemplate', 'FileName', 'FileNumber',
                 'Capture', 'NumCapture')

    def __init__(self, prefix, nmcas=4, filesaver='HDF1:',
                 fileroot='/home/xspress3/cars5/Data'):
        dt = debugtime()
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix
        self.nmcas = nmcas
        attrs = []
        attrs.extend(['%s%s' % (filesaver, p) for p in self.pathattrs])

        self.filesaver = filesaver
        self.fileroot = fileroot
        self._prefix = prefix
        self.mcas = []
        for i in range(nmcas):
            imca = i+1
            dprefix = "%sdet1:" % prefix
            rprefix = "%sMCA%iROI" % (prefix, imca)
            data_pv = "%sMCA%i:ArrayData" % (prefix, imca)
            mca = ADMCA(dprefix, data_pv=data_pv, roi_prefix=rprefix)
            self.mcas.append(mca)
            attrs.append("%s:MCA%iROI:TSControl" % (prefix, imca))
            attrs.append("%s:MCA%iROI:TSNumPoints" % (prefix, imca))
        Device.__init__(self, prefix, attrs=attrs, delim='')
        for attr in self.det_attrs:
            self.add_pv("%sdet1:%s" % (prefix, attr), attr)
        for i in range(nmcas):
            imca = i+1
            for j in range(8):
                isca = j+1
                attr = "C%iSCA%i"% (imca, isca)
                self.add_pv("%s%s:Value_RBV" % (prefix, attr), attr)
        poll(0.003, 0.25)

    def roi_calib_info(self):
        buff = ['[rois]']
        add = buff.append
        rois = self.mcas[0].get_rois()
        for iroi, roi in enumerate(rois):
            name = roi.Name
            hi = roi.MinX + roi.SizeX
            if len(name.strip()) > 0 and hi > 0:
                dbuff = []
                for m in range(self.nmcas):
                    dbuff.extend([roi.MinX, roi.MinX+roi.SizeX])
                dbuff = ' '.join([str(i) for i in dbuff])
                add("ROI%2.2i = %s | %s" % (iroi, name, dbuff))

        add('[calibration]')
        add("OFFSET = %s " % (' '.join(["0.000 "] * self.nmcas)))
        add("SLOPE  = %s " % (' '.join(["0.010 "] * self.nmcas)))
        add("QUAD   = %s " % (' '.join(["0.000 "] * self.nmcas)))
        add('[dxp]')
        return buff

    def restore_rois(self, roifile):
        """restore ROI setting from ROI.dat file"""
        cp = ConfigParser()
        cp.read(roifile)
        roidat = []
        for a in cp.options('rois'):
            if a.lower().startswith('roi'):
                name, dat = cp.get('rois', a).split('|')
                lims = [int(i) for i in dat.split()]
                lo, hi = lims[0], lims[1]
                roidat.append((name.strip(), lo, hi))

        for mca in self.mcas:
            mca.set_rois(roidat)


class Xspress3Trigger(Trigger):
    """Triggers for Xspress3, AD2 version
    where Start does an EraseStart for the MCA arrays
    """
    def __init__(self, prefix, value=1, **kws):
        Trigger.__init__(self, prefix, value=value, **kws)
        self._start = get_pv(prefix + 'det1:Acquire')
        self._erase = get_pv(prefix + 'det1:ERASE')
        self.prefix = prefix
        self._val = value
        self.done = False
        self._t0 = 0
        self.runtime = -1

    def __repr__(self):
        return "Xspress3Trigger(%s, value=%i)" % (self.prefix, self._val)

    def __onComplete(self, pvname=None, **kws):
        self.done = True
        self.runtime = time.time() - self._t0

    def start(self, value=1):
        """Start Xspress3"""
        self.done = False
        runtime = -1
        self._t0 = time.time()
        self._start.put(value, callback=self.__onComplete)
        poll(0.01, 0.5)

    def abort(self, value=0):
        self._start.put(0, wait=False)
        poll(0.050, 0.5)


class Xspress3Counter(DeviceCounter):
    """Counters for Xspress3-1-10 (weird ROIs / areaDetector hybrid)
    """
    sca_labels = ('', 'Clock', 'ResetTicks', 'ResetCounts',
                  'AllEvent', 'AllGood', 'Window1', 'Window2', 'Pileup')
    scas2save = (1, 2, 3, 4, 5, 8)
    scas2save = (1, 2, 4)
    def __init__(self, prefix, outpvs=None, nmcas=4,
                 nrois=32, rois=None, nscas=1, use_unlabeled=False,
                 use_full=False):

        if not prefix.endswith(':'):
            prefix = "%s:" % prefix

        self.nmcas, self.nrois = int(nmcas), int(nrois)
        self.nscas = int(nscas)
        self.use_full = use_full
        self.use_unlabeled = False
        DeviceCounter.__init__(self, prefix, rtype=None, outpvs=outpvs)

        prefix = self.prefix
        self._fields = []
        self.extra_pvs = []
        pvs = self._pvs = {}

        time.sleep(0.01)
        # use roilist to set ROI to those listed:
        if rois is None:
            rois = ['']
        self.rois = [r.strip() for r in rois]

    def _get_counters(self):
        prefix = self.prefix
        self.counters = []
        t0 = time.time()
        def add_counter(pv, lab):
            self.counters.append(Counter(pv, label=lab))

        try:
            nmax = len(caget('%sMCA1:ArrayData' % prefix))
        except ValueError:
            nmax = 2048

        if 'outputcounts' not in [r.lower() for r in self.rois]:
            self.rois.append('OutputCounts')

        # build list of current ROI names
        current_rois = {}
        for iroi in range(1, self.nrois+1):
            label = caget("%sMCA1ROI:%i:Name" % (prefix, iroi)).strip()
            if len(label) > 0:
                current_rois[label.lower()] = iroi
            else:
                break

        for roiname in self.rois:
            lname = roiname.lower()
            if lname in current_rois:
                iroi = current_rois[lname]
                for imca in range(1, self.nmcas+1):
                    _pvname = '%sMCA%iROI:%i:Total_RBV' % (prefix, imca, iroi)
                    _label  = "%s mca%i" % (roiname, imca)
                    add_counter(_pvname, _label)

        for imca in range(1, self.nmcas+1):
            _pvname = '%sC%i:DTFactor_RBV' % (prefix, imca)
            _label = 'DTFactor mca%i' % (imca)
            add_counter(_pvname, _label)

        for isca in self.scas2save:
            for imca in range(1, self.nmcas+1):
                _pvname = '%sC%iSCA%i:Value_RBV' % (prefix, imca, isca)
                _label = '%s mca%i' % (self.sca_labels[isca], imca)
                add_counter(_pvname, _label)


        if self.use_full:
            for imca in range(1, self.nmcas+1):
                pv = '%sMCA%i.ArrayData' % (prefix, imca)
                add_counter(pv, 'spectra%i' % imca)

class Xspress3Detector(DetectorMixin):
    """
    Xspress 3 MultiMCA detector, 3.2
    """
    repr_fmt = 'nmcas=%i, nrois=%i, use_dtc=%s, use_full=%s'

    def __init__(self, prefix, label=None, nmcas=4, mode='scaler',
                 rois=None, nrois=32, pixeltime=0.1, use_dtc=False,
                 use=True, use_unlabeled=False, use_full=False,
                 filesaver='HDF1:', fileroot=None, **kws):

        dt = debugtime()
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix

        self.nmcas = nmcas = int(nmcas)
        self._chans = range(1, nmcas+1)
        self.nrois = nrois = int(nrois)
        DetectorMixin.__init__(self, prefix, label=label)
        self._xsp3 = Xspress3(prefix, nmcas=nmcas,
                              fileroot=fileroot,
                              filesaver=filesaver)
        self.prefix = prefix
        self.dwelltime = None
        self.mode = mode
        self.dwelltime_pv = get_pv('%sdet1:AcquireTime' % prefix)
        self.trigger = Xspress3Trigger(prefix)
        self.extra_pvs = self.add_extrapvs_GSE()
        self.use_dtc = use_dtc  # KLUDGE DTC!!
        self.label = label
        if self.label is None:
            self.label = self.prefix

        self._counter = None
        self.counters = []
        self._repr_extra = self.repr_fmt % (nmcas, nrois,
                                            repr(use_dtc),
                                            repr(use_full))


        self._connect_args = dict(nmcas=nmcas, nrois=nrois, rois=rois,
                                  use_unlabeled=use_unlabeled,
                                  use_full=use_full)
        self.connect_counters()

    def __repr__(self):
        return "%s('%s', label='%s', mode='%s', %s)" % (self.__class__.__name__,
                                                        self.prefix, self.label,
                                                        self.mode, self._repr_extra)

    def add_extrapvs_GSE(self):
        e = [('mca1 tau(nsec)', '13IDE:userTran3.A'),
             ('mca2 tau(nsec)', '13IDE:userTran3.B'),
             ('mca3 tau(nsec)', '13IDE:userTran3.C'),
             ('mca4 tau(nsec)', '13IDE:userTran3.D')]
        return e

    def connect_counters(self):
        self._counter = Xspress3Counter(self.prefix, **self._connect_args)
        self.counters = self._counter.counters
        self.extra_pvs = self._counter.extra_pvs

    def pre_scan(self, scan=None, **kws):
        """ """
        # print "Xspress3 pre_scan  ", self.mode
        if self.mode == SCALER_MODE:
            self.ScalerMode()
        elif self.mode == ROI_MODE:
            self.ROIMode()
        elif self.mode == NDARRAY_MODE:
            self.NDArrayMode()

        t0 = time.time()
        self._xsp3.put('Acquire', 0)
        poll(0.05, 0.5)

        if self._counter is None:
            self.connect_counters()

        self._counter._get_counters()
        self.counters = self._counter.counters
        self.extra_pvs = self._counter.extra_pvs

        dtime = 0.5
        if self.dwelltime is not None:
            dtime = self.dwelltime
        self.dwelltime_pv.put(dtime)

        # for i in range(1, self.nmcas+1):
        #     card = "%sC%i" % (self.prefix, i)
        #     caput("%s_PluginControlValExtraROI" % (card), 0)
        #     caput("%s_PluginControlVal"         % (card), 1)
        #    poll(0.005, 0.5)
        self._xsp3.put('ERASE', 1)

        self._xsp3.put('TriggerMode', 1)
        self._xsp3.put('NumImages', 1)
        self._xsp3.put('CTRL_DTC', self.use_dtc)
        poll(0.01, 0.5)
        self._xsp3.put('Acquire', 0, wait=True)
        poll(0.01, 0.5)
        self._xsp3.put('ERASE', 1, wait=True)
        poll(0.01, 0.5)


    def ContinuousMode(self, dwelltime=0.25, numframes=16384):
        """set to continuous mode: use for live reading

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None or int):   number of frames to collect [16384]

    Notes:
        1. The Xspress3 doesn't support true continuous mode, so this sets
        the dwelltime to 0.25 and NumImages to 16384
           """
        if numframes is not None:
            self._xsp3.put('NumImages', numframes)
        if dwelltime is not None:
            self._xsp3.SetDwelltime(dwelltime)
        self.mode = SCALER_MODE


    def ScalerMode(self, dwelltime=None, numframes=1):
        """ set to scaler mode: ready for step scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [1.0]
        numframes (None or int):   number of frames to collect [1]

    Notes:
        1. numframes should be 1, unless you know what you're doing.
        """
        # print "Xspress3 ScalerMode"
        self._xsp3.put('TriggerMode', 1) # Internal
        if numframes is not None:
            self._xsp3.put('NumImages', numframes)
        if dwelltime is not None:
            self.SetDwelltime(dwelltime)
        for i in self._chans:
            self._xsp3.put('MCA%iROI:TSControl' % i, 2) # 'Stop'
            self._xsp3.put('MCA%iROI:BlockingCallbacks' % i, 1)
        self.mode = SCALER_MODE

    def ROIMode(self, dwelltime=None, numframes=None):
        """ set to ROI mode: ready for slew scanning with ROI saving

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None int):   number of frames to collect [16384]
        sis_trigger_width (None or float):   output trigger width (in seconds)
             for optional SIS 3820 [None]

    Notes:
        1. this arms detector so that it is eady for slew scanning.
        2. setting dwelltime or numframes to None is discouraged,
           as it can lead to inconsistent data arrays.
        """
        self._xsp3.put('TriggerMode', 3) # External, TTL Veto
        for i in self._chans:
            self._xsp3.put('MCA%iROI:TSControl' % i, 2) # 'Stop'
        if numframes is not None:
            self._xsp3.put('NumImages', numframes)
            for i in self._chans:
                self._xsp3.put('MCA%iROI:TSNumPoints' % i, numframes)
                self._xsp3.put('MCA%iROI:BlockingCallbacks' % i, 1)

        if dwelltime is not None:
            self.SetDwelltime(dwelltime)
        self.mode = ROI_MODE


    def NDArrayMode(self, dwelltime=None, numframes=None):
        """ set to array mode: ready for slew scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None int):   number of frames to collect [16384]

    Notes:
        1. this arms detector and optional SIS8320 so that it is also
           ready for slew scanning.
        2. setting dwelltime or numframes to None is discouraged,
           as it can lead to inconsistent data arrays.
        """
        self._xsp3.put('TriggerMode', 3)
        self._xsp3.put('ERASE', 1)
        for i in self._chans:
            self._xsp3.put('MCA%iROI:TSControl' % i, 2) # 'Stop

        if numframes is not None:
            self._xsp3.put('NumAcquire', numframes)
        if dwelltime is not None:
            self.SetDwelltime(dwelltime)
        self.mode = NDARRAY_MODE

    def SetDwelltime(self, dwelltime):
        """set dwell time in seconds

    Arguments:
        dwelltime (float): dwelltime per frame in seconds.   No default
        """
        self._xsp3.put('AcquireTime', dwelltime)

    def Arm(self, mode=None, wait=False):
        if mode is not None:
            self.mode = mode
        time.sleep(.001)
        if self._mode == NDARRAY_MODE:
            self._xsp3.FileCaptureOn()
        elif self._mode == SCALER_MODE:
            self._xsp3.FileCaptureOff()
        elif self._mode == ROI_MODE:
            self._xsp3.FileCaptureOff()
            for i in self._chans:
                self._xsp3.put('MCA%iROI:TSControl' % i, 0) # 'Erase/Start'


    def DisArm(self, mode=None, wait=False):
        if mode is not None:
            self.mode = mode
        time.sleep(.001)
        self._xsp3.FileCaptureOff()

    def Start(self, mode=None, arm=False, wait=False):
        if mode is not None:
            self.mode = mode
        if arm:
            self.Arm()
        self._xsp3.put('Acquire', 1, wait=wait)

    def Stop(self, mode=None, disarm=False, wait=False):
        self._xsp3.put('Acquire', 0, wait=wait)
        if disarm:
            self.DisArm()
        self._xsp3.FileCaptureOff()

    def SaveArrayData(self, filename=None):
        pass
