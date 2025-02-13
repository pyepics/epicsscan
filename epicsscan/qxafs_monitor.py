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
from pyshortcuts import isotime
from epics import caget, caput, PV, get_pv
from epics.ca import CASeverityException
from epicsscan.scandb import ScanDB
from epicsscan.utils import hms

from optparse import OptionParser

from .detectors.counter import Counter, ROISumCounter, EVAL4PLOT

# minimum ID energy to put
MIN_ID_ENERGY =   2.0
MAX_ID_ENERGY = 200.0

DEFAULT_PIDFILE = os.path.join(os.path.expanduser('~'), 'qxafs_monitor.pid')

def ca_put(pvname, value, wait=False):
    "for verbose messages"
    print(f"put:  {pvname} -> {value} (wait={wait}):  {isotime()}")
    caput(pvname, value, wait=wait)

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
        self.writer_thread = None
        # self.idsync_thread = None
        self.needs_complete = False
        self.config = None
        self.id_deadband = 0.001
        self.dead_time = 1.0
        self.id_lookahead = 3
        self.with_id = True
        self.counters = []
        self.pidfile = pidfile or DEFAULT_PIDFILE
        self.pulsecount_pv = None
        self.heartbeat_pv = None
        if pulsecount_pvname is not None:
            self.pulsecount_pv = get_pv(pulsecount_pvname)
        if heartbeat_pvname is not None:
            self.heartbeat_pv = get_pv(heartbeat_pvname)
        self.connected = False
        self.confname = None
        self.connect()

    def connect(self):
        self.confname = self.scandb.get_info('qxafs_config', 'qxafs')
        self.config = json.loads(self.scandb.get_config(self.confname).notes)
        mcs_prefix = self.config.get('mcs_prefix', '13IDE:SIS1:')
        pulse_channel = f"{mcs_prefix}CurrentChannel"
        id_tracking = int(self.scandb.get_info('qxafs_id_tracking', '1'))
        self.id_lookahead = int(self.scandb.get_info('qxafs_id_lookahead', 3))

        self.pulse_pv = get_pv(pulse_channel, callback=self.onPulse)
        self.with_id = ('id_array_pv' in self.config and
                        'id_drive_pv' in self.config and id_tracking)
        if self.with_id:
            self.idarray_pv = get_pv(self.config['id_array_pv'])
            self.iddrive_pv = get_pv(self.config['id_drive_pv'])
            self.idbusy_pv = get_pv(self.config['id_busy_pv'])
            pvroot = self.config['id_busy_pv'].replace('BusyM.VAL', '')

            self.id_en_drv   = get_pv('%sEnergySetC.VAL' % pvroot)
            self.id_en_rbv   = get_pv('%sEnergyM.VAL' % pvroot)
            self.idstart_pv  = get_pv("%sStartC" % pvroot)
            self.idstop_pv   = get_pv("%sStopC" % pvroot)
            self.idgapsym_pv = get_pv('%sGapSymmetryM' % pvroot)
            self.idtaper_pv  = get_pv('%sTaperEnergyM' % pvroot)
            self.idtaperset_pv  = get_pv('%sTaperEnergySetC' % pvroot)
            time.sleep(0.25)

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
            self.write("QXAFS_connect_counters %i counters / %s" % (len(self.counters), time.ctime()))

    def qxafs_finish(self):
        nidarr = len(self.idarray)
        # self.idarray_pv.put(np.zeros(nidarr))
        self.set_state(0)
        self.needs_complete = True
        self.dtime = 0.0
        self.last, self.pulse = 0, 0
        self.last_move_time = 0
        self.counters = []
        time.sleep(1.0)

    def onPulse(self, pvname, value=0, **kws):
        self.pulse = value

    def write_scandata(self):
        """
        monitor point in XAFS scan, push data to scandb for plotting
        """
        msg_counter = 0
        last_pulse = 0
        self.pulse = 0
        self.qxafs_connect_counters()

        while True:
            if self.get_state() == 0:
                break
            npts = int(self.scandb.get_info(key='scan_total_points', default=0))
            if self.scandb.get_info(key='request_abort', as_bool=True):
                self.write(f"QXAFS saw request for abort: {time.ctime()}")
                self.qxafs_finish()
                break
            time.sleep(0.1)
            now = time.time()

            if self.pulse > last_pulse:
                if self.pulsecount_pv is not None:
                    self.pulsecount_pv.put(f"{self.pulse}")
                self.scandb.set_info('scan_current_point', self.pulse)
                if self.heartbeat_pv is not None:
                    self.heartbeat_pv.put(f"{int(time.time())}")

                if self.verbose and self.pulse % 25 == 0:
                    self.write(f"QXAFS: {self.pulse} / {npts}")

                last_pulse = self.pulse
                cpt = int(self.pulse)
                time_left = (npts-cpt)*self.dtime
                self.scandb.set_info('scan_time_estimate', time_left)
                time_est  = hms(time_left)
                msg = f'Point {cpt}/{npts}, time left:{time_est}'

                if cpt >= msg_counter:
                    self.scandb.set_info('scan_progress',  msg)
                    self.scandb.set_info('heartbeat', isotime())
                    msg_counter += 1

                ndat = {}
                for counter in self.counters:
                    try:
                        dat = counter.read()
                        ndat[counter.label] = len(dat)
                        if len(dat) > 1:
                            self.scandb.set_scandata(counter.label, dat[1:])
                        else:
                            if self.pulse > 2:
                                print("no data for counter ", counter.label)
                    except:
                        self.write("Could not set scandata for %r, %i" % (counter.label, cpt))
        print("write data done")
        self.write("Monitor QXAFS scan complete, finishing")
        self.qxafs_finish()

    def sync_undulator(self):
        last_pulse = 0
        self.pulse = 0
        self.last_move_time = time.time() - 30.0
        self.last_put_value = -1.0
        if self.with_id:
            self.idarray = self.idarray_pv.get()
        else:
            self.idarray = np.zeros(1)
        self.dtime = float(self.scandb.get_info(key='qxafs_dwelltime', default=0.5))
        if self.verbose:
            self.write(f"Sync Undulator QXAFS begin {len(self.idarray)} ID Points")
        id_lookahead = self.id_lookahead
        id_energy_rbv = -1.0
        while True:
            time.sleep(0.1)
            now = time.time()
            npts = int(self.scandb.get_info(key='scan_total_points', default=0))
            if self.get_state() == 0 or self.scandb.get_info(key='request_abort', as_bool=True):
                break
            if self.pulse > last_pulse and self.with_id:
                try:
                    id_busy = (self.idbusy_pv.get() == 1)
                except:
                    id_busy = False
                val0 = self.idarray[self.pulse]
                val = self.idarray[self.pulse + id_lookahead]
                dt = now-self.last_move_time
                # print(f"Pulse {self.pulse} ID_En_target={val0:.4f} id_busy={id_busy} lookahead={id_lookahead} last_move={dt:.2f} sec ago")
                if ((self.pulse > 2) and id_busy and
                    (now > self.last_move_time + self.dead_time)):
                    print(f"    stopping ID")
                    self.idstop_pv.put(1) # ca_put(self.idstop_pv.pvname, 1)
                    time.sleep(0.75)
                    id_busy = False

                if ((now > self.last_move_time + self.dead_time) and
                    (val > self.last_put_value + self.id_deadband) and
                    (val > MIN_ID_ENERGY) and (val < MAX_ID_ENERGY) and
                    not id_busy):
                    try:
                        self.id_en_drv.put(val) # ca_put(self.id_en_drv.pvname, val)
                        time.sleep(0.025)
                         self.idstart_pv.put(1) # ca_put(self.idstart_pv.pvname, 1)
                        self.last_put_value = val
                        self.last_move_time = time.time()
                    except CASeverityException:
                        print("ID: put for ID failed!")
                    time.sleep(0.10)
                    id_energy_rbv = self.id_en_rbv.get()
                    print(f"#Pulse {self.pulse} ID En target={val0:.3f} (putval={val:.3f}), readback={id_energy_rbv:.3f}")
                    if (self.pulse % 2) == 0 and ((val0 - id_energy_rbv) > 0.008):
                        id_lookahead = id_lookahead + 1

                last_pulse = self.pulse
                cpt = int(self.pulse)
        last_pulse = self.pulse = 0

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
            if state == 0 and self.needs_complete:
                self.needs_complete = False
                if self.writer_thread is not None:
                    self.writer_thread.join()
                    time.sleep(0.1)
                    self.writer_thread = None
            if state > 0:
                try:
                    confname = self.scandb.get_info('qxafs_config', 'qxafs')
                    if confname is not self.confname:
                        self.connect()
                    if self.writer_thread is None:
                        self.writer_thread = Thread(target=self.write_scandata, name='writer')
                        self.writer_thread.start()

                    self.sync_undulator()

                except:
                    self.write("QXAFS monitor gave an exception")
                    sys.excepthook(*sys.exc_info())
                    self.write("QXAFS monitor will try again")
            time.sleep(0.5)
            if self.heartbeat_pv is not None:
                self.heartbeat_pv.put("%i"%int(time.time()))
        self.write("QXAFS monitor  mainloop done ")

if __name__ == '__main__':

    PIDFILE = os.path.join(os.path.expanduser('~'), 'logs', 'qxafs_monitor.pid')
    HEARTBEAT_PVNAME = '13XRM:QXAFS:UnixTime'
    PULSECOUNT_PVNAME = '13XRM:QXAFS:ipt'

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
