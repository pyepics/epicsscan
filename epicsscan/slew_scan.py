#!/usr/bin/env python
"""
Slew Scan based on EpicsApps.StepScan.
"""
import sys
import os
import json
import shutil
import time
from pathlib import Path
from threading import Thread
import numpy as np
import yaml
from .scan import StepScan
from .positioner import Positioner
from .saveable import Saveable

from .detectors import (Counter, Trigger, AreaDetector, write_poni)
from .file_utils import fix_varname, fix_filename, increment_filename

from epics import PV, poll, get_pv, caget, caput
from newportxps import NewportXPS

from pyshortcuts import debugtimer, isotime

# this will preven yoml from "cleverly" making references to repeated values
yaml.SafeDumper.ignore_aliases = lambda *args: True

def save_yaml(filepath, data, default_flow_style=None, indent=4):
    """save data to file as yaml"""
    with open(filepath, 'w') as fh:
        fh.write(yaml.safe_dump(data,
                                default_flow_style=default_flow_style,
                                indent=indent))


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
        if self.scandb.get_infobool('zero_finemotors_beforemap'):
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

        inner_pos = self.scandb.get_slewpositioner(self.inner['label'])
        conf = self.scandb.get_config_id(inner_pos.config_id)
        scnf = self.slewscan_config = json.loads(conf.notes)

        self.xps = self.scandb.connections.get('mapping_xps', None)
        if self.xps is None:
            print("Slew SCAN creating New Connection to NewportXPS: ")
            # print(scnf)
            self.xps = NewportXPS(scnf['host'],
                                    username=scnf['username'],
                                    password=scnf['password'],
                                    group=scnf['group'],
                                    outputs=scnf['outputs'],
                                    extra_triggers=scnf.get('extra_triggers', 0))
            self.scandb.connections['mapping_xps'] = self.xps

        fileroot = self.scandb.get_info('server_fileroot', '.')
        userdir = self.scandb.get_info('user_folder', '.')
        basedir = os.path.join(fileroot, userdir, 'Maps')
        if not os.path.exists(basedir):
            os.mkdir(basedir, mode=509)
            os.chmod(basedir, 509)

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
        Path(mapdir).mkdir(exist_ok=True, mode=493)

        hfname= os.path.join(basedir, self.filename)
        self.set_info('filename', fname)
        self.set_info('map_folder', mapdir)

        with open(hfname, 'w') as fh:
            fh.write(f"{mapdir}\n")
        self.mapdir = mapdir
        self.fileroot = fileroot
        save_yaml(Path(mapdir, '_Scan.yaml'), self.scandict)


        dim  = 1 if self.outer is None else 2
        start, stop, npts = self.inner['start'], self.inner['stop'], self.inner['npts']
        self.rowtime = dtime = self.dwelltime*(npts-1)
        pospv = self.inner['pvdrive']
        if pospv.endswith('.VAL'):
            pospv = pospv[:-4]
        dirpv = f'{pospv}.DIR'
        if caget(dirpv) == 1:
            start, stop = stop, start
        step = abs(start-stop)/(npts-1)

        axis = None
        for ax, pvname in self.slewscan_config['motors'].items():
            if pvname == pospv:
                axis = ax

        if axis is None:
           raise ValueError(f"Could not find XPS Axis for {pospv=}")

        self.xps.define_line_trajectories(axis, group=scnf['group'],
                                          pixeltime=self.dwelltime,
                                          start=start, stop=stop, step=step)
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


    def post_slew_scan(self, **kws):
        for det in self.detectors:
            if isinstance(det, AreaDetector):
                self.set_info('xrd_1dint_status', 'finishing')

    def write_master(self, text):
        """ write a list of text lines to master file"""
        for txt in text.split('\n'):
            self.scandb.add_slewscanstatus(txt)

        mfile = Path(self.mapdir, 'Master.dat').absolute()
        mode = 'a' if mfile.exists() else 'w'
        with open(mfile, mode) as fh:
            fh.write(text)

    def save_mcs_data(self, filename='mcsdata.001', npts=1):
        scafile = self.scadet.get_next_filename()
        filename = Path(self.mapdir, scafile).absolute().as_posix()
        _, self.npts_sca = self.scadet.save_arraydata(filename=filename,
                                                   npts=self.npts_sca)

    def save_extra_data(self, xrfdet=None, xrddet=None):
        t0 = time.time()
        envdat = {}
        for desc, pvname, value in self.read_extra_pvs():
            envdat[desc] = [f"{value}", pvname]
        save_yaml(Path(self.mapdir, '_Environ.yaml'), envdat)
        if xrfdet is not None:
            fpath = Path(self.mapdir, f'ROICALIB_{xrfdet.label}.dat')
            xrfdet.save_calibration(fpath.absolute().as_posix())
        if xrddet is not None:
            xrd_poni = self.scandb.get_info('xrd_calibration', None)
            if xrd_poni is not None:
                calib = json.loads(self.scandb.get_detectorconfig(xrd_poni).text)
                poni_file =Path(self.mapdir, f'XRD_{xrddet.label}.poni').absolute().as_posix()
                write_poni(poni_file, calname=xrd_poni, **calib)

    def run(self, filename='map.001', comments=None, debug=False, npts=None):
        """
        run a slew scan
        """
        debug = self.scandb.get_infobool('debug_scan') or debug
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

        npulses = trajs[tname]['npulses'] + 1
        dwelltime = trajs[tname]['pixeltime']

        for p in self.positioners:
            p.move_to_pos(0, wait=False)

        for pv, v1, v2 in self.motor_vals.values():
            val = v1
            if tname == 'backward': val = v2
            pv.put(val, wait=False)

        self.scandb.clear_slewscanstatus()
        self.scandb.set_filename(self.filename)
        self.pre_scan(npulses=npulses, filename=self.filename,
                      dwelltime=dwelltime, mode='ndarray')

        dim  = 1
        npts = 1

        xnpts = self.inner['npts']
        xstart, xstop = self.inner['start'], self.inner['stop']
        xstep = abs(xstart-xstop)/(xnpts-1)
        xpos = self.inner['pvdrive']
        if xpos.endswith('.VAL'):
            xpos = xpos[:-4]

        if self.outer is not None:
            dim = 2
            npts = min(self.outer['npts'], len(self.positioners[0].array))
            start, stop = self.outer['start'], self.outer['stop']
            step = abs(start-stop)/(npts-1)
            ypos = self.outer['pvdrive']
            if ypos.endswith('.VAL'):
                ypos = ypos[:-4]
        mbuff = ["#Scan.version = 2.0",
                 f'#SCAN.starttime = {isotime()}',
                 f'#SCAN.filename  = {self.filename}',
                 f'#SCAN.dimension = {dim}',
                 f'#SCAN.nrows_expected = {npts}',
                 f'#SCAN.time_per_row_expected = {self.rowtime:.2f}',
                 f'#X.positioner  = {xpos}',
                 f'#X.start_stop_step_npts = {xstart}, {xstop}, {xstep}, {xnpts}']
        if dim == 2:
            mbuff.extend([f'#Y.positioner  = {ypos}',
                         f'#Y.start_stop_step_npts = {start}, {stop}, {step}, {npts}'])
        mbuff.extend(['#------------------------------------',
                      '# yposition  xrf_file  mcs_file  xps_file  xrd_file   time', ''])

        self.write_master('\n'.join(mbuff))

        detpath = self.mapdir[len(self.fileroot):]
        scadet = xrfdet = xrddet = None
        scafile = xrffile = xrdfile = '_unused_'
        for det in self.detectors:
            dlabel = det.label.lower()
            if dlabel in ('struck', 'usbctr', 'mcs'):
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

        # self.clear_interrupts()
        self.set_info('scan_progress', 'starting')
        rowdata_ok = True
        start_time = time.time()
        irow = 0
        dtimer =  debugtimer()
        self.scandb.set_info('repeated_map_rows', '')
        repeated_rows = []

        ex_thread = Thread(target=self.save_extra_data,
                           kwargs=dict(xrfdet=xrfdet, xrddet=xrddet),
                           name='ex_thread')
        ex_thread.start()
        ##
        ##
        while irow < npts:
            # check for pause, resume, and abort
            self.look_for_interrupts()
            while self.pause:
                time.sleep(0.25)
                abort = self.look_for_interrupts()
                if self.resume or abort:
                    break
            if self.abort:
                break
            irow += 1
            dtimer.add('=== row start %i ====' % irow)
            self.set_info('scan_progress', f'row {irow} of {npts}')
            trajname = ['foreward', 'backward'][(dir_off + irow) % 2]

            if debug:
                print(f"# Row {irow} of {npts} {trajname=}")

            if self.mkernel is not None:
                now = time.time()
                prescan_lasttime = float(self.scandb.get_info('prescan_lasttime', default=0.0))
                prescan_interval = float(self.scandb.get_info('prescan_interval', default=3600.0))
                run_prescan = (now > prescan_lasttime + prescan_interval)
                if run_prescan:
                    try:
                        self.mkernel.run(f"pre_scan_command(row={irow}, npts={npts})")
                    except:
                        print(f"Failed to run pre_scan_command(row={irow})")
                    self.set_info('prescan_lasttime', f"{now:.0f}")

            for pv, v1, v2 in self.motor_vals.values():
                val = v1 if (trajname == 'foreward') else v2
                pv.put(val, wait=False)

            lastrow_ok = rowdata_ok
            rowdata_ok = True

            dtimer.add(f'inner pos move started {irow=}')
            for det in self.detectors:
                det.arm(mode='ndarray', numframes=npulses, fnum=irow, wait=False)

            # wait for detectors to be armed
            tout = time.time()+2.0
            while not all([det.arm_complete for det in self.detectors]):
                if time.time() > tout:
                    break
                time.sleep(0.005)

            dtimer.add(f'detectors armed {det_arm_delay:.3f}')
            for det in self.detectors:
                det.start(arm=False, wait=False)

            time.sleep(det_start_delay)
            dtimer.add(f'detectors started {det_start_delay:.3f}')

            for p in self.positioners:
                p.move_to_pos(irow-1, wait=True)

            dtimer.add(f'Moved Positioners to row {irow-1}')
            for pv, v1, v2 in self.motor_vals.values():
                val = v1 if (trajname == 'foreward') else v2
                pv.put(val, wait=True)

            dtimer.add(f'Positioners in Place, Arm Traj')
            try:
                self.xps.arm_trajectory(trajname, move_to_start=False)
            except:
                print(f"XPS Failed to Arm Trajectory for row {irow} will try again")
                time.sleep(10.0)
                try:
                    self.xps.arm_trajectory(trajname, move_to_start=False)
                except:
                    print(f"XPS Failed to Arm Trajectory for row {irow} a second time. Aborting scan")
                    return

            time.sleep(0.025)
            if irow < 2 or not lastrow_ok:
                time.sleep(0.05)
            dtimer.add(f'XPS trajectory armed {trajname}')

            # start trajectory in another thread
            scan_thread = Thread(target=self.xps.run_trajectory,
                                 kwargs=dict(move_to_start=False,
                                             clean=False,
                                             save=False, verbose=False),
                                 name='trajectory_thread')
            scan_thread.start()

            dtimer.add(f'scan thread started {self.rowtime=}')
            posfile = f"xps.{irow:04}"
            if scadet is not None:
                scafile = f"{scadet.label}.{irow:04}"
            if xrfdet is not None:
                xrffile = f"{xrfdet.label}.{irow:04}"
            if xrddet is not None:
                xrdfile = f"{xrddet.label}.{irow:04}"

            if dim == 2:
                pos0 = f"{(self.positioners[0].array[irow-1]):10.6f}"
            else:
                pos0 = "_unused_"

            masterline = ' '.join([pos0, xrffile, scafile, posfile, xrdfile])
            # wait for trajectory to finish
            xt0 = time.time()
            while (scan_thread.is_alive() or (time.time() < xt0+0.5*self.rowtime)):
                time.sleep(0.05)
                if time.time() > xt0 + 0.90*self.rowtime:
                    break

            scan_thread.join(timeout=self.rowtime)
            dtimer.add('scan thread joined (complete)')
            mrows =[pos0, xrffile, scafile, posfile, xrdfile,
                    f"{(time.time()-start_time):10.6f}\n"]
            self.write_master(' '.join(mrows))

            pos_file = Path(self.mapdir, posfile).absolute().as_posix()
            pos_saver = Thread(target=self.xps.read_and_save,
                               args=(pos_file,),
                               kwargs={'use_ftp': False},
                               name='pos_saver')
            pos_saver.start()
            dtimer.add('started XPS save')

            if irow < npts-1:
                for p in self.positioners:
                    p.move_to_pos(irow, wait=False)
            dtimer.add('started next move, reading')

            self.npts_sca = npulses
            if scadet is not None:
                scadet.stop()
                self.scadet = scadet
                mcs_saver_thread = Thread(target=self.save_mcs_data,  name='mcs_saver')
                mcs_saver_thread.start()
            dtimer.add('started MCS data save')

            time.sleep(0.002)
            nxrf = nxrd = 0
            if xrfdet is not None:
                xrfdet.stop()
                time.sleep(0.02)
                t0 = time.time()
                write_complete = xrfdet.file_write_complete()
                ntry = 0
                while not write_complete and (time.time()-t0 < 10.0):
                    write_complete = xrfdet.file_write_complete()
                    ntry = ntry + 1
                    time.sleep(0.01*ntry)
                time.sleep(0.01)
                nxrf = xrfdet.get_numcaptured()
                if (nxrf < npulses-1) or not write_complete:
                    time.sleep(0.05)
                    xrfdet.finish_capture()
                    time.sleep(0.025)
                    nxrf = xrfdet.get_numcaptured()
                    write_complete = xrfdet.file_write_complete()
                if (nxrf < npulses-1) or not write_complete:
                    time.sleep(0.050)
                    xrfdet.finish_capture()
                    nxrf = xrfdet.get_numcaptured()
                    write_complete = xrfdet.file_write_complete()
                if (nxrf < npulses-2) or not write_complete:
                    print("XRF file write failed ", write_complete, nxrf, npulses, ntry)
                    rowdata_ok = False
                    xrfdet.stop()
                    time.sleep(0.10)
            dtimer.add(f'saved XRF data')

            if xrddet is not None:
                nxrd = xrddet.get_numcaptured()
                while ((nxrd < nxrf) and
                       (time.time()- t0 < 10.0)):
                    nxrd = xrddet.get_numcaptured()
                    time.sleep(0.003)
                xrddet.stop()
                dtimer.add('saved XRD data')

            mcs_saver_thread.join(timeout=0.5)
            dtimer.add('saved MCS data')
            if pos_saver.is_alive():
                pos_saver.join(timeout=0.5 + (npulses)/1000.)
            dtimer.add('saved XPS gathering data')
            rowdata_ok = rowdata_ok and (self.npts_sca >= npulses-2)
            rowdata_ok = rowdata_ok and (self.xps.ngathered >= npulses-2)

            if xrfdet is not None:
                rowdata_ok = rowdata_ok and (nxrf >= npulses-2)

            if debug or True:
                print("#== Row %d nXPS=%d, nMCS=%d, nXRF=%d, nXRD=%d  npulses=%d, OK=%s" %
                      (irow, self.xps.ngathered, self.npts_sca, nxrf, nxrd, npulses, repr(rowdata_ok)))
            if not rowdata_ok:
                fmt=  '#BAD Row %d nXPS=%d, nMCS=%d, nXRF=%d, nXRD=%d: (npulses=%d) redo!\n'
                self.write(fmt % (irow, self.xps.ngathered, self.npts_sca, nxrf, nxrd, npulses))
                irow -= 1
                [p.move_to_pos(irow, wait=False) for p in self.positioners]
                time.sleep(0.25)

            if debug or True:
                dtimer.show()

        ex_thread.join()
        self.write_master('\n')
        self.post_scan()
        self.set_info('scan_progress', 'done')
        return

    def check_beam_ok(self):
        return True
