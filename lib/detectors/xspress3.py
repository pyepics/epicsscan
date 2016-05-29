#!/usr/bin/python
import sys
import os
import time
from ConfigParser import ConfigParser

from epics import Device, caget, caput, poll
from epics.devices.mca import MCA, ROI, OrderedDict
from epics.devices.ad_mca import ADMCA, ADMCAROI

MAX_ROIS = 32

SCALER_MODE, ARRAY_MODE, ROI_MODE = 'SCALER', 'ARRAY', 'ROI'

class ADFileMixin(object):
    """mixin class for Xspress3"""
    def filePut(self, attr, value, **kws):
        return self.put("%s%s" % (self.filesaver, attr), value, **kws)

    def fileGet(self, attr, **kws):
        return self.get("%s%s" % (self.filesaver, attr), **kws)

    def setFilePath(self, pathname):
        fullpath = os.path.join(self.fileroot, pathname)
        return self.filePut('FilePath', fullpath)

    def setFileTemplate(self,fmt):
        return self.filePut('FileTemplate', fmt)

    def setFileWriteMode(self,mode):
        return self.filePut('FileWriteMode', mode)

    def setFileName(self,fname):
        return self.filePut('FileName', fname)

    def nextFileNumber(self):
        self.setFileNumber(1+self.fileGet('FileNumber'))

    def setFileNumber(self, fnum=None):
        if fnum is None:
            self.filePut('AutoIncrement', 1)
        else:
            self.filePut('AutoIncrement', 0)
            return self.filePut('FileNumber',fnum)

    def getLastFileName(self):
        return self.fileGet('FullFileName_RBV',as_string=True)

    def FileCaptureOn(self):
        return self.filePut('Capture', 1)

    def FileCaptureOff(self):
        return self.filePut('Capture', 0)

    def setFileNumCapture(self,n):
        return self.filePut('NumCapture', n)

    def FileWriteComplete(self):
        return (0==self.fileGet('WriteFile_RBV') )

    def getFileTemplate(self):
        return self.fileGet('FileTemplate_RBV',as_string=True)

    def getFileName(self):
        return self.fileGet('FileName_RBV',as_string=True)

    def getFileNumber(self):
        return self.fileGet('FileNumber_RBV')

    def getFilePath(self):
        return self.fileGet('FilePath_RBV',as_string=True)

    def getFileNameByIndex(self,index):
        return self.getFileTemplate() % (self.getFilePath(), self.getFileName(), index)

class Xspress3BaseMixin(object):
    """xspress3 mixin -- triggers, acquire, etc"""
    def useExternalTrigger(self):
        self.TriggerMode = 3

    def useInternalTrigger(self):
        self.TriggerMode = 1

    def SetTriggerMode(self, mode):
        self.TriggerMode = mode

    def Start(self, capture=True):
        time.sleep(.05)
        if capture:
            self.FileCaptureOn()
        self.Acquire = 1

    def Stop(self):
        self.Acquire = 0
        self.FileCaptureOff()

    def get_rois(self):
        return [m.get_rois() for m in self.mcas]

class Xspress3(Device, ADFileMixin, Xspress3BaseMixin):
    """Epics Xspress3.20 interface (with areaDetector2)"""

    det_attrs = ('NumImages', 'NumImages_RBV', 'Acquire', 'Acquire_RBV',
                 'ArrayCounter_RBV', 'ERASE', 'UPDATE', 'AcquireTime',
                 'TriggerMode', 'StatusMessage_RBV', 'DetectorState_RBV')

    _nonpvs = ('_prefix', '_pvs', '_delim', 'filesaver', 'fileroot',
                'pathattrs', '_nonpvs',  'nmca', 'mcas', '_chans')

    pathattrs = ('FilePath', 'FileTemplate', 'FileName', 'FileNumber',
                 'Capture', 'NumCapture')

    def __init__(self, prefix, nmca=4, filesaver='HDF1:',
                 fileroot='/home/xspress3/cars5/Data'):
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix
        self.nmca = nmca
        attrs = []
        attrs.extend(['%s%s' % (filesaver,p) for p in self.pathattrs])

        self.filesaver = filesaver
        self.fileroot = fileroot
        self._prefix = prefix
        self._chans = range(1, nmca+1)
        self.mcas = []
        for i in range(nmca):
            imca = i+1
            dprefix = "%sdet1:" % prefix
            rprefix = "%sMCA%iROI" % (prefix, imca)
            data_pv = "%sMCA%i:ArrayData" % (prefix, imca)
            mca = ADMCA(dprefix, data_pv=data_pv, roi_prefix=rprefix)
            self.mcas.append(mca)
            attrs.append("%s:MCA%iROI:TSControl" % (prefix, imca))
            attrs.append("%s:MCA%iROI:TSNumPoints" % (prefix, imca))
            # "MCA1ROI:BlockingCallbacks"

        Device.__init__(self, prefix, attrs=attrs, delim='')
        for attr in self.det_attrs:
            self.add_pv("%sdet1:%s" % (prefix, attr), attr)
        for i in range(nmca):
            imca = i+1
            for j in range(8):
                isca = j+1
                attr="C%iSCA%i"% (imca, isca)
                self.add_pv("%s%s:Value_RBV" % (prefix, attr), attr)
        time.sleep(0.05)

    def roi_calib_info(self):
        buff = ['[rois]']
        add = buff.append
        rois = self.mcas[0].get_rois()
        for iroi, roi in enumerate(rois):
            name = roi.Name
            hi   = roi.MinX + roi.SizeX
            if len(name.strip()) > 0 and hi > 0:
                dbuff = []
                for m in range(self.nmca):
                    dbuff.extend([roi.MinX, roi.MinX+roi.SizeX])
                dbuff = ' '.join([str(i) for i in dbuff])
                add("ROI%2.2i = %s | %s" % (iroi, name, dbuff))

        add('[calibration]')
        add("OFFSET = %s " % (' '.join(["0.000 "] * self.nmca)))
        add("SLOPE  = %s " % (' '.join(["0.010 "] * self.nmca)))
        add("QUAD   = %s " % (' '.join(["0.000 "] * self.nmca)))
        add('[dxp]')
        return buff

    def restore_rois(self, roifile):
        """restore ROI setting from ROI.dat file"""
        cp =  ConfigParser()
        cp.read(roifile)
        roidat = []
        iroi = 0
        for a in cp.options('rois'):
            if a.lower().startswith('roi'):
                name, dat = cp.get('rois', a).split('|')
                lims = [int(i) for i in dat.split()]
                lo, hi = lims[0], lims[1]
                roidat.append((name.strip(), lo, hi))

        for mca in self.mcas:
            mca.set_rois(roidat)

    def ContinuousMode(self, dwelltime=0.25, numframes=16384):
        """set to continuous mode: use for live reading

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [0.25]
        numframes (None or int):   number of frames to collect [16384]

    Notes:
        1. The Xspress3 doesn't support true continuous mode, so this sets
        the dwelltime to 0.25 and NumImages to 16384
           """
        if numframes is not None:
            self.put('NumImages', numframes)
        if dwelltime is not None:
            self.SetDwelltime(dwelltime)
        self._mode = SCALER_MODE


    def ScalerMode(self, dwelltime=1.0, numframes=1):
        """ set to scaler mode: ready for step scanning

    Arguments:
        dwelltime (None or float): dwelltime per frame in seconds [1.0]
        numframes (None or int):   number of frames to collect [1]

    Notes:
        1. numframes should be 1, unless you know what you're doing.
        """
        self.put('TriggerMode', 1) # Internal
        if numframes is not None:
            self.put('NumImages', numframes)
        if dwelltime is not None:
            self.SetDwelltime(dwelltime)
        for i in self._chans:
            self.put('MCA%iROI:TSControl' % i, 2) # 'Stop'

        self._mode = SCALER_MODE


    def ROIMode(self, dwelltime=0.25, numframes=16384):
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
        self.put('TriggerMode', 3) # External, TTL Veto
        for i in self._chans:
            self.put('MCA%iROI:TSControl' % i, 2) # 'Stop'
        if numframes is not None:
            self.put('NumImages', numframes)
            for i in self._chans:
                self.put('MCA%iROI:TSNumPoints' % i, numframes)
        if dwelltime is not None:
            self.SetDwelltime(dwelltime)
        self._mode = ROI_MODE


    def ArrayMode(self, dwelltime=0.25, numframes=16384, **kws):
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
        self.TriggerMode = 3
        self.put('ERASE', 1)
        for i in self._chans:
            self.put('MCA%iROI:TSControl' % i, 2) # 'Stop'

        if numframes is not None:
            self.put('NumAcquire', numframes)
        if dwelltime is not None:
            self.SetDwelltime(dwelltime)
        self._mode = ARRAY_MODE

    def SetDwelltime(self, dwelltime, **kws):
        """set dwell time in seconds

    Arguments:
        dwelltime (float): dwelltime per frame in seconds.   No default
        """
        self.put('AcquireTime', dwelltime)

    def Start(self, wait=False):
        time.sleep(.05)
        if self._mode == ARRAY_MODE:
            self.FileCaptureOn()
        elif self._mode == ROI_MODE:
            self.FileCaptureOff()
            for i in self._chans:
                self.put('MCA%iROI:TSControl' % i, 0) # 'Erase/Start'
        elif self._mode == SCALER_MODE:
            self.FileCaptureOff()
        self.put('Acquire', 1, wait=wait)

    def Stop(self, wait=False):
        self.put('Acquire', 0, wait=wait)
        self.FileCaptureOff()

    def SaveArrayData(self, filename=None):
        pass





class Xspress310(Device, ADFileMixin, Xspress3BaseMixin):
    """Epics Xspress3.10 interface (older version)"""
    attrs = ('NumImages', 'NumImages_RBV',
             'Acquire', 'Acquire_RBV',
             'ArrayCounter_RBV',
             'ERASE', 'UPDATE', 'AcquireTime',
             'TriggerMode', 'StatusMessage_RBV',
             'DetectorState_RBV')

    _nonpvs  = ('_prefix', '_pvs', '_delim', 'filesaver',
                'fileroot', 'pathattrs', '_nonpvs', '_save_rois',
                'nmca', 'dxps', 'mcas')

    pathattrs = ('FilePath', 'FileTemplate',
                 'FileName', 'FileNumber',
                 'Capture',  'NumCapture')

    def __init__(self, prefix, nmca=4, filesaver='HDF5:',
                 fileroot='/home/xspress3/cars5/Data'):
        self.nmca = nmca
        attrs = list(self.attrs)
        attrs.extend(['%s%s' % (filesaver,p) for p in self.pathattrs])

        self.filesaver = filesaver
        self.fileroot = fileroot
        self._prefix = prefix
        self._save_rois = []
        self.mcas = [MCA(prefix, mca=i+1) for i in range(nmca)]

        Device.__init__(self, prefix, attrs=attrs, delim='')
        time.sleep(0.1)


    def select_rois_to_save(self, roilist):
        """copy rois from MCA record to arrays to be saved
        by XSPress3"""
        roilist = list(roilist)
        if len(roilist) < 4: roilist.append((50, 4050))
        pref = self._prefix
        self._save_rois = []
        for iroi, roiname in enumerate(roilist):
            label = roiname
            if isinstance(roiname, tuple):
                lo, hi = roiname
                label = '[%i:%i]'  % (lo, hi)
            else:
                rname = roiname.lower().strip()
                lo, hi = 50, 4050
                for ix in range(MAX_ROIS):
                    nm = caget('%smca1.R%iNM' % (pref, ix))
                    if nm.lower().strip() == rname:
                        lo = caget('%smca1.R%iLO' % (pref, ix))
                        hi = caget('%smca1.R%iHI' % (pref, ix))
                        break
            self._save_rois.append(label)
            for imca in range(1, self.nmca+1):
                pv_lo = "%sC%i_MCA_ROI%i_LLM" % (pref, imca, iroi+1)
                pv_hi = "%sC%i_MCA_ROI%i_HLM" % (pref, imca, iroi+1)
                caput(pv_hi, hi)
                caput(pv_lo, lo)

    def roi_calib_info(self):
        buff = ['[rois]']
        add = buff.append
        rois = self.get_rois()
        for iroi in range(len(rois[0])):
            name = rois[0][iroi].NM
            hi   = rois[0][iroi].HI
            if len(name.strip()) > 0 and hi > 0:
                dbuff = []
                for m in range(self.nmca):
                    dbuff.extend([rois[m][iroi].LO, rois[m][iroi].HI])
                dbuff = ' '.join([str(i) for i in dbuff])
                add("ROI%2.2i = %s | %s" % (iroi, name, dbuff))

        add('[calibration]')
        add("OFFSET = %s " % (' '.join(["0.000 "] * self.nmca)))
        add("SLOPE  = %s " % (' '.join(["0.010 "] * self.nmca)))
        add("QUAD   = %s " % (' '.join(["0.000 "] * self.nmca)))
        add('[dxp]')
        return buff

    def restore_rois(self, roifile):
        """restore ROI setting from ROI.dat file"""
        cp =  ConfigParser()
        cp.read(roifile)
        rois = []
        self.mcas[0].clear_rois()
        prefix = self.mcas[0]._prefix
        if prefix.endswith('.'):
            prefix = prefix[:-1]
        iroi = 0
        for a in cp.options('rois'):
            if a.lower().startswith('roi'):
                name, dat = cp.get('rois', a).split('|')
                lims = [int(i) for i in dat.split()]
                lo, hi = lims[0], lims[1]
                # print('ROI ', name, lo, hi)
                roi = ROI(prefix=prefix, roi=iroi)
                roi.LO = lo
                roi.HI = hi
                roi.NM = name.strip()
                rois.append(roi)
                iroi += 1

        poll(0.050, 1.0)
        self.mcas[0].set_rois(rois)
        cal0 = self.mcas[0].get_calib()
        for mca in self.mcas[1:]:
            mca.set_rois(rois, calib=cal0)
