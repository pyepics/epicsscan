"""
Eiger support

Eiger 500K

"""
import os
import sys
import time
import requests
import json
import subprocess
import numpy as np
import h5py
from glob import glob

from telnetlib import Telnet

from epics import get_pv, caput, caget, Device, poll, PV

from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE
from .areadetector import AreaDetector
from ..debugtime import debugtime
from ..scandb import ScanDB

from pyFAI.azimuthalIntegrator import AzimuthalIntegrator


def restart_procserv_ioc(ioc_port=29200):
    """
    send a Ctrl-C to a procServ ioc running on localhost
    """
    tn = Telnet('localhost', ioc_port)
    tn.write('\x03')
    tn.write('\n')
    time.sleep(3)

class EigerResponse:
    def __init__(self, command, retval):
        self.command = command
        self.status = retval.status_code
        self.reason = retval.reason
        self.keywords = ['command', 'status', 'reason']
        for key, val in json.loads(retval.text).items():
            self.keywords.append(key)
            setattr(self, key, val)

    def __repr__(self):
        out = []
        for key in self.keywords:
            out.append("%s: %s" % (key, getattr(self, key)))
        return('\n'.join(out))

class EigerSimplon:
    """
    Connect to Eiger Simplon API
    useful for restarting data acquistion and
    setting simple parameters

    eiger = EigerSimplon('164.54.160.234', procserv_iocport=8045)

    print(eiger._get(module='detector', task='status', parameter='state'))
    print(eiger._get(module='detector', task='config', parameter='photon_energy'))


    """
    def __init__(self, url, prefix='13EIG1:cam1:', procserv_iocport=None):
        self.conf = {'api': '1.6.6', 'url': url}
        self.procserv_iocport = procserv_iocport
        self.last_status = 200
        self.message = ''
        self.prefix=prefix

    def _exec(self, request='get', module='detector', task='status',
              parameter='state', value=None):

        cmd = "http://{url:s}/{module:s}/api/{api:s}/{task:s}/{parameter:s}"
        kws = {}
        kws.update(self.conf)
        kws.update(module=module, task=task, parameter=parameter)
        command = cmd.format(**kws)

        if request == 'put':
            jsondata = None
            if value is not None:
                jsondata = json.dumps({'value': value})
            return requests.put(command, data=jsondata)
        else: # get
            return EigerResponse(command, requests.get(command))

    def _put(self, module='detector', task='status', parameter='state',
             value=''):
        return self._exec(request='put', module=module, task=task,
                   parameter=parameter, value=value)

    def _get(self, module='detector', task='status', parameter='state',
             value=''):
        return self._exec(request='get', module=module, task=task,
                          parameter=parameter, value=value)

    def set_energy(self, energy=15000):
        return self._put(module='detector', task='config',
                         parameter='photon_energy', value=energy)

    def get_energy(self, energy=15000):
        return self._get(module='detector', task='config',
                         parameter='photon_energy')

    def clear_disk(self):
        return self._put(module='filewriter', task='command',
                         parameter='clear')

    def show_diskspace(self):
        return self._get(module='filewriter', task='status',
                         parameter='buffer_free')

    def restart_daq(self):
        """
        restart DAQ and then
        send Ctrl-C to procServ to restart IOC
        """
        self._put(module='system', task='command', parameter='restart')
        t0 = time.time()
        time.sleep(3.0)

        for i in range(150):
            self._put(module='detector', task='command', parameter='initialize')
            if self.last_status != 200:
                time.sleep(0.250)
            else:
                break
        if self.last_status != 200:
            raise ValueError('eiger detector initialize failed')
        print("Detector Initialized in %.2f sec" % (time.time()-t0))

        set_pvs = True
        time.sleep(5.0)
        if self.procserv_iocport is not None:
            print("Restarting Epics IOC for Eiger with procserv")
            restart_procserv_ioc(self.procserv_iocport)
        else:
            print("Restarting Epics IOC for Eiger with SysReset")
            reset_pv = self.prefix.replace('cam1:', ':') + 'SysReset'
            caput(reset_pv, 1, wait=True)
            print("Warning -- you will need to restart Epics IOC")

        time.sleep(5.0)
        self._put('detector', 'command', 'arm', value=True)
        self._put('detector', 'config', 'pixel_mask_applied', value=True)

        # make sure the epics interface has useful values set for Continuous Mode
        if set_pvs:
            print("Setting Eiger to Continuous Mode")
            prefix = self.prefix
            caput(prefix + 'AcquireTime',   0.103, wait=True)
            caput(prefix + 'AcquirePeriod', 0.103, wait=True)
            caput(prefix + 'NumImages',     519, wait=True)
            caput(prefix + 'FWEnable',      1, wait=True)
            time.sleep(0.5)
            caput(prefix + 'AcquireTime',   0.25, wait=True)
            caput(prefix + 'AcquirePeriod', 0.25, wait=True)
            caput(prefix + 'NumImages',     64000, wait=True)
            caput(prefix + 'FWEnable',      0, wait=True)
        print("Restart Done.")



MAXVAL = 2**32 - 2**15

class EigerFileCopier(object):
    def __init__(self, mountpoint='/eiger1', **kws):

        self.scandb = scandb.ScanDB()
        self.source_dir = mountpoint
        self.rsync_cmd = '/bin/rsync -va'
        self.rsync_opts = '-va'
        self.map_folder = ''
        self.config_time = 0
        self.set_state('idle')
        self.sleep_time = 5.0

    def set_state(self, state):
        self.scandb.set_info('eiger_needs_sync', state)

    def get_state(self, state):
        return self.scandb.set_info('eiger_needs_sync')

    def read_config(self):
        self.config_time = time.time()
        self.map_folder = self.scandb.get_info('map_folder')
        if self.map_folder.endswith('/'):
            self.map_folder = self.map_folder[:-1]

        eiger_poni = self.scandb.get_info('eiger_calibration')
        calib = json.loads(self.scandb.get_detectorconfig(eiger_poni).text)
        self.integrator = AzimuthalIntegrator(**calib)

    def run_command(self, cmd):
        print("# %s  : %s " % (time.ctime(), cmd))
        subprocess.call(cmd, shell=True)


    def copy(self, finish=False):
        if len(self.map_folder) < 0 or self.get_state() == 'idle':
            return

        cmd = "%s %s/*.h5 %s/." % (self.rsync_cmd,
                                   self.source_dir,
                                   self.map_folder)

        self.run_command(cmd)
        if finish:
            time.sleep(self.sleep_time)
            self.run_command(cmd)

    def integrate(self):
        eigerfiles = glob(os.path.join(self.map_folder, '*_data_000001.h5'))
        for efile in sorted(eigerfiles):
            outfile = efile.replace('_data_000001.h5', '.npy')
            if not os.path.exists(outfile):
                self.save_1dint(efile, outfile)

    def save_1dint(self, h5file, outfile):
        xrdfile = h5py.File(h5file, 'r')
        xrdsum = xrdfile['/entry/data/data'][1:-1, 1:-1, 3:-3][:,::-1,:]
        nframes, nx, ny = xrdsum.shape
        xrdfile.close()
        t0 = time.time()
        dat = []
        do_int = self.integrator.integrate1d
        for i in range(nframes):
            img = xrdsum[i, :, :]
            img[np.where(img>MAXVAL)] = 0
            q, x = do_int(img, 2048, method='csr',
                          unit='q_A^-1',
                          correctSolidAngle=True,
                          polarization_factor=0.999)
            if i == 0:
                dat.append(q)
            dat.append(x)
        dat = np.array(dat)
        _path, fname = os.path.split(outfile)
        print("writing 1D integration to %s, %.2f sec" %  (fname, time.time()-t0))
        np.save(outfile, dat)

    def run(self):
        while True:
            time.sleep(self.sleep_time)
            state = self.get_state()
            if state.startswith('starting'):
                self.read_config()
                self.set_state('scanning')
            elif state.startswith('scanning'):
                self.copy()
                self.integrate()
            elif state.startswith('finishing'):
                self.copy(finish=True)
                self.integrate()
                self.set_state('idle')
                self.map_folder = ''
            elif state.startswith('idle'):
                time.sleep(self.sleep_time)


class AD_Eiger(AreaDetector):
    """
    Eiger areaDetector

    a pretty generic areaDetector, but overwriting
    pre_scan() to collect offset frames
    """
    def __init__(self, prefix, label='eiger', mode='scaler', url=None,
                 filesaver='TIFF1:', fileroot='/home/xas_user', scandb=None, **kws):

        AreaDetector.__init__(self, prefix, label=label, mode=mode,
                             filesaver=filesaver, fileroot=fileroot,
                              scandb=scandb, **kws)

        self.simplon = None
        if url is not None:
            self.simplon = EigerSimplon(url, prefix)
        self.cam.PV('FWEnable')
        self.cam.PV('FWClear')
        self.cam.PV('FWNImagesPerFile')
        self.cam.PV('FWAutoRemove')
        self.cam.PV('FWNamePattern')
        self.cam.PV('FilePath')
        self.cam.PV('SaveFiles')
        self.cam.PV('SequenceId')
        self.cam.PV('DetectorState_RBV')
        self.cam.PV('AcquireBusy')
        self.mode = mode

        self.stop_delay = self.readout_time = 5.0e-5
        self.arm_delay = 0.15
        self.start_delay = 0.1
        self.dwelltime = None
        self.datadir = ''
        self.ad.FileCaptureOff()

    def custom_pre_scan(self, row=0, dwelltime=None, **kws):
        # print("Custom Prescan AD getFilePath ", self.datadir)
        time.sleep(0.5)
        # self.cam.put('FilePath', os.path.join(self.fileroot, self.datadir))
        if self.scandb is not None:
            self.scandb.set_info('eiger_starting_seqid',
                                 self.cam.get('SequenceId', as_string=True))
            self.scandb.set_info('eiger_needs_sync', 'scanning')
        self.cam.put('FWEnable', 'Yes')
        self.cam.put('SaveFiles', 'No')
        self.cam.put('FWAutoRemove', 'No')

    def post_scan(self, **kws):
        if self.scandb is not None:
            self.scandb.set_info('eiger_needs_sync', 'finishing')
        self.ContinuousMode()

    def open_shutter(self):
        pass

    def close_shutter(self):
        pass

    def AcquireOffset(self, timeout=10, open_shutter=True):
        pass

    def arm(self, mode=None, fnum=None, wait=True, numframes=None):
        if mode is not None:
            self.mode = mode
        # force arm delay
        if self.cam.get('Acquire') != 0:
            self.cam.put('Acquire', 0, wait=True)
            time.sleep(5*self.arm_delay)

        if self.mode == NDARRAY_MODE:
            numframes = 1

        if numframes is not None:
            self.cam.put('NumImages', numframes)

        time.sleep(self.arm_delay/3.0)
        if wait:
            time.sleep(self.arm_delay)

    def disarm(self, mode=None, wait=True):
        if mode is not None:
            self.mode = mode
        if wait:
            time.sleep(self.arm_delay)

    def start(self, mode=None, arm=False, wait=True):
        if mode is not None:
            self.mode = mode
        if arm:
            self.arm(mode=mode, wait=wait)
        # note: need to wait a bit for acquire to start
        for i in range(10):
            self.cam.put('Acquire', 1, wait=False)
            time.sleep(self.start_delay/5.0)
            if self.cam.get('Acquire') == 1:
                break
        if wait:
            time.sleep(self.start_delay)

    def stop(self, mode=None, disarm=False, wait=True):
        if wait:
            time.sleep(self.stop_delay)
        self.cam.put('Acquire', 0, wait=wait)
        if disarm:
            self.disarm()
        self.ad.FileCaptureOff()

    def set_dwelltime(self, dwelltime=None):
        """set dwell time in seconds
        """
        if dwelltime is None and self.dwelltime is not None:
            dwelltime = self.dwelltime
        if dwelltime is None:
            return

        self.dwelltime = dwelltime
        self.cam.put('AcquireTime',   dwelltime-self.readout_time)
        self.cam.put('AcquirePeriod', dwelltime)

    def ContinuousMode(self, dwelltime=0.25, numframes=64000):
        self.ScalerMode(dwelltime=dwelltime, numframes=numframes)
        self.cam.put('FWEnable', 0)

    def ScalerMode(self, dwelltime=0.25, numframes=1):
        """ set to scaler mode: ready for step scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [1.0]
        numframes (None or int):   number of frames to collect [1]

    Notes:
        1. numframes should be 1, unless you know what you're doing.
        2. Files will be saved by the file saver
        """
        try:
            self.cam.put('TriggerMode', 'Internal Series') # Internal Mode
        except ValueError:
            pass
        if numframes is not None:
            self.cam.put('NumImages', numframes)
            self.cam.put('NumTriggers', 1)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        self.mode = SCALER_MODE

    def NDArrayMode(self, dwelltime=None, numframes=None):
        """ set to array mode: ready for slew scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None int):   number of frames to collect [16384]

    Notes:
        1. this arms detector and optional SIS8320 so that it is also
           ready for slew scanning.
        2. setting dwelltime or numframes to None is discouraged,
           as it can lead to inconsistent data arrays.
        """

        self.cam.put('TriggerMode', 'External Enable')
        self.cam.put('Acquire', 0, wait=True)

        if numframes is not None:
            self.cam.put('NumImages', 1)
            self.cam.put('NumTriggers', numframes)

        self.cam.put('FWEnable', 1)
        nperfile = min(99000, max(1000, numframes)) + 1000
        self.cam.put('FWNImagesPerFile', nperfile)

        if dwelltime is not None:
            dwelltime = self.dwelltime
        self.set_dwelltime(dwelltime)
        self.mode = NDARRAY_MODE

    def config_filesaver(self, path=None, name=None, number=None,
                         numcapture=None, template=None, auto_save=None,
                         write_mode=None, auto_increment=None, enable=True):
        if path is not None:
            self.datadir = path


    def get_next_filename(self):
        pattern = self.cam.get('FWNamePattern')
        seqid = "%d" % (1+self.cam.get('SequenceId'))
        prefix = pattern.replace('$id', seqid)
        return "%s_master.h5" % (prefix)

    def file_write_complete(self):
        """
        assume that if the detector is working,
        that the file will be written
        """
        detstate = self.cam.get('DetectorState_RBV')
        acq_busy = self.cam.get('AcquireBusy')
        return (acq_busy==0) and (detstate != 6) # Error

    def get_numcaptured(self):
        return self.cam.get('NumImagesCounter_RBV')
