"""
Basic Counter
"""
import numpy as np
from collections import OrderedDict
from epics import get_pv, caget

from epicsscan.saveable import Saveable

class Counter(Saveable):
    """simple scan counter object
    a value that will be counted at each point
    in a step scan
    """
    def __init__(self, pvname, label=None, units=''):
        Saveable.__init__(self, pvname, label=label, units=units)
        self.pv = get_pv(pvname)
        if label is None:
            label = pvname
        self.label = label
        self.units = units
        self.clear()

    def __repr__(self):
        return "counter(%s, label='%s')" % (self.pv.pvname, self.label)

    def read(self, **kws):
        "read counter to internal buffer"
        val = self.pv.get(**kws)
        if isinstance(val, np.ndarray):
            self.buff = val.tolist()
        elif isinstance(val, (list, tuple)):
            self.buff = list(val)
        else:
            self.buff.append(val)
        return val

    def clear(self):
        "clear counter"
        self.buff = []

    def get_buffers(self):
        "return {label: buffer} dictionary"
        return {self.label: self.buff}

class MotorCounter(Counter):
    """Motor Counter: save Readback value
    """
    invalid_device_msg = 'MotorCounter must use an Epics Motor'
    def __init__(self, prefix, label=None):
        pvname = '%s.RBV' % prefix
        if label is None:
            label = "%s(actual)" % caget('%s.DESC' % prefix)
        Counter.__init__(self, pvname, label=label)


class DeviceCounter(object):
    """Generic Multi-PV Counter

    intended be used as base class for ScalerCounter, MCACounter, etc
    """
    invalid_device_msg = 'DeviceCounter of incorrect Record Type'
    def __init__(self, prefix, rtype=None, fields=None, outpvs=None):
        if prefix.endswith('.VAL'):
            prefix = prefix[-4]
        self.prefix = prefix
        if rtype is not None:
            try:
                rtype_found = caget("%s.RTYP" % self.prefix)
            except:
                rtype_found = None
            if rtype_found is not None and rtype_found != rtype:
                raise TypeError(self.invalid_device_msg)
        self.outpvs = outpvs
        self.set_counters(fields)

    def set_counters(self, fields):
        """set counters
        with list or tuple of (label, pv)
        """
        self.counters = []
        if hasattr(fields, '__iter__'):
            for suffix, label in fields:
                self.counters.append(Counter("%s%s" % (self.prefix, suffix),
                                             label=label))

    def postvalues(self):
        """post first N counter values to output PVs
        (N being the number of output PVs)

        May want ot override this method....
        """
        if self.outpvs is not None:
            for counter, pv in zip(self.counters, self.outpvs):
                pv.put(counter.buff)

    def read(self, **kws):
        "read counters"
        for counter in self.counters:
            counter.read(**kws)
        self.postvalues()

    def clear(self):
        "clear counters"
        for c in self.counters:
            c.clear()

    def get_buffers(self):
        "get dictionary of {label: buffer}"
        out = OrderedDict()
        for counter in self.counters:
            out[counter.label] = counter.buff
        return out
