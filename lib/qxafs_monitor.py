#!/usr/bin/env python
"""
xafs scan
based on EpicsApps.StepScan.

"""
import os
import time
import json
import sys
import numpy as np
from epics import caget, caput, PV, get_pv

from epicsscan.scandb import ScanDB
from epicsscan.utils import hms, tstamp
from scan_credentials import conn

from optparse import OptionParser

# minimum ID energy to put
MIN_ID_ENERGY =   2.0
MAX_ID_ENERGY = 200.0

PIDFILE = '/home/xas_user/logs/qxafs_monitor.pid'
HEARTBEAT_PVNAME = '13XRM:edb:info02'
PULSECOUNT_PVNAME = '13XRM:edb:info03'

class QXAFS_ScanWatcher(object):
    def __init__(self, verbose=False, **conn_kws):
        self.verbose = verbose
        self.scandb = ScanDB(**conn_kws)
        self.state = 0
        self.last = self.pulse = -1
        self.last_move_time = 0
        self.set_state(0)
        self.config = None
        self.dead_time = 1.1
        self.id_lookahead = 2
        self.counters = []
        self.connect()

    def connect(self):
        self.config = json.loads(self.scandb.get_config('qxafs').notes)
        pulse_channel = "%sCurrentChannel" % self.config['mcs_prefix']
        self.pulse_pv = PV(pulse_channel, callback=self.onPulse)
        self.idarray_pv = PV(self.config['id_array_pv'])
        self.iddrive_pv = PV(self.config['id_drive_pv'])
        self.idbusy_pv = PV(self.config['id_busy_pv'])
        self.pulsecount_pv = PV(PULSECOUNT_PVNAME)
        self.heartbeat_pv = PV(HEARTBEAT_PVNAME)

    def qxafs_connect_counters(self):
        self.counters = []
        time.sleep(0.1)
        pvs = []
        for c in self.scandb.get_scandata():
            pv = get_pv(c.pvname)
            pvs.append((c.name, pv))
        time.sleep(0.1)
        for cname, pv in pvs:
            pv.connect()
            self.counters.append((cname, pv))
        if self.verbose:
            print("QXAFS_connect_counters %i counters" % (len(self.counters)))
            
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
        self.idarray = self.idarray_pv.get()
        self.dtime = float(self.get_info(key='qxafs_dwelltime', default=0.5))
        if self.verbose:
            print("Monitor QXAFS begin %i ID Points"  % len(self.idarray))

        self.qxafs_connect_counters()
        while True:
            # print(" QXAFS Pulse ", self.pulse, last_pulse, self.get_state())
            if self.get_state() == 0:
                print("Break : state=0")
                break
            npts = int(self.get_info(key='scan_total_points', default=0))
            time.sleep(0.05)
            now = time.time()
            if self.pulse > last_pulse:
                self.pulsecount_pv.put("%i" % self.pulse)
                self.set_info('scan_current_point', self.pulse)
                self.heartbeat_pv.put("%i" % int(time.time()))
                if self.verbose and self.pulse % 5 == 0:
                    print("QXAFS Monitor " , self.pulse, len(self.counters))
                val = self.idarray[self.pulse + self.id_lookahead]
                if (self.iddrive_pv.write_access and
                    (self.idbusy_pv.get() == 0) and
                    ((now- self.last_move_time) > self.dead_time) and
                    (val > MIN_ID_ENERGY) and
                    (val < MAX_ID_ENERGY)):
                    try:
                        self.iddrive_pv.put(val)
                        self.last_move_time = time.time()
                    except:
                        pass
                last_pulse = self.pulse
                cpt = int(self.pulse)
                time_left = (npts-cpt)*self.dtime
                self.scandb.set_info('scan_time_estimate', time_left)
                time_est  = hms(time_left)
                msg = 'Point %i/%i, %i time left: %s' % (cpt, npts, msg_counter, time_est)
                if cpt >= msg_counter:
                    self.scandb.set_info('scan_progress',  msg)
                    self.scandb.set_info('heartbeat', tstamp())                    
                    msg_counter += 1
                for name, pv in self.counters:
                    try:
                        value = pv.get()
                        if pv.nelm > 1:
                            self.scandb.set_scandata(name, value)
                        else:
                            self.scandb.append_scandata(name, value)
                    except:
                        print "Could not set scandata for %s: %i, %s" % (name, pv)
                self.scandb.commit()
        self.pulsecount_pv.put("%i" % self.pulse)
        self.set_info('scan_current_point', self.pulse)
        print("Monitor QXAFS done")
        last_pulse = self.pulse = 0
        self.qxafs_finish()

    def get_info(self, *args, **kws):
        return self.scandb.get_info(*args, **kws)

    def set_info(self, key,  val):
        return self.scandb.set_info(key, val)

    def set_state(self, val):
        return self.set_info('qxafs_running', val)

    def get_state(self):
        val  = self.scandb.get_info(key='qxafs_running', default=0)
        return int(val)

    def mainloop(self):
        self.qxafs_connect_counters()
        while True:
            state = self.get_state()
            # print("Main loop ", state, 2==state)
            if 2 == int(state):
                self.monitor_qxafs()
            time.sleep(1.0)
            self.heartbeat_pv.put("%i"%int(time.time()))
            # self.set_state(0)


def start(verbose=False):
    """save pid for later killing, start process"""
    fpid = open(PIDFILE, 'w')
    fpid.write("%d\n" % os.getpid() )
    fpid.close()
    
    watcher = QXAFS_ScanWatcher(verbose=verbose, **conn)
    watcher.mainloop()

def get_lastupdate():
    try:
        return int(caget(HEARTBEAT_PVNAME, as_string=True))
    except:
        return -1

def kill_old_process():
    try:
        caput(HEARTBEAT_PVNAME, '1')
        finp = open(PIDFILE)
        pid = int(finp.readlines()[0][:-1])
        finp.close()
        cmd = "kill -9 %d" % pid
        os.system(cmd)
        print ' killing pid=', pid, ' at ', time.ctime()
    except:
        pass


def run_qxafs_monitor():
    usage = "usage: %prog [options] file(s)"

    parser = OptionParser(usage=usage, prog="qxafs_monitor",  version="1")

    parser.add_option("-f", "--force", dest="force", action="store_true",
                      default=False, help="force restart, default = False")
    parser.add_option("-v", "--verbose", dest="verbose", action="store_true",
                      default=False, help="verbose messages, default = False")

    
    (options, args) = parser.parse_args()

    oldtime = get_lastupdate()
    if (options.force or (abs(time.time() - oldtime) > 120.0)):
        kill_old_process()
        time.sleep(1.0)
        start(verbose=options.verbose)
    else:
        print 'QXAFS Monitor running OK at ', time.ctime()
 
if __name__ == '__main__':
    run_qxafs_monitor()
    
       
