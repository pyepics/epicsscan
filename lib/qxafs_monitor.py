#!/usr/bin/env python
"""
companion script for QXAFS for use with epicsscan 

This program needs to be run as a separate process.

It looks in the scan DBB for a wakeup signal, then
monitors the SIS channel as the QXAFS scan runs, and 
does two tasks:
  a) move the undulator to the correct energy based on
     the pre-loaded id_array and the current SIS point
  b) push data from the counters into the ScandDB, so
     that live clients can read the data.


"""
import os
import time
import json
import sys
import numpy as np
from epics import caget, caput, PV, get_pv

from epicsscan.scandb import ScanDB
from epicsscan.scan import hms
from scan_credentials import conn

from optparse import OptionParser

# minimum ID energy to put
MIN_ID_ENERGY =   2.0
MAX_ID_ENERGY = 200.0

PIDFILE = '/home/epics/logs/qxafs_monitor.pid'
HEARTBEAT_PVNAME = '13XRM:edb:info02'
PULSECOUNT_PVNAME = '13XRM:edb:info03'

class QXAFS_ScanWatcher(object):
    def __init__(self, **conn_kws):
        self.scandb = ScanDB(**conn_kws)
        self.state = 0
        self.last = self.pulse = -1
        self.last_move_time = 0
        self.set_state(0)
        self.config = None
        self.dead_time = 1.1
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

    def qxafs_prep(self):
        self.idarray = self.idarray_pv.get()
        self.dtime = float(self.get_info(key='qxafs_dwelltime', default=0.5))
        self.pulse = 0
        self.last_move_time = 0
        self.counters = []
        for c in self.scandb.get_scandata():
            pv = get_pv(c.pvname)

        time.sleep(0.05)
        for c in self.scandb.get_scandata():
            pv = get_pv(c.pvname)
            pv.connect()
            self.counters.append((c.name, pv, pv.nelm))

    def qxafs_finish(self):
        nidarr = len(self.idarray)
        self.idarray_pv.put(np.zeros(nidarr))
        self.set_state(0)
        self.dtime = 0.0
        self.last, self.pulse = 0, 0
        self.last_move_time = 0
        self.counters = []

    def onPulse(self, pvname, value=0, **kws):
        self.pulse = value

    def monitor_qxafs(self):
        self.qxafs_prep()
        print("Monitor QXAFS begin")
        msg_counter = 0
        last_pulse = 0
        self.pulse = 0
        while True:
            if self.get_state() == 0:
                print("Break : state=0")
                break
            npts = int(self.get_info(key='scan_total_points', default=0))
            time.sleep(0.05)
            now = time.time()
            self.pulsecount_pv.put("%i" % self.pulse)
            if self.pulse > last_pulse:
                self.heartbeat_pv.put("%i" % int(time.time()))
                val = self.idarray[self.pulse]
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
                msg = 'Point %i/%i, time left: %s' % (cpt, npts, time_est)
                if cpt >= 10*msg_counter:
                    self.scandb.set_info('scan_progress',  msg)
                    msg_counter += 1
                    print(msg)
                for name, pv, nelm in self.counters:
                    try:
                        if nelm > 1:
                            self.scandb.set_scandata(name, pv.get())
                        else:
                            buff = pv.get()
                            self.scandb.append_scandata(name, pv.get())
                    except:
                        print "Could not set scandata for %s: %i, %s" % (name, nelm, pv)

                self.scandb.commit()
        print("Monitor QXAFS done")
        last_pulse = self.pulse = 0
        self.qxafs_finish()

    def get_info(self, *args, **kws):
        return self.scandb.get_info(*args, **kws)

    def set_state(self, val):
        return self.scandb.set_info('qxafs_running', val)

    def get_state(self):
        return int(self.scandb.get_info(key='qxafs_running', default=0))

    def mainloop(self):
        while True:
            if 1 == self.get_state():
                self.monitor_qxafs()
            time.sleep(1.0)
            self.heartbeat_pv.put("%i"%int(time.time()))


def start():
    """save pid for later killing, start process"""
    fpid = open(PIDFILE, 'w')
    fpid.write("%d\n" % os.getpid() )
    fpid.close()

    watcher = QXAFS_ScanWatcher(**conn)
    watcher.mainloop()

def get_lastupdate():
    return int(caget(HEARTBEAT_PVNAME, as_string=True))

def kill_old_process():
    try:
        caput(HEARTBEAT_PVNAME, '1')
        finp = open(pidfile)
        pid = int(finp.readlines()[0][:-1])
        finp.close()
        cmd = "kill -9 %d" % pid
        os.system(cmd)
        print ' killing pid=', pid, ' at ', time.ctime()
    except:
        pass

if __name__ == '__main__':
    usage = "usage: %prog [options] file(s)"

    parser = OptionParser(usage=usage, prog="qxafs_monitor",  version="1")

    parser.add_option("-f", "--force", dest="force", action="store_true",
                      default=False, help="force restart, default = False")

    (options, args) = parser.parse_args()

    oldtime = get_lastupdate()
    if (options.force or (abs(time.time() - oldtime) > 120.0)):
        kill_old_process()
        time.sleep(1.0)
        start()
    else:
        print 'QXAFS Monitor running OK at ', time.ctime()
