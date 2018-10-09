"""
Eiger support

Eiger 500K

"""
import os
import time
import requests
import json
import subprocess
from telnetlib import Telnet

from epics import get_pv, caput, caget, Device, poll, PV

from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE
from .areadetector import AreaDetector
from ..debugtime import debugtime



def restart_procserv_ioc(ioc_port=29200):
    """
    send a Ctrl-C to a procServ ioc running on localhost
    """
    tn = Telnet('localhost', ioc_port)
    tn.write('\x03')
    tn.write('\n')
    time.sleep(3)

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
            ret = requests.put(command, data=jsondata)
        else:
            ret = requests.get(command)

        self.last_status = ret.status_code
        out = ["# %s" % command,
               "# response: %s: %s" % (ret.status_code, ret.reason)]
        dat = None
        try:
            dat = json.loads(ret.text)
        except ValueError:
            out.append('no valid json data')
        if dat is not None:
            if isinstance(dat, (list, tuple)):
                out.append(" %s" % (dat))
            elif isinstance(dat, dict):
                for key, val in dat.items():
                    out.append("  %s: %s" % (key, val))
        self.message = '\n'.join(out)

    def _put(self, module='detector', task='status',
             parameter='state', value=''):
        self._exec(request='put', module=module, task=task,
                   parameter=parameter, value=value)

    def _get(self, module='detector', task='status',
             parameter='state', value=''):
        self._exec(request='get', module=module, task=task,
                   parameter=parameter, value=value)
        return self.message

    def set_energy(self, energy=15000):
        self._put(module='detector', task='config',
                  parameter='photon_energy', value=energy)

    def get_energy(self, energy=15000):
        self._get(module='detector', task='config',
                  parameter='photon_energy')
        return self.message

    def clear_disk(self):
        self._put(module='filewriter', task='command',
                  parameter='clear')
        return self.message

    def show_diskspace(self):
        self._get(module='filewriter', task='status',
                parameter='buffer_free')
        return self.message

    def restart_daq(self):
        """
        restart DAQ and then
        send Ctrl-C to procServ to restart IOC
        """
        self._put(module='system', task='command', parameter='restart')
        t0 = time.time()
        time.sleep(3.0)

        for i in range(50):
            self._put(module='detector', task='command', parameter='initialize')
            if self.last_status != 200:
                time.sleep(0.50)
            else:
                break
        if self.last_status != 200:
            raise ValueError('eiger detector initialize failed')

        set_pvs = False
        if self.procserv_iocport is not None:
            restart_procserv_ioc(self.procserv_iocport)
            time.sleep(5.0)
            set_pvs = True
        else:
            print("Warning -- you will need to restart Epics IOC")

        self._put('detector', 'command', 'arm', value=True)
        self._put('detector', 'config', 'pixel_mask_applied', value=False)

        # make sure the epics interface has useful values set for Continuous Mode
        if set_pvs:
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