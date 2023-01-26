"""
Basic Counter
"""
import numpy as np
from collections import OrderedDict
from epics import get_pv, caget, poll

from ..saveable import Saveable
from ..file_utils import fix_varname

EVAL4PLOT= '@@'
class Counter(Saveable):
    """simple scan counter object
    a value that will be counted at each point
    in a step scan
    """
    def __init__(self, pvname, label=None, units=''):
        Saveable.__init__(self, pvname, label=label, units=units)
        self.pvname = pvname
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
        if hasattr(self, 'net_buff'):
            return  self.net_buff
        return self.buff

    def clear(self):
        "clear counter"
        self.buff = []
        if hasattr(self, 'net_buff'):
            delattr(self, 'netc_buff')

    def get_buffers(self, net=True):
        "return {label: buffer} dictionary"
        if net and hasattr(self, 'net_buff'):
            return {self.label: self.net_buff}
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
    def __init__(self, label, roifmt, dtcfmt, nmcas, units='counts', data=None):
        Saveable.__init__(self, label=label, roifmt=roifmt, dtcfmt=dtcfmt,
                          nmcas=nmcas, units=units)
        self.dtcorr = dtcfmt != '1'
        if not self.dtcorr:
            label = label + ' no_dtc'
        self.label = fix_varname(label)
        self.nmcas = nmcas
        self.roifmt = roifmt
        self.dtcfmt = dtcfmt
        self.units = units
        self.pvname = EVAL4PLOT + self.__repr__()
        self.roi_pvs = []
        self.dtc_pvs = []
        self.data = data
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
        if self.data is not None:
            vals = [self.data[pv.pvname] for pv in self.roi_pvs]
        else:
            vals = [pv.get(**kws) for pv in self.roi_pvs]
        val, npts = 0.0, None
        for v in vals:
            try:
                nv = len(v)
            except:
                nv = 1
            if npts is None:
                npts = nv
            npts = min(npts, nv)
        for i, v in enumerate(vals):
            dx, nd = 1.0, 0
            if self.dtcorr:
                dtc_pvname = self.dtc_pvs[i].pvname
                if self.data is not None and dtc_pvname in self.data:
                    try:
                        dx = self.data[dtc_pvname]
                    except:
                        dx = 1.0
                else:
                    try:
                        dx = self.dtc_pvs[i].get()
                    except:
                        dx = 1.0
                if npts == 1:
                    dtc = dx
                else:
                    dtc = np.ones(npts)
                    dx[np.where(dx<0.999)] = 1.0
                    nd = min(npts, len(dx))
                    dtc[:nd] = dx[:nd]

            if npts == 1:
                try:
                    val += v*dtc
                except:
                    print("error read v and dtc with npts == 1")
                    val += v
            else:
                val += v[:npts]*dtc[:npts]
        if npts == 1:
            if isinstance(val, np.ndarray):
                val = val[0]
            self.buff.append(val)
        else:
            self.buff = val.tolist()
        return self.buff

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
        print("DeviceCounter.read ", self.prefix, kws)
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
