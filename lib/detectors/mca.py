"""
MCA and MultiMCA detectors
"""
import time
import numpy as np
from epics import PV, get_pv, caget, caput, poll, Device
from epics.devices import MCA,DXP
from .areadetector import ADFileMixin

from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE
from .counter import DeviceCounter
from .trigger import Trigger


class DXPCounter(DeviceCounter):
    """DXP Counter: saves all input and output count rates"""
    _fields = (('InputCountRate', 'ICR'),
               ('OutputCountRate', 'OCR'))
    def __init__(self, prefix, outpvs=None):
        DeviceCounter.__init__(self, prefix, rtype=None, outpvs=outpvs)
        prefix = self.prefix
        self.set_counters(self._fields)

class McaCounter(DeviceCounter):
    """Simple MCA Counter: saves all ROIs (total or net) and, optionally full spectra
    """
    invalid_device_msg = 'McaCounter must use an Epics MCA'
    def __init__(self, prefix, outpvs=None, nrois=32, rois=None,
                 use_net=False, use_unlabeled=False, use_full=False):
        nrois = int(nrois)
        DeviceCounter.__init__(self, prefix, rtype='mca', outpvs=outpvs)

        # use roilist to limit ROI to those listed:
        roilist = None
        if rois is not None and len(rois) > 0:
            roilist = [s.lower().strip() for s in rois]

        prefix = self.prefix
        fields = []
        for i in range(nrois):
            label = caget('%s.R%iNM' % (prefix, i))
            if roilist is not None and label.lower().strip() not in roilist:
                continue

            if len(label) > 0 or use_unlabeled:
                suff = '.R%i' % i
                if use_net:
                    suff = '.R%iN' % i
                fields.append((suff, label))
        if use_full:
            fields.append(('.VAL', 'mca spectra'))
        self.set_counters(fields)

class MultiMcaCounter(DeviceCounter):
    invalid_device_msg = 'McaCounter must use an Epics Multi-Element MCA'
    _dxp_fields = (('InputCountRate', 'ICR'),
                   ('OutputCountRate', 'OCR'))
    def __init__(self, prefix, outpvs=None, nmcas=4, nrois=32,
                 rois=None, search_all=False, use_net=False,
                 use_unlabeled=False, use_full=False):
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix
        nmcas, nrois = int(nmcas), int(nrois)
        DeviceCounter.__init__(self, prefix, rtype=None, outpvs=outpvs)

        # use roilist to limit ROI to those listed:
        roilist = []
        if rois is not None and len(rois) > 0:
            roilist = [s.lower().strip() for s in rois]

        nmcas, nrois = int(nmcas), int(nrois)
        DeviceCounter.__init__(self, prefix, rtype=None, outpvs=outpvs)
        prefix = self.prefix
        fields = []
        extras = []
        for imca in range(1, nmcas+1):
            mca = 'mca%i' % imca
            dxp = 'dxp%i' % imca
            extras.extend([
                ("%s.Calib_Offset" % mca, "%s%s.CALO" % (prefix, mca)),
                ("%s.Calib_Slope"  % mca, "%s%s.CALS" % (prefix, mca)),
                ("%s.Calib_Quad"   % mca, "%s%s.CALQ" % (prefix, mca)),
                ("%s.Peaking_Time" % dxp, "%s%s:PeakingTime" % (prefix, dxp))
                ])

        pvs = {}

        for imca in range(1, nmcas+1):
            mca = 'mca%i' % imca
            for i in range(nrois):
                for suf in ('NM', 'HI'):
                    pvname = '%s%s.R%i%s' % (prefix, mca, i, suf)
                    pvs[pvname] = get_pv(pvname)

        poll(0.001, 1.0)

        for i in range(nrois):
            should_break = False
            for imca in range(1, nmcas+1):
                mca = 'mca%i' % imca
                namepv = '%s%s.R%iNM' % (prefix, mca, i)
                rhipv = '%s%s.R%iHI' % (prefix, mca, i)
                roi = pvs[namepv].get()
                if roi is None or (roi.lower().strip() not in roilist):
                    continue
                roi_hi = pvs[rhipv].get()
                label = '%s %s'% (roi, mca)
                if (roi is not None and (len(roi) > 0 and roi_hi > 0) or
                        use_unlabeled):
                    suff = '%s.R%i' % (mca, i)
                    if use_net:
                        suff = '%s.R%iN' %  (mca, i)
                    fields.append((suff, label))
                if roi_hi < 1 and not search_all:
                    should_break = True
                    break
            if should_break:
                break

        for dsuff, dname in self._dxp_fields:
            for imca in range(1, nmcas +1):
                suff = 'dxp%i:%s' %  (imca, dsuff)
                label = '%s%i' % (dname, imca)
                fields.append((suff, label))

        if use_full:
            for imca in range(1, nmcas+1):
                mca = 'mca%i.VAL' % imca
                fields.append((mca, 'spectra%i' % imca))
        self.extra_pvs = extras
        self.set_counters(fields)


class McaDetector(DetectorMixin):
    trigger_suffix = 'EraseStart'
    repr_fmt = ', nrois=%i, use_net=%s, use_full=%s'
    def __init__(self, prefix, nrois=32, rois=None,
                 use_net=False, use_full=False, **kws):
        nrois = int(nrois)
        DetectorMixin.__init__(self, prefix, **kws)
        self.mca = MCA(prefix)
        self.dwelltime_pv = get_pv('%s.PRTM' % prefix)
        self.dwelltime = None
        self.trigger = Trigger("%sEraseStart" % prefix)
        self._counter = McaCounter(prefix, nrois=nrois, rois=rois,
                                   use_full=use_full, use_net=use_net)
        self.counters = self._counter.counters
        self._repr_extra = self.repr_fmt % (nrois, repr(use_net), repr(use_full))

    def pre_scan(self, **kws):
        if self.dwelltime is not None and isinstance(self.dwelltime_pv, PV):
            self.dwelltime_pv.put(self.dwelltime)

class MultiXMAP(Device, ADFileMixin):
    """
    multi-Channel XMAP DXP device
    """

    attrs = ['PresetReal','Dwell','Acquiring', 'EraseStart','StopAll',
             'PresetMode', 'PixelsPerBuffer_RBV', 'NextPixel',
             'PixelsPerRun', 'Apply', 'AutoApply', 'CollectMode',
             'SyncCount', 'BufferSize_RBV']

    pathattrs = ('FilePath', 'FileTemplate', 'FileWriteMode',
                 'FileName', 'FileNumber', 'FullFileName_RBV',
                 'Capture',  'NumCapture', 'WriteFile_RBV',
                 'AutoSave', 'EnableCallbacks',  'ArraySize0_RBV',
                 'FileTemplate_RBV', 'FileName_RBV', 'AutoIncrement')

    _nonpvs  = ('_prefix', '_pvs', '_delim', 'filesaver', 'fileroot',
                'pathattrs', '_nonpvs', 'nmca', 'dxps', 'mcas')

    def __init__(self, prefix, filesaver='netCDF1:',nmca=4,
                 fileroot='T:/xas_user'):
        self.filesaver = filesaver
        self.fileroot = fileroot
        self._prefix = prefix
        self.nmca   = nmca

        self.dxps = [DXP(prefix, mca=i+1) for i in range(nmca)]
        self.mcas = [MCA(prefix, mca=i+1) for i in range(nmca)]

        Device.__init__(self, prefix, attrs=self.attrs,
                              delim='', mutable=True)
        for p in self.pathattrs:
            pvname = '%s%s%s' % (prefix, filesaver, p)
            self.add_pv(pvname, attr=p)

    def get_calib(self):
        return [m.get_calib() for m in self.mcas]

    def get_rois(self):
        return [m.get_rois() for m in self.mcas]

    def roi_calib_info(self):
        buff = ['[rois]']
        add = buff.append
        rois = self.get_rois()
        for iroi in range(len(rois[0])):
            name = rois[0][iroi].NM
            s = [[rois[m][iroi].LO, rois[m][iroi].HI] for m in range(self.nmca)]
            dat = repr(s).replace('],', '').replace('[', '').replace(']','').replace(',','')
            add("ROI%2.2i = %s | %s" % (iroi, name, dat))

        caldat = np.array(self.get_calib())
        add('[calibration]')
        add("OFFSET = %s " % (' '.join(["%.7g" % i for i in caldat[:, 0]])))
        add("SLOPE  = %s " % (' '.join(["%.7g" % i for i in caldat[:, 1]])))
        add("QUAD   = %s " % (' '.join(["%.7g" % i for i in caldat[:, 2]])))

        add('[dxp]')
        for a in self.dxps[0]._attrs:
            vals = [str(dxp.get(a, as_string=True)).replace(' ','_') for dxp in self.dxps]
            add("%s = %s" % (a, ' '.join(vals)))
        return buff

    def restore_rois(self, roifile):
        """restore ROI setting from ROI.dat file"""
        cp =  ConfigParser()
        cp.read(roifile)
        rois = []
        self.mcas[0].clear_rois()
        prefix = self.mcas[0]._prefix
        if prefix.endswith('.'):
            prefix = prefix[:-1]
        iroi = 0
        for a in cp.options('rois'):
            if a.lower().startswith('roi'):
                name, dat = cp.get('rois', a).split('|')
                lims = [int(i) for i in dat.split()]
                lo, hi = lims[0], lims[1]
                roi = ROI(prefix=prefix, roi=iroi)
                roi.LO = lo
                roi.HI = hi
                roi.NM = name.strip()
                rois.append(roi)
                iroi += 1

        poll(0.050, 1.0)
        self.mcas[0].set_rois(rois)
        cal0 = self.mcas[0].get_calib()
        for mca in self.mcas[1:]:
            mca.set_rois(rois, calib=cal0)


    def start(self):
        "Start Struck"
        self.EraseStart = 1

        if self.Acquiring == 0:
            poll()
            self.EraseStart = 1
        return self.EraseStart

    def stop(self):
        "Stop Struck Collection"
        self.StopAll = 1
        return self.StopAll

    def next_pixel(self):
        "Advance to Next Pixel:"
        self.NextPixel = 1
        return self.NextPixel

    def finish_pixels(self, timeout=2):
        "Advance to Next Pixel until CurrentPixel == PixelsPerRun"
        pprun = self.PixelsPerRun
        cur   = self.dxps[0].get('CurrentPixel')
        t0 = time.time()
        while cur < pprun and time.time()-t0 < timeout:
            time.sleep(0.1)
            pprun = self.PixelsPerRun
            cur   = self.dxps[0].get('CurrentPixel')
        ok = cur >= pprun
        if not ok:
            print('XMAP needs to finish pixels ', cur, ' / ' , pprun)
            for i in range(pprun-cur):
                self.next_pixel()
                time.sleep(0.10)
            self.FileCaptureOff()
        return ok, pprun-cur

    def getCurrentPixel(self):
        return self.dxps[0].get('CurrentPixel')

    def readmca(self,n=1):
        "Read a Struck MCA"
        return self.get('mca%i' % n)

    def SCAMode(self):
        "put XMAP in SCA mapping mode"
        self.CollectMode = 2

    def SpectraMode(self):
        "put XMAP in MCA spectra mode"
        self.stop()
        self.CollectMode = 0
        self.PresetMode = 0
        # wait until BufferSize is ready
        buffsize = -1
        t0 = time.time()
        while time.time() - t0 < 5:
            self.CollectMode = 0
            time.sleep(0.05)
            if self.BufferSize_RBV < 16384:
                break

    def MCAMode(self, filename=None, filenumber=None, npulses=11):
        "put XMAP in MCA mapping mode"
        self.AutoApply = 1
        self.stop()
        self.PresetMode = 0
        self.setFileWriteMode(2)
        if npulses < 2:
            npulses = 2
        self.CollectMode = 1
        self.PixelsPerRun = npulses

        # First, make sure ArraySize0_RBV for the netcdf plugin
        # is the correct value
        self.FileCaptureOff()
        self.start()
        f_size = -1
        t0 = time.time()
        while (f_size < 16384) and time.time()-t0 < 10:
            for i in range(5):
                time.sleep(0.1)
                self.NextPixel = 1
                f_size = self.fileGet('ArraySize0_RBV')
                if f_size > 16384:
                    break
        #
        self.PixelsPerRun = npulses
        self.SyncCount =  1

        self.setFileNumber(filenumber)
        if filename is not None:
            self.setFileName(filename)

        # wait until BufferSize is ready
        self.Apply = 1
        self.CollectMode = 1
        self.PixelsPerRun = npulses
        time.sleep(0.50)
        t0 = time.time()
        while time.time() - t0 < 10:
            time.sleep(0.25)
            if self.BufferSize_RBV > 16384:
                break

        # set expected number of buffers to put in a single file
        ppbuff = self.PixelsPerBuffer_RBV
        time.sleep(0.25)
        if ppbuff is None:
            ppbuff = 124
        self.setFileNumCapture(1 + (npulses-1)/ppbuff)
        f_buffsize = -1
        t0 = time.time()
        while time.time()- t0 < 5:
            time.sleep(0.1)
            f_buffsize = self.fileGet('ArraySize0_RBV')
            if self.BufferSize_RBV == f_buffsize:
                break

        time.sleep(0.5)
        return

class MultiMcaDetector(DetectorMixin):
    trigger_suffix = 'EraseStart'
    collect_mode = 'CollectMode'
    repr_fmt = ', nmcas=%i, nrois=%i, use_net=%s, use_full=%s'

    def __init__(self, prefix, label=None, nmcas=4, nrois=32, rois=None,
                 mode='scalar', search_all=False, use_net=False,
                 use_unlabeled=False, use_full=False, **kws):
        DetectorMixin.__init__(self, prefix, label=label)
        nmcas, nrois = int(nmcas), int(nrois)
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix
        self.prefix = prefix
        self.dwelltime_pv = get_pv('%sPresetReal' % prefix)
        self.trigger = Trigger("%sEraseStart" % prefix)
        self.dwelltime = None
        self.extra_pvs = None
        self._counter = None
        self.mode = mode
        self._med = MultiXMAP(prefix=prefix)
        self._connect_args = dict(nmcas=nmcas, nrois=nrois, rois=rois,
                                  search_all=search_all, use_net=use_net,
                                  use_unlabeled=use_unlabeled,
                                  use_full=use_full)

        self._repr_extra = self.repr_fmt % (nmcas, nrois,
                                            repr(use_net), repr(use_full))

    def connect_counters(self):
        self._counter = MultiMcaCounter(self.prefix, **self._connect_args)
        self.counters = self._counter.counters
        self.extra_pvs = self._counter.extra_pvs

    def config_filesaver(self, **kws):
        self._med.config_filesaver(**kws)

    def save_calibration(self, filename, **kws):
        buff = self._med.roi_calib_info()
        with open(filename, 'w') as fh:
            fh.write('\n'.join(buff))
            fh.write('\n')

    def post_scan(self, **kws):
        "run just after scan"
        self.ContinuousMode()

    def ContinuousMode(self, dwelltime=0.0, numframes=0):
        """set to continuous mode: use for live reading
        """
        self.mode = SCALER_MODE
        self._med.SpectraMode()

    def ScalerMode(self, dwelltime=None, numframes=1):
        """ set to scaler mode: ready for step scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [1.0]
        numframes (None or int):   number of frames to collect [1]

    Notes:
        1. numframes is ignored
        """
        self.mode = SCALER_MODE
        self._med.SpectraMode()
        self._med.PresetMode = 1 # real time
        self._med.put('PresetReal', dwelltime)

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
        print("MulitXMAP ROI Mode unsupported, using NDArrayMode")
        self.NDArrayMode(dwelltime=dwelltime, numframes=numframes)

    def NDArrayMode(self, dwelltime=None, numframes=None):
        """ set to array mode: ready for slew scanning

        Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None int):   number of frames to collect [16384]

        """

        self.mode = NDARRAY_MODE
        self._med.MCAMode(npulses=numframes)

    def set_dwelltime(self, dwelltime):
        """set dwell time in seconds

    Arguments:
        dwelltime (float): dwelltime per frame in seconds.   No default
        """
        self._med.put('PresetMode', 1)
        self._med.put('PresetReal', dwelltime)

    def get_next_filename(self):
        return self._med.getNextFileName()

    def arm(self, mode=None, fnum=None, wait=False, numframes=None):
        if mode is not None:
            self.mode = mode
        self._med.put('StopAll',  1, wait=True)
        self._med.put('EraseAll', 1, wait=True)
        if fnum is not None:
            self.fnum = fnum
            self._med.setFileNumber(fnum)

        if numframes is not None:
            self._med.put('PixelsPerRun', numframes)

        if self.mode == NDARRAY_MODE:
            self._med.FileCaptureOn()
            time.sleep(0.05)
        elif self.mode == SCALER_MODE:
            self._med.FileCaptureOff()
        elif self.mode == ROI_MODE:
            self._med.FileCaptureOff()

    def disarm(self, mode=None, wait=False):
        if mode is not None:
            self.mode = mode
        time.sleep(.05)
        self._med.FileCaptureOff()

    def start(self, mode=None, arm=False, wait=False):
        if mode is not None:
            self.mode = mode
        if arm:
            self.arm()
        self._med.put('EraseStart', 1, wait=wait)

    def stop(self, mode=None, disarm=False, wait=False):
        self._med.put('StopAll', 0, wait=wait)
        if disarm:
            self.disarm()

    def save_arraydata(self, filename=None):
        pass

    def file_write_complete(self):
        return self._med.FileWriteComplete()

    def get_numcaptured(self):
        return self._med.getCurrentPixel()

    def finish_capture(self):
        self._med.finish_pixels()

    def pre_scan(self, mode=None, npulses=None, dwelltime=None, **kws):
        "run just prior to scan"
        if mode is not None:
            self.mode = mode

        caput("%sReadBaselineHistograms.SCAN" % (self.prefix), 0)
        caput("%sReadTraces.SCAN" % (self.prefix), 0)
        caput("%sReadLLParams.SCAN" % (self.prefix), 0)
        caput("%sReadAll.SCAN"   % (self.prefix), 9)
        caput("%sStatusAll.SCAN" % (self.prefix), 9)


        if self.mode == SCALER_MODE:
            self.ScalerMode(dwelltime=dwelltime, numframes=npulses)
        elif self.mode == ROI_MODE:
            self.ROIMode(dwelltime=dwelltime, numframes=npulses)
        elif self.mode == NDARRAY_MODE:
            self._med.FileCaptureOff()
            time.sleep(0.01)
            self.NDArrayMode(dwelltime=dwelltime, numframes=npulses)

        if dwelltime is not None:
            self.dwelltime = dwelltime

        if self.dwelltime is not None:
            self.dwelltime_pv.put(self.dwelltime)

        if npulses is not None:
            self._med.put('PixelsPerRun', npulses)

        self.config_filesaver(number=1,
                              name='xmap',
                              template="%s%s.%4.4d",
                              auto_increment=False,
                              auto_save=True)

        if self._counter is None:
            self.connect_counters()

        self.counters = self._counter.counters
        self.extra_pvs = self._counter.extra_pvs
