"""
Eiger support

Eiger 500K

"""
import time
from epics import get_pv, caput, caget, Device, poll, PV

from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE
from .areadetector import AreaDetector
from ..debugtime import debugtime

import requests
import json
from telnetlib import Telnet


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

    eiger = EigerSimpplon'164.54.160.234', procserv_iocport=8045)

    print(eiger._get(module='detector', task='status', parameter='state'))
    print(eiger._get(module='detector', task='config', parameter='photon_energy'))


    """
    def __init__(self, url, procserv_iocport=None):
        self.conf = {'api': '1.6.6', 'url': url}
        self.procserv_iocport = procserv_iocport
        self.last_status = 200
        self.message = ''

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
        time.sleep(3.0)
        for i in range(20):
            self._put(module='detector', task='command', parameter='initialize')
            if self.last_status != 200:
                time.sleep(1.0)
            else:
                break
        if self.last_status != 200:
            raise ValueError('eiger detector initialize failed')

        if self.procserv_iocport is not None:
            restart_procserv_ioc(self.procserv_iocport)
            time.sleep(5.0)
        else:
            print("Warning -- you will need to restart Epics IOC")



class AD_Eiger(AreaDetector):
    """
    Eiger areaDetector

    a pretty generic areaDetector, but overwriting
    pre_scan() to collect offset frames
    """
    def __init__(self, prefix, label='exrd', mode='scaler',
                 filesaver='HDF1:', fileroot='/home/xas_user', **kws):

        AreaDetector.__init__(self, prefix, label=label, mode=mode,
                             filesaver=filesaver, fileroot=fileroot, **kws)
        self.cam.PV('FWEnable')
        self.cam.PV('FWNImagesPerFile')
        self.cam.PV('FWSaveFiles')
        self.cam.PV('FWAutoRemove')
        self.cam.PV('FWNamePattern')
        self.cam.PV('FilePath')
        self.mode = mode
        readout_time = 1.0e-5
        self.arm_delay = 0.10
        self.start_delay = 0.05
        self.stop_delay = 0.001
        self.dwelltime = None
        self.ad.FileCaptureOff()


    def custom_pre_scan(self, row=0, dwelltime=None, **kws):
        fpath = self.ad.getFilePath()
        print("Custom Prescan AD getFilePath ", self.ad.getFilePath())

        self.cam.put('FilePath', fpath)
        self.cam.put('FWEnable', 'Yes')
        self.cam.put('FWAutoRemove', 'No')
        self.cam.put('FWNImagesPerFile', 10000)
        self.cam.put('FWNamePattern', 'exrd$id')
        self.cam.put('SavesFiles', 'No')

        # need to launch script to rsync from webdav share

    def post_scan(self, **kws):
        self.stop()
        self.ContinuousMode()

#         datdir = None
#         if self.data_dir is not None:
#             datdir = self.data_dir[:]
#         else:
#             datdir = self.ad.getFilePath()
#         if datdir is not None:
#             if datdir.endswith('/'):
#                 datdir = datdir[:-1]
#             fpath, xpath = os.path.split(datdir)
#             fpath, xpath = os.path.split(fpath)


    def open_shutter(self):
        pass

    def close_shutter(self):
        pass

    def AcquireOffset(self, timeout=10, open_shutter=True):
        pass

    def stop(self, mode=None, disarm=False, wait=False):
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

    def ContinuousMode(self, dwelltime=None, numframes=300200100):
        self.ScalerMode(dwelltime=dwelltime)

    def ScalerMode(self, dwelltime=None, numframes=1):
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

        if numframes is not None:
            self.cam.put('NumImages', 1)
            self.cam.put('NumTriggers', numframes)

        if dwelltime is not None:
            dwelltime = self.dwelltime
        self.set_dwelltime(dwelltime)
        self.mode = NDARRAY_MODE
