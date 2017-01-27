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

from .debugtime import debugtime


class Slew_Scan(StepScan):
    """Slew Scans"""
    def __init__(self, filename=None, auto_increment=True,
                 comments=None, messenger=None, scandb=None,
                 prescan_func=None, larch=None, **kws):

        StepScan.__init__(self, auto_increment=auto_increment,
                          comments=comments, messenger=messenger,
                          scandb=scandb, **kws)
        self.larch = larch
        self.scantype = 'slew'
        self.detmode  = 'ndarray'
        self.motor_vals = {}
        self.orig_positions = {}

    def prepare_scan(self):
        """prepare slew scan"""
        self.set_info('scan_progress', 'preparing')
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

        caput('13XRM:map:basedir', basedir)
        caput('13XRM:map:status', 'Starting')
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
        h5fname= os.path.join(basedir, fname + '.h5')
        fhx  = open(h5fname, 'w')
        fhx.write("%s\n"% mapdir)
        fhx.close()
        caput('13XRM:map:filename', h5fname)

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

        txt.append('#------------------#')
        txt.append('[slow_positioners]')
        for i, pos in enumerate(self.scandb.get_positioners()):
            dpv = pos.drivepv
            if dpv.endswith('.VAL'): dpv = dpv[:-4]
            txt.append("%i = %s | %s" % (i+1, dpv, pos.name))

        txt.append('#------------------#')
        txt.append('[fast_positioners]')
        for i, pos in enumerate(self.scandb.get_slewpositioners()):
            dpv = pos.drivepv
            if dpv.endswith('.VAL'): dpv = dpv[:-4]
            txt.append("%i = %s | %s" % (i+1, dpv, pos.name))

        dim  = 1
        if self.outer is not None:
            dim = 2
        l_, pvs, start, stop, npts = self.inner
        pospv = pvs[0]
        if pospv.endswith('.VAL'):
            pospv = pospv[:-4]
        step = abs(start-stop)/(npts-1)
        self.rowtime = dtime = self.dwelltime*(npts-1)
        caput('13XRM:map:npts', npts)
        caput('13XRM:map:nrow', 0)
        axis = None
        for ax, pvname in self.slewscan_config['motors'].items():
            if pvname == pospv:
                axis = ax

        if axis is None:
            raise ValueError("Could not find XPS Axis for %s" % pospv)

        self.xps.define_line_trajectories(axis,
                                          start=start, stop=stop,
                                          step=step, scantime=dtime)

        txt.extend(['#------------------#', '[scan]',
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
            caput('13XRM:map:maxrow', npts)

        xrd_det = None
        xrf_det = None
        for det in self.detectors:
            if isinstance(det, AreaDetector):
                xrd_det = det
            if 'xspress3' in det.label.lower():
                xrf_det = det

        txt.append('#------------------#')
        txt.append('[xrf]')
        if xrf_det is None:
            txt.append('use = False')
        else:
            txt.append('use = True')
            txt.append('type = xsp3')
            txt.append('prefix = %s' % xrf_det.prefix)
            txt.append('fileplugin = %s' % xrf_det.filesaver)

        txt.append('#------------------#')
        txt.append('[xrd_ad]')
        if xrd_det is None:
            txt.append('use = False')
        else:
            txt.append('use = True')
            txt.append('type = AreaDetector')
            txt.append('prefix = %s' % xrd_det.prefix)
            txt.append('fileplugin = %s' % xrd_det.filesaver)

        sini = os.path.join(mapdir, 'Scan.ini')
        f = open(sini, 'w')
        f.write('\n'.join(txt))
        f.close()
        f = open(sname, 'w')
        f.write('\n'.join(txt))
        f.close()
        # print("Wrote Simple Scan Config: ", sname)

        trajs = self.xps.trajectories
        self.motor_vals = {}
        self.orig_positions = {}
        for i, axes in enumerate(trajs['foreward']['axes']):
            pvname = self.slewscan_config['motors'][axes]
            v1, v2 = trajs['foreward']['start'][i], trajs['backward']['start'][i]
            thispv = PV(pvname)
            self.motor_vals[pvname] = (thispv, v1, v2)
            self.orig_positions[thispv] = thispv.get()

        for p in self.positioners:
            self.orig_positions[p.pv] = p.current()


        detpath = self.mapdir[len(self.fileroot):]
        if detpath.startswith('/'):
            detpath = detpath[1:]
        for det in self.detectors:
            det.config_filesaver(path=detpath)
        return sname

    def post_scan(self):
        self.set_info('scan_progress', 'finishing')
        for pv, val in self.orig_positions.items():
            pv.put(val)

        for m in self.post_scan_methods:
            m()

        for det in self.detectors:
            det.disarm(mode=self.detmode)
            det.ContinuousMode()

    def run(self, filename='map.001', comments=None, debug=False, npts=None):
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

        # print(" Traj: ", tname, self.xps.trajectories[tname])
        # pvnames = trajs[tname]['axes']
        # print("SlewScan Config ", pvnames, self.slewscan_config['motors'])

        self.xps.arm_trajectory(tname)

        npulses = trajs[tname]['npulses'] + 1
        dwelltime = trajs[tname]['pixeltime']

        master_file = os.path.join(self.mapdir, 'Master.dat')
        env_file = os.path.join(self.mapdir, 'Environ.dat')
        roi_file = os.path.join(self.mapdir, 'ROI.dat')

        [p.move_to_pos(0, wait=False) for p in self.positioners]
        for pv, v1, v2 in self.motor_vals.values():
            val = v1
            if tname == 'backward': val = v2
            pv.put(val, wait=False)

        self.pre_scan(npulses=npulses, dwelltime=dwelltime, mode='ndarray')

        master = open(master_file, 'w')

        dim = 2
        l_, pvs, start, stop, _npts = self.outer
        if npts is None:
            npts = _npts
        npts = min(npts, len(self.positioners[0].array))
        step = abs(start-stop)/(npts-1)
        ypos = str(pvs[0])
        if ypos.endswith('.VAL'):
            ypos = ypos[:-4]
        master.write("#Scan.version = 1.4\n")
        master.write('#SCAN.starttime = %s\n' % time.ctime())
        master.write('#SCAN.filename  = %s\n' % self.filename)
        master.write('#SCAN.dimension = %i\n' % dim)
        master.write('#SCAN.nrows_expected = %i\n' % npts)
        master.write('#SCAN.time_per_row_expected = %.2f\n' % self.rowtime)
        master.write('#Y.positioner  = %s\n' %  ypos)
        master.write('#Y.start_stop_step = %f, %f, %f \n' %  (start, stop, step))
        master.write('#------------------------------------\n')
        master.write('# yposition  xrf_file  struck_file  xps_file  xrd_file   time\n')
        master.flush()
        os.fsync(master.fileno())

        def make_filename(fname, i):
            return "%s.%4.4i" % (fname, i)

        detpath = self.mapdir[len(self.fileroot):]
        scadet = xrfdet = xrddet = None
        scafile = xrffile = xrdfile = '_unused_'
        for det in self.detectors:
            if det.label.lower() == 'struck':
                scadet = det
            elif det.label.lower() == 'xspress3':
                xrfdet = det
            elif 'xrd' in det.label.lower():
                xrddet = det
            det.NDArrayMode(numframes=npulses)


        self.clear_interrupts()
        self.set_info('scan_progress', 'starting')
        self.set_info('filename', filename)

        start_time = time.time()
        irow = 0
        caput('13XRM:map:status', 'Collecting')
        dtimer =  debugtime()
        while irow < npts:
            irow += 1
            dtimer.add('=== row start %i ====' % irow)
            self.set_info('scan_progress', 'row %i of %i' % (irow, npts))
            caput('13XRM:map:nrow', irow)
            trajname = ['foreward', 'backward'][(dir_off + irow) % 2]
            # print('row %i of %i, %s %s' % (irow, npts, trajname, self.larch is None))
            if self.larch is not None and irow > 1 and irow % 10 == 0:
                try:
                    self.larch.run("pre_scan_command(row=%i, npts=%i)" % (irow, npts))
                except:
                    print("Failed to run pre_scan_command(row=%i)" % irow)

            for pv, v1, v2 in self.motor_vals.values():
                val = v1
                if trajname == 'backward': val = v2
                pv.put(val, wait=False)
            dtimer.add('inner pos move started irow=%i' % irow)
            for det in self.detectors:
                det.arm(mode='ndarray', numframes=npulses, fnum=irow)
            time.sleep(0.1)
            dtimer.add('detectors armed')
            for det in self.detectors:
                det.start()
            time.sleep(0.1)
            dtimer.add('detectors started')
            self.xps.arm_trajectory(trajname)
            if irow < 2:
                time.sleep(0.25)
            # dtimer.add('outer pos move')
            dtimer.add('trajectory armed')

            [p.move_to_pos(irow-1, wait=True) for p in self.positioners]
            # dtimer.add('inner pos move(2)')
            for pv, v1, v2 in self.motor_vals.values():
                val = v1
                if trajname == 'backward': val = v2
                pv.put(val, wait=True)
            dtimer.add('inner pos move done')
            # start trajectory in another thread
            time.sleep(0.05)
            scan_thread = Thread(target=self.xps.run_trajectory,
                                 kwargs=dict(save=False), name='trajectory_thread')
            scan_thread.start()
            dtimer.add('scan thread started')
            posfile = "xps.%4.4i" % (irow)
            if scadet is not None:
                scafile = scadet.get_next_filename()
            if xrfdet is not None:
                xrffile = xrfdet.get_next_filename()
            if xrddet is not None:
                xrdfile = xrddet.get_next_filename()
            
            if irow < 2:
                for det in self.detectors:
                    if det.label == 'xspress3':
                        det.save_calibration(roi_file)
                self.save_envdata(filename=env_file)
            
            pos0 = self.positioners[0]    
            masterline = "%8.4f %s %s %s %s" % (pos0.array[irow-1],
                                                xrffile, scafile,
                                                posfile, xrdfile)

            # wait for trajectory to finish
            dtimer.add('scan thread run join()')
            scan_thread.join()
            dtimer.add('scan thread joined')
            if self.look_for_interrupts():
                caput('13XRM:map:status', 'Aborting')
                break
            # dtimer.add("stopping detectors after delay")
            for det in self.detectors:
                det.stop()

            masterline = "%s %8.4f\n" % (masterline, time.time()-start_time)
            master.write(masterline)
            master.flush()
            os.fsync(master.fileno())

            if irow < npts-1:
                [p.move_to_pos(irow, wait=False) for p in self.positioners]
            dtimer.add('start read')
            rowdata_ok = True
            xpsfile = os.path.abspath(os.path.join(self.mapdir, posfile))
            
            xps_saver_thread = Thread(target=self.xps.read_and_save,
                                  args=(xpsfile,), name='xps_saver')
            xps_saver_thread.start()

            npts_sca = npulses
            if scadet is not None:
                sisfile = os.path.abspath(os.path.join(self.mapdir, scafile))                
                ncsa, npts_sca = scadet.save_arraydata(filename=sisfile, npts=npulses)
            dtimer.add('saved SIS data')

            xps_saver_thread.join()
            dtimer.add('saved XPS data')

            nxrf = nxrd = 0
            if xrfdet is not None:
                t0 = time.time()
                while not xrfdet.file_write_complete() and (time.time()-t0 < 5.0):
                    time.sleep(0.1)
                # print(" File write complete? ", xrfdet.file_write_complete())
                nxrf = xrfdet._xsp3.getNumCaptured_RBV()
                if (nxrf < npulses -2) or not xrfdet.file_write_complete():
                    rowdata_ok = False
                    xrfdet.stop()
                    time.sleep(0.25)
            dtimer.add('saved XRF data')

            if xrddet is not None:
                t0 = time.time()
                while not xrddet.file_write_complete() and (time.time()-t0 < 10.0):
                    time.sleep(0.1)
                # print(" File write complete? ", xrfdet.file_write_complete())
                nxrd = xrddet.ad.getNumCaptured_RBV()
                if (nxrd < npulses-2) or not xrddet.file_write_complete():
                    rowdata_ok = False
                    xrddet.stop()
                    time.sleep(0.25)
            dtimer.add('saved XRD data')

            rowdata_ok = (rowdata_ok and
                          (npts_sca > npulses-2) and
                          (self.xps.ngathered > npulses-2))

            if debug:
                print("Row OK ? ", rowdata_ok, npulses, npts_sca,
                      self.xps.ngathered, nxrf, nxrd)
            if not rowdata_ok:
                fmt=  '## BAD DATA (NSIS=%i, NXPS=%i): redoing row\n'
                self.write(fmt % (npts_sca, self.xps.ngathered))
                irow -= 1
                [p.move_to_pos(irow, wait=False) for p in self.positioners]
            if self.look_for_interrupts():
                caput('13XRM:map:status', 'Aborting')
                break
            if debug:
                dtimer.show()
        caput('13XRM:map:status', 'Finishing')
        self.post_scan()
        caput('13XRM:map:status', 'IDLE')
        print('Scan done.')
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
