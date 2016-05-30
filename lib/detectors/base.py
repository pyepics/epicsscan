"""
basic Detector classes, including DetectorMixin and SimpleDetector
"""
from epicsscan.saveable import Saveable
from .trigger import Trigger
from .counter import Counter, MotorCounter

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
        self.extra_pvs = []
        self._repr_extra = ''
        self._savevals = {}
        if self.trigger_suffix is not None:
            self.trigger = Trigger("%s%s" % (prefix, self.trigger_suffix))

    def __repr__(self):
        return "%s(%s', label='%s'%s)" % (self.__class__.__name__,
                                          self.prefix, self.label,
                                          self._repr_extra)

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

    def set_dwelltime(self, val):
        "set detector dwelltime"
        self.dwelltime = val
        if self.dwelltime_pv is not None:
            self.dwelltime_pv.put(val)

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
