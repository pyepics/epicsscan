#!/usr/bin/env python
"""
xafs scan
based on EpicsApps.StepScan.

"""
import time
import json
import numpy as np
from threading import Thread
from epics import caget, caput, PV, get_pv
from larch import Group

from .scan import StepScan
from .positioner import Positioner
from .saveable import Saveable
from .file_utils import fix_varname
from .utils import ScanDBAbort, hms
from .detectors import Struck, TetrAMM, Xspress3, Counter
from .xps import NewportXPS
from .debugtime import debugtime
XAFS_K2E = 3.809980849311092
HC       = 12398.4193
RAD2DEG  = 180.0/np.pi
MAXPTS   = 8192


class PVSlaveThread(Thread):
    """
    Sets up a Thread to allow a Master Index PV (say, an advancing channel)
    to send a Slave PV to a value from a pre-defined array.

    undulator = PVSlaveThread(master_pvname='13IDE:SIS1:CurrentChannel',
                              slave_pvname='ID13us:ScanEnergy')
    undulator.set_array(array_of_values)
    undulator.enable()
    # start thread
    undulator.start()

    # other code that may trigger the master PV

    # to finish, set 'running' to False, and join() thread
    undulator.running = False
    undulator.join()

    """
    def __init__(self, master_pvname=None,  slave_pvname=None, scan=None,
                 values=None, maxpts=8192, wait_time=0.05, dead_time=1.1,
                 offset=3, ready_pv=None, ready_val=0):
        Thread.__init__(self)
        self.maxpts = maxpts
        self.offset = offset
        self.wait_time = wait_time
        self.dead_time = dead_time
        self.last_move_time = time.time() - 100.0
        self.last = -1
        self.pulse = -1
        self.scan = scan
        self.running = False
        self.vals = values
        self.ready_pv = None
        self.ready_val = ready_val
        # if ready_pv is None:
        #     ready_pv = 'ID13us:Busy.VAL'

        if self.vals is None:
            self.vals  = np.zeros(self.maxpts)
        self.master = None
        self.slave = None
        if master_pvname is not None:
            self.set_master(master_pvname)
        if slave_pvname is not None:
            self.set_slave(slave_pvname)
        if ready_pv is not None:
            self.ready_pv = get_pv(ready_pv)

    def set_master(self, pvname):
        self.master = get_pv(pvname, callback=self.onPulse)

    def set_slave(self, pvname):
        self.slave = get_pv(pvname)

    def onPulse(self, pvname, value=1, **kws):
        self.pulse  = max(0, min(self.maxpts, value + self.offset))

    def set_array(self, vals):
        "set array values for slave PV"
        n = len(vals)
        if n > self.maxpts:
            vals = vals[:self.maxpts]
        self.vals  = np.ones(self.maxpts) * vals[-1]
        self.vals[:n] = vals

    def enable(self):
        self.last = self.pulse = -1
        self.last_message = 0.1
        self.running = True

    def run(self):
        while self.running:
            time.sleep(0.005)
            now = time.time()
            if self.pulse > self.last:
                ready = True
                if self.ready_pv is not None:
                    ready = (self.ready_pv.get() == self.ready_val)
                ready = ready and ((now- self.last_move_time) > self.dead_time)
                if ready and self.slave.write_access:
                    val = self.vals[self.pulse]
                    try:
                        print("Put ID To %i  E=%.4f" % (self.pulse, val))
                        self.slave.put(val)
                        self.last_move_time = time.time()
                    except:
                        print("PVFollow Put failed: ", self.slave.pvname , val)
                self.last = self.pulse
                if (self.scan is not None) and self.pulse > 3:
                    npts = self.scan.npts
                    cpt = self.pulse
                    dtime = self.scan.dwelltime
                    if isinstance(dtime, list):
                        dtime = dtime[0]
                    time_left = (npts-cpt)*dtime
                    self.scan.set_info('scan_time_estimate', time_left)
                    time_est  = hms(time_left)
                    msg = 'Point %i/%i, time left: %s' % (cpt, npts, time_est)
                    if (cpt - self.last_message) >  self.scan.message_points:
                        self.scan.write("%s\n" % msg)
                        self.last_message = cpt*1.0
                    self.scan.set_info('scan_progress', msg)
                    for c in self.scan.counters:
                        try:
                            c.buff = c.pv.get().tolist()
                        except:
                            pass
                        name = getattr(c, 'db_label', None)
                        if name is None:
                            name = c.label
                        c.db_label = fix_varname(name)
                        self.scan.scandb.set_scandata(c.db_label, c.buff)
                    self.scan.scandb.commit()


def etok(energy):
    return np.sqrt(energy/XAFS_K2E)

def ktoe(k):
    return k*k*XAFS_K2E

def energy2angle(energy, dspace=3.13555):
    omega   = HC/(2.0 * dspace)
    return RAD2DEG * np.arcsin(omega/energy)

class ScanRegion(Saveable):
    def __init__(self, start, stop, npts=None,
                 relative=True, e0=None, use_k=False,
                 dtime=None, dtime_final=None, dtime_wt=1):
        Saveable.__init__(self, start, stop, npts=npts,
                          relative=relative,
                          e0=e0, use_k=use_k,
                          dtime=dtime,
                          dtime_final=dtime_final,
                          dtime_wt=dtime_wt)


class XAFS_Scan(StepScan):
    """XAFS Scan"""
    def __init__(self, label=None, energy_pv=None, read_pv=None,
                 extra_pvs=None,  e0=0, elem='', edge='', scandb=None, **kws):
        self.label = label
        self.e0 = e0
        self.elem = elem
        self.edge = edge
        self.energies = []
        self.regions = []
        StepScan.__init__(self, **kws)
        self.scantype = 'xafs'
        self.detmode  = 'scaler'
        self.dwelltime = []
        self.energy_pos = None
        self.scandb = scandb
        self.set_energy_pv(energy_pv, read_pv=read_pv, extra_pvs=extra_pvs)

    def set_energy_pv(self, energy_pv, read_pv=None, extra_pvs=None):
        self.energy_pv = energy_pv
        self.read_pv = read_pv
        if energy_pv is not None:
            self.energy_pos = Positioner(energy_pv, label='Energy',
                                         extra_pvs=extra_pvs)
            self.positioners = []
            self.add_positioner(self.energy_pos)
        if read_pv is not None:
            self.add_counter(read_pv, label='Energy_readback')

    def add_region(self, start, stop, step=None, npts=None,
                   relative=True, use_k=False, e0=None,
                   dtime=None, dtime_final=None, dtime_wt=1, min_estep=0.01):
        """add a region to an EXAFS scan.
        Note that scans must be added in order of increasing energy
        """
        if e0 is None:
            e0 = self.e0
        if dtime is None:
            dtime = self.dtime
        if min_estep < 0:
            min_estep = 0.01
        self.e0 = e0
        self.dtime = dtime

        if npts is None and step is None:
            print('add_region needs start, stop, and either step on npts')
            return

        if step is not None:
            npts = 1 + int(0.1  + abs(stop - start)/step)

        en_arr = list(np.linspace(start, stop, npts))
        # note: save region definition using npts here,
        # even though npts may be reduced below, this set
        # will provide reproducible results, and so can be
        # save for later re-use.
        #         self.regions.append(ScanRegion(start, stop, npts=npts,
        #                              relative=relative,
        #                              e0=e0, use_k=use_k,
        #                              dtime=dtime,
        #                              dtime_final=dtime_final,
        #                              dtime_wt=dtime_wt))
        #

        self.regions.append((start, stop, npts, relative, e0, use_k, dtime,
                             dtime_final, dtime_wt))

        if use_k:
            en_arr = [e0 + ktoe(v) for v in en_arr]
        elif relative:
            en_arr = [e0 +    v    for v in en_arr]

        # check that all energy values in this region are
        # greater than previously defined regions
        en_arr.sort()
        min_energy = min_estep
        if len(self.energies) > 0:
            min_energy += max(self.energies)
        en_arr = [e for e in en_arr if e > min_energy]

        npts   = len(en_arr)

        dt_arr = [dtime]*npts
        # allow changing counting time linear or by a power law.
        if dtime_final is not None and dtime_wt > 0:
            _vtime = (dtime_final-dtime)*(1.0/(npts-1))**dtime_wt
            dt_arr= [dtime + _vtime *i**dtime_wt for i in range(npts)]
        self.energies.extend(en_arr)
        self.dwelltime.extend(dt_arr)
        if self.energy_pos is not None:
            self.energy_pos.array = np.array(self.energies)

class QXAFS_Scan(XAFS_Scan):
    """QuickXAFS Scan"""

    def __init__(self, label=None, energy_pv=None, read_pv=None,
                 extra_pvs=None, e0=0, elem='', edge='', scandb=None, **kws):

        self.label = label
        self.e0 = e0
        self.energies = []
        self.regions = []
        self.xps = None
        XAFS_Scan.__init__(self, label=label, energy_pv=energy_pv,
                           read_pv=read_pv, e0=e0, scandb=scandb,
                           extra_pvs=extra_pvs, elem=elem, edge=edge, **kws)
        self.set_energy_pv(energy_pv, read_pv=read_pv, extra_pvs=extra_pvs)
        self.scantype = 'xafs'
        self.detmode  = 'roi'
        self.config = None
        if scandb is not None:
            self.connect_qxafs()


    def connect_qxafs(self):
        """initialize a QXAFS scan"""
        if self.config is None:
            self.config = json.loads(self.scandb.get_config('qxafs').notes)
        conf = self.config
        if self.xps is None:
            self.xps = NewportXPS(conf['host'],
                                  username=conf['username'],
                                  password=conf['password'],
                                  group=conf['group'],
                                  outputs=conf['outputs'],
                                  extra_triggers=conf.get('extra_triggers', 0))

        qconf = self.config
        caput(qconf['id_track_pv'], 1)
        caput(qconf['y2_track_pv'], 1)
        self.scandb.set_info('qxafs_running', 0)
        caput(qconf['id_array_pv'], np.zeros(2000))

    def make_trajectory(self, reverse=False,
                        theta_accel=2, width_accel=0.050, **kws):
        """this method builds the text of a Trajectory script for
        a Newport XPS Controller based on the energies and dwelltimes"""

        if self.config is None:
            self.connect_qxafs()

        qconf = self.config
        qconf['theta_motor'] = qconf['motors']['THETA']
        qconf['width_motor'] = qconf['motors']['HEIGHT']

        dspace = caget(qconf['dspace_pv'])
        height = caget(qconf['height_pv'])
        th_off = caget(qconf['theta_motor'] + '.OFF')
        wd_off = caget(qconf['width_motor'] + '.OFF')
        # theta_accel = max(1.5, theta_accel)

        # we want energy trajectory points to be at or near
        # midpoints of desired energy values
        enx = [2*self.energies[0]  - self.energies[1]]
        enx.extend(list(self.energies))
        enx.append(2*self.energies[-1]  - self.energies[-2])
        enx = np.array(enx)
        energy = (enx[1:] + enx[:-1])/2.0

        # but now update self.energies to better reflect what will
        # be the result of this trajectory:
        self.energy_pos.array = (energy[1:] + energy[:-1])/2.0

        times  = np.array(len(energy)*[self.dwelltime[0]])

        if reverse:
            energy = energy[::-1]
            times  = times[::-1]

        # print("QXAFS Traj: energy = ", energy)
        traw    = energy2angle(energy, dspace=dspace)
        theta  = 1.0*traw
        theta[1:-1] = traw[1:-1]/2.0 + traw[:-2]/4.0 + traw[2:]/4.0
        width  = height / (2.0 * np.cos(theta/RAD2DEG))

        width -= wd_off
        theta -= th_off

        tvelo = np.gradient(theta)/times
        wvelo = np.gradient(width)/times
        tim0  = abs(tvelo[0] / theta_accel)
        the0  = 0.5 * tvelo[ 0] * tim0
        wid0  = 0.5 * wvelo[ 0] * tim0
        the1  = 0.5 * tvelo[-1] * tim0
        wid1  = 0.5 * wvelo[-1] * tim0

        print("Theta Accel ", theta_accel)
        dtheta = np.diff(theta)
        dwidth = np.diff(width)
        dtime  = times[1:]
        fmt = '%.8f, %.8f, %.8f, %.8f, %.8f'
        efirst = fmt % (tim0, the0, tvelo[0], wid0, wvelo[0])
        elast  = fmt % (tim0, the1, 0.00,     wid1, 0.00)

        buff  = ['', efirst]
        npts = len(dtheta)
        for i in range(npts):
            buff.append(fmt % (dtime[i], dtheta[i], tvelo[i],
                               dwidth[i], wvelo[i]))
        buff.append(elast)

        old =  Group(buffer='\n'.join(buff),
                     start_theta=theta[0]+the0,
                     start_width=width[0]-wid0,
                     theta=theta, tvelo=tvelo,   times=times,
                     energy=energy, width=width, wvelo=wvelo)

        buff.append("")
        buff = '\n'.join(buff)
        traj = {'energy': energy, 'buff': buff,
                'width': width, 'theta': theta, 'theta0': the0,
                'axes': ['THETA', 'HEIGHT'],
                'start': [theta[0]-the0, width[0]-wid0],
                'stop':  [theta[-1]+the0, width[-1]+wid0],
                'pixeltime': self.dwelltime[0],
                'npulses': npts, 'nsegments': npts}
        self.xps.trajectories['qxafs'] = traj
        self.xps.upload_trajectory('qxafs.trj', buff)
        return traj

    def finish_qscan(self):
        """initialize a QXAFS scan"""
        qconf = self.config
        caput(qconf['id_track_pv'],  1)
        caput(qconf['y2_track_pv'],  1)
        time.sleep(0.1)

    def gathering2energy(self, text):
        """read gathering file, calculate and return
        energy and height. Gathering data is text with columns of
         Theta_Current, Theta_Set, Height_Current, Height_Set
        """
        angle, height = [], []
        for line in text.split('\n'):
            line = line[:-1].strip()
            if len(line) > 4:
                words = line[:-1].split()
                angle.append(float(words[0]))
                height.append(float(words[2]))
        angle  = np.array(angle)
        height = np.array(height)
        angle  = (angle[1:] + angle[:-1])/2.0
        height = (height[1:] + height[:-1])/2.0

        qconf = self.config
        angle += caget(qconf['theta_motor'] + '.OFF')
        dspace = caget(qconf['dspace_pv'])
        energy = HC/(2.0 * dspace * np.sin(angle/RAD2DEG))
        return (energy, height)


    def run(self, filename=None, comments=None, debug=False, reverse=False):
        """
        run the actual QXAFS scan
        """
        dtimer =  debugtime()

        self.complete = False
        if filename is not None:
            self.filename  = filename

        if comments is not None:
            self.comments = comments

        ts_start = time.time()
        if not self.verify_scan():
            self.write('Cannot execute scan: %s' % self._scangroup.error_message)
            self.set_info('scan_message', 'cannot execute scan')
            return

        dtimer.add('scan verified')
        self.scandb.set_info('qxafs_running', 1) # preparing
        self.connect_qxafs()
        qconf = self.config
        dtimer.add('connect qxafs')
        traj = self.make_trajectory()

        dtimer.add('make traj')
        energy_orig = caget(qconf['energy_pv'])
        id_offset = 1000.0*caget(qconf['id_offset_pv'])
        idarray = 1.e-3*(1.0+id_offset/energy_orig)*traj['energy']
        idarray = np.concatenate((idarray, idarray[-1]+np.arange(1,26)/250.0))
        # print("idarray: ", idarray)
        dtimer.add('idarray')
        time.sleep(0.1)
        caput(qconf['theta_motor'] + '.DVAL', traj['start'][0])
        caput(qconf['width_motor'] + '.DVAL', traj['start'][1])

        orig_positions = [p.current() for p in self.positioners]
        # print("Original Positions: ", orig_positions)
        dtimer.add('orig positions')
        try:
            caput(qconf['id_drive_pv'], idarray[0], wait=False)
        except:
            pass
        caput(qconf['energy_pv'],  traj['energy'][0], wait=False)

        self.clear_interrupts()
        dtimer.add('clear interrupts')
        sis_prefix = qconf['mcs_prefix']

        caput(qconf['id_array_pv'], idarray)
        self.scandb.set_info('qxafs_dwelltime', self.dwelltime[0])

        caput(qconf['energy_pv'], traj['energy'][0], wait=True)
        try:
            caput(qconf['id_drive_pv'], idarray[0], wait=True, timeout=5.0)
        except:
            pass

        npts = len(self.positioners[0].array)
        self.dwelltime_varys = False
        dtime = self.dwelltime[0]
        dtimer.add('set dwelltime')
        self.set_info('scan_progress', 'preparing scan')
        extra_vals = []
        for desc, pv in self.extra_pvs:
            extra_vals.append((desc, pv.get(as_string=True), pv.pvname))

        self.xps.arm_trajectory('qxafs')
        dtimer.add('traj armed')
        out = self.pre_scan(npulses=traj['npulses'],
                            dweltims=dtime, mode='roi')
        self.check_outputs(out, msg='pre scan')
        dtimer.add('prescan ran')

        det_arm_delay = det_start_delay = 0.05
        det_prefixes = []
        for det in self.detectors:
            det_prefixes.append(det.prefix)
            det.arm(mode='roi', numframes=traj['npulses'], fnum=0, wait=False)
            det_arm_delay = max(det_arm_delay, det.arm_delay)
            det_start_delay = max(det_start_delay, det.start_delay)

        time.sleep(det_arm_delay)

        dtimer.add('detectors armed')
        ## need to use self.rois to re-load ROI arrays
        ## names like  MCA1ROI:N:TSTotal
        _counters = []
        for c in self.counters:
            pvname = c.pv.pvname
            found = any([pref in pvname for pref in det_prefixes])
            if found:
                _counters.append((pvname, c.label))

        self.counters = [Counter(pv, label=lab) for pv, lab in _counters]

        self.init_scandata()
        dtimer.add('init scandata')
        for det in self.detectors:
            det.start(arm=False, wait=False)
        time.sleep(det_start_delay)
        dtimer.add('detectors started')

        self.datafile = self.open_output_file(filename=self.filename,
                                              comments=self.comments)

        self.scandb.set_info('qxafs_running', 2) # running
        self.datafile.write_data(breakpoint=0)
        dtimer.add('datafile opened')
        self.filename =  self.datafile.filename

        self.scandb.set_filename(self.filename)
        self.set_info('request_abort', 0)
        self.set_info('scan_time_estimate', npts*dtime)
        self.set_info('scan_total_points', npts)

        self.datafile.flush()
        self.set_info('scan_progress', 'starting scan')
        self.cpt = 0
        self.npts = npts

        ts_init = time.time()
        self.inittime = ts_init - ts_start
        start_time = time.strftime('%Y-%m-%d %H:%M:%S')
        dtimer.add('info set')
        time.sleep(1.0)
        out = self.xps.run_trajectory(name='qxafs', save=False)
        dtimer.add('trajectory run')

        self.set_info('scan_progress', 'reading data')
        for det in self.detectors:
            det.stop()

        time.sleep(0.5)

        npulses, gather_text = self.xps.read_gathering()
        energy, height = self.gathering2energy(gather_text)

        self.pos_actual = []
        for e in energy:
           self.pos_actual.append([e])

        ne = len(energy)
        caput(qconf['energy_pv'], energy_orig-0.50)

        self.finish_qscan()

        out = self.post_scan()
        self.check_outputs(out, msg='post scan')


        [c.read() for c in self.counters]

        narr, ix = 0, 0
        t0  = time.time()
        while narr < (ne-1) and (time.time()-t0) < 15.0:
            time.sleep(0.1 + ix*0.1)
            [c.read() for c in self.counters]
            ndat = [len(c.buff) for c in self.counters]
            narr = min(ndat)

        # print("Read QXAFS Data %i points (NE=%i) %.3f secs" % (narr, ne, time.time() - t0))
        # remove hot first pixel AND align to proper energy
        # really, we tested this, comparing to slow XAFS scans!
        for c in self.counters:
            c.buff = c.buff[1:]

        self.set_all_scandata()
        dtimer.add('set scan data')
        for val, pos in zip(orig_positions, self.positioners):
            pos.move_to(val, wait=False)

        self.datafile.write_data(breakpoint=-1, close_file=True, clear=False)

        caput(qconf['energy_pv'], energy_orig, wait=True)

        if self.look_for_interrupts():
            self.write("scan aborted at point %i of %i." % (self.cpt, self.npts))
            raise ScanDBAbort("scan aborted")

        # run post_scan methods
        self.set_info('scan_progress', 'finishing')
        out = self.post_scan()
        self.check_outputs(out, msg='post scan')
        self.complete = True
        self.set_info('scan_progress',
                      'scan complete. Wrote %s' % self.datafile.filename)
        self.scandb.set_info('qxafs_running', 0)
        self.runtime  = time.time() - ts_start
        dtimer.add('done')
        # dtimer.show()
        return self.datafile.filename
        ##
