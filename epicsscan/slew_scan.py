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

from .scan import StepScan
from .positioner import Positioner
from .saveable import Saveable

from .utils import ScanDBAbort
from .detectors import Struck, TetrAMM, Xspress3
from .detectors import (Counter, Trigger, AreaDetector, write_poni)
from .file_utils import fix_varname, fix_filename, increment_filename

from epics import PV, poll, get_pv, caget, caput
from newportxps import NewportXPS

from .debugtime import debugtime

class Slew_Scan(StepScan):
    """Slew Scans"""
    def __init__(self, filename=None, auto_increment=True,
                 comments=None, messenger=None, scandb=None,
                 prescan_func=None, mkernel=None, **kws):

        StepScan.__init__(self, auto_increment=auto_increment,
                          comments=comments, messenger=messenger,
                          scandb=scandb, **kws)
        self.mkernel = mkernel
        self.scantype = 'slew'
        self.detmode  = 'ndarray'
        self.motor_vals = {}
        self.orig_positions = {}
        self.postscan_func = self.post_slew_scan

    def prepare_scan(self):
        """prepare slew scan"""
        self.set_info('scan_progress', 'preparing')

        # ZeroFineMotors before map?
        if self.scandb.get_info('zero_finemotors_beforemap', as_bool=True):
            zconf = self.scandb.get_config('zero_finemotors')
            zconf = json.loads(zconf.notes)
            vals  = dict(finex=0.0, finey=0.0, coarsex=0.0, coarsey=0.0)
            pvs   = dict(finex=None, finey=None, coarsex=None, coarsey=None)
            for pos in self.scandb.get_positioners():
                pname = str(pos.name.lower().replace(' ', ''))
                if pname in vals:
                    pvs[pname]  = PV(pos.drivepv)
                    vals[pname] = caget(pos.drivepv)
            if abs(vals['finex']) > 1.e-5 and pvs['coarsex'] is not None:
                coarsex = vals['coarsex'] + float(zconf['finex_scale']) * vals['finex']
                pvs['coarsex'].put(coarsex, wait=True)
            if abs(vals['finey']) > 1.e-5 and pvs['coarsey'] is not None:
                coarsey = vals['coarsey'] + float(zconf['finey_scale']) * vals['finey']
                pvs['coarsey'].put(coarsey, wait=True)
            time.sleep(0.1)
            pvs['finex'].put(0, wait=True)
            pvs['finey'].put(0, wait=True)
            time.sleep(0.1)

        inner_pos = self.scandb.get_slewpositioner(self.inner[0])
        conf = self.scandb.get_config_id(inner_pos.config_id)
        scnf = self.slewscan_config = json.loads(conf.notes)
        self.xps = NewportXPS(scnf['host'],
                              username=scnf['username'],
                              password=scnf['password'],
                              group=scnf['group'],
                              outputs=scnf['outputs'],
                              extra_triggers=scnf.get('extra_triggers', 0))

        currscan = 'CurrentScan.ini'
        fileroot = self.scandb.get_info('server_fileroot')
        userdir = self.scandb.get_info('user_folder')
        basedir = os.path.join(fileroot, userdir, 'Maps')
        if not os.path.exists(basedir):
            os.mkdir(basedir)

        mappref = self.scandb.get_info('epics_map_prefix')
        if mappref is not None:
            caput('%sbasedir' % (mappref), userdir)
            caput('%sstatus'  % (mappref), 'Starting')
        sname = os.path.join(basedir, currscan)
        if not self.filename.endswith('.h5'):
            self.filename = self.filename + '.h5'

        fname  = fix_filename(self.filename)
        mapdir = os.path.join(basedir, fname[:-3] + '_rawmap')
        counter = 0
        while os.path.exists(mapdir) and counter < 9999:
            fname = increment_filename(fname)
            mapdir = os.path.join(basedir, fname[:-3] + '_rawmap')
            counter += 1

        self.filename = fname

        os.mkdir(mapdir)

        hfname= os.path.join(basedir, self.filename)
        self.set_info('filename', fname)
        self.set_info('map_folder', mapdir)

        fhx  = open(hfname, 'w')
        fhx.write("%s\n"% mapdir)
        fhx.close()
        if mappref is not None:
            caput('%sfilename' % (mappref), self.filename)

        self.mapdir = mapdir
        self.fileroot = fileroot

        txt = ['# FastMap configuration file (saved: %s)'%(time.ctime()),
               '#-------------------------#','[general]',
               'basedir = %s' % userdir,
               '[xps]']

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
        dirpv = pospv + '.DIR'
        if caget(dirpv) == 1:
            start, stop = stop, start
        step = abs(start-stop)/(npts-1)
        self.rowtime = dtime = self.dwelltime*(npts-1)
        if mappref is not None:
            caput('%snpts' % (mappref), npts)
            caput('%snrow' % (mappref), 0)
        axis = None
        for ax, pvname in self.slewscan_config['motors'].items():
            if pvname == pospv:
                axis = ax

        if axis is None:
            raise ValueError("Could not find XPS Axis for %s" % pospv)

        self.xps.define_line_trajectories(axis,
                                          start=start, stop=stop,
                                          step=step, scantime=dtime)

        self.comments = self.comments.replace('\n', ' | ')

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
            if mappref is not None:
                caput('%smaxrow' % (mappref), npts)

        xrd_det = None
        xrf_det = None
        for det in self.detectors:
            # print("prepare detector ", det)
            if isinstance(det, AreaDetector):
                xrd_det = det
                self.set_info('xrd_1dint_status', 'starting')
                self.set_info('xrd_1dint_label', det.label)

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
            self.orig_positions[pvname] = thispv.get()

        for p in self.positioners:
            self.orig_positions[p.pv.pvname] = p.current()

        detpath = self.mapdir[len(self.fileroot):]
        if detpath.startswith('/'):
            detpath = detpath[1:]
        for det in self.detectors:
            det.data_dir = mapdir
            try:
                det.stop()
                det.config_filesaver(path=detpath)
            except AttributeError:
                pass
        for det in self.detectors:
            det.arm(mode='ndarray', numframes=npts, fnum=1, wait=False)

        return sname

    def post_slew_scan(self, **kws):
        for det in self.detectors:
            if isinstance(det, AreaDetector):
                self.set_info('xrd_1dint_status', 'finishing')

    def write_master(self, textlines):
        """ write a list of text lines to master file"""
        for text in textlines:
            self.scandb.add_slewscanstatus(text)

        self.mastertext.extend(textlines)
        # print("Write Master ", len(self.mastertext))
        oldfile = os.path.join(self.mapdir, '_Master_.dat')
        destfile = os.path.join(self.mapdir, 'Master.dat')
        if os.path.exists(destfile):
            shutil.move(destfile, oldfile)
        fh = open(destfile, 'w')
        fh.write('\n'.join(self.mastertext))
        fh.write('')
        fh.close()
        os.utime(destfile, None)
        time.sleep(0.025)


    def run(self, filename='map.001', comments=None, debug=False, npts=None):
        """
        run a slew scan
        """
        debug = self.scandb.get_info('debug_scan', as_bool=True) or debug
        self.prepare_scan()
        trajs = self.xps.trajectories

        dir_off = 1
        tname = 'foreward'
        # if trajs['foreward']['axes'][0] == 'X':
        #     dir_off += 1
        if trajs['foreward']['start'] >  trajs['foreward']['stop']:
            dir_off += 1
        if dir_off % 2 == 0:
            tname = 'backward'

        # pvnames = trajs[tname]['axes']
        # print("SlewScan Config ", pvnames, self.slewscan_config['motors'])

        self.xps.arm_trajectory(tname)
        npulses = trajs[tname]['npulses'] + 1
        dwelltime = trajs[tname]['pixeltime']

        env_file = os.path.join(self.mapdir, 'Environ.dat')
        roi_file = os.path.join(self.mapdir, 'ROI.dat')
        poni_file = os.path.join(self.mapdir, 'XRD.poni')

        for p in self.positioners:
            p.move_to_pos(0, wait=False)

        for pv, v1, v2 in self.motor_vals.values():
            val = v1
            if tname == 'backward': val = v2
            pv.put(val, wait=False)

        self.pre_scan(npulses=npulses, dwelltime=dwelltime, mode='ndarray')
        self.scandb.clear_slewscanstatus()
        dim  = 1
        npts = 1
        if self.outer is not None:
            dim = 2
            l_, pvs, start, stop, _npts = self.outer
            npts = min(_npts, len(self.positioners[0].array))
            step = abs(start-stop)/(npts-1)
            ypos = str(pvs[0])
            if ypos.endswith('.VAL'):
                ypos = ypos[:-4]
        mbuff = ["#Scan.version = 2.0",
                '#SCAN.starttime = %s' % time.ctime(),
                '#SCAN.filename  = %s' % self.filename,
                '#SCAN.dimension = %i' % dim,
                '#SCAN.nrows_expected = %i' % npts,
                '#SCAN.time_per_row_expected = %.2f' % self.rowtime]
        if dim == 2:
            mbuff.extend(['#Y.positioner  = %s' %  (ypos),
                         '#Y.start_stop_step = %f, %f, %f' %  (start, stop, step)])
        mbuff.extend(['#------------------------------------',
             '# yposition  xrf_file  struck_file  xps_file  xrd_file   time'])

        self.mastertext = []
        self.write_master(mbuff)

        def make_filename(fname, i):
            return "%s.%4.4i" % (fname, i)

        detpath = self.mapdir[len(self.fileroot):]
        scadet = xrfdet = xrddet = None
        scafile = xrffile = xrdfile = '_unused_'
        for det in self.detectors:
            dlabel = det.label.lower()
            # print('detector ', det, dlabel)
            if dlabel == 'struck':
                scadet = det
            elif dlabel in ('xspress3', 'multimca')  or 'mca' in dlabel:
                xrfdet = det
            elif dlabel.startswith('xrd') or dlabel.startswith('eiger'):
                xrddet = det
            det.NDArrayMode(numframes=npulses)

        det_arm_delay = det_start_delay = 0.025
        for det in self.detectors:
            det_arm_delay = max(det_arm_delay, det.arm_delay)
            dx = getattr(det, 'start_delay_arraymode', det.start_delay)
            det_start_delay = max(det_start_delay, dx)

        self.clear_interrupts()
        self.set_info('scan_progress', 'starting')
        self.scandb.set_filename(self.filename)
        mappref = self.scandb.get_info('epics_map_prefix')
        rowdata_ok = True
        start_time = time.time()
        irow = 0
        if mappref is not None:
            caput('%sstatus' % (mappref), 'Collecting')
        dtimer =  debugtime()
        self.scandb.set_info('repeated_map_rows', '')
        repeated_rows = []
        while irow < npts:
            if self.look_for_interrupts():
                if mappref is not None:
                    caput('%sstatus' % (mappref), 'Aborting')
                break

            irow += 1
            dtimer.add('=== row start %i ====' % irow)
            self.set_info('scan_progress', 'row %i of %i' % (irow, npts))
            if mappref is not None:
                caput('%snrow' % (mappref), irow)
            trajname = ['foreward', 'backward'][(dir_off + irow) % 2]

            if debug:
                print("# Row %i of %i trajectory='%s'" % (irow, npts, trajname))

            if self.mkernel is not None:
                now = time.time()
                prescan_lasttime = float(self.scandb.get_info('prescan_lasttime'))
                prescan_interval = float(self.scandb.get_info('prescan_interval'))
                run_prescan = (now > prescan_lasttime + prescan_interval)
                if run_prescan:
                    try:
                        self.mkernel.run("pre_scan_command(row=%i, npts=%i)" % (irow, npts))
                    except:
                        print("Failed to run pre_scan_command(row=%i)" % irow)
                    self.set_info('prescan_lasttime', "%i" % int(now))

            for pv, v1, v2 in self.motor_vals.values():
                val = v2  if (trajname == 'backward') else v1
                pv.put(val, wait=False)

            lastrow_ok = rowdata_ok
            rowdata_ok = True

            dtimer.add('inner pos move started irow=%i' % irow)
            for det in self.detectors:
                det.arm(mode='ndarray', numframes=npulses, fnum=irow, wait=False)
            time.sleep(0.005)

            # wait for detectors to be armed
            tout = time.time()+2.0
            while not all([det.arm_complete for det in self.detectors]):
                if time.time() > tout:
                    break
                time.sleep(0.005)

            dtimer.add('detectors armed %.3f' % det_arm_delay)
            for det in self.detectors:
                det.start(arm=False, wait=False)

            time.sleep(det_start_delay)
            dtimer.add('detectors started  %.3f' % det_start_delay)
            self.xps.arm_trajectory(trajname)
            if irow < 2 or not lastrow_ok:
                time.sleep(0.05)
            dtimer.add('XPS trajectory armed')

            for p in self.positioners:
                p.move_to_pos(irow-1, wait=True)

            for pv, v1, v2 in self.motor_vals.values():
                val = v1
                if trajname == 'backward': val = v2
                pv.put(val, wait=True)

            dtimer.add('positioner moves done')
            # start trajectory in another thread
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
                self.save_envdata(filename=env_file)
                if xrfdet is not None:
                    xrfdet.save_calibration(roi_file)
                if xrddet is not None:
                    xrd_poni = self.scandb.get_info('xrd_calibration')
                    calib = json.loads(self.scandb.get_detectorconfig(xrd_poni).text)
                    write_poni(poni_file, calname=xrd_poni, **calib)

            if dim == 2:
                pos0 = "%8.4f" % self.positioners[0].array[irow-1]
            else:
                pos0 = "_unused_"

            masterline = "%s %s %s %s %s" % (pos0, xrffile, scafile,
                                             posfile, xrdfile)
            if xrddet is not None:
                xt0 = time.time()

            # wait for trajectory to finish
            dtimer.add('scan thread run join()')
            xt0 = time.time()
            while scan_thread.is_alive():
                time.sleep(0.1)
                if time.time()-xt0 > 0.8*self.rowtime:
                    break
                if self.look_for_interrupts():
                    break

            scan_thread.join(timeout=self.rowtime/2.0)
            dtimer.add('scan thread joined')
            if self.look_for_interrupts():
                if mappref is not None:
                    caput('%sstatus' % (mappref), 'Aborting')
                break

            self.write_master(["%s %8.4f" % (masterline, time.time()-start_time)])

            if irow < npts-1:
                for p in self.positioners:
                    p.move_to_pos(irow, wait=False)

            dtimer.add('start read')

            pos_file = os.path.abspath(os.path.join(self.mapdir, posfile))
            pos_saver_thread = Thread(target=self.xps.read_and_save,
                                  args=(pos_file,), name='pos_saver')
            pos_saver_thread.start()

            npts_sca = npulses
            nsca = -1
            if scadet is not None:
                scadet.stop()
                sisfile = os.path.abspath(os.path.join(self.mapdir, scafile))
                ncsa, npts_sca = scadet.save_arraydata(filename=sisfile, npts=npulses)
            dtimer.add('saved SIS data')

            nxrf = nxrd = 0
            if xrfdet is not None:
                xrfdet.stop()
                t0 = time.time()
                write_complete = xrfdet.file_write_complete()
                ntry = 0
                while not write_complete and (time.time()-t0 < 10.0):
                    write_complete = xrfdet.file_write_complete()
                    time.sleep(0.05)
                    ntry = ntry + 1
                nxrf = xrfdet.get_numcaptured()
                if (nxrf < npulses-1) or not write_complete:
                    time.sleep(0.250)
                    xrfdet.finish_capture()
                    nxrf = xrfdet.get_numcaptured()
                    write_complete = xrfdet.file_write_complete()
                if (nxrf < npulses-1) or not write_complete:
                    time.sleep(0.250)
                    xrfdet.finish_capture()
                    nxrf = xrfdet.get_numcaptured()
                    write_complete = xrfdet.file_write_complete()
                if (nxrf < npulses-2) or not write_complete:
                    print("XRF file write failed ", write_complete, nxrf,
                          npulses, ntry)
                    rowdata_ok = False
                    xrfdet.stop()
                    time.sleep(0.1)
            dtimer.add('saved XRF data')

            if xrddet is not None:
                nxrd = xrddet.get_numcaptured()
                while ((nxrd < nxrf) and
                       (time.time()- t0 < 10.0)):
                    nxrd = xrddet.get_numcaptured()
                    time.sleep(0.003)
                xrddet.stop()
                dtimer.add('saved XRD data')

            pos_saver_thread.join(timeout=15)
            if pos_saver_thread.is_alive():
                print('ERROR:  NewportXPS gathering thread is still alive')
            dtimer.add('saved XPS data')

            rowdata_ok = (rowdata_ok and
                          (npts_sca >= npulses-2) and
                          (self.xps.ngathered >= npulses-2) and
                          (nxrf >= npulses-2) and
                          (not pos_saver_thread.is_alive()))

            if debug:
                print("#== Row %d nXPS=%d, nSIS=%d, nXRF=%d, nXRD=%d  npulses=%d, OK=%s" %
                      (irow, self.xps.ngathered, npts_sca, nxrf, nxrd, npulses, repr(rowdata_ok)))
            if not rowdata_ok:
                fmt=  '#BAD Row %d nXPS=%d, nSIS=%d, nXRF=%d, nXRD=%d: (npulses=%d) redo!\n'
                self.write(fmt % (irow, self.xps.ngathered, npts_sca, nxrf, nxrd, npulses))
                irow -= 1
                [p.move_to_pos(irow, wait=False) for p in self.positioners]
                # for det in self.detectors:
                #     det.arm(mode='ndarray', numframes=npulses, fnum=irow-1, wait=False)
                time.sleep(0.25)

            elif irow < npts-1:
                for p in self.positioners:
                    p.move_to_pos(irow, wait=True)

            # check again for pause, resume, and abort
            self.look_for_interrupts()
            while self.pause:
                time.sleep(0.25)
                if self.look_for_interrupts():
                    break
            if self.look_for_interrupts():
                if mappref is not None:
                    caput('%sstatus' % (mappref), 'Aborting')
                break
            if debug:
                dtimer.show()
            time.sleep(0.01)

        if mappref is not None:
            caput('%sstatus' % (mappref), 'Finishing')

        self.post_scan()
        print('Scan done.')
        self.set_info('scan_progress', 'done')
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
