"""
Area Detector
"""
import os

from epics import PV, get_pv, caget, caput

from epicsscan.file_utils import fix_filename

from .base import DetectorMixin
from .counter import Counter

AD_FILE_PLUGINS = ('TIFF1', 'JPEG1', 'NetCDF1',
                   'HDF1', 'Nexus1', 'Magick1')

class ADFileMixin(object):
    """mixin class for Xspress3"""
    def filePut(self, attr, value, **kws):
        "put file attribute"
        return self.put("%s%s" % (self.filesaver, attr), value, **kws)

    def fileGet(self, attr, **kws):
        "get file attribute"
        return self.get("%s%s" % (self.filesaver, attr), **kws)

    def setFilePath(self, pathname):
        "set FilePath"
        fullpath = os.path.join(self.fileroot, pathname)
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

class AreaDetector(DetectorMixin):
    """very simple area detector interface...
    trigger / dwelltime, uses array counter as only counter
    """
    trigger_suffix = 'cam1:Acquire'
    settings = {'cam1:ImageMode': 0,
                'cam1:ArrayCallbacks': 1}

    def __init__(self, prefix, file_plugin=None, fileroot='', **kws):
        if not prefix.endswith(':'):
            prefix = "%s:" % prefix
        self.fileroot = fileroot
        DetectorMixin.__init__(self, prefix, **kws)
        self.dwelltime_pv = get_pv('%scam1:AcquireTime' % prefix)
        self.dwelltime = None
        self.file_plugin = None
        self.counters = [Counter("%scam1:ArrayCounter_RBV" % prefix,
                                 label='Image Counter')]
        if file_plugin in AD_FILE_PLUGINS:
            self.file_plugin = file_plugin
            f_counter = Counter("%s%s:FileNumber_RBV" % (prefix, file_plugin),
                                label='File Counter')
            self.counters.append(f_counter)
        self._repr_extra = ', file_plugin=%s' % repr(file_plugin)

    def pre_scan(self, scan=None, **kws):
        if self.dwelltime is not None and isinstance(self.dwelltime_pv, PV):
            self.dwelltime_pv.put(self.dwelltime)

        settings = self.settings
        settings.update(kws)
        for key, val in settings.items():
            pvn = "%s%s" % (self.prefix, key)
            oval = caget(pvn)
            caput(pvn, val)
            self._savevals[pvn] = oval

        # set folder
        # note: 'server_fileroot' is fileroot as seen from the
        #              servers (this script) machine
        #       'fileroot' is fileroot as seen from the
        #              detectors machine
        if self.file_plugin is not None:
            fpre = "%s%s" % (self.prefix, self.file_plugin)
            ext = self.file_plugin[:-1].lower()
            caput("%s:FileTemplate" % fpre, '%%s%%s_%%4.4d.%s' % ext)
            caput("%s:FileNumber" % fpre, 1)
            caput("%s:EnableCallbacks" % fpre, 1)
            caput("%s:AutoIncrement" % fpre, 1)
            caput("%s:AutoSave" % fpre, 1)

            caput("%s:FileName" % fpre, 'image')
            fname = scan.filename
            label = self.label
            if label is None:
                label = self.prefix
            fname = fix_filename("%s_%s" % (fname, label))
            s_froot = scan.scandb.get_info('server_fileroot')
            workdir = scan.scandb.get_info('user_folder')
            d_froot = self.fileroot
            if d_froot is None or len(d_froot) < 1:
                d_froot = s_froot

            s_filepath = os.path.join(s_froot, workdir, fname)
            d_filepath = os.path.join(d_froot, workdir, fname)
            if not os.path.exists(s_filepath):
                os.makedirs(s_filepath)
            caput("%s:FilePath"  % fpre, d_filepath)

    def post_scan(self, **kws):
        if self.file_plugin is not None:
            fpre = "%s%s" % (self.prefix, self.file_plugin)
            caput("%s:EnableCallbacks" % fpre, 0)
            caput("%s:AutoSave" % fpre, 0)
        for key, val in self._savevals.items():
            caput(key, val)
