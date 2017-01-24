"""
Area Detector
"""
import os
import time
from epics import PV, get_pv, caget, caput, Device, poll

from epicsscan.file_utils import fix_filename

from .base import DetectorMixin, SCALER_MODE, NDARRAY_MODE, ROI_MODE
from .counter import Counter

AD_FILESAVERS = ('TIFF1:', 'JPEG1:', 'netCDF1:', 'HDF1:', 'Nexus1:')

AD_CAM_ATTRS = ("Acquire", "AcquirePeriod", "AcquirePeriod_RBV",
                "AcquireTime", "AcquireTime_RBV", "ArrayCallbacks",
                "ArrayCallbacks_RBV", "ArrayCounter", "ArrayCounter_RBV",
                "ArrayRate_RBV", "ArraySizeX_RBV", "ArraySizeY_RBV",
                "ArraySize_RBV", "BinX", "BinX_RBV", "BinY", "BinY_RBV",
                "ColorMode", "ColorMode_RBV", "DataType", "DataType_RBV",
                "DetectorState_RBV", "Gain", "Gain_RBV", "ImageMode",
                "ImageMode_RBV", "MaxSizeX_RBV", "MaxSizeY_RBV", "MinX",
                "MinX_RBV", "MinY", "MinY_RBV", "NumImages",
                "NumImagesCounter_RBV", "NumImages_RBV", "SizeX", "SizeX_RBV",
                "SizeY", "SizeY_RBV", "TimeRemaining_RBV", "TriggerMode",
                "TriggerMode_RBV", "TriggerSoftware", 'Model_RBV',
                'ShutterControl', 'ShutterMode')

AD_FILE_ATTRS = ('AutoIncrement', 'AutoSave', 'Capture', 'EnableCallbacks',
                 'FileName', 'FileName_RBV', 'FileNumber', 'FileNumber', 'FileNumber_RBV',
                 'FilePath', 'FilePath_RBV', 'FileTemplate', 'FileTemplate_RBV',
                 'FileWriteMode', 'FileWriteMode', 'FullFileName_RBV', 'NumCapture',
                 'NumCaptured_RBV', 'WriteFile_RBV')

class ADFileMixin(object):
    """mixin class for area detector, MUST part of an epics Device"""

    def config_filesaver(self, path=None, name=None, number=None,
                         numcapture=None, template=None, auto_save=None,
                         write_mode=None, auto_increment=None, enable=True):

        """configure filesaver, setting multiple attributes at once
        Arguments
        ---------
           path
           name
           number
           numcapture
           template
           auto_save
           write_mode
           auto_increment
        Each of these is forwarded to the right PV, if not None.
        """
        if path is not None:
            self.setFilePath(path)
        if name is not None:
            self.setFileName(name)
        if number is not None:
            self.filePut('AutoIncrement', 0, wait=True)
            self.filePut('FileNumber', number)
        if numcapture is not None:
            self.setFileNumCapture(numcapture)
        if template is not None:
            self.setFileTemplate(template)

        if auto_increment is not None:
            self.filePut('AutoIncrement', auto_increment)
        if auto_save is not None:
            self.filePut('AutoSave', auto_save)
        if write_mode is not None:
            self.filePut('FileWriteMode', write_mode)
        if enable is not None:
            self.filePut('EnableCallbacks', enable)

    def filePut(self, attr, value, **kws):
        "put file attribute"
        return self.put("%s%s" % (self.filesaver, attr), value, **kws)

    def fileGet(self, attr, **kws):
        "get file attribute"
        return self.get("%s%s" % (self.filesaver, attr), **kws)

    def setFilePath(self, pathname):
        "set FilePath"
        if pathname.startswith('/'):
            pathname = pathname[1:]
        fullpath = os.path.join(str(self.fileroot), str(pathname))
        return self.filePut('FilePath', fullpath)

    def setFileTemplate(self, fmt):
        "set FileTemplate"
        return self.filePut('FileTemplate', fmt)

    def setFileWriteMode(self, mode):
        "set FileWriteMode"
        return self.filePut('FileWriteMode', mode)

    def setFileName(self, fname):
        "set FileName"
        return self.filePut('FileName', fname)

    def nextFileNumber(self):
        "increment FileNumber"
        self.setFileNumber(1+self.fileGet('FileNumber'))

    def setFileNumber(self, fnum=None):
        "set FileNumber:  if None, number will be auto incremented"
        if fnum is None:
            self.filePut('AutoIncrement', 1)
        else:
            self.filePut('AutoIncrement', 0)
            return self.filePut('FileNumber', fnum)

    def getLastFileName(self):
        "get FullFileName"
        return self.fileGet('FullFileName_RBV', as_string=True)

    def getNumCapture(self):
        "get NumCapture"
        return self.fileGet('NumCapture')

    def getNumCaptured_RBV(self):
        "get NumCaptured_RBV readback"
        return self.fileGet('NumCaptured_RBV')

    def FileCaptureOn(self):
        "turn Capture on"
        return self.filePut('Capture', 1)

    def FileCaptureOff(self):
        "turn Capture off"
        return self.filePut('Capture', 0)

    def setFileNumCapture(self, n):
        "set NumCapture"
        return self.filePut('NumCapture', n)

    def FileWriteComplete(self):
        "return whether WriteFile_RBV is complete"
        return self.fileGet('WriteFile_RBV') == 0

    def getFileTemplate(self):
        "get FileTemplate readback"
        return self.fileGet('FileTemplate_RBV', as_string=True)

    def getFileName(self):
        "get FileName readback"
        return self.fileGet('FileName_RBV', as_string=True)

    def getFileNumber(self):
        "get FileNumber readback"
        return self.fileGet('FileNumber_RBV')

    def getFilePath(self):
        "get FilePath readback"
        return self.fileGet('FilePath_RBV', as_string=True)

    def getFileNameByIndex(self, index):
        "get FileName for index"
        return self.getFileTemplate() % (self.getFilePath(),
                                         self.getFileName(), index)

class AD_Base(Device, ADFileMixin):
    """Base area Detecor with File Mixin"""

    _nonpvs  = ('_prefix', '_pvs', '_delim', 'filesaver', 'fileroot',
                 'pathattrs', '_nonpvs')
    def __init__(self, prefix, filesaver='TIFF1:', fileroot='T:/xas_user'):
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix

        attrs = ['%s%s' % (filesaver, p) for p in AD_FILE_ATTRS]
        Device.__init__(self, prefix, delim='', mutable=False, attrs=attrs)
        self.filesaver = filesaver
        self.fileroot = fileroot
        self._prefix = prefix

        
class AD_Camera(Device):
    """area Detecor camera"""
    _nonpvs  = ('_prefix', '_pvs', '_delim', '_nonpvs')
    def __init__(self, prefix):
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix
        Device.__init__(self, '%scam1:' % prefix, delim='', attrs=AD_CAM_ATTRS)
        
class AreaDetector(DetectorMixin):
    """very simple area detector interface...
    trigger / dwelltime, uses array counter as only counter
    """
    trigger_suffix = 'cam1:Acquire'
    settings = {'cam1:ImageMode': 0,
                'cam1:ArrayCallbacks': 1}

    def __init__(self, prefix, filesaver='TIFF1:', fileroot='',
                 label='ad', mode='scaler', **kws):
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix

        self.dwelltime = None
        self.filesaver = filesaver
        self.fileroot = fileroot
        self.mode = mode

        DetectorMixin.__init__(self, prefix, label=label, **kws)

        self.cam = AD_Camera(prefix)
        self.ad  = AD_Base(prefix, filesaver=filesaver, fileroot=fileroot)

        self.dwelltime_pv = get_pv('%scam1:AcquireTime' % prefix)
        self.counters = [Counter("%scam1:ArrayCounter_RBV" % prefix,
                                 label='Image Counter')]
        if filesaver in AD_FILESAVERS:
            self.filesaver = filesaver
            f_counter = Counter("%s%s:FileNumber_RBV" % (prefix, filesaver),
                                label='File Counter')
            self.counters.append(f_counter)
        self._repr_extra = 'filesaver=%s' % repr(filesaver)

    def __repr__(self):
        return "%s('%s', label='%s', mode='%s', %s)" % (self.__class__.__name__,
                                                        self.prefix, self.label,
                                                        self.mode, self._repr_extra)

    def config_filesaver(self, **kws):
        self.ad.config_filesaver(**kws)

    def pre_scan(self, mode=None, npulses=None, dwelltime=None, **kws):
        "run just prior to scan"
        if mode is not None:
            self.mode = mode

        self.cam.put('Acquire', 0, wait=True)
        poll(0.05, 0.5)

        if self.mode == SCALER_MODE:
            self.ScalerMode()
        elif self.mode == ROI_MODE:
            self.ROIMode()
        elif self.mode == NDARRAY_MODE:
            time.sleep(0.01)
            self.NDArrayMode(dwelltime=dwelltime, numframes=npulses)

        if dwelltime is not None:
            self.dwelltime = dwelltime
        if self.dwelltime is not None:
            self.dwelltime_pv.put(self.dwelltime)

        if npulses is not None:
            self.cam.put('NumImages', npulses)

        self.config_filesaver(number=1, name=self.label, numcapture=npulses,
                              template="%s%s.%4.4d", auto_increment=True,
                              auto_save=True, enable=True)

    def post_scan(self, **kws):
        self.config_filesaver(enable=False)
        self.ContinuousMode()

    def ContinuousMode(self, dwelltime=None, numframes=300200100):
        """set to continuous mode: use for live reading

        Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [None]
        numframes (None or int):   number of frames to collect [None]

        """
        if numframes is not None:
            self.cam.put('NumImages', numframes)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        
        self.ad.FileCaptureOff()
        self.cam.put('ImageMode', 'Continuous')
        self.cam.put('Acquire', 1)

    def ScalerMode(self, dwelltime=None, numframes=1):
        """ set to scaler mode: ready for step scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [1.0]
        numframes (None or int):   number of frames to collect [1]

    Notes:
        1. numframes should be 1, unless you know what you're doing.
        2. Files will be saved by the file saver
        """

        self.cam.put('TriggerMode', 1) # Internal
        if numframes is not None:
            self.cam.put('NumImages', numframes)
        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        self.ad.put('ROIStats1:TSControl', 2) # 'Stop'
        self.mode = SCALER_MODE
        self.ad.setFileNumCapture(1)

    def ROIMode(self, dwelltime=None, numframes=None):
        """ set to ROI mode: ready for slew scanning with ROI saving

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None int):   number of frames to collect [16384]
        sis_trigger_width (None or float):   output trigger width (in seconds)
             for optional SIS 3820 [None]

    Notes:
        1. this arms detector so that it is eady for slew scanning.
        2. setting dwelltime or numframes to None is discouraged,
           as it can lead to inconsistent data arrays.
        """
        self.cam.put('TriggerMode', 'External') # External
        self.ad.put('ROIStat1:TSControl', 2) # 'Stop'

        if numframes is not None:
            self.cam.put('NumImages', numframes)
            self.ad.put('ROIStats1:ArrayCallbacks', 1)
            self.ad.put('ROIStats1:TSNumPoints', numframes)
            self.ad.put('ROIStats1:BlockingCallbacks', 1)

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
        self.cam.put('TriggerMode', 'External')
        self.ad.put('ROIStat1:TSControl', 2) # 'Stop

        if numframes is not None:
            self.cam.put('NumImages', numframes)
            self.ad.setFileNumCapture(numframes)

        if dwelltime is not None:
            self.set_dwelltime(dwelltime)
        self.mode = NDARRAY_MODE

    def set_dwelltime(self, dwelltime):
        """set dwell time in seconds

    Arguments:
        dwelltime (float): dwelltime per frame in seconds.   No default
        """
        self.cam.put('AcquireTime', dwelltime)

    def arm(self, mode=None, wait=False, numframes=None):
        if mode is not None:
            self.mode = mode
        self.cam.put('Acquire', 0, wait=True)

        if self.mode == SCALER_MODE:
            numframes = 1

        if numframes is not None:
            self.cam.put('NumImages', numframes)
            self.ad.setFileNumCapture(numframes)

        self.ad.setFileWriteMode(2) # Stream
        if self.mode == ROI_MODE:
            self.ad.FileCaptureOff()
            self.ad.put('ROIStat1:TSControl', 0) # Erase/Start
        else:
            self.ad.FileCaptureOn()

    def disarm(self, mode=None, wait=False):
        if mode is not None:
            self.mode = mode
        time.sleep(.05)
        self.ad.FileCaptureOff()

    def start(self, mode=None, arm=False, wait=False):
        if mode is not None:
            self.mode = mode
        if arm or self.mode == SCALER_MODE:
            self.arm()
        self.cam.put('Acquire', 1, wait=wait)

    def stop(self, mode=None, disarm=False, wait=False):
        self.cam.put('Acquire', 0, wait=wait)
        if disarm:
            self.disarm()
        self.ad.FileCaptureOff()

    def save_arraydata(self, filename=None):
        pass

    def file_write_complete(self):
        return self.ad.FileWriteComplete()
