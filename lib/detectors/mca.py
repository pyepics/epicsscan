"""
MCA and MultiMCA detectors
"""

from epics import PV, get_pv, caget, caput, poll
from epics.devices import MCA

from .base import DetectorMixin
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

class MultiMcaDetector(DetectorMixin):
    trigger_suffix = 'EraseStart'
    collect_mode = 'CollectMode'
    repr_fmt = ', nmcas=%i, nrois=%i, use_net=%s, use_full=%s'

    def __init__(self, prefix, label=None, nmcas=4, nrois=32, rois=None,
                 search_all=False, use_net=False,
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


    def pre_scan(self, **kws):
        if self._counter is None:
            self.connect_counters()
        if self.dwelltime is not None and isinstance(self.dwelltime_pv, PV):
            self.dwelltime_pv.put(self.dwelltime)
        caput("%sCollectMode" % (self.prefix), 0)   # mca spectra
        caput("%sPresetMode"  % (self.prefix), 1)   # real time
        caput("%sReadBaselineHistograms.SCAN" % (self.prefix), 0)
        caput("%sReadTraces.SCAN" % (self.prefix), 0)
        caput("%sReadLLParams.SCAN" % (self.prefix), 0)
        caput("%sReadAll.SCAN"   % (self.prefix), 9)
        caput("%sStatusAll.SCAN" % (self.prefix), 9)
