"""
Eiger support

Eiger 500K

"""
from __future__ import print_function
import os
import sys
import time
import requests
import json
import subprocess
import numpy as np
import h5py
from glob import glob
from datetime import datetime
from telnetlib import Telnet
from base64 import b64encode, b64decode
from epics import get_pv, caput, caget, Device, poll, PV

from .counter import Counter
from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE
from .areadetector import AreaDetector
from ..debugtime import debugtime

MAX_FRAMES = 8192


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

    def get_pixel_mask(self):
        _dat = self._get(task='config', parameter='pixel_mask')
        return np.fromstring(b64decode(_dat.value['data']), dtype='uint32')

    def set_pixel_mask(self, mask):
        if mask.dtype != np.uint32:
            raise ValueError("mask must have dtype of uint32")
        ny_pixs = self._get(module='detector', task='config',
                            parameter='y_pixels_in_detector').value
        nx_pixs = self._get(module='detector', task='config',
                            parameter='x_pixels_in_detector').value
        if mask.shape != (ny_pixs, nx_pixs):
            raise ValueError("mask must have shape (%d, %d)" % (ny_pixs, nx_pixs))

        val = self._get(task='config', parameter='pixel_mask').value
        val['data'] = str(b64encode(mask.flatten()), 'latin-1')
        _dat = self._put(task='config', parameter='pixel_mask', value=val)

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
            # print("Warning -- you will need to restart Epics IOC")

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


class AD_Eiger(AreaDetector):
    """
    Eiger areaDetector

    a pretty generic areaDetector, but overwriting
    pre_scan() to collect offset frames
    """

    def __init__(self, prefix, label='eiger', mode='scaler', url=None,
                 filesaver='HDF1:', roistat='ROIStat1:',
                 fileroot='/home/xas_user', **kws):
        AreaDetector.__init__(self, prefix, label=label, mode=mode,
                              filesaver=filesaver, roistat=roistat,
                              fileroot=fileroot, **kws)

        self.simplon = None
        if url is not None:
            self.simplon = EigerSimplon(url, prefix)

        self.cam.PV('FWEnable')
        self.cam.PV('FWClear')
        self.cam.PV('DataSource')
        self.cam.PV('FilePath')
        self.cam.PV('SaveFiles')
        self.cam.PV('SequenceId')
        self.cam.PV('DetectorState_RBV')
        self.cam.PV('AcquireBusy')
        self.mode = mode

        self.readout_time = 5.0e-5
        self.stop_delay = 0.05
        self.arm_delay = 0.25
        self.start_delay = 0.1
        self.dwelltime = None
        self.datadir = ''
        self.ad.FileCaptureOff()

    def custom_pre_scan(self, row=0, dwelltime=None, **kws):
        # t0 = time.time()
        # self.simplon.clear_disk()
        # print(" Ad Eiger pre-scan ") # cleared disk: %.1f sec" % (time.time()-t0))

        if self.cam.get('Acquire') != 0:
            self.cam.put('Acquire', 0, wait=True)
            time.sleep(5*self.arm_delay)
        # print("Eiger is off  ",   self.cam.get('Acquire', as_string=True))

        self.ad.setFileTemplate("%s%s_%4.4d.h5")
        if self.filesaver.startswith('HDF'):
            self.ad.filePut('Compression', 'zlib')
            self.ad.filePut('ZLevel', 4)

        self.cam.put('FWCompression', 'Disabled')
        self.cam.put('FWEnable', 'No')
        self.cam.put('SaveFiles', 'No')
        self.cam.put('FWAutoRemove', 'No')
        self.cam.put('DataSource', 'Stream')
        self.cam.put('ArrayCallbacks', 'Enable')
        self.cam.put('StreamEnable', 'Yes')
        self.cam.put('ShutterMode', 'None')
        if self.mode == ROI_MODE:
            for iroi in range(8):
                pref = '%s%d:' % (self.roistat._prefix, 1+iroi)
                if caget(pref + 'Use') == 1:
                    label = caget(pref + 'Name', as_string=True).strip()
                    if len(label) > 0:
                        pvname = pref + 'TSTotal'
                        self.counters.append(Counter(pvname, label=label))
        time.sleep(0.25)

    def post_scan(self, **kws):
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

        if self.cam.get('Acquire') != 0:
            self.cam.put('Acquire', 0, wait=True)
            time.sleep(5*self.arm_delay)

        if fnum is not None:
            self.fnum = fnum
            self.ad.setFileNumber(fnum)

        if self.mode == SCALER_MODE:
            numframes = 1

        if numframes is not None:
            self.cam.put('NumImages', numframes)
            self.ad.setFileNumCapture(numframes)

        self.ad.setFileWriteMode(2) # Stream
        if self.mode == ROI_MODE:
            self.ad.FileCaptureOff()
            self.cam.put('NumTriggers', numframes)
            self.roistat.arm(numframes=numframes)
            time.sleep(0.25)
            self.roistat.start(erase=True)
        else:
            self.ad.FileCaptureOn(verify_rbv=True)

        time.sleep(self.arm_delay/3.0)
        if wait:
            time.sleep(self.arm_delay)


    def start(self, mode=None, arm=False, wait=True):
        if mode is not None:
            self.mode = mode
        if arm or self.mode == SCALER_MODE:
            self.arm()
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
        time.sleep(0.05)
        self.cam.put('NumImages', numframes, wait=True)


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
        self.ad.FileCaptureOff()
        if numframes is not None:
            self.cam.put('NumImages', numframes)
            self.cam.put('NumTriggers', 1)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        self.mode = SCALER_MODE

    def ROIMode(self, dwelltime=None, numframes=None, nrois=4):
        """ set to ROI mode: ready for slew scanning with ROI saving

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None int):   number of frames to collect [16384]

    Notes:
        1. this arms detector so that it is eady for slew scanning and
           saving of ROI time series
        2. setting dwelltime or numframes to None is discouraged,
           as it can lead to inconsistent data arrays.
        """
        # print("AD Eiger ROI Mode ", dwelltime, numframes)
        self.cam.put('TriggerMode', 'External Enable')
        self.cam.put('Acquire', 0, wait=True)
        self.cam.put('NumImages', 1)

        if numframes is None:
            numframes = MAX_FRAMES
        self.roistat.stop()
        self.roistat.arm(numframes=numframes)

        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        self.mode = ROI_MODE


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
        self.cam.put('NumImages', 1)

        if numframes is not None:
            self.cam.put('NumImages', 1)
            self.cam.put('NumTriggers', numframes)

        # self.cam.put('FWEnable', 1)
        # nperfile = min(99000, max(1000, numframes)) + 1000
        # self.cam.put('FWNImagesPerFile', nperfile)

        if dwelltime is not None:
            dwelltime = self.dwelltime
        self.set_dwelltime(dwelltime)
        self.mode = NDARRAY_MODE

    def config_filesaver(self, path=None, **kws):
        if path is not None:
            self.datadir = path
        self.ad.config_filesaver(path=path, **kws)

    def get_next_filename(self):
        return self.ad.getNextFileName()

    def file_write_complete(self):
        """
        assume that if the detector is working,
        that the file will be written
        """
        detstate = self.cam.get('DetectorState_RBV')
        acq_busy = self.cam.get('AcquireBusy')
        return (acq_busy==0) and (detstate != 6) # Error

    def get_numcaptured(self):
        return self.ad.getNumCaptured_RBV()
