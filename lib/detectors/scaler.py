"""
Basic Scaler Counter and Detector
"""
from epics import PV, get_pv, caget
from epics.devices import Scaler

from .counter import DeviceCounter
from .base import DetectorMixin

class ScalerCounter(DeviceCounter):
    """Counter for Scaler"""
    invalid_device_msg = 'ScalerCounter must use an Epics Scaler'
    def __init__(self, prefix, outpvs=None, nchan=8,
                 use_calc=False, use_unlabeled=False):
        DeviceCounter.__init__(self, prefix, rtype='scaler',
                               outpvs=outpvs)
        prefix = self.prefix
        fields = [('.T', 'CountTime')]
        extra_pvs = []
        nchan = int(nchan)
        for i in range(1, nchan+1):
            label = caget('%s.NM%i' % (prefix, i))
            if len(label) > 0 or use_unlabeled:
                suff = '.S%i' % i
                if use_calc:
                    suff = '_calc%i.VAL' % i
                    extra_pvs.append(('Scaler.Calc%i' % i,
                                      '%s_calc%i.CALC' % (prefix, i)))
                fields.append((suff, label))
        self.extra_pvs = extra_pvs
        self.set_counters(fields)

class ScalerDetector(DetectorMixin):
    """Scaler Detector"""
    trigger_suffix = '.CNT'
    def __init__(self, prefix, nchan=8, use_calc=True,
                 mode='scaler', rois=None,**kws):
        DetectorMixin.__init__(self, prefix, **kws)
        nchan = int(nchan)
        self.scaler = Scaler(prefix, nchan=nchan)
        self._counter = ScalerCounter(prefix, nchan=nchan,
                                      use_calc=use_calc)
        self.dwelltime_pv = get_pv('%s.TP' % prefix)
        self.dwelltime = None
        self.mode = mode
        self.counters = self._counter.counters
        self.extra_pvs = [('Scaler.frequency', '%s.FREQ' % prefix),
                          ('Scaler.read_delay', '%s.DLY' % prefix)]
        self._repr_extra = ', nchans=%i, use_calc=%s' % (nchan,
                                                         repr(use_calc))

        self.extra_pvs.extend(self._counter.extra_pvs)

    def pre_scan(self, **kws):
        "run just prior to scan"
        self.ScalerMode(dwelltime=self.dwelltime)

    def post_scan(self, **kws):
        "run just after scan"
        self.ContinuousMode()

    def ScalerMode(self, dwelltime=1.0, numframes=1, **kws):
        "set to scaler mode, for step scanning"
        if dwelltime is not None:
            self.scaler.CountTime(dwelltime)
        return self.scaler.OneShotMode()

    def ContinuousMode(self, dwelltime=None, numframes=None, **kws):
        "set to continuous mode"
        if dwelltime is not None:
            self.scaler.CountTime(dwelltime)
        return self.scaler.AutoCountMode()

    def arm(self, mode=None, wait=False, fnum=None):
        "arm detector, ready to collect with optional mode"
        self.scaler.OneShotMode()

    def start(self, mode=None, arm=False, wait=False):
        "start detector, optionally arming and waiting"
        if arm:
            self.arm(mode=mode)
        self.scaler.Count(wait=wait)

    def stop(self, mode=None, disarm=False, wait=False):
        "stop detector, optionally disarming and waiting"
        self.scaler.put('CNT', 0, wait=wait)
        if disarm:
            self.disarm(mode=mode)
