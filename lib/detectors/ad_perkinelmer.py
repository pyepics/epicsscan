"""
Quantum Xspress3 detector
"""
import time
from epics import get_pv, caput, caget, Device, poll

from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE
from .areadetector import AreaDetector
from ..debugtime import debugtime

class AD_PerkinElmer(AreaDetector):
    """
    Perkin-Elmer areaDetector
    
    a pretty generic areaDetector, but overwriting 
    pre_scan() to collect offset frames
    """
    def __init__(self, prefix, label='xrd', mode='scaler',
                 filesaver='netCDF1:', fileroot='T:/xas_user', **kws):

        AreaDetector.__init__(self, prefix, label=label, mode=mode,
                             filesaver=filesaver, fileroot=fileroot, **kws)
        self.cam.PV('PEAcquireOffset')
        self.cam.PV('PEAcquireOffsetFrames')
        self.cam.PV('PENumOffsetFrames')
        self.mode = mode
        self.arm_delay = 0.25
        self.start_delay = 0.50

    def custom_pre_scan(self, row=0, dwelltime=None, **kws):
        if row == 0:
            self.AcquireOffset(timeout=10, open_shutter=True)

    def AcquireOffset(self, timeout=10, open_shutter=True):
        """Acquire Offset -- a slightly complex process
        Arguments
        ---------
        timeout :       float (default 10)  time in seconds to wait
        open_shutter :  bool (default True)  open shutters on exit

        1. close shutter
        2. set image mode to single /internal trigger
        3. acquire offset correction
        4. reset image mode and trigger mode
        5. optionally (by default) open shutter
        """
        self.cam.ShutterMode =  1    # Epics PV
        self.cam.ShutterControl = 0  # Close
        image_mode_save = self.cam.ImageMode
        trigger_mode_save = self.cam.TriggerMode
        self.cam.ImageMode = 0
        self.cam.TriggerMode = 0
        offtime = self.cam.PENumOffsetFrames * self.cam.AcquireTime
        time.sleep(0.50)
        self.cam.PEAcquireOffset = 1
        t0 = time.time()
        time.sleep(offtime/3.0)
        while self.cam.PEAcquireOffset > 0 and time.time()-t0 < timeout+offtime:
            time.sleep(0.1)
        time.sleep(1.00)
        self.cam.ImageMode = image_mode_save
        self.cam.TriggerMode = trigger_mode_save
        time.sleep(1.00)
        if open_shutter:
            self.cam.ShutterControl = 1
        self.cam.ShutterMode = 0
        time.sleep(1.50)
        
