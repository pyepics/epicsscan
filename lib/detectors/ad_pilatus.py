"""
Quantum Xspress3 detector
"""
import time
import glob
import os
from epics import get_pv, caput, caget, Device, poll, PV

from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE
from .counter import Counter
from .areadetector import AreaDetector
from ..debugtime import debugtime

class AD_Pilatus(AreaDetector):
    """
    Pilatus areaDetector

    Pilatus 100K
    """
    def __init__(self, prefix, label='xrd', mode='scaler',
                 readout_time = 0.003,
                 filesaver='HDF1:', fileroot='/cars5/Data/xas_user', **kws):

        AreaDetector.__init__(self, prefix, label=label, mode=mode,
                             filesaver=filesaver, fileroot=fileroot, **kws)
        self.mode = mode
        self.arm_delay    = 0.25
        self.start_delay  = 0.10
        self.readout_time = 0.01
        self.cam.ShutterMode =  0    # None
        self.dwelltime = None
        self.ad.FileCaptureOff()

    def custom_pre_scan(self, row=0, dwelltime=None, **kws):
        fpath, xpath = os.path.split(self.ad.getFilePath())
        fpath, xpath = os.path.split(fpath)
        fpath = os.path.join(fpath, 'work')

        self.config_filesaver(template="%s%s_%4.4d.h5")
        for iroi in range(1, 5):
            pref = '%s%d:' % (self.roistat._prefix, iroi)
            if caget(pref + 'Use') == 1:
                label = caget(pref + 'Name', as_string=True).strip()
                if len(label) > 0:
                    pvname = pref + 'Total_RBV'
                    self.counters.append(Counter(pvname, label=label))
        self.set_dwelltime(self.dwelltime)
        self.cam.put('FilePath', fpath)
        self.cam.put('FileNumber', 1)
        self.cam.put('FileName', 'pil')
        self.cam.put('AutoIncrement', 1)
        self.cam.put('FileTemplate', '%s%s_%4.4d_.tif')

    def open_shutter(self):
        pass

    def close_shutter(self):
        pass

    def AcquireOffset(self, timeout=10, open_shutter=True):
        pass

    def set_dwelltime(self, dwelltime=None):
        """set dwell time in seconds
        """
        if dwelltime is None and self.dwelltime is not None:
            dwelltime = self.dwelltime
        if dwelltime is None:
            return

        self.dwelltime = dwelltime
        self.cam.put('AcquireTime',   dwelltime-self.readout_time)
        self.cam.put('AcquirePeriod', dwelltime)

    def ContinuousMode(self, dwelltime=None, numframes=300200100):
        self.ScalerMode(dwelltime=dwelltime)

    def ScalerMode(self, dwelltime=None, numframes=1):
        """ set to scaler mode: ready for step scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [1.0]
        numframes (None or int):   number of frames to collect [1]

    Notes:
        1. numframes should be 1, unless you know what you're doing.
        2. Files will be saved by the file saver
        """
        try:
            self.cam.put('TriggerMode', 'Internal') # Internal
        except ValueError:
            pass
        if numframes is not None:
            self.cam.put('NumImages', numframes)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        self.mode = SCALER_MODE
        self.ad.setFileNumCapture(1)

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
        self.cam.put('TriggerMode', 'Mult. Trigger')
        self.cam.put('ImageMode', 'Multiple')
        self.roistat.stop()

        if numframes is not None:
            self.cam.put('NumImages', numframes)
            self.ad.setFileNumCapture(numframes)

        if dwelltime is not None:
            dwelltime = self.dwelltime
        self.set_dwelltime(dwelltime)
        self.mode = NDARRAY_MODE
