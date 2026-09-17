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
from .scan import set_scandata_with_roisums

# minimum ID energy to put
MIN_ID_ENERGY =   2.0
MAX_ID_ENERGY = 200.0


class QXAFS_ScanWatcher(object):
    def __init__(self, verbose=False, heartbeat_pvname=None,
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
        self.needs_complete = False
        self.config = None
        self.dead_time = 1.0
        self.with_id = True
        self.with_gapscan = False
        self.gapscan_mode = 4
        self.counters = []
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
        self.confname = self.scandb.get_info('qxafs_config', default='qxafs')

        self.config = json.loads(self.scandb.get_config(self.confname).notes)
        mcs_prefix = self.config.get('mcs_prefix', '13IDE:MCS1:')
        # print(self.config)
        self.pulse_pv = get_pv(f"{mcs_prefix}CurrentChannel", callback=self.onPulse)
        time.sleep(0.025)

        self.with_id      = self.scandb.get_infobool('qxafs_id_tracking')
        self.with_gapscan = self.scandb.get_infobool('qxafs_use_gapscan')
        self.gapscan_mode = self.scandb.get_info('qxafs_gapscan_mode', 4)

        if self.config.get('id_busy_pv', '_no_') == '_no_':
            self.with_id = False

        if self.with_id:
            self.idbusy_pv = get_pv(self.config['id_busy_pv'])
            pvroot = self.config['id_busy_pv'].replace('BusyM.VAL', '')
            self.idgapscan_next = get_pv(f'{pvroot}MoveToNextGapC.VAL')
            self.idgapscan_busy = get_pv(f'{pvroot}BusyDeviceM.VAL')
            self.idgapscan_index = get_pv(f'{pvroot}ScanIndexM.VAL')

            # self.idarray_pv = get_pv(self.config['id_array_pv'])
            # self.iddrive_pv = get_pv(self.config['id_drive_pv'])
            # self.id_en_drv   = get_pv(f'{pvroot}EnergySetC.VAL')
            # self.id_en_rbv   = get_pv(f'{pvroot}EnergyM.VAL')
            # self.idstart_pv  = get_pv(f"{pvroot}StartC")
            # self.idstop_pv   = get_pv(f"{pvroot}StopC")
            # self.idgapsym_pv = get_pv(f'{pvroot}GapSymmetryM')
            # self.idtaper_pv  = get_pv(f'{pvroot}TaperEnergyM')
            # self.idtaperset_pv  = get_pv(f'{pvroot}TaperEnergySetC')


        time.sleep(0.05)
        self.connected = True

    def connect_counters(self):
        self.counters = []
        time.sleep(0.05)
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
            if pvname.startswith(EVAL4PLOT):
                counter = ROISumCounter(name, units=row.units)
            else:
                counter = Counter(pvname, label=name, units=row.units)
            self.counters.append(counter)
        time.sleep(0.05)
        if self.verbose:
            self.write(f"Connect {len(self.counters)} counters {isotime()}")

    def qxafs_abort(self):
        if self.config is not None:
            print("will abort QXAFS")
            pv_stop_theta = get_pv(self.config['motors']['THETA'] + '.STOP', connect=True)
            time.sleep(0.5)
            if pv_stop_theta.connected:
                pv_stop_theta.put(1, wait=True)
                time.sleep(0.5)
                pv_stop_theta.put(0)
                print("Aborted QXAFS")
            time.sleep(2.0)
            self.scandb.set_info('request_abort', 0)
            time.sleep(2.0)

    def qxafs_finish(self):
        self.set_state(0)
        self.needs_complete = True
        self.dtime = 0.0
        self.last, self.pulse = 0, 0
        self.last_move_time = 0
        self.counters = []
        time.sleep(1.0)

    def onPulse(self, pvname, value=0, **kws):
        self.pulse = value

    def old_sync_undulator(self):
        mode = self.scandb.get_info('qxafs_gapscan_mode', '4')
        mode = int(mode)
        # print(f"Sync undulator {mode=}")
        if mode == 0:    # simple push of ID value, without gapscan
            self.with_gapscan = False
            self.sync_id_mode_0()
        if mode in (3, 4) and self.with_gapscan:  # gap values with software put
            self.sync_id_mode4()
        elif self.with_gapscan:  # gap values with TTL pulses
            raise ValueError(" sync_undulatore mode=2 not supported")

    def sync_data(self):
        """
        Publish scan data, and setup GapScan mode 3 or 4:
        push to next value in preloaded gap array
        """
        last_pulse = 0
        self.pulse = 0
        gap_mode = self.scandb.get_info('qxafs_gapscan_mode', '4')
        gap_mode = int(gap_mode)
        if gap_mode == 0:
            self.with_id = False

        self.dtime = float(self.scandb.get_info(key='slew1d_dwelltime', default=0.5))
        if self.verbose:
            self.write(f"QXAFS Sync begin: mode {gap_mode}")
        npts = int(self.scandb.get_info(key='scan_total_points', default=0))
        # print("Sync : npts ", npts, self.dtime, self.pulse, last_pulse, self.with_id)
        self.connect_counters()

        while True:
            time.sleep(0.1)
            now = time.time()
            if self.get_state() == 0:
                break
            if self.scandb.get_infobool('request_abort'):
                print("abort")
                self.qxafs_abort()
                time.sleep(1.0)
            if self.pulse > last_pulse:
                last_pulse = self.pulse
                cpt = int(self.pulse)
                time_left = (npts-cpt)*self.dtime
                self.scandb.set_info('scan_time_estimate', time_left)
                time_est  = hms(time_left)
                msg = f'Point {cpt}/{npts}, time left:{time_est}'

                if self.with_id:
                    if self.idgapscan_busy.get() == 1: # not still busy from last move
                        self.idgapscan_next.put(1)
                    time.sleep(0.025)
                    gapscan_index = self.idgapscan_index.get()
                    if (gap_mode == 4 and gapscan_index < self.pulse and
                        self.idgapscan_next.write_access and
                        self.idgapscan_busy.get() == 1):
                        print(f"gapscan extra push {gapscan_index=}, {self.pulse=}")
                        self.idgapscan_next.put(1)

                self.scandb.set_info('scan_progress',  msg)
                self.scandb.set_info('heartbeat', isotime())
                _t0 = time.time()
                dat = [c.read() for c in self.counters]
                # print("-> put scan data ", self.pulse)
                set_scandata_with_roisums(self.scandb, self.counters,
                                          skip_first=True)
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

    def write(self, msg):
        sys.stdout.write("%s\n" % msg)
        sys.stdout.flush()

    def mainloop(self):
        if not self.connected:
            self.connect()
        self.connect_counters()

        while True:
            state = self.get_state()
            if state == 0 and self.needs_complete:
                self.needs_complete = False
            if state > 0:
                try:
                    confname = self.scandb.get_info('qxafs_config', default='qxafs')
                    self.dtime = float(self.scandb.get_info(key='qxafs_dwelltime',
                                                            default=0.5))

                    if confname is not self.confname:
                        self.connect()
                    self.sync_data()

                except:
                    self.write("QXAFS monitor gave an exception")
                    sys.excepthook(*sys.exc_info())
                    self.write("QXAFS monitor will try again")
            time.sleep(0.5)
            if self.heartbeat_pv is not None:
                self.heartbeat_pv.put("%i"%int(time.time()))
        self.write("QXAFS monitor  mainloop done ")

if __name__ == '__main__':

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

    if (options.force or (abs(time.time() - heartbeat) > 60.0)):
        watcher = QXAFS_ScanWatcher(verbose=options.verbose,
                                    heartbeat_pvname=HEARTBEAT_PVNAME,
                                    pulsecount_pvname=PULSECOUNT_PVNAME)
        watcher.mainloop()
    else:
        print(f'QXAFS Monitor running OK at {isotime()}')
