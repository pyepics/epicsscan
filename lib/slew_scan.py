#!/usr/bin/env python
"""
xafs scan
based on EpicsApps.StepScan.

"""
import sys
import os
import json
import shutil
import time
from threading import Thread
import numpy as np


from .scan import StepScan
from .positioner import Positioner
from .saveable import Saveable

from .utils import ScanDBAbort
from .detectors import Struck, TetrAMM, Xspress3
from .detectors import (Counter, Trigger, AreaDetector)
from file_utils import fix_varname, fix_filename, increment_filename

from epics import PV, poll, get_pv, caget, caput
from .xps import NewportXPS


class Slew_Scan(StepScan):
    """Slew Scans"""
    def __init__(self, filename=None, auto_increment=True,
                 comments=None, messenger=None, scandb=None,
                 prescan_func=None, **kws):
        StepScan.__init__(self, auto_increment=auto_increment,
                          comments=comments, messenger=messenger,
                          scandb=scandb, **kws)
        self.scantype = 'slew'
        self.detmode  = 'ndarray'

    def prepare_scan(self):
        """prepare slew scan"""

        print("Enabling Slew SCAN")
        conf = self.scandb.get_config(self.scantype)
        conf = self.slewscan_config = json.loads(conf.notes)
        self.xps = NewportXPS(conf['host'],
                              username=conf['username'],
                              password=conf['password'],
                              group=conf['group'],
                              outputs=conf['outputs'])

        currscan = 'CurrentScan.ini'
        fileroot  = self.scandb.get_info('server_fileroot')
        userdir = self.scandb.get_info('user_folder')
        basedir = os.path.join(fileroot, userdir, 'Maps')
        if not os.path.exists(basedir):
            os.mkdir(basedir)

        sname = os.path.join(basedir, currscan)
        oname = os.path.join(basedir, 'PreviousScan.ini')
        fname = fix_filename(self.filename)
        mapdir = os.path.join(basedir, fname + '_rawmap')
        counter = 0
        while os.path.exists(mapdir) and counter < 9999:
            fname = increment_filename(fname)
            mapdir = os.path.join(basedir, fname + '_rawmap')
            counter += 1
        os.mkdir(mapdir)
        self.mapdir = mapdir
        self.fileroot = fileroot

        if os.path.exists(sname):
            shutil.copy(sname, oname)

        txt = ['# FastMap configuration file (saved: %s)'%(time.ctime()),
               '#-------------------------#','[general]',
               'basedir = %s' % userdir,
               '[xps]']

        scnf = json.loads(self.scandb.get_config('slew').notes)
        posnames = ', '.join(scnf['motors'].keys())
        txt.extend(['host = %s' % scnf['host'],
                    'user = %s' % scnf['username'],
                    'passwd = %s' % scnf['password'],
                    'group = %s' % scnf['group'],
                    'positioners = %s' % posnames])

        txt.append('[slow_positioners]')
        for i, pos in enumerate(self.scandb.get_positioners()):
            txt.append("%i = %s | %s" % (i+1, pos.drivepv, pos.name))

        dim  = 1
        if self.outer is not None:
            dim = 2
        l_, pvs, start, stop, npts = self.inner
        pospv = pvs[0]
        if pospv.endswith('.VAL'):
            pospv = pospv[:-4]
        step = abs(start-stop)/(npts-1)
        self.rowtime = dtime = self.dwelltime*(npts-1)

        axis = None
        for ax, pvname in self.slewscan_config['motors'].items():
            if pvname == pospv:
                axis = ax

        if axis is None:
            raise ValueError("Could not find XPS Axis for %s" % pospv)

        self.xps.define_line_trajectories(axis,
                                          start=start, stop=stop,
                                          step=step, scantime=dtime)

        txt.extend(['[scan]',
                    'filename = %s' % self.filename,
                    'comments = %s' % self.comments,
                    'dimension = %i' % dim,
                    'pos1 = %s'     % pospv,
                    'start1 = %.4f' % start,
                    'stop1 = %.4f'  % stop,
                    'step1 = %.4f'  % step,
                    'time1 = %.4f'  % dtime])



        if dim == 2:
            l_, pvs, start, stop, npts = self.outer
            pospv = pvs[0]
            if pospv.endswith('.VAL'):
                pospv = pospv[:-4]
            step = abs(start-stop)/(npts-1)
            txt.extend(['pos2 = %s'   % pospv,
                        'start2 = %.4f' % start,
                        'stop2 = %.4f' % stop,
                        'step2 = %.4f' % step])

        txt.append('#------------------#')
        txt.append('[xrd_ad]')
        xrd_det = None
        for det in self.detectors:
            if isinstance(det, AreaDetector):
                xrd_det = det

        if xrd_det is None:
            txt.append('use = False')
        else:
            txt.append('use = True')
            txt.append('type = AreadDetector')
            txt.append('prefix = %s' % det.prefix)
            txt.append('fileplugin = :')

        sini = os.path.join(mapdir, 'Scan.ini')
        f = open(sini, 'w')
        f.write('\n'.join(txt))
        f.close()
        f = open(sname, 'w')
        f.write('\n'.join(txt))
        f.close()
        print("Wrote Simple Scan Config: ", sname)
        return sname

    def run(self, filename='map.001', comments=None, debug=False):
        """
        run a slew scan
        """
        self.prepare_scan()
        self.xps.arm_trajectory('backward')

        pjoin = os.path.join
        abspath = os.path.abspath
        master_file = os.path.join(self.mapdir, 'Master.dat')
        env_file = os.path.join(self.mapdir, 'Environ.dat')
        roi_file = os.path.join(self.mapdir, 'ROI.dat')

        master = open(master_file, 'w')

        dim = 2
        l_, pvs, start, stop, npts = self.outer
        step = abs(start-stop)/(npts-1)
        master.write("#Scan.version = 1.3\n")
        master.write('#SCAN.starttime = %s\n' % time.ctime())
        master.write('#SCAN.filename  = %s\n' % self.filename)
        master.write('#SCAN.dimension = %i\n' % dim)
        master.write('#SCAN.nrows_expected = %i\n' % npts)
        master.write('#SCAN.time_per_row_expected = %.2f\n' % self.rowtime)
        master.write('#Y.positioner  = %s\n' %  str(pvs[0]))
        master.write('#Y.start_stop_step = %f, %f, %f \n' %  (start, stop, step))
        master.write('#------------------------------------\n')
        master.write('# yposition  xmap_file  struck_file  xps_file    time\n')


        detpath = self.mapdir[len(self.fileroot):]
        for det in self.detectors:
            det.arm(mode=self.detmode)
            det.config_filesaver(number=1, path=detpath, auto_increment=True)

        print("Ready for SLEWSCAN !! ", self.mapdir )

        self.clear_interrupts()
        self.set_info('scan_progress', 'starting')
        self.set_info('filename', filename)

        npts = len(self.positioners[0].array)
        def make_filename(n, i):
            return abspath(pjoin(self.mapdir, "%s.%4.4i" % (n, i)))

        for i in range(npts):
            print('row %i of %i' % (i+1, npts))
            self.set_info('scan_progress', 'row %i of %i' % (i+1, npts))
            [p.move_to_pos(i, wait=False) for p in self.positioners]
            [p.move_to_pos(i, wait=True) for p in self.positioners]
            yval = self.positioners[0].array[i]
            time.sleep(0.5)
            master.write("%8.4f ..... \n" % yval)


        return

        # watch scan
        # first, wait for scan to start (status == 2)
        collecting = False
        t0 = time.time()
        while not collecting and time.time()-t0 < 120:

            collecting = (2 == caget('%sstatus' % mapper))
            time.sleep(0.25)
            if self.look_for_interrupts():
                break
        if self.abort:
            caput("%sAbort" % mapper, 1)

        nrow = 0
        t0 = time.time()
        maxrow = caget('%smaxrow' % mapper)
        info = caget("%sinfo" % mapper, as_string=True)
        self.set_info('scan_progress', info)
        #  wait for scan to get past row 1
        while nrow < 1 and time.time()-t0 < 120:
            nrow = caget('%snrow' % mapper)
            time.sleep(0.25)
            if self.look_for_interrupts():
                break
        if self.abort:
            caput("%sAbort" % mapper, 1)

        maxrow  = caget("%smaxrow" % mapper)
        time.sleep(1.0)
        fname  = caget("%sfilename" % mapper, as_string=True)
        self.set_info('filename', fname)

        # wait for map to finish:
        # must see "status=Idle" for 10 consequetive seconds
        collecting_map = True
        nrowx, nrow = 0, 0
        t0 = time.time()
        while collecting_map:
            time.sleep(0.25)
            status_val = caget("%sstatus" % mapper)
            status_str = caget("%sstatus" % mapper, as_string=True)
            nrow       = caget("%snrow" % mapper)
            self.set_info('scan_status', status_str)
            time.sleep(0.25)
            if self.look_for_interrupts():
                break
            if nrowx != nrow:
                info = caget("%sinfo" % mapper, as_string=True)
                self.set_info('scan_progress', info)
                nrowx = nrow
            if status_val == 0:
                collecting_map = ((time.time() - t0) < 10.0)
            else:
                t0 = time.time()

        # if aborted from ScanDB / ScanGUI wait for status
        # to go to 0 (or 5 minutes)
        self.look_for_interrupts()
        if self.abort:
            caput('%sAbort' % mapper, 1)
            time.sleep(0.5)
            t0 = time.time()
            status_val = caget('%sstatus' % mapper)
            while status_val != 0 and (time.time()-t0 < 10.0):
                time.sleep(0.25)
                status_val = caget('%sstatus' % mapper)

        status_strg = caget('%sstatus' % mapper, as_string=True)
        self.set_info('scan_status', status_str)
        if self.abort:
            raise ScanDBAbort("slewscan aborted")
        return
