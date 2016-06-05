"""
Struck SIS3820
"""
import sys
import time
import copy
import numpy
from epics import Device
from epics.devices.scaler import Scaler
from epics.devices.mca import MCA


SCALER_MODE, ARRAY_MODE = 'SCALER', 'ARRAY'

HEADER = '''# Struck MCA data: %s
# Nchannels, Nmca = %i, %i
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
             'Dwell', 'Acquiring', 'NuseAll',
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
        self.ROIMode = self.ScalerMode

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

    def SetDwellTime(self, val):
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
        if numframes is not None:
            self.put('NuseAll', numframes)
        if dwelltime is not None:
            self.SetDwelltime(dwelltime)
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
            self.SetDwelltime(dwelltime)
        if self.scaler is not None:
            self.scaler.OneShotMode()
        self._mode = SCALER_MODE

    def ArrayMode(self, dwelltime=0.25, numframes=16384, trigger_width=None):
        """ set to array mode: ready for slew scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None int):   number of frames to collect [16384]
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
            self.SetDwelltime(dwelltime)
        self._mode = ARRAY_MODE

        self.put('StopAll', 1)
        self.put('EraseAll', 1)
        self.ExternalMode(trigger_width=trigger_width)

    def Start(self, wait=False):
        "Start Struck"
        if self.scaler is not None:
            self.scaler.OneShotMode()
        return self.put('EraseStart', 1, wait=wait)

    def Stop(self):
        "Stop Struck Collection"
        return self.put('StopAll', 1)

    def Erase(self):
        "Start Struck"
        return self.put('EraseAll', 1)

    def mcaNread(self, nmca=1):
        "Read a Struck MCA"
        return self.get('mca%i.NORD' % nmca)

    def readmca(self, nmca=1, count=None):
        "Read a Struck MCA"
        return self.get('mca%i' % nmca, count=count)

    def read_all_mcas(self):
        return [self.readmca(nmca=i+1) for i in range(self._nchan)]

    def SaveArrayData(self, fname='Struck.dat', ignore_prefix=None,
                      npts=None):
        "save MCA spectra to ASCII file"
        sdata, names, addrs = [], [], []
        npts = 1.e99
        time.sleep(0.005)
        for nchan in range(self._nchan):
            nmca = nchan + 1
            _name = 'MCA%i' % nmca
            _addr = '%s.MCA%i' % (self._prefix, nmca)
            time.sleep(0.002)
            if self.scaler is not None:
                scaler_name = self.scaler.get('NM%i' % nmca)
                if scaler_name is not None:
                    _name = scaler_name.replace(' ', '_')
                    _addr = self.scaler._prefix + 'S%i' % nmca
            mcadat = self.readmca(nmca=nmca)
            npts = min(npts, len(mcadat))
            if len(_name) > 0 or sum(mcadat) > 0:
                names.append(_name)
                addrs.append(_addr)
                sdata.append(mcadat)

        sdata = numpy.array([s[:npts] for s in sdata]).transpose()
        sdata[:, 0] = sdata[:, 0]/self.clockrate

        nelem, nmca = sdata.shape
        npts = min(nelem, npts)

        addrs = ' | '.join(addrs)
        names = ' | '.join(names)
        formt = '%9i ' * nmca + '\n'

        fout = open(fname, 'w')
        fout.write(HEADER % (self._prefix, npts, nmca, addrs, names))
        for i in range(npts):
            fout.write(formt % tuple(sdata[i]))
        fout.close()
        return (nmca, npts)
