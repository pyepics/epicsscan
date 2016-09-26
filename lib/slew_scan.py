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
        # print("Wrote Simple Scan Config: ", sname)
        return sname

    def post_scan(self):
        self.set_info('scan_progress', 'finishing')
        for m in self.post_scan_methods:
            m()

        for det in self.detectors:
            det.disarm(mode=self.detmode)
            det.ContinuousMode()


    def run(self, filename='map.001', comments=None, debug=False):
        """
        run a slew scan
        """
        self.prepare_scan()
        trajs = self.xps.trajectories
        dir_off = 1
        tname = 'foreward'
        if trajs['foreward']['axes'][0] == 'X':
            dir_off += 1
        if trajs['foreward']['start'] >  trajs['foreward']['stop']:
            dir_off += 1
        if dir_off % 2 == 0:
            tname = 'backward'

        self.xps.arm_trajectory(tname)
        npulses = trajs[tname]['npulses']
        dwelltime = trajs[tname]['pixeltime']

        master_file = os.path.join(self.mapdir, 'Master.dat')
        env_file = os.path.join(self.mapdir, 'Environ.dat')
        roi_file = os.path.join(self.mapdir, 'ROI.dat')

        [p.move_to_pos(0, wait=False) for p in self.positioners]
        self.pre_scan(npulses=npulses, dwelltime=dwelltime, mode='ndarray')

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

        def make_filename(fname, i):
            return "%s.%4.4i" % (fname, i)

        detpath = self.mapdir[len(self.fileroot):]
        scadet = xrfdet = xrddet = None
        xrbase = xrdbase = scabase = posbase = '__UNUSED'
        posbase = os.path.abspath(os.path.join(self.mapdir, 'xps'))
        for det in self.detectors:
            if det.label.lower() == 'struck':
                scadet = det
                scabase=  os.path.abspath(os.path.join(self.mapdir, 'struck'))
            elif det.label.lower() == 'xspress3':
                xrfdet = det
                xrfbase =  os.path.abspath(os.path.join(self.mapdir, 'xsp3'))
            elif 'perkin' in det.label.lower():
                xrddet = det
                xrfbase =  os.path.abspath(os.path.join(self.mapdir, 'xrd'))

            det.arm(mode=self.detmode, numframes=npulses)
            det.config_filesaver(number=1, path=detpath, auto_increment=True,
                                 auto_save=True)

        self.clear_interrupts()
        self.set_info('scan_progress', 'starting')
        self.set_info('filename', filename)

        npts = len(self.positioners[0].array)
        start_time = time.time()
        irow = 0
        while irow < npts:
            irow += 1
            self.set_info('scan_progress', 'row %i of %i' % (irow, npts))
            rowdata_ok = True

            trajname = ['foreward', 'backward'][(dir_off + irow) % 2]
            print('row %i of %i, %s' % (irow, npts, trajname))
            self.xps.arm_trajectory(trajname)
            for det in self.detectors:
                det.start(arm=True, mode='ndarray')

            [p.move_to_pos(irow-1, wait=True) for p in self.positioners]

            # start trajectory in another thread
            scan_thread = Thread(target=self.xps.run_trajectory,
                                 kwargs=dict(save=False), name='trajectory_thread')
            scan_thread.start()

            posfile = make_filename(posbase, irow)
            scafile = make_filename(scabase, irow)
            xrffile = make_filename(xrfbase, irow)
            xrdfile = make_filename(xrdbase, irow)
            if irow < 2:
                for det in self.detectors:
                    if det.label == 'xspress3':
                        det.save_calibration(roi_file)
                self.save_envdata(filename=env_file)

            masterline = "%8.4f" % (self.positioners[0].array[irow-1])

            for fname in (posfile, xrffile, xrdfile, scafile, posfile):
                if not fname.startswith('__UNUSED'):
                    d, fn = os.path.split(fname)
                    masterline = "%s %s" % (masterline, fn)

            # wait for trajectory to finish
            scan_thread.join()
            if self.look_for_interrupts():
                break

            masterline = "%s %8.4f\n" % (masterline, time.time()-start_time)
            master.write(masterline)
            if irow < npts-1:
                [p.move_to_pos(irow, wait=False) for p in self.positioners]

            saver_thread = Thread(target=self.xps.read_and_save,
                                  args=(posfile,), name='saver_thread')
            saver_thread.start()

            if xrfdet is not None:
                t0 = time.time()
                while not xrfdet.file_write_complete() and (time.time()-t0 < 5.0):
                    time.sleep(0.1)
                # print(" File write complete? ", xrfdet.file_write_complete())
                if not xrfdet.file_write_complete():
                    rowdata_ok = False
                    time.sleep(0.25)
                    xrfdet.stop()
                    time.sleep(0.25)
            if scadet is not None:
                scadet.save_arraydata(filename=scafile, npts=npulses)
            saver_thread.join()
            if not rowdata_ok:
                self.write('bad data for row: redoing this row\n')
                irow -= 1
                [p.move_to_pos(irow, wait=False) for p in self.positioners]
            if self.look_for_interrupts():
                break
            self.check_beam_ok()

        self.post_scan()
        return

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
