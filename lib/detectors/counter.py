"""
Basic Counter
"""
import numpy as np
from collections import OrderedDict
from epics import get_pv, caget, poll

from ..saveable import Saveable

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

class DummyCounter(Saveable):
    """dummy counter, not associated with PV"""
    def __init__(self, pvname, label=None, units=''):
        Saveable.__init__(self, pvname, label=label, units=units)
        self.pvname = pvname
        if label is None:
            label = pvname
        self.label = label
        self.units = units
        self.clear()

    def __repr__(self):
        return "counter(%s, label='%s')" % (self.pvname, self.label)

    def read(self, val, **kws):
        self.buff = list(val)
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


class ROISumCounter(Saveable):
    """
    ROI Sum counter as for Xspress3 ROIs or using AD ROIstats plugin
    use dtcfmt='1' to mean no deadtime correction
    """
    def __init__(self, label, roifmt, dtcfmt, nmcas, units='counts'):
        Saveable.__init__(self, label=label, roifmt=roifmt, dtcfmt=dtcfmt,
                          nmcas=nmcas, units=units)

        self.label = label
        self.dtcorr = dtcfmt != '1'
        if not self.dtcorr:
            self.label = label + ' no_dtc'
        self.nmcas = nmcas
        self.roifmt = roifmt
        self.dtcfmt = dtcfmt
        self.units = units

        self.pvname = '@@' + self.__repr__()

        self.roi_pvs = []
        self.dtc_pvs = []

        for imca in range(1, nmcas+1):
            self.roi_pvs.append(get_pv(roifmt % imca))
            if self.dtcorr:
                self.dtc_pvs.append(get_pv(dtcfmt % imca))
        poll()
        self.clear()

    def __repr__(self):
        return "%s('%s', '%s', '%s', %d)" % (self.__class__.__name__,
                                             self.label, self.roifmt,
                                             self.dtcfmt, self.nmcas)

    def read(self, **kws):
        vals = [pv.get(**kws) for pv in self.roi_pvs]
        dtc = [1.0]*len(vals)
        if self.dtcorr:
            dtc = [pv.get(**kws) for pv in self.dtc_pvs]
        val = 0.0
        for v, d in zip(vals, dtc):
            if isinstance(d, np.ndarray):
                if len(d) == 0:
                    d = 1
                elif len(d) == 1:
                    d = max(1.0, d[0])
                elif len(d) < len(v):
                    dx = np.ones[len(v)]
                    dx[:len(d)] = d
                    d = dx[:]
                    d[np.where(d<0.99999)] = 1.0
            else:
                d = max(1.0, d)
            val += v*d
        self.buff = val
        return val

    def clear(self):
        "clear counter"
        self.buff = []

    def get_buffers(self):
        "return {label: buffer} dictionary"
        return {self.label: self.buff}


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

        May want to override this method....
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
