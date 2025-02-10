#!/usr/bin/env python
from __future__ import print_function

MODDOC = """
=== Epics Scanning ===


This does not used the Epics SScan Record, and the scan is intended to run
as a python application, but many concepts from the Epics SScan Record are
borrowed.  Where appropriate, the difference will be noted here.

A Step Scan consists of the following objects:
   a list of Positioners
   a list of Triggers
   a list of Counters

Each Positioner will have a list (or numpy array) of position values
corresponding to the steps in the scan.  As there is a fixed number of
steps in the scan, the position list for each positioners must have the
same length -- the number of points in the scan.  Note that, unlike the
SScan Record, the list of points (not start, stop, step, npts) must be
given.  Also note that the number of positioners or number of points is not
limited.

A Trigger is simply an Epics PV that will start a particular detector,
usually by having 1 written to its field.  It is assumed that when the
Epics ca.put() to the trigger completes, the Counters associated with the
triggered detector will be ready to read.

A Counter is simple a PV whose value should be recorded at every step in
the scan.  Any PV can be a Counter, including waveform records.  For many
detector types, it is possible to build a specialized class that creates
many counters.

Because Triggers and Counters are closely associated with detectors, a
Detector is also defined, which simply contains a single Trigger and a list
of Counters, and will cover most real use cases.

In addition to the core components (Positioners, Triggers, Counters, Detectors),
a Step Scan contains the following objects:

   breakpoints   a list of scan indices at which to pause and write data
                 collected so far to disk.
   extra_pvs     a list of (description, PV) tuples that are recorded at
                 the beginning of scan, and at each breakpoint, to be
                 recorded to disk file as metadata.
   pre_scan()    method to run prior to scan.
   post_scan()   method to run after scan.
   at_break()    method to run at each breakpoint.

Note that Postioners and Detectors may add their own pieces into extra_pvs,
pre_scan(), post_scan(), and at_break().

With these concepts, a Step Scan ends up being a fairly simple loop, going
roughly (that is, skipping error checking) as:

   pos = <DEFINE POSITIONER LIST>
   det = <DEFINE DETECTOR LIST>
   run_pre_scan(pos, det)
   [p.move_to_start() for p in pos]
   record_extra_pvs(pos, det)
   for i in range(len(pos[0].array)):
       [p.move_to_pos(i) for p in pos]
       while not all([p.done for p in pos]):
           time.sleep(0.001)
       [trig.start() for trig in det.triggers]
       while not all([trig.done for trig in det.triggers]):
           time.sleep(0.001)
       [det.read() for det in det.counters]

       if i in breakpoints:
           write_data(pos, det)
           record_exrta_pvs(pos, det)
           run_at_break(pos, det)
   write_data(pos, det)
   run_post_scan(pos, det)

Note that multi-dimensional mesh scans over a rectangular grid is not
explicitly supported, but these can be easily emulated with the more
flexible mechanism of unlimited list of positions and breakpoints.
Non-mesh scans are also possible.

A step scan can have an Epics SScan Record or StepScan database associated
with it.  It will use these for PVs to post data at each point of the scan.
"""
import os
import sys
import shutil
import time
from threading import Thread
import json
import numpy as np
import random

from .file_utils import fix_varname, fix_filename, increment_filename

from epics import PV, poll, get_pv, caget, caput

from .utils import hms
from .detectors import (Counter, Trigger, AreaDetector, SCALER_MODE)
from .datafile import ASCIIScanFile
from .positioner import Positioner

from .debugtime import debugtime

MIN_POLL_TIME = 1.e-3

class ScanPublisher(Thread):
    """ Provides a way to run user-supplied functions per scan point,
    in a separate thread, so as to not delay scan operation.

    Initialize a ScanPublisher with a function to call per point, and the
    StepScan instance.  On .start(), a separate thread will createrd and
    the .run() method run.  Here, this runs a loop, looking at the .cpt
    attribute.  When this .cpt changes, the executing will run the user
    supplied code with arguments of 'scan=scan instance', and 'cpt=cpt'

    Thus, at each point in the scan the scanning process should set .cpt,
    and the user-supplied func will execute.

    To stop the thread, set .cpt to None.  The thread will also automatically
    stop if .cpt has not changed in more than 1 hour
    """
    # number of seconds to wait for .cpt to change before exiting thread
    timeout = 3600.
    def __init__(self, func=None, scan=None, cpt=-1, npts=None, func_kws=None):
        Thread.__init__(self)
        self.func = func
        self.cpt = cpt
        self.func_kws = func_kws or {}
        self.func_kws.update({'npts': npts, 'scan': scan})

    def run(self):
        """execute thread, watching the .cpt attribute. Any chnage will
        cause self.func(cpt=self.cpt, scan=self.scan) to be run.
        The thread will stop when .pt == None or has not changed in
        a time  > .timeout
        """
        last_point = self.cpt
        t0 = time.time()

        while True:
            poll(MIN_POLL_TIME, 0.25)
            if self.cpt != last_point:
                last_point =  self.cpt
                t0 = time.time()
                if self.cpt is not None and hasattr(self.func, '__call__'):
                    self.func(cpt=self.cpt, **self.func_kws)
            if self.cpt is None or time.time()-t0 > self.timeout:
                return

class StepScan(object):
    """
    General Step Scanning for Epics
    """
    def __init__(self, filename=None, auto_increment=True, comments=None,
                 messenger=None, data_callback=None, scandb=None,
                 prescan_func=None, postscan_func=None, mkernel=None, **kws):

        self.pos_settle_time = MIN_POLL_TIME
        self.det_settle_time = MIN_POLL_TIME
        self.pos_maxmove_time = 3600.0
        self.det_maxcount_time = 86400.0
        self.dwelltime = None
        self.dwelltime_varys = False
        self.comments = comments
        self.filename = filename
        self.auto_increment = auto_increment
        self.filetype = 'ASCII'
        self.scantype = 'linear'
        self.detmode  = SCALER_MODE
        self.scandb = scandb
        self.mkernel = mkernel
        self.prescan_func = prescan_func
        self.postscan_func = postscan_func
        self.verified = False
        self.abort = False
        self.pause = False
        self.inittime = 0 # time to initialize scan (pre_scan, move to start, begin i/o)
        self.looptime = 0 # time to run scan loop (even if aborted)
        self.exittime = 0 # time to complete scan (post_scan, return positioners, complete i/o)
        self.runtime  = 0 # inittime + looptime + exittime
        self.last_error_msg = ''
        self.messenger = messenger or sys.stdout.write
        self.data_callback = data_callback
        self.publish_thread = None

        if filename is not None:
            self.datafile = self.open_output_file(filename=filename,
                                                  comments=comments)
        self.cpt = 0
        self.npts = 0
        self.complete = False
        self.debug = False
        self.message_points = 25
        self.extra_pvs = []
        self.positioners = []
        self.triggers = []
        self.counters = []
        self.detectors = []

        self.breakpoints = []
        self.at_break_methods = []
        self.pre_scan_methods = []
        self.post_scan_methods = []
        self.pos_actual  = []
        self.orig_positions = {}
        self.dtimer = debugtime()

    def set_info(self, attr, value):
        """set scan info to _scan variable"""
        if self.scandb is not None:
            self.scandb.set_info(attr, value)
            self.scandb.set_info('heartbeat', time.ctime())

    def open_output_file(self, filename=None, comments=None):
        """opens the output file"""
        creator = ASCIIScanFile
        # if self.filetype == 'ASCII':
        #     creator = ASCIIScanFile
        if filename is not None:
            self.filename = filename
        if comments is not None:
            self.comments = comments

        return creator(name=self.filename,
                       auto_increment=self.auto_increment,
                       comments=self.comments, scan=self)

    def add_counter(self, counter, label=None):
        "add simple counter"
        if isinstance(counter, str):
            counter = Counter(counter, label)
        if counter not in self.counters:
            self.counters.append(counter)
        self.verified = False

    def add_trigger(self, trigger, label=None, value=1):
        "add simple detector trigger"
        if trigger is None:
            return
        if isinstance(trigger, str):
            trigger = Trigger(trigger, label=label, value=value)
        if trigger not in self.triggers:
            self.triggers.append(trigger)
        self.verified = False

    def add_extra_pvs(self, extra_pvs):
        """add extra pvs (tuple of (desc, pvname))"""
        if extra_pvs is None or len(extra_pvs) == 0:
            return
        for desc, pvname in extra_pvs:
            if isinstance(pvname, PV):
                pv = pvname
            else:
                pv = get_pv(pvname)

            if (desc, pv) not in self.extra_pvs:
                self.extra_pvs.append((desc, pv))

    def add_positioner(self, pos):
        """ add a Positioner """
        self.add_extra_pvs(pos.extra_pvs)
        self.at_break_methods.append(pos.at_break)
        self.post_scan_methods.append(pos.post_scan)
        self.pre_scan_methods.append(pos.pre_scan)

        if pos not in self.positioners:
            self.positioners.append(pos)
        self.verified = False

    def add_detector(self, det):
        """ add a Detector -- needs to be derived from Detector_Mixin"""
        rois = getattr(self, 'rois', getattr(det, 'rois', None))
        if rois is not None:
            det.rois = self.rois = rois
        # if det.extra_pvs is None: # not fully connected!
        det.mode = self.detmode
        det.connect_counters()
        time.sleep(0.025)

        self.add_extra_pvs(det.extra_pvs)
        self.at_break_methods.append(det.at_break)
        self.post_scan_methods.append(det.post_scan)
        self.pre_scan_methods.append(det.pre_scan)
        self.add_trigger(det.trigger)
        for counter in det.counters:
            self.add_counter(counter)
        if det not in self.detectors:
            self.detectors.append(det)
        self.verified = False

    def set_dwelltime(self, dtime=None):
        """set scan dwelltime per point to constant value"""
        if dtime is not None:
            self.dwelltime = dtime
        for d in self.detectors:
            d.set_dwelltime(self.dwelltime)

    def at_break(self, breakpoint=0, clear=False):
        out = [m(breakpoint=breakpoint) for m in self.at_break_methods]
        if self.datafile is not None:
            self.datafile.write_data(breakpoint=breakpoint)
        if self.mkernel is not None:
            try:
                self.mkernel.run("pre_scan_command()")
            except:
                self.write("Failed to run pre_scan_command()\n")
        return out

    def pre_scan(self, row=0, filename=None, **kws):
        dtimer = debugtime()
        self.set_info('scan_progress', 'running pre_scan routines')
        for (desc, pv) in self.extra_pvs:
            pv.connect(timeout=0.1)

        dtimer.add('pre_scan connect to extra pvs')
        if filename is None:
            filename = self.filename
        kws['filename'] = filename
        kws['dwelltime'] = self.dwelltime
        if isinstance(kws['dwelltime'], (list, tuple, np.ndarray)):
            kws['dwelltime'] = self.dwelltime[0]
        out = []
        for meth in self.pre_scan_methods:
            out.append(meth(scan=self, row=row, **kws))
            time.sleep(0.025)
            dtimer.add('pre_scan ran %s' % meth)

        for det in self.detectors:
            for counter in det.counters:
                self.add_counter(counter)
            dtimer.add('pre_scan add counters for %s' % det)

        if callable(self.prescan_func):
            try:
                ret = self.prescan_func(scan=self, row=row, **kws)
            except:
                ret = None
            out.append(ret)
        dtimer.add('pre_scan ran local prescan')
        if self.mkernel is not None:
            try:
                self.mkernel.run("pre_scan_command(row=%i)" % row)
            except:
                self.write("Failed to run pre_scan_command()\n")
        dtimer.add('pre_scan ran macro prescan')
        # dtimer.show()
        return out

    def post_scan(self, row=0, filename=None, **kws):
        self.set_info('scan_progress', 'running post_scan routines')
        if filename is None:
            filename = self.filename
        kws['filename'] = filename
        out = []

        for pvname, val in self.orig_positions.items():
            caput(pvname, val, wait=False)

        for meth in self.post_scan_methods:
            out.append(meth(scan=self, row=row, **kws))

        for det in self.detectors:
            det.stop(disarm=True)

        if callable(self.postscan_func):
            try:
                ret = self.postscan_func(scan=self, row=row, **kws)
            except:
                ret = None
            out.append(ret)

        if self.mkernel is not None:
            try:
                self.mkernel.run(f"post_scan_command(row={row})")
            except:
                self.write("Failed to run post_scan_command()\n")
        self.set_info('scan_progress', 'finishing')
        return out

    def verify_scan(self):
        """ this does some simple checks of Scans, checking that
        the length of the positions array matches the length of the
        positioners array.

        For each Positioner, the max and min position is checked against
        the HLM and LLM field (if available)
        """
        npts = None
        for pos in self.positioners:
            if not pos.verify_array():
                self.set_error('Positioner {0} array out of bounds'.format(
                    pos.pv.pvname))
                return False
            if npts is None:
                npts = len(pos.array)
            if len(pos.array) != npts:
                self.set_error('Inconsistent positioner array length')
                return False
        return True


    def check_outputs(self, out, msg='unknown'):
        """ check outputs of a previous command
            Any True value indicates an error
        That is, return values must be None or evaluate to False
        to indicate success.
        """
        if not isinstance(out, (tuple, list)):
            out = [out]
        if any(out):
            raise Warning('error on output: %s' % msg)

    def read_extra_pvs(self):
        "read values for extra PVs and 'extra_pvs' values from database"
        out = []
        if self.scandb is None:
            return out
        db_prefix = self.scandb.get_info('extra_pvs_prefix')
        if len(db_prefix) > 0:
            prefix = fix_varname(db_prefix).title()
            for key, row in self.scandb.get_info(prefix=db_prefix,
                                            order_by='display_order',
                                            full_row=True).items():
                notes = row.notes
                if notes is None or len(notes) < 1:
                    notes = 'unknown'
                desc = prefix + '.' + fix_varname(notes.title())
                out.append((desc, row.key, row.value))

        for desc, pv in self.extra_pvs:
            out.append((desc, pv.pvname, pv.get(as_string=True)))
        return out

    def clear_data(self):
        """clear scan data"""
        for c in self.counters:
            c.clear()
        self.pos_actual = []

    def publish_data(self, cpt, npts=0, scan=None, **kws):
        """function to publish data:

        this will be called per point by an non-blocking thread
        """
        time_left = (npts-cpt)* (self.pos_settle_time + self.det_settle_time)
        if self.dwelltime_varys:
            time_left += self.dwelltime[cpt:].sum()
        else:
            time_left += (npts-cpt)*self.dwelltime

        self.set_info('scan_time_estimate', time_left)
        time_est  = hms(time_left)

        if cpt < 4 and self.scandb is not None:
            self.scandb.set_filename(self.filename)

        msg = 'Point %i/%i,  time left: %s' % (cpt, npts, time_est)
        self.set_info('scan_progress', msg)
        if cpt % self.message_points == 0:
            self.messenger("%s\n" % msg)

        if not self.publishing_scandata:
            self.set_all_scandata()
        if callable(self.data_callback):
            self.data_callback(scan=self, cpt=cpt, npts=npts, **kws)

    def set_all_scandata(self):
        self.publishing_scandata = True
        if self.scandb is not None:
            for c in self.counters:
                name = getattr(c, 'db_label', None)
                if name is None:
                    name = c.label
                c.db_label = fix_varname(name)
                self.scandb.set_scandata(c.db_label, c.buff)
        self.publishing_scandata = False

    def init_scandata(self):
        if self.scandb is None:
            return
        self.scandb.clear_scandata()

        time.sleep(0.025)
        names = []
        npts = len(self.positioners[0].array)
        for p in self.positioners:
            try:
                units = p.pv.units
            except:
                units = 'unknown'

            name = fix_varname(p.label)
            if name in names:
                name += '_2'
            if name not in names:
                # print("ADD SCAN DATA POS ", name, p.array)
                self.scandb.add_scandata(name, p.array.tolist(),
                                         pvname=p.pv.pvname,
                                         units=units, notes='positioner')
                names.append(name)
        for c in self.counters:
            units = getattr(c, 'units', None)
            if units is None and hasattr(c, 'pv'):
                try:
                    units = c.pv.units
                except:
                    units = None
            if units is None:
                units = 'counts'

            name = fix_varname(c.label)
            pvname = getattr(c, 'pvname', name)
            if name in names:
                name += '_2'
            if name not in names:
                # print("ADD SCAN DATA DET ", name, pvname)
                self.scandb.add_scandata(name, [],
                                         pvname=pvname,
                                         units=units, notes='counter')
                names.append(name)

    def set_error(self, msg):
        """set scan error message"""
        self.last_error_msg = msg
        if self.scandb is not None:
            self.set_info('last_error', msg)

    def get_infobool(self, key):
        if self.scandb is not None:
            return self.scandb.get_info(key, as_bool=True)
        return False

    def look_for_interrupts(self):
        """set interrupt requests:

        abort / pause / resume
        if scandb is being used, these are looked up from database.
        """
        self.abort  = self.get_infobool('request_abort')
        self.pause  = self.get_infobool('request_pause')
        self.resume = self.get_infobool('request_resume')
        return self.abort

    def write(self, msg):
        self.messenger(msg)

    def clear_interrupts(self):
        """re-set interrupt requests:

        abort / pause / resume

        if scandb is being used, these are looked up from database.
        """
        self.abort = self.pause = self.resume = False
        self.set_info('request_abort', 0)
        self.set_info('request_pause', 0)
        self.set_info('request_resume', 0)


    def estimate_scan_time(self):
        "estimate scan time"
        self.pos_settle_time = max(MIN_POLL_TIME, self.pos_settle_time)
        self.det_settle_time = max(MIN_POLL_TIME, self.det_settle_time)
        npts = self.npts = len(self.positioners[0].array)
        # print('est time ', npts, self.dwelltime)
        self.dwelltime_varys = False
        if self.dwelltime is not None:
            self.min_dwelltime = self.dwelltime
            self.max_dwelltime = self.dwelltime
            if isinstance(self.dwelltime, (list, tuple)):
                self.dwelltime = np.array(self.dwelltime)
            if isinstance(self.dwelltime, np.ndarray):
                self.min_dwelltime = min(self.dwelltime)
                self.max_dwelltime = max(self.dwelltime)
                self.dwelltime_varys = True

        time_est = npts*(self.pos_settle_time + self.det_settle_time)
        if self.dwelltime_varys:
            time_est += self.dwelltime.sum()
        else:
            time_est += npts*self.dwelltime
        return time_est


    def prepare_scan(self, debug=False):
        """prepare stepscan"""
        self.pos_settle_time = max(MIN_POLL_TIME, self.pos_settle_time)
        self.det_settle_time = max(MIN_POLL_TIME, self.det_settle_time)

        if not self.verify_scan():
            self.write('Cannot execute scan: %s\n' % self.last_error_msg)
            self.set_info('scan_message', 'cannot execute scan')
            return
        userdir = '.'
        if self.scandb is not None:
            userdir = self.scandb.get_info('user_folder')

        self.clear_interrupts()
        self.dtimer.add('PRE: cleared interrupts')

        self.orig_positions = {}
        for p in self.positioners:
            self.orig_positions[p.pv.pvname] = p.current()

        self.dtimer.add('PRE: orig positions')
        out = [p.move_to_start(wait=False) for p in self.positioners]
        self.check_outputs(out, msg='move to start')
        self.dtimer.add('PRE: move to start')
        npts = self.npts = len(self.positioners[0].array)
        for det in self.detectors:
            det.arm(mode=self.detmode, fnum=1, numframes=1)
            fname = fix_varname(fix_filename("%s_%s" % (self.filename, det.label)))
            det.config_filesaver(path=userdir, name=fname, numcapture=npts)

        self.dtimer.add('PRE: armed detectors ')
        self.message_points = min(100, max(10, 25*round(npts/250.0)))
        self.dwelltime_varys = False

        if self.dwelltime is not None:
            self.min_dwelltime = self.dwelltime
            self.max_dwelltime = self.dwelltime
            if isinstance(self.dwelltime, (list, tuple)):
                self.dwelltime = np.array(self.dwelltime)
            if isinstance(self.dwelltime, np.ndarray):
                self.min_dwelltime = min(self.dwelltime)
                self.max_dwelltime = max(self.dwelltime)
                self.dwelltime_varys = True

        time_est = npts*(self.pos_settle_time + self.det_settle_time)
        if self.dwelltime_varys:
            time_est += self.dwelltime.sum()
            for d in self.detectors:
                d.set_dwelltime(self.dwelltime[0])
        else:
            time_est += npts*self.dwelltime
            for d in self.detectors:
                d.set_dwelltime(self.dwelltime)
        self.dtimer.add('PRE: set dwelltime')

        if self.scandb is not None:
            self.set_info('scan_progress', 'preparing scan')

        out = self.pre_scan(mode=self.detmode)
        self.check_outputs(out, msg='pre scan')

        self.datafile = self.open_output_file(filename=self.filename,
                                              comments=self.comments)

        self.datafile.write_data(breakpoint=0)
        self.filename = self.datafile.filename
        self.dtimer.add('PRE: opened output file')
        self.clear_data()
        if self.scandb is not None:
            self.init_scandata()
            self.set_info('request_abort', 0)
            self.set_info('scan_time_estimate', time_est)
            self.set_info('scan_total_points', npts)
            self.set_info('scan_current_point', 0)
            self.scandb.set_filename(self.filename)

        self.dtimer.add('PRE: initialized scandata')
        # self.set_info('scan_progress', 'starting scan')

        self.publish_thread = ScanPublisher(func=self.publish_data,
                                            scan=self, npts=npts, cpt=0)
        self.publish_thread.start()
        self.cpt = 0
        self.npts = npts
        out = [p.move_to_start(wait=True) for p in self.positioners]
        self.check_outputs(out, msg='move to start, wait=True')
        [p.current() for p in self.positioners]
        for d in self.counters:
            d.read()
            d.clear()
        self.dtimer.add('PRE: start scan')
        if debug:
            self.dtimer.show()

    def run(self, filename=None, comments=None, debug=False):
        """ run a stepscan:
           Verify, Save original positions,
           Setup output files and messenger thread,
           run pre_scan methods
           Loop over points
           run post_scan methods
        """
        if filename is not None:
            self.filename  = filename
        if comments is not None:
            self.comments = comments
        if self.comments is None:
            self.comments = ''

        # caput('13XRM:map:filename', filename)
        self.complete = False
        self.dtimer = debugtime()
        self.publishing_scandata = False

        ts_start = time.time()
        self.prepare_scan(debug=debug)
        ts_init = time.time()
        self.inittime = ts_init - ts_start
        i = -1
        while not self.abort:
            i += 1
            if i >= self.npts:
                break
            try:
                point_ok = True
                self.cpt = i+1
                self.look_for_interrupts()
                self.dtimer.add('Pt %i : looked for interrupts' % i)
                while self.pause:
                    time.sleep(0.025)
                    if self.look_for_interrupts():
                        break
                # set dwelltime
                if self.dwelltime_varys:
                    for d in self.detectors:
                        d.set_dwelltime(self.dwelltime[i])
                for det in self.detectors:
                    det.arm(mode=self.detmode, fnum=1, numframes=1)
                    time.sleep(det.arm_delay)
                self.dtimer.add('Pt %i : det arm' % i)
                # move to next position
                [p.move_to_pos(i) for p in self.positioners]
                self.dtimer.add('Pt %i : move_to_pos (%i)' % (i, len(self.positioners)))

                self.set_info('scan_current_point', i)
                # move positioners
                t0 = time.time()
                while (not all([p.done for p in self.positioners]) and
                       time.time() - t0 < self.pos_maxmove_time):
                    if self.look_for_interrupts():
                        break
                    poll(MIN_POLL_TIME, 0.25)
                self.dtimer.add('Pt %i : pos done' % i)
                poll(self.pos_settle_time, 0.25)
                self.dtimer.add('Pt %i : pos settled' % i)

                # trigger detectors
                [trig.start() for trig in self.triggers]
                #for det in self.detectors:
                #    det.start(mode=self.detmode, arm=False, wait=False)
                self.dtimer.add('Pt %i : triggers fired, (%d)' % (i, len(self.triggers)))

                # wait for detectors
                t0 = time.time()
                time.sleep(max(0.05, 0.8*self.min_dwelltime))
                while not all([trig.done for trig in self.triggers]):
                    if (time.time() - t0) > 5.0*(1 + 2*self.max_dwelltime):
                        print("Trigger timed-out!")
                        for trig in self.triggers:
                            print(trig, trig.done)
                        break
                    poll(MIN_POLL_TIME, 0.5)
                self.dtimer.add('Pt %i : triggers done' % i)
                if self.look_for_interrupts():
                    break
                # print("STEP SCAN triggers may be done: ", i,
                #      [(trig, trig.done) for trig in self.triggers])
                time.sleep(0.1)
                point_ok = (all([trig.done for trig in self.triggers]) and
                            time.time()-t0 > (0.75*self.min_dwelltime))
                # print("STEP SCAN  point_ok = ", point_ok)
                if not point_ok:
                    point_ok = True
                    poll(0.1, 1.0)
                    for trig in self.triggers:
                        poll(0.05, 1.0)
                        point_ok = point_ok and (trig.runtime > (0.8*self.min_dwelltime))
                        if not point_ok:
                            print('Trigger problem?:', trig, trig.runtime, self.min_dwelltime)
                            trig.abort()

                # read counters and actual positions
                poll(0.01, self.det_settle_time)
                self.dtimer.add('Pt %i : det settled done. ' % i)

                dready = [True]
                t0 = time.time()
                for counter in self.counters:
                    if hasattr(counter, 'pv'):
                        val = counter.pv.get(timeout=0.1)
                    if ('clock' in counter.label.lower() or
                        'counttime' in counter.label.lower()):
                        dready.append((val > 0))
                if not all(dready):
                    print(f"## waiting for valid clock data, point {i}")
                    time.sleep(0.05 + self.det_settle_time)
                    dready = [True]
                    for counter in self.counters:
                        if ('clock' in counter.label.lower() or
                            'counttime' in counter.label.lower()):
                            val = counter.pv.get(timeout=0.5)
                            dready.append((val > 0))
                        if hasattr(counter, 'pv'):
                            _x = counter.pv.get()
                    if not all(dready):
                        time.sleep(0.05)
                    if time.time() - t0 > 10:
                        dready = [True]
                dat = [c.read() for c in self.counters]
                # print("read counters: ", dat, time.time()-t0)
                self.dtimer.add('Pt %i : read counters' % i)
                self.pos_actual.append([p.current() for p in self.positioners])
                if self.publish_thread is not None:
                    self.publish_thread.cpt = self.cpt
                self.dtimer.add('Pt %i : sent message' % i)

                # if this is a breakpoint, execute those functions
                if i in self.breakpoints:
                    self.at_break(breakpoint=i, clear=True)
                self.dtimer.add('Pt %i: done.' % i)
                self.look_for_interrupts()

            except KeyboardInterrupt:
                self.set_info('request_abort', 1)
                self.abort = True
            if not point_ok:
                self.write('point messed up.  Will try again\n')
                time.sleep(0.25)
                for trig in self.triggers:
                    trig.abort()
                for det in self.detectors:
                    det.pre_scan(scan=self)
                i -= 1

            self.dtimer.add('Pt %i: completely done.' % i)

        # scan complete
        # return to original positions, write data
        self.dtimer.add('Post scan start')
        self.set_all_scandata()

        ts_loop = time.time()
        self.looptime = ts_loop - ts_init

        self.datafile.write_data(breakpoint=-1, close_file=True, clear=False)
        self.dtimer.add('Post: file written')
        if self.look_for_interrupts():
            self.write("scan aborted at point %i of %i\n" % (self.cpt, self.npts))

        # run post_scan methods
        out = self.post_scan()
        self.check_outputs(out, msg='post scan')
        self.dtimer.add('Post: post_scan done')
        self.complete = True

        # end data thread
        if self.publish_thread is not None:
            self.publish_thread.cpt = None
            self.publish_thread.join()

        self.set_info('scan_progress',
                      'scan complete. Wrote %s' % self.datafile.filename)
        ts_exit = time.time()
        self.exittime = ts_exit - ts_loop
        self.runtime  = ts_exit - ts_start
        self.dtimer.add('Post: fully done')

        if debug:
            self.dtimer.show()
        return self.datafile.filename
