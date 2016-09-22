#!/usr/bin/env python
"""
xafs scan
based on EpicsApps.StepScan.

"""
import numpy as np
from threading import Thread
from epics import caget, caput, PV

from .scan import StepScan
from .positioner import Positioner
from .saveable import Saveable

from .utils import ScanDBAbort
from .detectors import Struck, TetrAMM, Xspress3

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
                 values=None, maxpts=8192, wait_time=0.05, dead_time=0.5,
                 offset=3):
        Thread.__init__(self)
        self.maxpts = maxpts
        self.offset = offset
        self.wait_time = wait_time
        self.dead_time = dead_time
        self.last_move_time = time.time() - 100.0
        self.pulse = -1
        self.last  = None
        self.scan = scan
        self.running = False
        self.vals = values
        if self.vals is None:
            self.vals  = np.zeros(self.maxpts)
        self.master = None
        self.slave = None
        if master_pvname is not None: self.set_master(master_pvname)
        if slave_pvname is not None: self.set_slave(slave_pvname)

    def set_master(self, pvname):
        self.master = PV(pvname, callback=self.onPulse)

    def set_slave(self, pvname):
        self.slave = PV(pvname)

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
        self.running = True

    def run(self):
        while self.running:
            time.sleep(self.wait_time)
            now = time.time()
            if (self.pulse > self.last and self.last is not None and
                (now - self.last_move_time) > self.dead_time):
                val = self.vals[self.pulse]
                if self.slave.write_access:
                    try:
                        self.slave.put(val)
                        self.last_move_time = time.time()
                    except:
                        print("PVFollow Put failed: ", self.slave.pvname , val)
                self.last = self.pulse
                if (self.scan is not None and self.pulse > 3 and self.pulse % 5 == 0):
                    npts = self.scan.npts
                    cpt = self.pulse
                    dtime = self.scan.dwelltime
                    if isinstance(dtime, list):
                        dtime = dtime[0]
                    time_left = (npts-cpt)*dtime
                    self.scan.set_info('scan_time_estimate', time_left)
                    time_est  = hms(time_left)
                    msg = 'Point %i/%i,  time left: %s' % (cpt, npts, time_est)
                    if cpt % self.scan.message_points == 0:
                        self.scan.write("%s\n" % msg)
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
                 extra_pvs=None,  e0=0, **kws):
        self.label = label
        self.e0 = e0
        self.energies = []
        self.regions = []
        StepScan.__init__(self, **kws)
        self.scantype = 'xafs'
        self.detmode  = 'scaler'
        self.dwelltime = []
        self.energy_pos = None
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
        # savd for later re-use.
        self.regions.append(ScanRegion(start, stop, npts=npts,
                                       relative=relative,
                                       e0=e0, use_k=use_k,
                                       dtime=dtime,
                                       dtime_final=dtime_final,
                                       dtime_wt=dtime_wt))

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
                 extra_pvs=None, e0=0, **kws):

        self.label = label
        self.e0 = e0
        self.energies = []
        self.regions = []
        self.xps = None
        XAFS_Scan.__init__(self, label=label, energy_pv=energy_pv,
                           read_pv=read_pv, e0=e0, extra_pvs=extra_pvs,  **kws)

        self.set_energy_pv(energy_pv, read_pv=read_pv, extra_pvs=extra_pvs)
        self.scantype = 'qxafs'
        self.detmode  = 'roi'

    def make_trajectory(self, reverse=False,
                        theta_accel=0.25, width_accel=0.25, **kws):
        """this method builds the text of a Trajectory script for
        a Newport XPS Controller based on the energies and dwelltimes"""

        qconf = self.slewscan_config
        qconf['theta_motor'] = qconf['motors']['THETA']
        qconf['width_motor'] = qconf['motors']['HEIGHT']

        dspace = caget(qconf['dspace_pv'])
        height = caget(qconf['height_pv'])
        th_off = caget(qconf['theta_motor'] + '.OFF')
        wd_off = caget(qconf['width_motor'] + '.OFF')

        energy = np.array(self.energies)
        times  = np.array(self.dwelltime)
        if reverse:
            energy = energy[::-1]
            times  = times[::-1]

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

        dtheta = np.diff(theta)
        dwidth = np.diff(width)
        dtime  = times[1:]
        fmt = '%.8f, %.8f, %.8f, %.8f, %.8f'
        efirst = fmt % (tim0, the0, tvelo[0], wid0, wvelo[0])
        elast  = fmt % (tim0, the1, 0.00,     wid1, 0.00)

        buff  = ['', efirst]
        for i in range(len(dtheta)):
            buff.append(fmt % (dtime[i], dtheta[i], tvelo[i],
                               dwidth[i], wvelo[i]))
        buff.append(elast)

        return  Group(buffer='\n'.join(buff),
                      start_theta=theta[0]-the0,
                      start_width=width[0]-wid0,
                      theta=theta, tvelo=tvelo,   times=times,
                      energy=energy, width=width, wvelo=wvelo)


    def init_qscan(self, traj):
        """initialize a QXAFS scan"""

        qconf = self.slewscan_config

        caput(qconf['id_track_pv'],  1)
        caput(qconf['y2_track_pv'],  1)

        time.sleep(0.1)
        caput(qconf['width_motor'] + '.DVAL', traj.start_width)
        caput(qconf['theta_motor'] + '.DVAL', traj.start_theta)
        caput(qconf['y2_track_pv'], 0)


    def finish_qscan(self):
        """initialize a QXAFS scan"""
        qconf = self.slewscan_config

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

        qconf = self.slewscan_config
        angle += caget(self.qconf['theta_motor'] + '.OFF')
        dspace = caget(self.qconf['dspace_pv'])
        energy = HC/(2.0 * dspace * np.sin(angle/RAD2DEG))
        return (energy, height)


    def run(self, filename=None, comments=None, debug=False, reverse=False):
        """
        run the actual QXAFS scan
        """

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

        qconf = self.slewscan_config
        energy_orig = caget(qconf['energy_pv'])

        traj = self.make_trajectory(reverse=reverse)
        self.init_qscan(traj)

        idarray = 0.001*traj.energy + caget(qconf['id_offset_pv'])

        try:
            caput(qconf['id_drive_pv'], idarray[0], wait=False)
        except:
            pass
        caput(qconf['energy_pv'],  traj.energy[0], wait=False)

        self.xps.upload_trajectoryFile(qconf['traj_name'], traj.buffer)

        self.clear_interrupts()
        orig_positions = [p.current() for p in self.positioners]

        sis_prefix = qconf['mcs_prefix']
        und_thread = PVSlaveThread(master_pvname=sis_prefix+'CurrentChannel',
                                   slave_pvname=qconf['id_drive_pv'],
                                   scan=self)

        und_thread.set_array(idarray)
        und_thread.running = False

        npulses = len(traj.energy) + 1

        caput(qconf['energy_pv'], traj.energy[0], wait=True)
        try:
            caput(qconf['id_drive_pv'], idarray[0], wait=True, timeout=5.0)
        except:
            pass

        npts = len(self.positioners[0].array)
        self.dwelltime_varys = False
        dtime = self.dwelltime[0]

        self.set_info('scan_progress', 'preparing scan')
        extra_vals = []
        for desc, pv in self.extra_pvs:
            extra_vals.append((desc, pv.get(as_string=True), pv.pvname))

        sis_opts = {}
        xsp3_prefix = None
        for d in self.detectors:
            if 'scaler' in d.label.lower():
                sis_opts['scaler'] = d.prefix
            elif 'xspress3' in d.label.lower():
                xsp3_prefix = d.prefix

        qxsp3 = Xspress3(xsp3_prefix)
        qxsp3.Acquire = 0
        sis  = Struck(sis_prefix, **sis_opts)

        caput(qconf['energy_pv'], traj.energy[0])

        out = self.pre_scan()
        self.check_outputs(out, msg='pre scan')
        sis.stop()
        orig_counters = self.counters[:]
        # specialized QXAFS Counters
        qxafs_counters = []
        for i, mca in enumerate(sis.mcas):
            scalername = getattr(sis.scaler, 'NM%i' % (i+1), '')
            if len(scalername) > 1:
                qxafs_counters.append((scalername, mca._pvs['VAL']))

        ## need to use self.rois to re-load ROI arrays
        ## names like  MCA1ROI:N:TSTotal
        for roi in range(1, 5):
            desc = caget('%sC1_ROI%i:ValueSum_RBV.DESC' % (xsp3_prefix, roi))
            if len(desc) > 0 and not desc.lower().startswith('unused'):
                for card in range(1, 5):
                    pvname = '%sC%i_ROI%i:ArrayData_RBV' % (xsp3_prefix, card, roi)
                    _desc = "%s_mca%i" % (desc, card)
                    qxafs_counters.append((_desc, PV(pvname)))

        # SCAs for count time
        for card in range(1, 5):
            pvname = '%sC%iSCA0:TSArrayValue' % (xsp3_prefix, card)
            qxafs_counters.append(("Clock_mca%i" % card, PV(pvname)))

        self.counters = []
        for label, cpv in qxafs_counters:
            _c = Counter(cpv.pvname, label=label)
            self.counters.append(_c)

        self.init_scandata()

        sis.ArrayMode(numframes=npts+5)
        qxsp3.ArrayMode(numframs=npts+5)

        self.datafile = self.open_output_file(filename=self.filename,
                                              comments=self.comments)

        self.datafile.write_data(breakpoint=0)
        self.filename =  self.datafile.filename

        self.set_info('filename', self.filename)
        self.set_info('request_abort', 0)
        self.set_info('scan_time_estimate', npts*dtime)
        self.set_info('scan_total_points', npts)

        out = [p.move_to_start(wait=True) for p in self.positioners]
        self.check_outputs(out, msg='move to start, wait=True')

        caput(qconf['energy_pv'], traj.energy[0], wait=True)
        caput(qconf['width_motor'] + '.DVAL', traj.start_width, wait=True)
        caput(qconf['theta_motor'] + '.DVAL', traj.start_theta, wait=True)

        self.set_info('scan_progress', 'starting scan')
        self.cpt = 0
        self.npts = npts

        und_thread.enable()
        und_thread.start()
        time.sleep(0.1)

        ts_init = time.time()
        self.inittime = ts_init - ts_start
        start_time = time.strftime('%Y-%m-%d %H:%M:%S')

        self.xps.SetupTrajectory(npts+1, dtime, traj_file=qconf['traj_name'])

        sis.Start()
        qxsp3.Start()

        time.sleep(0.1)
        self.xps.RunTrajectory()
        self.xps.EndTrajectory()

        sis.Stop()
        qxsp3.Stop()
        self.finish_qscan()
        und_thread.running = False
        und_thread.join()

        self.set_info('scan_progress', 'reading data')

        npulses, gather_text = self.xps.ReadGathering()
        energy, height = self.gathering2energy(gather_text)
        self.pos_actual = []
        for e in energy:
           self.pos_actual.append([e])
        ne = len(energy)
        caput(qconf['energy_pv'], energy_orig-2.0)

        nout = sis.CurrentChannel
        narr = 0
        t0  = time.time()
        while narr < (nout-1) and (time.time()-t0) < 30.0:
            time.sleep(0.05)
            try:
                dat =  [p.get(timeout=5.0) for (_d, p) in qxafs_counters]
                narr = min([len(d) for d in dat])
            except:
                narr = 0

        # reset the counters, and fill in data read from arrays
        # note that we may need to trim *1st point* from qxspress3 data
        self.counters = []
        for label, cpv in qxafs_counters:
            _c = Counter(cpv.pvname, label=label)
            arr = cpv.get()
            if len(arr) > ne:
                arr = arr[-ne:]
            _c.buff = arr.tolist()
            self.counters.append(_c)

        self.publish_scandata()

        for val, pos in zip(orig_positions, self.positioners):
            pos.move_to(val, wait=False)

        self.datafile.write_data(breakpoint=-1, close_file=True, clear=False)
        if self.look_for_interrupts():
            self.write("scan aborted at point %i of %i." % (self.cpt, self.npts))
            raise ScanDBAbort("scan aborted")

        # run post_scan methods
        self.set_info('scan_progress', 'finishing')
        caput(qconf['energy_pv'], energy_orig, wait=True)
        out = self.post_scan()
        self.check_outputs(out, msg='post scan')
        self.complete = True
        self.set_info('scan_progress',
                      'scan complete. Wrote %s' % self.datafile.filename)
        self.runtime  = time.time() - ts_start
        return self.datafile.filename
        ##
