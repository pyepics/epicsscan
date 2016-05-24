#!/usr/bin/env python
"""
Support for QuadEM, especially TetrAMM model

"""
import time
import numpy
from epics import Device, poll

HEADER = '''# TetraAMM MCA data: %s
# Nchannels, Nmca = %i, %i
# Time in microseconds
#----------------------
# %s
# %s
'''

class TetrAMM(Device):
    """
    TetrAMM quad channel electrometer, version 2.9
    """

    attrs = ('Acquire',
             'AcquireMode',
             'Range',
             'ValuesPerReading',
             'SampleTime_RBV',
             'AveragingTime',
             'NumAcquire',
             'NumAcquired',
             'TriggerMode',
             'TriggerPolarity',
             'ReadFormat',
             'TS:TSAcquire',
             'TS:TSNumPoints',
             'TS:TSAveragingTime',
             'TS:TSAcquireMode',
             'TS:TSTimeAxis',
             )

    curr_attrs  = ('CurrentName%i',
                   'CurrentOffset%i',
                   'CurrentScale%i',
                   'Current%i:MeanValue_RBV',
                   'Current%i:Sigma_RBV',
                   'TS:Current%i:TimeSeries',
                   )


    _nonpvs  = ('_prefix', '_pvs', '_delim', '_chans',
               'clockrate')

    def __init__(self, prefix, nchan=4, clockrate=1.0):
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix
        self._chans = range(1, nchan+1)
        self.clockrate = clockrate # clock rate in seconds!

        attrs = list(self.attrs)
        for i in self._chans:
            for a in self.curr_attrs:
                attrs.append(a  % i)

        Device.__init__(self, prefix, delim='', attrs=attrs, mutable=False)
        self._aliases = {}
        for i in self._chans:
            self._aliases['Current%i'% i] = 'Current%i:MeanValue_RBV' % i
            self._aliases['Sigma%i'% i]   = 'Current%i:Sigma_RBV' % i
            self._aliases['Offset%i'% i]  = 'CurrentOffset%i' % i
            self._aliases['Scale%i'% i]   = 'CurrentScale%i' % i
            self._aliases['Name%i'% i]    = 'CurrentName%i' % i
            self._aliases['TimeSeries%i'% i] = 'TS:Current%i:TimeSeries' % i

        for attr in ('TS:TSAcquire', 'TS:TSNumPoints',
                     'TS:TSAveragingTime', 'TS:TSAcquireMode',
                     'TS:TSTimeAxis'):
            self._aliases[attr[3:]] = attr


    def AutoCountMode(self):
        "set to autocount mode"
        self.put('AcquireMode', 0)

    def OneShotMode(self):
        "set to one shot mode"
        self.put('AcquireMode', 2)
        self.put('NumAcquire', 1)

    def MultiplShotMode(self, n=1):
        "set to one shot mode"
        self.put('AcquireMode', 1)
        self.put('TSAcquireMode', 0) # fixed length
        self.put('NumAcquire', n)
        self.put('TSNumPoints', n)

    def CountTime(self, ctime, nreadings=None):
        "set count time, with nreadings (Values per internal read)"
        self.put('AveragingTime', ctime)
        self.put('TSAveragingTime', ctime)
        if nreadings is None:
            nreadings = max(10, min(10000, 100*ctime))
        self.put('ValuesPerRead', nreadings)

    def Count(self, ctime=None, wait=False):
        "set count, with optional counttime"
        if ctime is not None:
            self.CountTime(ctime)
        self.put('Acquire', 1, wait=wait)
        poll()

    def EnableCalcs(self):
        "enable calculations"
        pass

    def setCalc(self, i, calc):
        "set the calculation for channel i"
        raise NotImplementedException

    def setScale(self, i, scale=1.e9):
        "set current scale for channel i"
        attr = 'CurrentScale%i' % i
        return self.put(attr, scale)

    def setScale(self, i, offset=0.0):
        "set current offset for channel i"
        attr = 'CurrentOffset%i' % i
        return self.put(attr, offset)

    def _readattr(self, attr):
        return [self.get(attr % i) for i in self._chans]

    def getNames(self):
        "get all names"
        return self._readattr('CurrentName%i')

    def Read(self, i, use_calc=True):
        "read all values"
        return self._readattr('Current%i:MeanValue_RBV' % i)

    def ReadSigma(self, i):
        "read all sigma values"
        return self._readattr('Current%i:Sigma_RBV' % i)


    def ExternalMode(self, mode=2, **kws):
        """put TetrAMM in External Mode, with the following options:
        option            meaning                   default value
        ----------------------------------------------------------
        mode            triggermode                    0

        Modes are:
          0 internal
          1 external trigger
          2 external bulb
          3 external gate
        """
        return self.put('TriggerMode', mode)

    def InternalMode(self, **kws):
        "put TetrAMM in Internal Mode"
        return self.put('TriggerMode', 0)  # internal, Free Run

    def setPresetReal(self, val):
        "Set Preset Real Tiem"
        pass

    def setDwell(self, val):
        "Set Dwell Time"
        return self.put('AveragingTime', val)
        return self.put('TSAveragingTime', val)

    def setDwell(self, val):
        "Set Dwell Time"
        return self.put('AveragingTime', val)
        return self.put('TSAveragingTime', val)

    def start(self, wait=False, time_series=False):
        """start,  """
        return self.put('Acquire', 1, wait=wait)

    def stop(self, wait=False):
        "Stop Collection"
        return self.put('Acquire', 0, wait=wait)

    def mcaNread(self, nmca=1):
        "Read a TetrAMM TimeSeries"
        return self.get('TimeSeries%i' % nmca)

    def readmca(self, nmca=1, count=None):
        "Read a TetrAMM TimeSeries"
        return self.get('TimeSeries%i' % nmca, count=count)

    def read_all_mcas(self):
        return [self.readmca(nmca=i) for i in self._chans]

    def saveMCAdata(self, fname='Struck.dat', mcas=None,
                    ignore_prefix=None, npts=None):
        "save MCA spectra to ASCII file"
        sdata, names, addrs = [], [], []
        npts =  1.e99
        time.sleep(0.005)
        for nmca in self._chans:
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
        sdata[:, 0] = sdata[:, 0]/(self.clockrate)

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

if __name__ == '__main__':
    q = TetrAMM('13IDE:TetrAMM:')

    t0 = time.time()
    fmt = "%s  : [%.4f, %.4f, %.4f, %.4f]  [%.4f, %.4f, %.4f, %.4f] "
    while time.time() -t0 < 10000:

        print fmt % (time.ctime(),
                     q.Current1, q.Current2, q.Current3, q.Current4,
                     q.Sigma1, q.Sigma2, q.Sigma3, q.Sigma4)

        time.sleep(0.5)
