"""
basic Detector classes, including DetectorMixin and SimpleDetector
"""
from epicsscan.saveable import Saveable
from .trigger import Trigger
from .counter import Counter, MotorCounter

SCALER_MODE, NDARRAY_MODE, ROI_MODE = 'scaler', 'ndarray', 'roi'

class DetectorMixin(Saveable):
    """
    Base detector mixin class
    """
    trigger_suffix = None
    def __init__(self, prefix, label=None, **kws):
        Saveable.__init__(self, prefix, label=label, **kws)
        self.prefix = prefix
        self.label = label
        if self.label is None:
            self.label = self.prefix
        self.trigger = None
        self.counters = []
        self.dwelltime_pv = None
        self.dwelltime = None
        self._mode     = SCALER_MODE
        self.extra_pvs = []
        self._repr_extra = ''
        self._savevals = {}
        if self.trigger_suffix is not None:
            self.trigger = Trigger("%s%s" % (prefix, self.trigger_suffix))

    def __repr__(self):
        return "%s('%s', label='%s'%s)" % (self.__class__.__name__,
                                          self.prefix, self.label,
                                          self._repr_extra)

    def ScalerMode(self, dwelltime=1.0, numframes=1, **kws):
        "set to scaler mode, for step scanning"
        pass

    def ContinuousMode(self, dwelltime=None, numframes=None, **kws):
        "set to continuous mode"
        return self.ScalerMode(dwelltime=dwelltime, numframes=numframes, **kws)

    def ROIMode(self, dwelltime=1.0, numframes=1, **kw):
        "set to ROI mode, for slew-scanning of scalers to 1D arrays"
        return self.ScalerMode(dwelltime=dwelltime, numframes=numframes, **kws)

    def NDArrayMode(self, dwelltime=0.25, numframes=16384, **kws):
        """set to NDArray mode, for slew-scanning saving full arrays
        typically through areaDetector file saving mechanism"""
        return self.ScalerMode(dwelltime=dwelltime, numframes=numframes, **kws)

    def config_filesaver(self, **kws):
        "configure filesaver"
        pass

    def save_calibration(self, filename, **kws):
        "save calibration information to file"
        pass

    def arm(self, mode=None, wait=False):
        "arm detector, ready to collect with optional mode"
        pass

    def disarm(self, mode=None, wait=False):
        "disarm detector, ready to not collect, from mode"
        pass

    def start(self, mode=None, arm=False, wait=False):
        "start detector, optionally setting mode, arming, and waiting"
        pass

    def stop(self, mode=None, disarm=False, wait=False):
        "stop detector, optionally setting mode, disarming, and waiting"
        pass

    def save_arraydata(self, filename=None):
        "save array data to external file"
        pass

    def sett(self):
        pass


    def set_dwelltime(self, val):
        "set detector dwelltime"
        self.dwelltime = val
        if self.dwelltime_pv is not None:
            self.dwelltime_pv.put(val)


    def connect_counters(self):
        "connect to counters"
        pass

    def pre_scan(self, **kws):
        "run prior to scan"
        pass

    def post_scan(self, **kws):
        "run after can"
        pass

    def at_break(self, breakpoint=None, **kws):
        "run at breakpoint"
        pass

class SimpleDetector(DetectorMixin):
    "Simple Detector: a single Counter without a trigger"
    trigger_suffix = None
    def __init__(self, prefix, **kws):
        DetectorMixin.__init__(self, prefix, **kws)
        self.counters = [Counter(prefix)]

class MotorDetector(DetectorMixin):
    "Motor Detector: a Counter for  Motor Readback, no trigger"
    trigger_suffix = None
    def __init__(self, prefix, **kws):
        DetectorMixin.__init__(self, prefix, **kws)
        self.counters = [MotorCounter(prefix)]
