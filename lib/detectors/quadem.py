"""
QuadEM using TetrAMM
"""
from __future__ import print_function

import numpy as np
from epics import Device, poll
from .struck import Struck

SCALER_MODE, ARRAY_MODE = 'SCALER', 'ARRAY'

HEADER = '''# TetrAMM MCS Data: %s,  %s
# Nchannels, Nmca = %i, %i
# Time in microseconds
#----------------------
# %s
# %s
'''


class TetrAMM(Device):
    """
    TetrAMM quad channel electrometer, version 2.9

    Can also use SIS3820 (Struck) to manage triggering and timing
    """

    attrs = ('Acquire', 'AcquireMode', 'AveragingTime', 'NumAcquire',
             'ValuesPerReading', 'Range', 'SampleTime_RBV', 'NumAcquired',
             'TriggerMode', 'TriggerPolarity', 'ReadFormat')


    curr_attrs = ('Name%i', 'Offset%i', 'Scale%i', '%i:MeanValue_RBV',
                  '%i:Sigma_RBV', '%i:TSAcquiring', '%i:TSControl',
                  '%i:TSTotal', '%i:TSSigma', '%i:TSNumPoints', )

    _nonpvs = ('_prefix', '_pvs', '_delim', '_chans', '_mode', '_sis')

    def __init__(self, prefix, nchan=4, sis_prefix=None):
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix
        self._mode = SCALER_MODE
        self.ROIMode = self.ScalerMode
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

        self._sis = None
        if sis_prefix is not None:
            self.sis_prefix = sis_prefix
            self._sis = Struck(prefix)

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
            self.SetDwelltime(dwelltime)
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
            self.SetDwelltime(dwelltime)
        if self._sis is not None:
            self._sis.ScalerMode()
        self._mode = SCALER_MODE


    def ArrayMode(self, dwelltime=0.25, numframes=16384, sis_trigger_width=None):
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
        3. This puts the TetrAMM in ARRAY mode, which will effect the
           behavior of 'Start'.
        """
        self.put('AcquireMode', 1)
        self.SetTriggerMode('bulb')
        if numframes is not None:
            self.put('NumAcquire', numframes)
        if dwelltime is not None:
            self.SetDwelltime(dwelltime)
        for i in self._chans:
            self.put('Current%i:TSControl' % i, 2) # Stop
            if numframes is not None:
                self.put('Current%i:TSNumPoints' % i, numframes)

        if self._sis is not None:
            self._sis.ArrayMode(dwelltime=dwelltime, numframes=numframes,
                                trigger_width=sis_trigger_width)
        self._mode = ARRAY_MODE

    def SetDwelltime(self, dwelltime, valuesperread=None):
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
        if self._sis is not None:
            self._sis.SetDwellTime(dwelltime)

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
        it is appropriate for SCALER mode, but not ARRAY mode.
        """
        if dwelltime is not None:
            self.setDwellTime(dwelltime)
        out = self.put('Acquire', 1, wait=wait)
        poll()
        return out

    def Start(self, wait=False):
        """start collection, with slightly different behavior for
    SCALER and ARRAY mode.

    Arguments:
        wait (bool):   whether to wait for counting to complete [False]

    Notes:
        In SCALER mode, for simple counting: this simply collects one set of
        Current readings, by setting Acquire to 1 and optionally waiting for
        it to complete.

        In ARRAY mode: this will first start the Time Series, then set Acquire
        to 1.  If an SIS is used, this will then set the SIS EraseStart to 1
        and optionally waiting for it to complete.

        """
        if self._mode == ARRAY_MODE:
            for i in self._chans:
                self.put('Current%i:TSControl' % i, 0)  # 'Erase/Start'
            if self._sis is  not None:
                self.put('Acquire', 1, wait=False)
                poll(0.025, 1.0)
                out = self._sis.Start(wait=wait)
            else:
                out = self.put('Acquire', 1, wait=wait)
        else:
            out = self.put('Acquire', 1, wait=wait)

        poll()
        return out

    def Stop(self, wait=False):
        """Stop Collection

    Arguments:
        wait (bool):   whether to wait for stopping to complete [False]

    Notes:
        In ARRAY mode, this will stop all the Time Series and the SIS.
        """
        if self._mode == ARRAY_MODE:
            for i in self._chans:
                self.put('Current%i:TSControl' % i, 2) # 'Stop'
        if self._sis is not None:
            self._sis.Stop()
        return self.put('Acquire', 0, wait=wait)

    def SaveArrayData(self, filename='tetramm_arrays.dat'):
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
        if self._sis is not None:
            sis_header = 'SIS %s' % self._sis.prefix
            names.insert(0, 'TSCALER')
            addrs.insert(0, self.sis_prefix + 'VAL')
            sdata.insert(0, self._sis.readmc(mca=1)/self._sis.clockrate)

        npts = len(sdata[0])
        sdata = np.array([s[:npts] for s in sdata]).transpose()

        nelem, nmca = sdata.shape
        npts = min(nelem, npts)

        addrs = ' | '.join(addrs)
        names = ' | '.join(names)
        formt = '%9i '  + '%9g ' * (nmca-1) + '\n'

        buff = [HEADER % (self._prefix, sis_header,
                          npts, nmca, addrs, names)]
        for i in range(npts):
            buff.append(formt % tuple(sdata[i]))
        buff.append()
        fout = open(filename, 'w')
        fout.write('\n'.join(buff))
        fout.close()
        return (nmca, npts)
