#!/usr/bin/env python
"""
xafs scan
based on EpicsApps.StepScan.

"""
from __future__ import print_function

import os
import time
import json
import sys
from multiprocessing import Process
from threading import Thread
import numpy as np
from epics import caget, caput, PV, get_pv
from epics.ca import CASeverityException
from epicsscan.scandb import ScanDB
from epicsscan.utils import hms, tstamp
from newportxps import NewportXPS

from optparse import OptionParser

from .detectors.counter import Counter, ROISumCounter, EVAL4PLOT


# minimum ID energy to put
MIN_ID_ENERGY =   2.0
MAX_ID_ENERGY = 200.0

DEFAULT_PIDFILE = os.path.join(os.path.expanduser('~'), 'qxafs_monitor.pid')


class QXAFS_ScanWatcher(object):
    def __init__(self, verbose=False, pidfile=None,
                 heartbeat_pvname=None,
                 pulsecount_pvname=None, **kws):
        self.verbose = verbose
        self.scandb = ScanDB()
        try:
            self.set_state(0)
        except:
            raise RuntimeError("Cannot connect to ScanDB")

        self.state = 0
        self.last = self.pulse = -1
        self.last_move_time = 0
        self.config = None
        self.dead_time = 0.5
        self.id_lookahead = 2
        self.with_id = False
        self.counters = []
        self.pidfile = pidfile or DEFAULT_PIDFILE
        self.pulsecount_pv = None
        self.heartbeat_pv = None
        if pulsecount_pvname is not None:
            self.pulsecount_pv = PV(pulsecount_pvname)
        if heartbeat_pvname is not None:
            self.heartbeat_pv = PV(heartbeat_pvname)
        self.connected = False
        self.confname = None
        self.connect()

    def connect(self):
        self.confname = self.scandb.get_info('qxafs_config', 'qxafs')
        self.config = json.loads(self.scandb.get_config(self.confname).notes)
        print("QXAFS CONNECT ", self.confname, self.config)
        mcs_prefix = self.config.get('mcs_prefix', '13IDE:SIS1:')
        pulse_channel = f"{mcs_prefix}CurrentChannel"
        self.pulse_pv = PV(pulse_channel, callback=self.onPulse)


        self.with_id = ('id_array_pv' in self.config and
                        'id_drive_pv' in self.config)
        if self.with_id:
            self.idarray_pv = PV(self.config['id_array_pv'])
            self.iddrive_pv = PV(self.config['id_drive_pv'])
            self.idbusy_pv = PV(self.config['id_busy_pv'])
            pvroot = self.config['id_busy_pv'].replace('Busy', '')

            self.idstop_pv   = PV("%sStop" % pvroot)
            self.idgapsym_pv = PV('%sGapSymmetry' % pvroot)
            self.idtaper_pv  = PV('%sTaperEnergy' % pvroot)
            self.idtaperset_pv  = PV('%sTaperEnergySet' % pvroot)
        self.xps = NewportXPS(self.config['host'])

        time.sleep(0.1)
        self.connected = True

    def qxafs_connect_counters(self):
        self.counters = []
        time.sleep(0.1)
        pvs = []
        for row in self.scandb.get_scandata():
            # do not set energy values during scan
            if row.notes.strip().startswith('positioner'):
                continue
            pvname = row.pvname.strip()
            name = row.name.strip()
            lname = name.lower()
            if lname.startswith('energy'): # skip Energy readback
                pass
            if row.pvname.startswith(EVAL4PLOT):
                counter = eval(pvname[len(EVAL4PLOT):])
            else:
                counter = Counter(pvname, label=name, units=row.units)
            self.counters.append(counter)
        time.sleep(0.05)
        if self.verbose:
            self.write("QXAFS_connect_counters %i counters" % (len(self.counters)))

    def qxafs_finish(self):
        nidarr = len(self.idarray)
        # self.idarray_pv.put(np.zeros(nidarr))
        self.set_state(0)
        self.dtime = 0.0
        self.last, self.pulse = 0, 0
        self.last_move_time = 0
        self.counters = []

    def onPulse(self, pvname, value=0, **kws):
        self.pulse = value

    def monitor_qxafs(self):
        msg_counter = 0
        last_pulse = 0
        self.pulse = 0
        self.last_move_time = 0
        if self.with_id:
            self.idarray = self.idarray_pv.get()
        else:
            self.idarray = np.zeros(1)

        self.dtime = float(self.scandb.get_info(key='qxafs_dwelltime', default=0.5))
        if self.verbose:
            self.write("Monitor QXAFS begin %i ID Points"  % len(self.idarray))
        self.qxafs_connect_counters()
        while True:
            if self.get_state() == 0:
                print("Break : state=0")
                break
            npts = int(self.scandb.get_info(key='scan_total_points', default=0))
            if self.scandb.get_info(key='request_abort', as_bool=True):
                self.write("QXAFS abort request during scan: %s" % time.ctime())
                abort_proc = Process(target=self.xps.abort_group)
                abort_proc.start()
                self.write("QXAFS abort process begun: %s" % (time.ctime()))
                time.sleep(0.5)
                self.qxafs_finish()
                time.sleep(0.5)
                self.write("QXAFS scan finished, join abort process: %s" % (time.ctime()))
                abort_proc.join(5.0)
                if abort_proc.is_alive():
                    self.write("QXAFS join abort timed-out, trying to terminate")
                    abort_proc.terminate()
                    time.sleep(2.0)
                self.write("QXAFS abort process done: %s" % (time.ctime()))
                self.scandb.set_info('request_abort', 0)
                time.sleep(1.0)

            time.sleep(0.1)
            now = time.time()
            # look for and prevent out-of-ordinary values for Taper (50 eV)
            # or for Gap Symmetry
            if self.with_id:
                gapsym = self.idgapsym_pv.get()
                taper  = self.idtaper_pv.get()
                if abs(gapsym) > 0.050 or abs(taper) > 0.050:
                    self.idtaperset_pv.put(0, wait=True)
                    time.sleep(0.250)
                    val = self.idarray[last_pulse + self.id_lookahead]
                    try:
                        self.iddrive_pv.put(val, wait=True, timeout=5.0)
                    except CASeverityException:
                        pass
                    time.sleep(0.250)

            if self.pulse > last_pulse:
                if self.pulsecount_pv is not None:
                    self.pulsecount_pv.put("%i" % self.pulse)
                self.scandb.set_info('scan_current_point', self.pulse)
                if self.heartbeat_pv is not None:
                    self.heartbeat_pv.put("%i" % int(time.time()))

                # if the ID has been moving for more than 0.75 sec, stop it
                if self.with_id:
                    if ((self.pulse > 2) and
                        (self.idbusy_pv.get() == 1) and
                        (now >  self.last_move_time + 0.75)):
                        self.idstop_pv.put(1)
                        time.sleep(0.1)

                    val = self.idarray[self.pulse + self.id_lookahead]

                    if self.verbose and self.pulse % 25 == 0:
                        self.write("QXAFS: %d/%d ID Energy=%.3f " % (self.pulse, npts, val))

                    if ((self.idbusy_pv.get() == 0) and
                        (now > self.last_move_time + self.dead_time) and
                        (val > MIN_ID_ENERGY) and (val < MAX_ID_ENERGY)):
                        try:
                            self.iddrive_pv.put(val, wait=False)
                        except CASeverityException:
                            pass
                        time.sleep(0.1)
                        self.last_move_time = time.time()
                else:
                    if self.verbose and self.pulse % 25 == 0:
                        self.write("QXAFS: %d/%d " % (self.pulse, npts))

                last_pulse = self.pulse
                cpt = int(self.pulse)
                time_left = (npts-cpt)*self.dtime
                self.scandb.set_info('scan_time_estimate', time_left)
                time_est  = hms(time_left)
                msg = 'Point %i/%i, time left: %s' % (cpt, npts, time_est)

                if cpt >= msg_counter:
                    self.scandb.set_info('scan_progress',  msg)
                    self.scandb.set_info('heartbeat', tstamp())
                    msg_counter += 1
                for counter in self.counters:
                    try:
                        dat = counter.read()
                        if len(dat) > 1:
                            self.scandb.set_scandata(counter.label, dat[1:])
                    except:
                        self.write("Could not set scandata for %r, %i" % (counter.label, cpt))
                self.scandb.commit()
        if self.pulsecount_pv is not None:
            self.pulsecount_pv.put("%i" % self.pulse)
        self.scandb.set_info('scan_current_point', self.pulse)
        self.write("Monitor QXAFS scan complete, finishing")
        last_pulse = self.pulse = 0
        self.qxafs_finish()

    def set_state(self, val):
        return self.scandb.set_info('qxafs_running', val)

    def get_state(self):
        val  = self.scandb.get_info(key='qxafs_running', default=0)
        return int(val)

    def get_lastupdate(self):
        if self.heartbeat_pv is not None:
            return int(self.heartbeat_pv.get(as_string=True))
        return -1

    def kill_old_process(self):
        if self.heartbeat_pv is not None:
            self.heartbeat_pv.put("-1")

        pid = None
        with open(self.pidfile) as fh:
            pid = int(fh.readlines()[0][:-1])

        if pid is not None:
            self.write('killing pid=', pid, ' at ', time.ctime())
            os.system("kill -9 %d" % pid)
            time.sleep(1.0)

    def save_pid(self):
        with  open(self.pidfile, 'w') as fh:
            fh.write("%d\n" % os.getpid() )
            fh.close()

    def write(self, msg):
        sys.stdout.write("%s\n" % msg)
        sys.stdout.flush()

    def mainloop(self):
        if not self.connected:
            self.connect()
        self.save_pid()
        self.qxafs_connect_counters()
        while True:
            state = self.get_state()
            if 2 == int(state):
                try:
                    confname = self.scandb.get_info('qxafs_config', 'qxafs')
                    if confname is not self.confname:
                        self.connect()
                    self.monitor_qxafs()
                except:
                    self.write("QXAFS monitor gave an exception, will try again")
            else:
                if self.scandb.get_info(key='request_abort', as_bool=True):
                    self.write("QXAFS abort requested while not scanning")
                    self.xps.abort_group()
                    time.sleep(1.0)
            time.sleep(1.0)
            if self.heartbeat_pv is not None:
                self.heartbeat_pv.put("%i"%int(time.time()))
        self.write("QXAFS monitor  mainloop done ")

if __name__ == '__main__':

    PIDFILE = os.path.join(os.path.expanduser('~'), 'logs', 'qxafs_monitor.pid')
    HEARTBEAT_PVNAME = '13XRM:edb:info02'
    PULSECOUNT_PVNAME = '13XRM:edb:info03'

    usage = "usage: %prog [options] file(s)"

    parser = OptionParser(usage=usage, prog="qxafs_monitor",  version="1")
    parser.add_option("-f", "--force", dest="force", action="store_true",
                      default=False, help="force restart, default = False")
    parser.add_option("-v", "--verbose", dest="verbose", action="store_true",
                      default=False, help="verbose messages, default = False")

    (options, args) = parser.parse_args()

    try:
        heartbeat = int(caget(HEARTBEAT_PVNAME, as_string=True))
    except:
        heartbeat = -1

    pid = -1
    with open(PIDFILE) as fh:
        pid = int(fh.readlines()[0][:-1])

    # check if pid is actually running:
    if pid > 0:
        try:
            os.kill(pid, 0)
        except OSError:
            pid = -1

    if (options.force or (abs(time.time() - heartbeat) > 60.0) or pid < 0):
        heartbeat = -1
        if pid > 0:
            print('killing pid=', pid, ' at ', time.ctime())
            os.system("kill -9 %d" % pid)
            time.sleep(1.0)

        watcher = QXAFS_ScanWatcher(verbose=options.verbose,
                                    heartbeat_pvname=HEARTBEAT_PVNAME,
                                    pulsecount_pvname=PULSECOUNT_PVNAME,
                                    pidfile=PIDFILE)
        print("start QXAFS Monitor (pid %d)" % (os.getpid()))
        watcher.mainloop()
    else:
        print('QXAFS Monitor running OK (pid %d) at %s ' % (pid, time.ctime()))
