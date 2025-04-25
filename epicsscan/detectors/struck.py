#!/usr/bin/env python
"""
Struck SIS3820
"""
import os
import sys
import time
import copy
import numpy
import asteval
from epics import Device, caget
from epics.devices.scaler import Scaler
from epics.devices.mca import MCA

from .counter import DeviceCounter
from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE

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
               'clockrate', 'scaler', 'mcas', 'ast_interp', 'scaler_config')

    def __init__(self, prefix, scaler=None, nchan=8, clockrate=50.0):
        self._nchan = nchan
        self.scaler = None
        self.clockrate = clockrate # clock rate in MHz
        self._mode = SCALER_MODE

        if scaler is not None:
            self.scaler = Scaler(scaler, nchan=nchan)

        self.mcas = []
        for i in range(nchan):
            self.mcas.append(MCA(prefix, mca=i+1, nrois=2))

        Device.__init__(self, prefix, delim='',
                        attrs=self.attrs, mutable=False)

        time.sleep(0.05)
        for pvname, pv in self._pvs.items():
            pv.get()

        self.ast_interp = asteval.Interpreter()
        self.scaler_config = self.read_scaler_config()

    def ExternalMode(self, countonstart=None, initialadvance=None,
                     realtime=0, prescale=1, trigger_width=None):
        """put Struck in External Mode, with the following options:
        option            meaning                   default value
        ----------------------------------------------------------
        countonstart    set Count on Start             None
        initialadvance  set Initial Channel Advance    None
        reatime         set Preset Real Time           0
        prescale        set Prescale value             1
        trigger_width   set trigger width in sec       None

        here, `None` means "do not change from current value"
        """
        t0 = time.time()
        if self.scaler is not None:
            self.scaler.put('CONT', 0)

        out = self.put('ChannelAdvance', 1)  # external
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
        time.sleep(0.002)
        return out

    def InternalMode(self, prescale=None):
        "put Struck in Internal Mode"
        out = self.put('ChannelAdvance', 0)  # internal
        if self.scaler is not None:
            self.scaler.put('CNT',  0, wait=True)
            time.sleep(0.01)
            self.scaler.put('CONT', 0, wait=True)
        if prescale is not None:
            self.put('Prescale', prescale)
        time.sleep(0.01)
        return out

    def set_dwelltime(self, val):
        "Set Dwell Time"
        if isinstance(val, (list, tuple, numpy.ndarray)):
            val = val[0]
        if val is not None:
            self.put('Dwell', val)

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
            self.put('NuseAll', numframes, wait=False)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        if self.scaler is not None:
            time.sleep(0.025)
            self.scaler.put('CONT', 0, wait=True)
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
            self.put('NuseAll', numframes, wait=True)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        if self.scaler is not None:
            self.scaler.put('CONT', 0, wait=True)
        self._mode = SCALER_MODE

    def NDArrayMode(self, dwelltime=None, numframes=None, countonstart=True,
                    trigger_width=None):
        """ set to array mode: ready for slew scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None or int):   number of frames to collect [8192]
        countonstart (None or bool):  whether to count on start [True]
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

        time.sleep(0.01)
        self.ExternalMode(trigger_width=trigger_width,
                          countonstart=countonstart)

    def ROIMode(self, dwelltime=None, numframes=None, countonstart=True,
                trigger_width=None):
        """set to ROI mode: ready for slew scanning"""
        self.NDArrayMode(dwelltime=dwelltime, numframes=numframes,
                         countonstart=countonstart, trigger_width=trigger_width)


    def start(self, wait=False):
        "Start Struck"
        if self.scaler is not None:
            self.scaler.put('CONT', 0) # , wait=True)

        espv = self.PV('EraseStart')
        return espv.put(1, wait=wait)

    def stop(self):
        "Stop Struck Collection: is sometimes not reliable"
        self.put('StopAll', 1)
        time.sleep(0.010)
        for i in range(3):
            if self.get('Acquiring'):
                if self.scaler is not None:
                    self.scaler.put('CNT', 0, wait=False)# True)
                    time.sleep(0.010)
                self.put('StopAll', 1)
            if self.get('Acquiring'):
                time.sleep(0.01 * (i+1))
        return

    def erase(self):
        "Start Struck"
        return self.put('EraseAll', 1)

    def mcaNread(self, nmcas=1):
        "Read a Struck MCA"
        return self.get('mca%i.NORD' % nmcas)

    def readmca(self, nmca=1, count=None):
        "Read a Struck MCA"
        return self.get('mca%i' % nmca, count=count)

    def read_all_mcas(self):
        return [self.readmca(nmca=i+1) for i in range(self._nchan)]

    def read_scaler_config(self):
        """read names and calcs for scaler channels"""
        if self.scaler is None:
            return []
        conf = []
        for n in range(1, self._nchan+1):
            name = self.scaler.get('NM%i' % n).strip()
            if len(name) > 0:
                name = name.strip().replace(' ', '_')
                calc = self.scaler.get('expr%i' % n)
                conf.append((n, name, calc))
        return conf

    def save_arraydata(self, filename='sis.dat', npts=None, **kws):
        "save MCA spectra to ASCII file"
        nmcas, npts, names, headers, fmts, sdata = self.get_arraydata(npts=npts)
        buff = ['# Struck MCA data: %s' % self._prefix,
                '# Nchannels, Nmcas = %i, %i' % (npts, nmcas),
                '# Time in microseconds']

        buff.extend(headers)
        buff.append("#%s" % ("-"*60))
        buff.append("# %s" % ' | '.join(names))

        fmt  = ''.join(fmts)
        for i in range(npts):
            buff.append(fmt.format(*sdata[i]))
        buff.append('')
        fout = open(filename, 'w')
        fout.write("\n".join(buff))
        fout.close()
        return (nmcas, npts)

    def get_arraydata(self, npts=None, **kws):
        "save MCA spectra to ASCII file"
        t0 = time.time()
        rdata, sdata, names, calcs, fmts = [], [], [], [], []
        headers = []
        if npts is None:
            npts = self.NuseAll
        npts_req = npts
        avars = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
        avars = ['A', 'B', 'C', 'D']
        adat = {}
        for name in avars:
            self.ast_interp.symtable[name] = adat[name] = numpy.zeros(npts)
        scaler_config = self.read_scaler_config()

        # read MCAs until all data have a consistent length (up to ~2 seconds)
        t0 = time.time()
        time.sleep(0.005)
        waiting_for_data = True
        while waiting_for_data:
            npts_chan = []
            for nchan, name, calc in scaler_config:
                dat = self.readmca(nmca=nchan)
                if (dat is None or not isinstance(dat, numpy.ndarray)):
                    dat = []
                npts_chan.append(len(dat))
            if npts_req is None:
                npts_req = npts_chan[0]
            waiting_for_data = (npts_req-npts_chan[0]) > 3
            waiting_for_data = waiting_for_data or (max(npts_chan) != min(npts_chan))
            waiting_for_data = waiting_for_data and (time.time() < (t0+2.0))

        # print("SIS read time = %.3f" % (time.time()-t0))

        if max(npts_chan) != min(npts_chan):
            print(" Struck warning, inconsistent number of points!")
            print(" -- ", npts_chan)

        # make sure all data is the same length for calcs
        npts = min(npts, min(npts_chan))

        # final read
        icol = 0
        hformat = "# Column.%i: %16s | %s"
        calcs_map = {}
        for nchan, name, calc in scaler_config:
            icol += 1
            dat = self.readmca(nmca=nchan)
            varname = avars[nchan-1]
            adat[varname] = dat
            label = "%s | %s" % ("%smca%i" % (self._prefix, nchan), varname)
            if icol == 1 or len(calc) > 1:
                if icol == 1:
                    calc = 'A / 50.0'
                label = "calculated | %s" % calc
                rdata.append(("%s_raw" % name, nchan, varname, dat))

            headers.append(hformat % (icol, name, label))
            names.append(name)
            calcs.append(calc)
            calcs_map["%s_raw" % name] = varname
            calcs_map[name] = calc
            fmt = ' {:14f} '
            if icol == 1:
                fmt = ' {:14.2f} '
            fmts.append(fmt)

        for key, val in adat.items():
            try:
                self.ast_interp.symtable[key] = val[:npts]
            except TypeError:
                self.ast_interp.symtable[key] = val

        for calc in calcs:
            result = self.ast_interp.eval(calc)
            if result is None:
                result = numpy.zeros(1)
            sdata.append(result)


        for name, nchan, varname, rdat in rdata:
            icol += 1
            label = "%s | %s" % ("%smca%i" % (self._prefix, nchan), varname)
            headers.append(hformat % (icol, name, label))
            names.append(name)
            sdata.append(rdat)
            fmts.append(' {:10.0f} ')

        try:
            sdata = numpy.array([s[:npts] for s in sdata]).transpose()
            npts, nmcas = sdata.shape
        except:
            return (0, 0, names, headers, fmts, sdata)
        #print("SIS Calc: RETURN ", nmcas, npts, names, headers, fmts, sdata.shape)
        return (nmcas, npts, names, headers, fmts, sdata)


class StruckCounter(DeviceCounter):
    """Counter for Struck"""
    invalid_device_msg = 'StruckCounter must use an Epics Scaler'
    def __init__(self, prefix, scaler=None, outpvs=None, nchan=8,
                 use_calc=True, use_unlabeled=False):
        DeviceCounter.__init__(self, prefix)
        fields = [] # ('.T', 'CountTime')]
        extra_pvs = []
        nchan = int(nchan)
        if scaler is not None:
            for i in range(1, nchan+1):
                label = caget('%s.NM%i' % (scaler, i))
                if label is None:
                    time.sleep(0.1)
                    label = caget('%s.NM%i' % (scaler, i))
                    if label is None:
                        label = ''
                if len(label) > 0 or use_unlabeled:
                    suff = 'mca%i' % (i)
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
        self.arm_delay = 0.025
        self.start_delay = 0.025
        self.struck = Struck(prefix, scaler=scaler, nchan=nchan)
        DetectorMixin.__init__(self, prefix, **kws)
        self.label = label

        self.dwelltime_pv = self.struck._pvs['Dwell']
        self._counter = StruckCounter(prefix, scaler=scaler,
                                      nchan=nchan, use_calc=True)
        self.counters = self._counter.counters
        time.sleep(0.01)
        scaler_conf = self.struck.read_scaler_config()
        for c in self.counters:
            if c.label.lower() in ('tscaler', 'time'):
                c.units = 'microseconds'
            for (i, label, expr) in scaler_conf:
                if c.label == label:
                    c.extra_label = expr


    def pre_scan(self, mode=None, npulses=None, dwelltime=None, **kws):
        "run just prior to scan"
        self.struck.stop()
        self.struck.InternalMode()
        time.sleep(0.05)

        self.arm(mode=mode, numframes=npulses)
        self.counters = self._counter.counters
        if dwelltime is not None:
            self.dwelltime = dwelltime
        self.struck.set_dwelltime(self.dwelltime)
        if npulses is not None:
            self.struck.put('NuseAll', npulses)

    def apply_offsets(self):
        nmcas, npts, names, headers, fmts, sdata = self.struck.get_arraydata()
        for counter in self.counters:
            if counter.label in names:
                ix = names.index(counter.label)
                counter.net_buff = sdata[:, ix]

    def arm(self, mode=None, fnum=None, wait=True, numframes=None):
        "arm detector, ready to collect with optional mode"
        # print("Struck Arm: ", mode, numframes)
        if mode is not None:
            self.mode = mode
        if fnum is not None:
            self.fnum = fnum
        if self.mode == SCALER_MODE:
            self.struck.ScalerMode()
        elif self.mode == ROI_MODE:
            self.struck.ROIMode(numframes=numframes)
        elif self.mode == NDARRAY_MODE:
            self.struck.NDArrayMode(numframes=numframes)
        if wait:
            time.sleep(self.arm_delay)

    def ContinuousMode(self, **kws):
        self.struck.ContinuousMode(**kws)

    def start(self, mode=None, arm=False, wait=True):
        "start detector, optionally arming and waiting"
        t0 = time.time()
        if arm:
            self.arm(mode=mode, wait=wait)
        self.struck.start(wait=wait)
        if wait:
            time.sleep(self.start_delay)

    def stop(self, disarm=False):
        "stop detector"
        self.struck.stop()
        if disarm:
            self.struck.InternalMode()

    def disarm(self, mode=None, wait=False):
        self.struck.stop()
        self.struck.InternalMode()

    def post_scan(self, **kws):
        "run just after scan"
        self.disarm()

    def save_arraydata(self, filename=None, npts=None):
        if filename is not None:
            return self.struck.save_arraydata(filename=filename, npts=npts)
        return None

    def config_filesaver(self, **kws):
        "configure filesaver"
        pass
