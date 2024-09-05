"""
QuadEM using TetrAMM
"""
from __future__ import print_function

import numpy as np
from epics import Device, poll, caget, get_pv
from . import Struck

from .counter import DeviceCounter
from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE

HEADER = '''# TetrAMM MCS Data: %s,  %s
# Nchannels, Nmcas = %i, %i
# Time in microseconds
#----------------------
# %s
# %s
'''

class TetrAMM(Device):
    """
    TetrAMM quad channel electrometer, version 2.9

    Can also use SIS3820 (Struck) or USBCTR MCS to manage triggering and timing
    """

    attrs = ('Acquire', 'AcquireMode', 'AveragingTime', 'NumAcquire',
             'ValuesPerReading', 'Range', 'SampleTime_RBV', 'NumAcquired',
             'TriggerMode', 'TriggerPolarity', 'ReadFormat')


    curr_attrs = ('Name%i', 'Offset%i', 'Scale%i', '%i:MeanValue_RBV',
                  '%i:Sigma_RBV', '%i:TSAcquiring', '%i:TSControl',
                  '%i:TSTotal', '%i:TSSigma', '%i:TSNumPoints', )

    _nonpvs = ('_prefix', '_pvs', '_delim', '_chans', '_mode', '_mcs')

    def __init__(self, prefix, nchan=4, mcs_prefix=None, mcs_type='usbctr'):

        self._mode = SCALER_MODE
        self.ROIMode = self.NDArrayMode
        self._chans = range(1, nchan+1)

        attrs = list(self.attrs)
        for i in self._chans:
            for a in self.curr_attrs:
                attrs.append(("Current" + a) % i)

        Device.__init__(self, prefix, delim='', attrs=attrs, mutable=False)
        self._aliases = {}
        for i in self._chans:
            self._aliases['Current%i'% i] = 'Current%i:MeanValue_RBV' % i
            self._aliases['Sigma%i'% i] = 'Current%i:Sigma_RBV' % i
            self._aliases['Offset%i'% i] = 'CurrentOffset%i' % i
            self._aliases['Scale%i'% i] = 'CurrentScale%i' % i
            self._aliases['Name%i'% i] = 'CurrentName%i' % i
            self._aliases['TSControl%i'% i] = 'Current%i:TSControl' % i
            self._aliases['TSAcquiring%i'% i] = 'Current%i:TSAcquiring' % i
            self._aliases['TSNumPoints%i'% i] = 'Current%i:TSNumPoints' % i
            self._aliases['TSTotal%i'% i] = 'Current%i:TSTotal' % i
            self._aliases['TSSigma%i'% i] = 'Current%i:TSSigma' % i

        self._mcs = None
        if mcs_prefix is not None:
            self.mcs_prefix = mcs_prefix
            mcs = Struck if 'struck' mca_type.lower() else USBCTR
            self._mcs = mcs(prefix)

    def ContinuousMode(self, dwelltime=None, numframes=None):
        """set to continuous mode: use for live reading

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [None]
        numframes (None or int):   number of frames to collect [None]

    Notes:
        1. This sets AquireMode to Continuous.  If dwelltime or numframes
           is not None, they will be set

        2. This puts the TetrAMM in SCALER mode, which will effect the
           behavior of 'Start'.
        """
        self.put('AcquireMode', 0)
        self.SetTriggerMode('internal')
        if numframes is not None:
            self.put('NumAcquire', numframes)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        self._mode = SCALER_MODE

    def ScalerMode(self, dwelltime=1.0, numframes=1):
        """ set to scaler mode: ready for step scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [1.0]
        numframes (None or int):   number of frames to collect [1]

    Notes:
        1. numframes should be 1, unless you know what you're doing.

        2. This puts the TetrAMM in SCALER mode, which will effect the
           behavior of 'Start'.
        """
        self.put('AcquireMode', 2)
        self.SetTriggerMode('internal')
        if numframes is not None:
            self.put('NumAcquire', numframes)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        if self._mcs is not None:
            self._mcs.ScalerMode()
        self._mode = SCALER_MODE


    def NDArrayMode(self, dwelltime=0.25, numframes=16384, sis_trigger_width=None):
        """ set to array mode: ready for slew scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None int):   number of frames to collect [16384]
        sis_trigger_width (None or float):   output trigger width (in seconds)
             for optional SIS 3820 [None]

    Notes:
        1. this arms detector and optional SIS8320 so that it is also
           ready for slew scanning.
        2. setting dwelltime or numframes to None is discouraged,
           as it can lead to inconsistent data arrays.
        3. This puts the TetrAMM in NDARRAY mode, which will effect the
           behavior of 'Start'.
        """
        self.put('AcquireMode', 1)
        self.SetTriggerMode('bulb')
        if numframes is not None:
            self.put('NumAcquire', numframes)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        for i in self._chans:
            self.put('Current%i:TSControl' % i, 2) # Stop
            if numframes is not None:
                self.put('Current%i:TSNumPoints' % i, numframes)

        if self._mcs is not None:
            self._mcs.NDArrayMode(dwelltime=dwelltime, numframes=numframes)
        self._mode = NDARRAY_MODE

    def set_dwelltime(self, dwelltime, valuesperread=None):
        """set dwell time in seconds

    Arguments:
        dwelltime (float): dwelltime per frame in seconds.   No default
        valuesperread (int or None):   values per reading for averaging
                  Defaults to 4000*dwelltime.

    Notes:
        ValuesPerRead cannot be below 5
        """
        if valuesperread is None:
            valuesperread = 10*max(1, int(dwelltime * 400))
        self.put('ValuesPerRead', max(5, valuesperread))
        if self._mcs is not None:
            self._mcs.SetDwellTime(dwelltime)

        return self.put('AveragingTime', dwelltime)

    def SetScale(self, i, scale=1.e9):
        """set current scale for channel i

    Arguments:
        i (int): channel to set Scale for (1, 2, 3, 4)
        scale (float):  current scale factor [1.e9]

    Notes:
        the TetrAMM reads current in Amperes by default.
        Setting to 1e9 will make the Current values be in nanpAmps.
        """
        return self.put('CurrentScale%i' % i, scale)

    def SetOffset(self, i, offset=0.0):
        """set current offset for channel i

    Arguments:
        i (int): channel to set Scale for (1, 2, 3, 4)
        offset (float):  current offset value [0]
        """
        return self.put('CurrentOffset%i' % i, offset)


    def _readattr(self, attr):
        return [self.get(attr % i) for i in self._chans]

    def ReadNames(self):
        "return list of all Channel Names"
        return self._readattr('CurrentName%i')

    def ReadCurrents(self):
        "return list of all Channel Current values"
        return self._readattr('Current%i:MeanValue_RBV')

    def ReadSigmas(self):
        "return list of all Channel Current Sigma values"
        return self._readattr('Current%i:Sigma_RBV')

    def ReadCurrentArrays(self):
        "return list of all Current Value arrays"
        return self._readattr('TSTotal%i')

    def ReadSigmaArrays(self):
        "return list of all Current Sigma arrays"
        return self._readattr('TSSigma%i')

    def SetTriggerMode(self, mode, polarity=None):
        """Set trigger mode

    Arguments:
        mode (int or string): mode index (see Notes), no default
        polarity (None or int): Trigger Polarity [None]

    Notes:
        1. mode can be an integer (0, 1, 2, 3) or a string
           ('internal', 'trigger', 'bulb', 'gate):
                0 internal
                1 external trigger
                2 external bulb
                3 external gate
         2. if polarity is not None, it will be set
        """
        if polarity is not None:
            self.put('TriggerPolarity', polarity)
        if isinstance(mode, basestring):
            lmode = mode.lower()
            if lmode.startswith('int'):
                mode = 0
            elif 'trig' in lmode:
                mode = 1
            elif 'bulb' in lmode:
                mode = 2
            elif 'gate' in lmode:
                mode = 3
        return self.put('TriggerMode', mode)

    def Count(self, dwelltime=None, wait=False):
        """start counting, with optional dwelltime and wait

    Arguments:
        dwelltime (float or None): dwelltime per frame in seconds.   If `None`,
             the dwelltime is not set.
        wait (bool):   whether to wait for counting to complete [False]

    Notes:
        this is a simplified version of Start(), starting only the basic counting.
        it is appropriate for SCALER mode, but not NDARRAY mode.
        """
        if dwelltime is not None:
            self.setDwellTime(dwelltime)
        out = self.put('Acquire', 1, wait=wait)
        poll()
        return out

    def start(self, wait=False):
        """start collection, with slightly different behavior for
    SCALER and NDARRAY mode.

    Arguments:
        wait (bool):   whether to wait for counting to complete [False]

    Notes:
        In SCALER mode, for simple counting: this simply collects one set of
        Current readings, by setting Acquire to 1 and optionally waiting for
        it to complete.

        In NDARRAY mode: this will first start the Time Series, then set Acquire
        to 1.  If an SIS is used, this will then set the SIS EraseStart to 1
        and optionally waiting for it to complete.

        """
        if self._mode in (NDARRAY_MODE, ROI_MODE):
            for i in self._chans:
                self.put('Current%i:TSControl' % i, 0)  # 'Erase/Start'
            if self._mcs is  not None:
                self.put('Acquire', 1, wait=False)
                poll(0.025, 1.0)
                out = self._mcs.Start(wait=wait)
            else:
                out = self.put('Acquire', 1, wait=wait)
        else:
            out = self.put('Acquire', 1, wait=wait)

        poll()
        return out

    def stop(self, wait=False):
        """Stop Collection

    Arguments:
        wait (bool):   whether to wait for stopping to complete [False]

    Notes:
        In NDARRAY mode, this will stop all the Time Series and the SIS.
        """
        if self._mode in (NDARRAY_MODE, ROI_MODE):
            for i in self._chans:
                self.put('Current%i:TSControl' % i, 2) # 'Stop'
        if self._mcs is not None:
            self._mcs.stop()
        return self.put('Acquire', 0, wait=wait)

    def save_arraydata(self, filename='tetramm_arrays.dat'):
        """
        save Current Array data to ASCII file

    Arguments:
        filename (string):  filename [tetramm_arrays.dat]

    Notes:
        if a SIS is used, this will also save the times from the SIS.
        """

        sdata = self.ReadCurrentArrays()
        names = self.ReadNames()
        fmt = '%sCurrent%i:MeanValue_RBV'
        addrs = [fmt % (self._prefix, i) for i in self._chans]

        sis_header = 'No SIS used'
        if self._mcs is not None:
            sis_header = 'MCS %s' % self._mcs.prefix
            names.insert(0, 'TSCALER')
            addrs.insert(0, self.mcs_prefix + 'VAL')
            sdata.insert(0, self._mcs.readmca(mca=1)/self._mcs.clockrate)

        npts = len(sdata[0])
        sdata = np.array([s[:npts] for s in sdata]).transpose()

        nelem, nmcas = sdata.shape
        npts = min(nelem, npts)

        addrs = ' | '.join(addrs)
        names = ' | '.join(names)
        formt = '%9i '  + '%9g ' * (nmcas-1) + '\n'

        buff = [HEADER % (self._prefix, sis_header,
                          npts, nmcas, addrs, names)]
        for i in range(npts):
            buff.append(formt % tuple(sdata[i]))
        buff.append()
        fout = open(filename, 'w')
        fout.write('\n'.join(buff))
        fout.close()
        return (nmcas, npts)

class TetrAMMCounter(DeviceCounter):
    """Counter for TetrAMM"""
    invalid_device_msg = 'TetrAMM epics device invalid'
    def __init__(self, prefix, outpvs=None, nchan=4,
                 use_calc=False, use_unlabeled=False):

        DeviceCounter.__init__(self, prefix, outpvs=outpvs)
        fields = [('AveragingTime_RBV', 'CountTime')]
        extra_pvs = []
        nchan = int(nchan)
        for i in range(1, nchan+1):
            labelx = '%sCurrentName%i' % (prefix, i)
            label = caget('%sCurrentName%i' % (prefix, i))
            if len(label) > 0 or use_unlabeled:
                suff = 'Current%i:MeanValue_RBV' % i
                extra_pvs.append(('TetrAMM.Offset%i' % i,
                                  '%sCurrentOffset%i' % (prefix, i)))
                extra_pvs.append(('TetrAMM.Scale%i' % i,
                                  '%sCurrentScale%i' % (prefix, i)))
                fields.append((suff, label))
        self.extra_pvs = extra_pvs
        self.set_counters(fields)


class TetrAMMDetector(DetectorMixin):
    """TetrAMM Detector"""
    trigger_suffix = 'Acquire'
    def __init__(self, prefix, nchan=4,
                 mode='scaler', rois=None, sis_prefix=None, **kws):

        DetectorMixin.__init__(self, prefix, **kws)
        nchan = int(nchan)
        self.tetramm  = TetrAMM(prefix, sis_prefix=sis_prefix)
        self._counter = TetrAMMCounter(prefix, nchan=nchan)
        self.dwelltime_pv = get_pv('%sAveragingTime' % prefix)
        self.dwelltime = None
        self.mode = mode
        self.counters = self._counter.counters

        extra_pvs = [('TetrAMM.Range', '%sRange_RBV' % (prefix)),
                     ('TetrAMM.SampleTime', '%sSampleTime_RBV' % (prefix)),
                     ('TetrAMM.ValuesPerRead', '%sValuesPerRead_RBV' % (prefix)),
                     ('TetrAMM.NumAverage', '%sNumAverage_RBV' % (prefix))]

        self.extra_pvs.extend(self._counter.extra_pvs)

    def pre_scan(self, **kws):
        "run just prior to scan"
        self.ScalerMode(dwelltime=self.dwelltime)

    def post_scan(self, **kws):
        "run just after scan"
        self.tetramm.ContinuousMode(dwelltime=0.1)
        return self.tetramm.put('Acquire', 1, wait=False)

    def ScalerMode(self, dwelltime=1.0, numframes=1, **kws):
        return self.tetramm.ScalerMode(dwelltime=dwelltime,
                                       numframes=numframes)

    def ContinuousMode(self, dwelltime=None, numframes=None, **kws):
        "set to continuous mode"
        return self.tetramm.ContinuousMode(dwelltime=dwelltime,
                                           numframes=numframes)


    def ROIMode(self, dwelltime=1.0, numframes=1, **kws):
        "set to ROI mode, for slew-scanning of scalers to 1D arrays"
        return self.tetramm.NDArrayMode(dwelltime=dwelltime,
                                        numframes=numframes, **kws)

    def arm(self, mode=None, wait=False):
        "arm detector, ready to collect with optional mode"
        if mode is not None:
            self.tetramm._mode = mode


    def disarm(self, mode=None, wait=False):
        "disarm detector, back to open loop"
        print(" DISARM TetrAMM")
        return self.tetramm.ContinuousMode(dwelltime=0.1)


    def start(self, mode=None, arm=False, wait=False):
        "start detector, optionally arming and waiting"
        if arm or mode is not None:
            self.arm(mode=mode)
        self.tetramm.start(wait=wait)

    def stop(self, mode=None, disarm=False, wait=False):
        "stop detector, optionally disarming and waiting"
        self.scaler.put('CNT', 0, wait=wait)
        if disarm:
            self.disarm(mode=mode)
