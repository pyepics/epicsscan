"""
Struck SIS3820
"""
import sys
import time
import copy
import numpy
from epics import Device, caget
from epics.devices.scaler import Scaler
from epics.devices.mca import MCA

from .counter import DeviceCounter
from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE

HEADER = '''# Struck MCA data: %s
# Nchannels, Nmcas = %i, %i
# Time in microseconds
#----------------------
# %s
# %s
'''

class Struck(Device):
    """
    Very simple implementation of Struck SIS MultiChannelScaler
    """
    attrs = ('ChannelAdvance', 'Prescale', 'EraseStart',
             'EraseAll', 'StartAll', 'StopAll',
             'PresetReal', 'ElapsedReal',
             'Dwell', 'Acquiring', 'NuseAll', 'MaxChannels',
             'CurrentChannel', 'CountOnStart',   # InitialChannelAdvance',
             'SoftwareChannelAdvance', 'Channel1Source',
             'ReadAll', 'DoReadAll', 'Model', 'Firmware')

    _nonpvs = ('_prefix', '_pvs', '_delim', '_nchan',
               'clockrate', 'scaler', 'mcas')

    def __init__(self, prefix, scaler=None, nchan=8, clockrate=50.0):
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix
        self._nchan = nchan
        self.scaler = None
        self.clockrate = clockrate # clock rate in MHz
        self._mode = SCALER_MODE
        self.ROIMode = self.NDArrayMode

        if scaler is not None:
            self.scaler = Scaler(scaler, nchan=nchan)

        self.mcas = []
        for i in range(nchan):
            self.mcas.append(MCA(prefix, mca=i+1, nrois=2))

        Device.__init__(self, prefix, delim='',
                        attrs=self.attrs, mutable=False)

    def ExternalMode(self, countonstart=0, initialadvance=None,
                     realtime=0, prescale=1, trigger_width=None):
        """put Struck in External Mode, with the following options:
        option            meaning                   default value
        ----------------------------------------------------------
        countonstart    set Count on Start             0
        initialadvance  set Initial Channel Advance    None
        reatime         set Preset Real Time           0
        prescale        set Prescale value             1
        trigger_width   set trigger width in sec       None
        """
        out = self.put('ChannelAdvance', 1)  # external
        if self.scaler is not None:
            self.scaler.OneShotMode()
        if realtime is not None:
            self.put('PresetReal', realtime)
        if prescale is not None:
            self.put('Prescale', prescale)
        if countonstart is not None:
            self.put('CountOnStart', countonstart)
        if initialadvance is not None:
            self.put('InitialChannelAdvancel', initialadvance)
        if trigger_width is not None:
            self.put('LNEOutputWidth', trigger_width)

        return out

    def InternalMode(self, prescale=None):
        "put Struck in Internal Mode"
        out = self.put('ChannelAdvance', 0)  # internal
        if self.scaler is not None:
            self.scaler.OneShotMode()
        if prescale is not None:
            self.put('Prescale', prescale)
        return out

    def set_dwelltime(self, val):
        "Set Dwell Time"
        return self.put('Dwell', val)

    def ContinuousMode(self, dwelltime=None, numframes=None):
        """set to continuous mode: use for live reading

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [None]
        numframes (None or int):   number of frames to collect [None]

    Notes:
        1. This sets AquireMode to Continuous.  If dwelltime or numframes
           is not None, they will be set
        """
        self.InternalMode()
        if numframes is not None:
            self.put('NuseAll', numframes)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        if self.scaler is not None:
            self.scaler.AutoCountMode()
        self._mode = SCALER_MODE

    def ScalerMode(self, dwelltime=1.0, numframes=1):
        """ set to scaler mode: ready for step scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [1.0]
        numframes (None or int):   number of frames to collect [1]

    Notes:
        1. numframes should be 1, unless you know what you're doing.
        """
        if numframes is not None:
            self.put('NuseAll', numframes)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        if self.scaler is not None:
            self.scaler.OneShotMode()
        self._mode = SCALER_MODE

    def NDArrayMode(self, dwelltime=None, numframes=None, trigger_width=None):
        """ set to array mode: ready for slew scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None int):   number of frames to collect [8192]
        trigger_width (None or float):   output trigger width (in seconds)
             for optional SIS 3820 [None]

    Notes:
        1. this arms SIS to be ready for slew scanning.
        2. setting dwelltime or numframes to None is discouraged,
           as it can lead to inconsistent data arrays.

        """
        if numframes is not None:
            self.put('NuseAll', numframes)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        self._mode = NDARRAY_MODE

        self.put('StopAll', 1)
        # self.put('EraseAll', 1)
        self.ExternalMode(trigger_width=trigger_width, countonstart=False)

    def start(self, wait=False):
        "Start Struck"
        if self.scaler is not None:
            self.scaler.OneShotMode()
        return self.put('EraseStart', 1, wait=wait)

    def stop(self):
        "Stop Struck Collection"
        return self.put('StopAll', 1)

    def erase(self):
        "Start Struck"
        return self.put('EraseAll', 1)

    def mcaNread(self, nmcas=1):
        "Read a Struck MCA"
        return self.get('mca%i.NORD' % nmcas)

    def readmca(self, nmcas=1, count=None):
        "Read a Struck MCA"
        return self.get('mca%i' % nmcas, count=count)

    def read_all_mcas(self):
        return [self.readmca(nmcas=i+1) for i in range(self._nchan)]

    def save_arraydata(self, filename='Struck.dat', ignore_prefix=None, npts=None):
        "save MCA spectra to ASCII file"
        sdata, names, addrs = [], [], []
        npts = 1.e99
        time.sleep(0.005)
        for nchan in range(self._nchan):
            nmcas = nchan + 1
            _name = 'MCA%i' % nmcas
            _addr = '%s.MCA%i' % (self._prefix, nmcas)
            time.sleep(0.002)
            if self.scaler is not None:
                scaler_name = self.scaler.get('NM%i' % nmcas)
                if scaler_name is not None:
                    _name = scaler_name.replace(' ', '_')
                    _addr = self.scaler._prefix + 'S%i' % nmcas
            mcadat = self.readmca(nmcas=nmcas)
            npts = min(npts, len(mcadat))
            if len(_name) > 0 or sum(mcadat) > 0:
                names.append(_name)
                addrs.append(_addr)
                sdata.append(mcadat)

        sdata = numpy.array([s[:npts] for s in sdata]).transpose()
        sdata[:, 0] = sdata[:, 0]/self.clockrate

        nelem, nmcas = sdata.shape
        npts = min(nelem, npts)

        addrs = ' | '.join(addrs)
        names = ' | '.join(names)
        formt = '%9i ' * nmcas + '\n'

        fout = open(filename, 'w')
        fout.write(HEADER % (self._prefix, npts, nmcas, addrs, names))
        for i in range(npts):
            fout.write(formt % tuple(sdata[i]))
        fout.close()
        return (nmcas, npts)

class StruckCounter(DeviceCounter):
    """Counter for Struck"""
    invalid_device_msg = 'StruckCounter must use an Epics Scaler'
    def __init__(self, prefix, scaler=None, outpvs=None, nchan=8,
                 use_calc=False, use_unlabeled=False):
        DeviceCounter.__init__(self, prefix)
        fields = [] # ('.T', 'CountTime')]
        extra_pvs = []
        nchan = int(nchan)
        if scaler is not None:
            for i in range(1, nchan+1):
                label = caget('%s.NM%i' % (scaler, i))
                if len(label) > 0 or use_unlabeled:
                    suff = 'MCA%i' % (i)
                    fields.append((suff, label))
        self.extra_pvs = extra_pvs
        self.set_counters(fields)

class StruckDetector(DetectorMixin):
    """Scaler Detector"""
    trigger_suffix = 'WHO?'
    def __init__(self, prefix, nchan=8, use_calc=True, label='struck',
                 mode='scaler',  scaler=None, rois=None, **kws):
        nchan = int(nchan)
        self.mode = mode

        self.struck = Struck(prefix, scaler=scaler, nchan=nchan)
        DetectorMixin.__init__(self, prefix, **kws)
        self.label = label

        self.dwelltime_pv = self.struck._pvs['Dwell']

        self._counter = StruckCounter(prefix, scaler=scaler,
                                      nchan=nchan)
        self.counters = self._counter.counters

    def pre_scan(self, mode=None, npulses=None, dwelltime=None, **kws):
        "run just prior to scan"
        if mode is not None:
            self.mode = mode
        # print("StruckDetector Prescan", mode, self.mode, kws)
        self.arm(mode=self.mode, numframes=npulses)
        self.counters = self._counter.counters
        if dwelltime is not None:
            self.dwelltime = dwelltime
        self.struck.set_dwelltime(self.dwelltime)
        if npulses is not None:
            self.struck.put('NuseAll', npulses)

    def post_scan(self, **kws):
        "run just after scan"
        self.struck.ContinuousMode(numframes=1)

    def arm(self, mode=None, wait=False, numframes=None):
        "arm detector, ready to collect with optional mode"
        if self.mode == SCALER_MODE:
            self.struck.ScalerMode()
        elif self.mode == ROI_MODE:
            self.struck.ROIMode()
        elif self.mode == NDARRAY_MODE:
            self.struck.NDArrayMode(numframes=numframes)

    def start(self, mode=None, arm=False, wait=False):
        "start detector, optionally arming and waiting"
        if arm:
            self.arm(mode=mode)
        self.struck.start(wait=wait)

    def stop(self):
        "stop detector"
        self.struck.stop()

    def save_arraydata(self, filename=None, npts=None):
        if filename is not None:
            self.struck.save_arraydata(filename=filename, npts=npts)
