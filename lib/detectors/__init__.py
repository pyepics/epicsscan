"""
Triggers, Counters, Detectors for Step Scan
"""

import os
import time
from numpy import ndarray
from collections import OrderedDict

from epics import PV, get_pv, caget, caput, poll
from epics.devices import Scaler, MCA

from ..saveable import Saveable
from ..file_utils import fix_filename

from .struck import Struck
from .xspress3 import Xspress3
from .quadem import TetrAMM

from .trigger import Trigger
from .counter import Counter, DeviceCounter, MotorCounter
from .base  import DetectorMixin, SimpleDetector, MotorDetector

from .scaler import ScalerCounter, ScalerDetector


class TetrAMMScalerDetector(DetectorMixin):
    trigger_suffix = 'Acquire'
    def __init__(self, prefix, nchan=8, use_calc=True, **kws):
        DetectorMixin.__init__(self, prefix, **kws)
        nchan = int(nchan)
        self.scaler = Scaler(prefix, nchan=nchan)
        self._counter = ScalerCounter(prefix, nchan=nchan,
                                      use_calc=use_calc)
        self.dwelltime_pv = get_pv('%s.TP' % prefix)
        self.dwelltime = None
        self.counters = self._counter.counters
        self.extra_pvs = [('Scaler.frequency', '%s.FREQ' % prefix),
                          ('Scaler.read_delay', '%s.DLY' % prefix)]
        self._repr_extra = ', nchans=%i, use_calc=%s' % (nchan,
                                                         repr(use_calc))

        self.extra_pvs.extend(self._counter.extra_pvs)

    def pre_scan(self, scan=None, **kws):
        self.scaler.OneShotMode()
        if self.dwelltime is not None and isinstance(self.dwelltime_pv, PV):
            self.dwelltime_pv.put(self.dwelltime)

    def post_scan(self, **kws):
        self.scaler.AutoCountMode()

class Xspress3Trigger(Trigger):
    """Triggers for Xspress3, AD2 version
    where Start does an EraseStart for the MCA arrays
    """
    def __init__(self, prefix, value=1, label=None, **kws):
        Trigger.__init__(self, prefix, label=label, value=value, **kws)
        self._start = get_pv(prefix + 'det1:Acquire')
        self._erase = get_pv(prefix + 'det1:ERASE')
        self.prefix = prefix
        self._val = value
        self.done = False
        self._t0 = 0
        self.runtime = -1

    def __repr__(self):
        return "<Xspress3Trigger(%s)>" % (self.prefix)

    def __onComplete(self, pvname=None, **kws):
        self.done = True
        self.runtime = time.time() - self._t0

    def start(self, value=None):
        """Start Xspress3"""
        self.done = False
        runtime = -1
        self._t0 = time.time()
        if value is None:
            value = self._val
        # self._erase.put(1, wait=True)
        # poll(0.01, 0.5)
        self._start.put(value, callback=self.__onComplete)
        poll(0.01, 0.5)

    def abort(self, value=0):
        self._start.put(0, wait=False)
        poll(0.050, 0.5)


class Xspress3Detector(DetectorMixin):
    """
    Xspress 3 MultiMCA detector, 3.2
    """
    repr_fmt = ', nmcas=%i, nrois=%i, use_dtc=%s, use_full=%s'

    def __init__(self, prefix, label=None, nmcas=4,
                 nrois=32, rois=None, pixeltime=0.1, use_dtc=False,
                 use=True, use_unlabeled=False, use_full=False, **kws):

        if not prefix.endswith(':'):
            prefix = "%s:" % prefix

        self.nmcas = nmcas = int(nmcas)
        self.nrois = nrois = int(nrois)
        DetectorMixin.__init__(self, prefix, label=label)

        self.prefix = prefix
        self.dwelltime = None
        self.dwelltime_pv = get_pv('%sdet1:AcquireTime' % prefix)
        self.trigger = Xspress3Trigger(prefix)
        self.extra_pvs = self.add_extrapvs_GSE()
        self.use_dtc = use_dtc  # KLUDGE DTC!!
        self.label = label
        if self.label is None:
            self.label = self.prefix

        self._counter = None
        self.counters = []
        self._repr_extra = self.repr_fmt % (nmcas, nrois,
                                            repr(use_dtc),
                                            repr(use_full))

        self._connect_args = dict(nmcas=nmcas, nrois=nrois, rois=rois,
                                  use_unlabeled=use_unlabeled,
                                  use_full=use_full)
        self.connect_counters()

    def __repr__(self):
        return "<%s: '%s', prefix='%s'%s>" % (self.__class__.__name__,
                                              self.label, self.prefix,
                                              self._repr_extra)

    def add_extrapvs_GSE(self):
        e = [('mca1 tau(nsec)', '13IDE:userTran3.A'),
             ('mca2 tau(nsec)', '13IDE:userTran3.B'),
             ('mca3 tau(nsec)', '13IDE:userTran3.C'),
             ('mca4 tau(nsec)', '13IDE:userTran3.D')]
        return e

    def connect_counters(self):
        # print("Xspres3 connect_counters ", self._connect_args)
        self._counter = Xspress3Counter(self.prefix, **self._connect_args)
        self.counters = self._counter.counters
        self.extra_pvs = self._counter.extra_pvs

    def pre_scan(self, scan=None, **kws):
        """ """
        caput("%sdet1:Acquire" % (self.prefix), 0)
        poll(0.05, 0.5)

        if self._counter is None:
            self.connect_counters()
        self._counter._get_counters()
        self.counters = self._counter.counters
        self.extra_pvs = self._counter.extra_pvs

        dtime = 0.5
        if self.dwelltime is not None:
            dtime = self.dwelltime
        self.dwelltime_pv.put(dtime)

        # for i in range(1, self.nmcas+1):
        #     card = "%sC%i" % (self.prefix, i)
        #     caput("%s_PluginControlValExtraROI" % (card), 0)
        #     caput("%s_PluginControlVal"         % (card), 1)
        #    poll(0.005, 0.5)
        caput("%sdet1:ERASE"         % (self.prefix), 1)
        caput("%sdet1:TriggerMode"   % (self.prefix), 1)   # Internal Mode
        caput("%sdet1:NumImages"     % (self.prefix), 1)   # 1 Image
        caput("%sdet1:CTRL_DTC"      % (self.prefix), self.use_dtc)
        poll(0.01, 0.5)

        caput("%sdet1:Acquire" % (self.prefix), 0, wait=True)
        poll(0.01, 0.5)
        caput("%sdet1:ERASE"   % (self.prefix), 1, wait=True)
        poll(0.01, 0.5)


class Xspress3Counter(DeviceCounter):
    """Counters for Xspress3-1-10 (weird ROIs / areaDetector hybrid)
    """
    sca_labels = ('', 'Clock', 'ResetTicks', 'ResetCounts',
                  'AllEvent', 'AllGood', 'Window1', 'Window2', 'Pileup')
    scas2save = (1, 2, 3, 4, 5, 8)
    def __init__(self, prefix, outpvs=None, nmcas=4,
                 nrois=32, rois=None, nscas=1, use_unlabeled=False,
                 use_full=False):

        if not prefix.endswith(':'):
            prefix = "%s:" % prefix

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
        self.rois = [r.lower().strip() for r in rois]

    def _get_counters(self):
        prefix = self.prefix
        self.counters = []
        def add_counter(pv, lab):
            self.counters.append(Counter(pv, label=lab))

        try:
            nmax = len(caget('%sMCA1:ArrayData' % prefix))
        except ValueError:
            nmax = 2048

        if 'outputcounts' not in self.rois:
            self.rois.append('outputcounts')

        for iroi in range(1, self.nrois+1):
            label = caget("%sMCA1ROI:%i:Name" % (prefix, iroi)).strip()
            if len(label) < 0:
                break
            elif label.lower() in self.rois:
                for imca in range(1, self.nmcas+1):
                    _pvname = '%sMCA%iROI:%i:Total_RBV' % (prefix, imca, iroi)
                    _label = "%s mca%i" % (label, imca)
                    add_counter(_pvname, _label)

        for isca in self.scas2save:
            for imca in range(1, self.nmcas+1):
                _pvname = '%sC%iSCA%i:Value_RBV' % (prefix, imca, isca)
                _label = '%s mca%i' % (self.sca_labels[isca], imca)
                add_counter(_pvname, _label)

        if self.use_full:
            for imca in range(1, self.nmcas+1):
                pv = '%sMCA%i.ArrayData' % (prefix, imca)
                add_counter(pv, 'spectra%i' % imca)


def get_detector(prefix, kind=None, label=None, **kws):
    """returns best guess of which Detector class to use
           Mca, MultiMca, Motor, Scaler, Simple
    based on kind and/or record type.
    """
    dtypes = {'scaler': ScalerDetector,
              'motor': MotorDetector,
              'area': AreaDetector,
              'areadetector': AreaDetector,
              'mca': McaDetector,
              'med': MultiMcaDetector,
              'multimca': MultiMcaDetector,
              'xspress3': Xspress3Detector,
              None: SimpleDetector}

    if kind is None:
        if prefix.endswith('.VAL'):
            prefix = prefix[-4]
        rtyp = caget("%s.RTYP" % prefix)
        if rtyp in ('motor', 'mca', 'scaler'):
            kind = rtyp
    else:
        kind = kind.lower()
    builder = dtypes.get(kind, SimpleDetector)
    # print("Get Detector: ", prefix, label, kws)
    return builder(prefix, label=label, **kws)
