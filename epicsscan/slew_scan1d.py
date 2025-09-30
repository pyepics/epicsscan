#!/usr/bin/env python
"""
Slew Scan based on EpicsApps.StepScan.
"""
import sys
import os
import json
import shutil
import time
from threading import Thread
import numpy as np
from pyshortcuts import debugtimer

from .scan import StepScan
from .positioner import Positioner
from .saveable import Saveable

from .detectors import Struck, TetrAMM, Xspress3
from .detectors import (Counter, Trigger, AreaDetector, write_poni)
from .file_utils import fix_varname, fix_filename, increment_filename, new_filename
from .detectors.counter import ROISumCounter, EVAL4PLOT

from epics import PV, poll, get_pv, caget, caput
from newportxps import NewportXPS

class Slew_Scan1D(StepScan):
    """1D Slew Scan, presenting data as a plain scan"""
    def __init__(self, filename=None, auto_increment=True,
                 comments=None, messenger=None, scandb=None,
                 prescan_func=None, mkernel=None, **kws):

        StepScan.__init__(self, auto_increment=auto_increment,
                          comments=comments, messenger=messenger,
                          scandb=scandb, **kws)
        self.mkernel = mkernel
        self.scantype = 'slew'
        self.detmode  = 'roi'
        self.motor_vals = {}
        self.orig_positions = {}

    def prepare_scan(self):
        """prepare slew scan"""
        self.set_info('scan_progress', 'preparing')

        # ZeroFineMotors before map? not available
        self.scandb.set_info('qxafs_config', 'slew')
        self.scandb.set_info('qxafs_running', 0) # abort

        inner_pos = self.scandb.get_slewpositioner(self.inner[0])
        if inner_pos is not None:  # would be None for Time series
            conf = self.scandb.get_config_id(inner_pos.config_id)
            scnf = self.slewscan_config = json.loads(conf.notes)
            self.xps = NewportXPS(scnf['host'],
                                  username=scnf['username'],
                                  password=scnf['password'],
                                  group=scnf['group'],
                                  outputs=scnf['outputs'],
                                  extra_triggers=scnf.get('extra_triggers', 0))

            l_, pvs, start, stop, npts = self.inner
            pospv = pvs[0]
            if pospv.endswith('.VAL'):
                pospv = pospv[:-4]
            dirpv = pospv + '.DIR'
            if caget(dirpv) == 1:
                start, stop = stop, start
            step = abs(start-stop)/(npts-1)
            self.rowtime = dtime = self.dwelltime*(npts-1)

            axis = None
            for ax, pvname in self.slewscan_config['motors'].items():
                if pvname == pospv:
                    axis = ax

            if axis is None:
                raise ValueError("Could not find XPS Axis for %s" % pospv)

            self.xps.define_line_trajectories(axis, pixeltime=self.dwelltime,
                                              start=start, stop=stop,
                                              step=step)

            trajs = self.xps.trajectories
            self.motor_vals = {}
            self.orig_positions = {}
            for i, axes in enumerate(trajs['foreward']['axes']):
                pvname = self.slewscan_config['motors'][axes]
                v1, v2 = trajs['foreward']['start'][i], trajs['backward']['start'][i]
                thispv = PV(pvname)
                self.motor_vals[pvname] = (thispv, v1, v2)
                self.orig_positions[pvname] = thispv.get()

        else:
            npts = self.inner[4]
            self.rowtime = dtime = self.dwelltime * npts
            xvals = self.dwelltime * np.arange(npts)
            self.xps = None
            self.motor_vals = {}
            self.orig_positions = {}
            pvname = self.inner[1][1]
            thispv = PV(pvname)
            self.motor_vals[pvname] = (thispv, xvals, xvals)
            self.orig_positions[pvname] = thispv.get()

        self.comments = self.comments.replace('\n', ' | ')

        xrd_det = None
        xrf_det = None
        for det in self.detectors:
            if isinstance(det, AreaDetector):
                xrd_det = det
                self.set_info('xrd_1dint_status', 'starting')
                self.set_info('xrd_1dint_label', det.label)

            if 'xspress3' in det.label.lower():
                xrf_det = det

        for p in self.positioners:
            self.orig_positions[p.pv.pvname] = p.current()

        for det in self.detectors:
            try:
                det.stop()
            except AttributeError:
                pass
        return

    def post_scan(self):
        self.set_info('scan_progress', 'finishing')
        for pvname, val in self.orig_positions.items():
            caput(pvname, val)

        for m in self.post_scan_methods:
            m()

        for det in self.detectors:
            det.stop()
            det.disarm(mode=self.detmode)

    def run(self, filename='fscan.001', comments=None, debug=False, npts=None):
        """
        run a 1D slew scan
        """
        dtimer = debugtimer()
        debug = self.scandb.get_info('debug_scan', as_bool=True) or debug
        self.prepare_scan()

        self.filename = filename
        if self.filename is None:
            self.filename  = 'slewscan1d.001'
        self.filename = new_filename(self.filename)
        ts_start = time.monotonic()

        if self.xps is not None:
            trajs = self.xps.trajectories
            dir_off = 1
            tname = 'foreward'
            if trajs['foreward']['start'] >  trajs['foreward']['stop']:
                dir_off += 1
            if dir_off % 2 == 0:
                tname = 'backward'

            self.xps.arm_trajectory(tname)
            npulses = trajs[tname]['npulses'] + 1
            dwelltime = trajs[tname]['pixeltime']

            for p in self.positioners:
                p.move_to_pos(0, wait=False)

            for pv, v1, v2 in self.motor_vals.values():
                val = v1
                if tname == 'backward': val = v2
                pv.put(val, wait=False)
        else:
            dwelltime = self.dwelltime
            npulses = len(self.positioners[0].array) + 1
        npts = npulses - 1

        out = self.pre_scan(npulses=npulses, dwelltime=dwelltime, mode='roi',
                            filename=self.filename)
        self.check_outputs(out, msg='pre scan')
        self.clear_interrupts()
        self.scandb.clear_slewscanstatus()
        dim  = 1

        self.dwelltime_varys = False
        dtime = self.dwelltime
        estimated_scantime = npts*dtime
        dtimer.add('set dwelltime')
        self.set_info('scan_progress', 'preparing scan')
        extra_vals = []
        for desc, pv in self.extra_pvs:
            extra_vals.append((desc, pv.get(as_string=True), pv.pvname))

        # get folder name for full data from detectors
        fileroot = self.scandb.get_info('server_fileroot')
        userdir  = self.scandb.get_info('user_folder')
        xrfdir   = os.path.join(userdir, 'XAFSXRF')
        xrfdir_server = os.path.join(fileroot, xrfdir)
        if not os.path.exists(xrfdir_server):
            os.mkdir(xrfdir_server, mode=509)

        det_arm_delay = 0.1
        det_start_delay = 0.5
        det_prefixes = []
        for det in reversed(self.detectors):
            det_prefixes.append(det.prefix)
            det.arm(mode='roi', numframes=npulses, fnum=0, wait=False)
            # det.config_filesaver(path=xrfdir)
            det_arm_delay = max(det_arm_delay, det.arm_delay)
            det_start_delay = max(det_start_delay, det.start_delay)
        time.sleep(det_arm_delay)

        self.scandb.set_info('qxafs_config', 'slew')
        self.scandb.set_info('qxafs_running', 2) # running
        # wait for detectors to be armed
        tout = time.time()+5.0
        while not all([det.arm_complete for det in self.detectors]):
            if time.time() > tout:
                break
            time.sleep(0.01)

        dtimer.add('detectors armed %.4f / %.4f' % (det_arm_delay, det_start_delay))
        self.init_scandata()
        dtimer.add('init scandata')
        if self.xps is None:  # internal Time Series
            wait_pv = None
            for det in self.detectors:
                if det.label == 'mcs':
                    det.mcs._pvs['ChannelAdvance'].put(0)
                    det.mcs._pvs['Dwell'].put(self.dwelltime)
                    wait_pv = det.mcs._pvs['Acquiring']

        for det in reversed(self.detectors):
            det.start(arm=False, wait=False)

        time.sleep(det_start_delay)
        dtimer.add('detectors started')

        self.datafile = self.open_output_file(filename=self.filename,
                                              comments=self.comments)

        self.datafile.write_data(breakpoint=0)
        dtimer.add('datafile opened')
        self.filename =  self.datafile.filename

        self.scandb.set_filename(self.filename)
        self.set_info('request_abort', 0)
        self.set_info('scan_time_estimate', npts*dtime)
        self.set_info('scan_total_points', npts)

        self.datafile.flush()
        self.set_info('scan_progress', 'starting scan')
        self.cpt = 0
        self.npts = npts

        # ts_init = time.monotonic()
        # self.inittime = ts_init - ts_start
        start_time = time.strftime('%Y-%m-%d %H:%M:%S')
        dtimer.add('info set')
        time.sleep(0.500)
        if self.xps is not None:
            dtimer.add('xps trajectory run')
            out = self.xps.run_trajectory(name=tname, save=False)
            dtimer.add('trajectory finished')
        else:
            t0 = time.time()
            time.sleep(self.dwelltime*2.0)
            if wait_pv  is not None:
                done = (wait_pv.get() == 0)
                while not done:
                    time.sleep(self.dwelltime/2)
                    done = (wait_pv.get() == 0)
                    if (time.time() - t0 ) > 3*self.dwelltime*npts:
                        done = True
            # print('Time Series appears done')

        self.set_info('scan_progress', 'reading data')
        # print("Slew1d done")
        for det in self.detectors:
            det.stop()

        dtimer.add('detectors stopped')
        dtimer.add('scan finished')
        #
        if self.xps is not None:
            npulses, gather_text = self.xps.read_gathering()
            xvals = self.gathering2xvals(gather_text)
        else:
            pvname = self.inner[1][1]
            pv, xvals, _xvals = self.motor_vals[pvname]
        self.pos_actual = []
        for x in xvals:
           self.pos_actual.append([x])
        nx = len(xvals)
        #
        [c.read() for c in self.counters]
        ndat = [len(c.buff[1:]) for c in self.counters]
        narr = min(ndat)
        t0  = time.monotonic()
        while narr < (nx-1) and (time.monotonic()-t0) < 5.0:
            time.sleep(0.05)
            [c.read() for c in self.counters]
            ndat = [len(c.buff[1:]) for c in self.counters]
            narr = min(ndat)

        mca_offsets = {}
        counter_buffers = []
        for c in self.counters:
            label = c.label.lower()
            if 'mca' in label and 'clock' in label:
                buff = np.array(c.read())
                offset = 1
                if buff[0] == 0 and buff[1] > 1.10*(buff[2:-1].mean()):
                    offset = 2
                key = label.replace('clock', '').strip()
                mca_offsets[key] = offset

        dtimer.add('read all counters (done)')
        # remove hot first pixel AND align to proper x values
        data4calcs = {}
        for c in self.counters:
            offset = 1
            label = c.label.lower()
            if 'mca' in label:
                words = label.split()
                key = ' '
                for word in words:
                    if word.startswith('mca'):
                        key = word
                offset = mca_offsets.get(key, 1)
            c.buff = c.buff[offset:]
            c.buff = c.buff[:nx]
            # print("-> ", c.label, offset, len(c.buff), c.buff[:3], c.buff[-2:])

            data4calcs[c.pvname] = np.array(c.buff)

        for c in self.counters:
            if c.pvname.startswith(EVAL4PLOT):
                _counter = eval(c.pvname[len(EVAL4PLOT):])
                _counter.data = data4calcs
                c.buff = _counter.read()

        self.set_all_scandata()
        dtimer.add('set scan data')

        self.datafile.write_data(breakpoint=-1, close_file=True, clear=False)
        time.sleep(0.05)
        if self.look_for_interrupts():
            self.write("scan aborted at point %i of %i." % (self.cpt, self.npts))

        out = self.post_scan()
        dtimer.add('post scan finished')
        self.check_outputs(out, msg='post scan')

        self.complete = True
        self.set_info('scan_progress',
                      'scan complete. Wrote %s' % self.datafile.filename)
        self.scandb.set_info('qxafs_running', 0)
        self.runtime  = time.monotonic() - ts_start
        dtimer.add('done')
        # dtimer.show()
        print("scan1d done at %s " % (time.ctime()))
        return self.datafile.filename
        ##

    def gathering2xvals(self, text):
        """read gathering file, calculate and return
        energy and height. Gathering data is text with columns of
         Theta_Current, Theta_Set, Height_Current, Height_Set
        """
        xvals = []
        for line in text.split('\n'):
            line = line[:-1].strip()
            if len(line) > 4:
                words = line[:-1].split()
                xvals.append(float(words[0]))

        xvals = np.array(xvals)
        return (xvals[1:] + xvals[:-1])/2.0


    def check_beam_ok(self):
        return True

    def save_envdata(self,filename='Environ.dat'):
        buff = []
        for desc, pvname, value in self.read_extra_pvs():
            buff.append("; %s (%s) = %s" % (desc, pvname, value))
        buff.append("")
        with open(filename,'w') as fh:
            fh.write('\n'.join(buff))
        fh.close()
