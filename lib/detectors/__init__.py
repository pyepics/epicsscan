"""
Triggers, Counters, Detectors for Step Scan
"""

import os
import time
from collections import OrderedDict

from numpy import ndarray

from epics import PV, get_pv, caget, caput, poll
from epics.devices import Scaler, MCA

from ..saveable import Saveable
from ..file_utils import fix_filename


from .trigger import Trigger
from .counter import Counter, DeviceCounter, MotorCounter
from .base  import DetectorMixin, SimpleDetector, MotorDetector
from .areadetector import AreaDetector
from .mca import McaDetector, MultiMcaDetector
from .scaler import ScalerCounter, ScalerDetector
from .xspress3 import Xspress3, Xspress3Detector
from .struck import Struck
from .quadem import TetrAMM


DET_DEFAULT_OPTS = {'scaler': {'use_calc': True, 'nchans': 8},
                    'areadetector': {'file_plugin': 'TIFF1',
                                     'fileroot': '',
                                     'auto_increment': True},
                    'mca': {'nrois': 32, 'use_full': False,
                            'use_net': False},
                    'xspress3': {'nrois': 32, 'nmcas': 4,
                                 'use_full': False},
                    'multimca': {'nrois': 32, 'nmcas': 4,
                                 'use_full': False, 'use_net': False}}

AD_FILE_PLUGINS = ('TIFF1', 'JPEG1', 'NetCDF1', 'HDF1', 'Nexus1')

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

    def pre_scan(self, **kws):
        self.scaler.OneShotMode()
        if self.dwelltime is not None and isinstance(self.dwelltime_pv, PV):
            self.dwelltime_pv.put(self.dwelltime)

    def post_scan(self, **kws):
        self.scaler.AutoCountMode()


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
