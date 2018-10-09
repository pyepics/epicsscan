"""
Quantum Xspress3 detector
"""
import time
from six.moves.configparser import ConfigParser

from epics import get_pv, caput, caget, Device, poll
from epics.devices.ad_mca import ADMCA

from .counter import Counter, DummyCounter, DeviceCounter
from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE
from .areadetector import ADFileMixin
from ..debugtime import debugtime

MAX_ROIS = 32
MAX_FRAMES = 16384

class Xspress3(Device, ADFileMixin):
    """Epics Xspress3.20 interface (with areaDetector2)"""

    det_attrs = ('NumImages', 'NumImages_RBV', 'Acquire', 'Acquire_RBV',
                 'ArrayCounter_RBV', 'ERASE', 'UPDATE', 'AcquireTime',
                 'TriggerMode', 'StatusMessage_RBV', 'DetectorState_RBV',
                 'CTRL_DTC')

    _nonpvs = ('_prefix', '_pvs', '_delim', 'filesaver', 'fileroot',
               'pathattrs', '_nonpvs', 'nmcas', 'mcas', '_chans')

    pathattrs = ('FilePath', 'FileTemplate', 'FileName', 'FileNumber',
                 'Capture', 'NumCapture', 'AutoIncrement', 'AutoSave')

    def __init__(self, prefix, nmcas=4, filesaver='HDF1:',
                 fileroot='/home/xspress3'):
        dt = debugtime()
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
            attrs.append("%s:C%iSCA:TSControl" % (prefix, imca))
            attrs.append("%s:C%iSCA:TSNumPoints" % (prefix, imca))
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

    def set_dwelltime(self, dwelltime):
        """set dwell time in seconds

        Arguments:
        dwelltime (float): dwelltime per frame in seconds.   No default
        """
        self.put('AcquireTime', dwelltime)

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

class Xspress3Counter(DeviceCounter):
    """Counters for Xspress3-1-10"""
    sca_labels = ('Clock', 'ResetTicks', 'ResetCounts',
                  'AllEvent', 'AllGood', 'Window1', 'Window2',
                  'Pileup', 'DTFactor')
    scas2save = (0, 1, 2, 3, 4, 7)
    scas2save = (0, 1, 3)
    scas2save = (0,)
    def __init__(self, prefix, outpvs=None, nmcas=4,
                 nrois=32, rois=None, nscas=1, use_unlabeled=False,
                 use_full=False, mode=None):

        # ROI #8 for DTFactor is a recent addition,
        # here we get ready to test if it is connected.
        self.sca8 = get_pv('%sC1SCA8:Value_RBV' % prefix)

        self.mode = mode
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
        if self.mode is None:
            self.mode == SCALER_MODE
        self.counters = []
        t0 = time.time()
        def add_counter(pv, lab):
            self.counters.append(Counter(pv, label=lab))

        if 'outputcounts' not in [r.lower() for r in self.rois]:
            self.rois.append('OutputCounts')

        # build list of current ROI names
        current_rois = {}
        for iroi in range(1, self.nrois+1):
            label = caget("%sMCA1ROI:%i:Name" % (prefix, iroi))
            if label is not None and len(label) > 0:
                current_rois[label.strip().lower()] = iroi
            else:
                break

        roi_format = '%sMCA%iROI:%i:Total_RBV'
        sca_format = '%sC%iSCA%i:Value_RBV'
        time.sleep(0.01)

        scas2save = (0, 8)
        has_sca8 = self.sca8.connected
        # print("XSPRESS3 has SCA8 : ", self.sca8, has_sca8)
        save_dtcorrect = False
        if not has_sca8:
            scas2save = (0, )
            save_dtcorrect = True

        if self.mode == ROI_MODE:
            save_dtcorrect = False
            roi_format = '%sMCA%iROI:%i:TSTotal'
            sca_format = '%sC%iSCA%i:TSArrayValue'
            if not has_sca8:
                scas2save = (0, 1, 3)

        for roiname in self.rois:
            lname = roiname.lower()
            if lname in current_rois:
                iroi = current_rois[lname]
                for imca in range(1, self.nmcas+1):
                    _pvname = roi_format % (prefix, imca, iroi)
                    _label  = "%s mca%i" % (roiname, imca)
                    add_counter(_pvname, _label)

        if save_dtcorrect:
            for imca in range(1, self.nmcas+1):
                _pvname = '%sC%i:DTFactor_RBV' % (prefix, imca)
                _label = 'DTFactor mca%i' % (imca)
                add_counter(_pvname, _label)

        if sca_format is not None:
            for isca in scas2save:
                for imca in range(1, self.nmcas+1):
                    _pvname = sca_format % (prefix, imca, isca)
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
                 filesaver='HDF1:', fileroot='/home/xspress3/data', **kws):

        self.nmcas = nmcas = int(nmcas)
        self._chans = range(1, nmcas+1)
        self.nrois = nrois = int(nrois)
        self.fileroot = fileroot
        self.filesaver = filesaver
        self.trigger_suffix = 'det1:Acquire'

        DetectorMixin.__init__(self, prefix, label=label)
        self._xsp3 = Xspress3(prefix, nmcas=nmcas,
                              fileroot=fileroot,
                              filesaver=filesaver)
        self.prefix = prefix
        self.dwelltime = None
        self.mode = mode
        self.dwelltime_pv = get_pv('%sdet1:AcquireTime' % prefix)
        self.extra_pvs = self.add_extrapvs_GSE()
        self.use_dtc = use_dtc  # KLUDGE DTC!!
        self.label = label
        if self.label is None:
            self.label = self.prefix
        self.arm_delay   = 0.1
        self.start_delay = 0.5
        self._counter = None
        self.counters = []
        self._repr_extra = self.repr_fmt % (nmcas, nrois,
                                            repr(use_dtc),
                                            repr(use_full))

        self._connect_args = dict(nmcas=nmcas, nrois=nrois, rois=rois,
                                  mode=mode, use_unlabeled=use_unlabeled,
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

    def config_filesaver(self, **kws):
        self._xsp3.config_filesaver(**kws)

    def save_calibration(self, filename, **kws):
        buff = self._xsp3.roi_calib_info()
        with open(filename, 'w') as fh:
            fh.write('\n'.join(buff))
            fh.write('\n')

    def pre_scan(self, mode=None, npulses=None, dwelltime=None, **kws):
        "run just prior to scan"
        dt = debugtime()

        if mode is not None:
            self.mode = mode

        # print("Xspress3 Prescan", self.mode, npulses, dwelltime, kws)

        self._xsp3.put('Acquire', 0, wait=True)
        poll(0.05, 0.5)
        self._xsp3.put('ERASE', 1)
        dt.add('xspress3: clear, erase')

        if self.mode == SCALER_MODE:
            self.ScalerMode(dwelltime=dwelltime, numframes=npulses)
        elif self.mode == ROI_MODE:
            self.ROIMode(dwelltime=dwelltime, numframes=npulses)
        elif self.mode == NDARRAY_MODE:
            self._xsp3.FileCaptureOff()
            time.sleep(0.01)
            self.NDArrayMode(dwelltime=dwelltime, numframes=npulses)

        dt.add('xspress3: set mode %s' % self.mode)
        if dwelltime is not None:
            self.dwelltime = dwelltime
        if self.dwelltime is not None:
            self.dwelltime_pv.put(self.dwelltime)

        if npulses is not None:
            self._xsp3.put('NumImages', npulses)

        dt.add('xspress3: set dtime, npulses')
        self.config_filesaver(number=1,
                              name='xsp3',
                              numcapture=npulses,
                              template="%s%s.%4.4d",
                              auto_increment=False,
                              auto_save=True)
        dt.add('xspress3: config filesaver')
        if self._counter is None:
            self.connect_counters()
        dt.add('xspress3: connect counters')
        self._counter._get_counters()

        self.counters = self._counter.counters
        self.extra_pvs = self._counter.extra_pvs
        dt.add('xspress3: done')
        # dt.show()

    def post_scan(self, **kws):
        "run just after scan"
        self.ContinuousMode()

    def ContinuousMode(self, dwelltime=0.25, numframes=16384):
        """set to continuous mode: use for live reading

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None or int):   number of frames to collect [16384]

    Notes:
        1. The Xspress3 doesn't support true continuous mode, so this sets
        the dwelltime to 0.25 and NumImages to 16384
           """
        self.ScalerMode(dwelltime=dwelltime, numframes=numframes)

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
        self._xsp3.put('ERASE', 1)
        if numframes is not None:
            self._xsp3.put('NumImages', numframes)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        for i in self._chans:
            self._xsp3.put('C%iSCA:TSControl' % i, 2) # 'Stop'
            self._xsp3.put('MCA%iROI:TSControl' % i, 2) # 'Stop'
            self._xsp3.put('MCA%iROI:BlockingCallbacks' % i, 1)
            self._xsp3.put('MCA%iROI:TSNumPoints' % i, MAX_FRAMES)
            self._xsp3.put('C%iSCA:TSNumPoints' % i, MAX_FRAMES)

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
        # print("Xspress3 ROI Mode ", dwelltime, numframes)

        self._xsp3.put('TriggerMode', 3) # External, TTL Veto
        for i in self._chans:
            self._xsp3.put('MCA%iROI:TSControl' % i, 2) # 'Stop'
            self._xsp3.put('C%iSCA:TSControl' % i, 2) # 'Stop'
        if numframes is None:
            numframes = MAX_FRAMES

        self._xsp3.put('NumImages', numframes)
        for i in self._chans:
            self._xsp3.put('MCA%iROI:TSNumPoints' % i, numframes)
            self._xsp3.put('C%iSCA:TSNumPoints' % i, numframes)
            self._xsp3.put('MCA%iROI:BlockingCallbacks' % i, 1)

        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
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
        # print("Xspress3 NDArrayMode ", dwelltime, numframes)
        self._xsp3.put('TriggerMode', 3)
        for i in self._chans:
            self._xsp3.put('MCA%iROI:TSControl' % i, 2) # 'Stop
            self._xsp3.put('C%iSCA:TSControl' % i, 2) # 'Stop

        if numframes is not None:
            self._xsp3.put('NumImages', numframes)

        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        self.mode = NDARRAY_MODE


    def set_dwelltime(self, dwelltime):
        """set dwell time in seconds

    Arguments:
        dwelltime (float): dwelltime per frame in seconds.   No default
        """
        self._xsp3.put('AcquireTime', dwelltime)

    def get_next_filename(self):
        return self._xsp3.getNextFileName()

    def get_numcaptured(self):
        return self._xsp3.getNumCaptured_RBV()

    def get_last_filename(self):
        return self._xsp3.getLastFileName()

    def finish_capture(self):
        self._xsp3.FileCaptureOff()
        time.sleep(0.1)

    def arm(self, mode=None, fnum=None, wait=True, numframes=None):
        t0 = time.time()
        if mode is not None:
            self.mode = mode
        if self._xsp3.DetectorState_RBV > 0:
            self._xsp3.put('Acquire', 0)
        self._xsp3.put('ERASE',   1) #, wait=True)

        if fnum is not None:
            self.fnum = fnum
            self._xsp3.setFileNumber(fnum)

        if numframes is not None:
            self._xsp3.put('NumImages', numframes)

        if self.mode == NDARRAY_MODE:
            self._xsp3.FileCaptureOn(verify_rbv=True)
        elif self.mode == SCALER_MODE:
            self._xsp3.FileCaptureOff()
        elif self.mode == ROI_MODE:
            self._xsp3.FileCaptureOff()
            for i in self._chans:
                self._xsp3.put('MCA%iROI:TSControl' % i, 0) # 'Erase/Start'
                self._xsp3.put('C%iSCA:TSControl' % i, 0)
        if self._xsp3.DetectorState_RBV > 0:
            self._xsp3.put('Acquire', 0, wait=True)
        if wait:
            time.sleep(self.arm_delay)
        # print("Xspress3 arm " , mode, fnum, numframes, time.time()-t0)

    def disarm(self, mode=None, wait=True):
        if mode is not None:
            self.mode = mode
        if wait:
            time.sleep(self.arm_delay)
        self._xsp3.FileCaptureOff()

    def start(self, mode=None, arm=False, wait=True):
        if mode is not None:
            self.mode = mode
        if arm:
            self.arm(mode=mode, wait=wait)
        self._xsp3.put('Acquire', 1, wait=False)
        time.sleep(0.05)
        if wait:
            time.sleep(self.start_delay)


    def stop(self, mode=None, disarm=False, wait=False):
        self._xsp3.put('Acquire', 0, wait=wait)
        if disarm:
            self.disarm()

    def save_arraydata(self, filename=None):
        pass

    def file_write_complete(self):
        return self._xsp3.FileWriteComplete()
