#!/usr/bin/env python
"""
Main GUI form for setting up and executing Step Scans

Principle features:
   1. overall configuration in database (postgres/sqlite for testing)
   2. notebook panels for
         Linear Scans
         Mesh Scans (2d maps)
         XAFS Scans
         Fly Scans (optional)

   3.  Other notes:
       Linear Scans support Slave positioners
       A Scan Definition files describes an individual scan.
       Separate window for configuring Detectors (Trigger + set of Counters)
           and Positioners, including adding any additional Counter
       Builtin Support for Detectors: Scalers, MultiMCAs, and AreaDetectors
       calculate / display estimated scan time on changes

       Give File Prefix on Scan Form

To Do:
   Plot Window allows simple math of columns, has "Go To" button.
   Plot window with drop-downs for column math, simple fits

   Sequence Window
   Edit Macros

"""
import os
import sys
import time
import shutil
import numpy as np
import json
import socket
from datetime import timedelta
from threading import Thread

import wx
import wx.lib.agw.flatnotebook as flat_nb
import wx.lib.scrolledpanel as scrolled
import wx.lib.mixins.inspection

import epics
from epics.wx import DelayedEpicsCallback, EpicsFunction, finalize_epics
from epics.wx.utils import popup

from .gui_utils import (SimpleText, FloatCtrl, Closure, pack, add_button,
                        add_menu, add_choice, add_menu, FileOpen,
                        CEN, LCEN, FRAMESTYLE, Font)

from ..utils import normalize_pvname, read_oldscanfile, atGSECARS
from ..stepscan import StepScan
from ..xafs_scan import XAFS_Scan

from ..file_utils import new_filename, nativepath, fix_filename

from ..scandb import ScanDB

from .scan_panels import (LinearScanPanel, MeshScanPanel,
                          SlewScanPanel,   XAFSScanPanel)

from ..site_config import get_fileroot

from ..larch_interface import LarchScanDBServer, larch_site_config
from ..positioner import Positioner
from ..detectors import (SimpleDetector, ScalerDetector, McaDetector,
                         MultiMcaDetector, AreaDetector, get_detector)

from .liveviewerApp    import ScanViewerFrame
from .edit_positioners import PositionerFrame
from .edit_detectors   import DetectorFrame, ROIFrame
from .edit_general     import SettingsFrame
from .edit_extrapvs    import ExtraPVsFrame
from .edit_scandefs    import ScandefsFrame
from .edit_sequences   import SequencesFrame
from .edit_macros      import MacroFrame

ICON_FILE = 'epics_scan.ico'
ALL_CEN =  wx.ALL|wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL
FNB_STYLE = flat_nb.FNB_NO_X_BUTTON|flat_nb.FNB_SMART_TABS|flat_nb.FNB_NO_NAV_BUTTONS|flat_nb.FNB_NODRAG

def compare_scans(scan1, scan2, verbose=False):
    "compare dictionary for 2 scans"

    REQ_COMPS = ('pos_settle_time', 'det_settle_time', 'dwelltime', 'type',
                 'extra_pvs', 'detectors', 'counters')

    OPT_COMPS = ('positioners', 'inner', 'outer', 'dimension', 'elem',
                 'e0', 'is_relative', 'regions', 'energy_drive',
                 'max_time')

    def equal(this, other):
        if verbose: print ' comp? ', this, other
        if isinstance(this, (str, unicode)):
            try:
                this = str(this)
            except:
                pass
            try:
                other = str(other)
            except:
                pass
            return this == other
        elif isinstance(this, (list, tuple)):
            out = True
            for thisitem, otheritem in zip(this, other):
                out = out and equal(thisitem, otheritem)
            return out
        elif isinstance(this, dict):
            out = True
            for thisitem in this:
                out = out and equal(this[thisitem], other[thisitem])
            return out
        return this == other
    for comp in REQ_COMPS:
        try:
            if not equal(scan1[comp], scan2[comp]):
                print scan1[comp], scan2[comp]
                return False
        except:
            return False

    for comp in OPT_COMPS:
        if comp in scan1:
            try:
                if not equal(scan1[comp], scan2[comp]):
                    print scan1[comp], scan2[comp]

                    return False
            except:
                return False
    return True


class ScanFrame(wx.Frame):
    _about = """StepScan GUI
  Matt Newville <newville @ cars.uchicago.edu>
  """
    def __init__(self, dbname='Test.db', server='sqlite', host=None,
                 user=None, password=None, port=None, create=True,  **kws):

        wx.Frame.__init__(self, None, -1, style=FRAMESTYLE, **kws)

        self.pvlist = {}

        self.subframes = {}
        self._larch = None
        self.epics_status = 0
        self.larch_status = 0
        self.last_scanname = ''
        self.scan_started = False

        self.scandb = ScanDB(dbname=dbname, server=server, host=host,
                 user=user, password=password, port=port, create=create)


        wx.EVT_CLOSE(self, self.onClose)

        self.createMainPanel()
        self.createMenus()
        self.statusbar = self.CreateStatusBar(2, 0)
        self.statusbar.SetStatusWidths([-3, -1])
        statusbar_fields = ["Initializing...", "Status"]
        for i in range(len(statusbar_fields)):
            self.statusbar.SetStatusText(statusbar_fields[i], i)


        self.set_workdir()

        self.scantimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onScanTimer, self.scantimer)

        self.inittimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onInitTimer, self.inittimer)
        self.inittimer.Start(100)


    def createMainPanel(self):
        self.SetTitle("Epics Scans")
        self.SetSize((750, 600))
        self.SetFont(Font(10))

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.nb = flat_nb.FlatNotebook(self, wx.ID_ANY, agwStyle=FNB_STYLE)
        self.nb.SetSize((750, 450))
        self.nb.SetBackgroundColour('#FCFCFA')
        self.SetBackgroundColour('#F0F0E8')

        self.scanpanels = {}
        inb  = 0
        for name, creator in (('Linear',  LinearScanPanel),
                              ('Slew',    SlewScanPanel),
                              ('Mesh',    MeshScanPanel),
                              ('XAFS',    XAFSScanPanel)):
            span = creator(self, scandb=self.scandb, pvlist=self.pvlist)
            self.nb.AddPage(span, "%s Scan" % name, True)
            self.scanpanels[name.lower()] =  (inb, span)
            inb += 1

        self.nb.SetSelection(0)
        sizer.Add(self.nb, 1, wx.ALL|wx.EXPAND)
        sizer.Add(wx.StaticLine(self, size=(675, 3),
                                style=wx.LI_HORIZONTAL), 0, wx.EXPAND)

        # bottom panel
        bpanel = wx.Panel(self)
        bsizer = wx.GridBagSizer(3, 5)

        self.nscans = FloatCtrl(bpanel, precision=0, value=1, 
                                minval=1, maxval=10000, size=(45, -1),
                                action=self.onSetNScans)

        self.filename = wx.TextCtrl(bpanel, -1,
                                    self.scandb.get_info('filename', default=''))
        self.filename.SetMinSize((400, 25))

        self.user_comms = wx.TextCtrl(bpanel, -1, "", style=wx.TE_MULTILINE)
        self.user_comms.SetMinSize((400, 75))

        self.msg1  = SimpleText(bpanel, "    ", size=(200, -1))
        self.msg2  = SimpleText(bpanel, "    ", size=(200, -1))
        self.msg3  = SimpleText(bpanel, "    ", size=(200, -1))


        bsizer.Add(SimpleText(bpanel, "Number of Scans:"), (0, 0), (1, 1), LCEN)
        bsizer.Add(SimpleText(bpanel, "File Name:"),       (1, 0), (1, 1), LCEN)
        bsizer.Add(SimpleText(bpanel, "Comments:"),        (2, 0), (1, 1), LCEN)
        bsizer.Add(self.nscans,     (0, 1), (1, 1), LCEN, 2)
        bsizer.Add(self.filename,   (1, 1), (1, 2), LCEN, 2)
        bsizer.Add(self.user_comms, (2, 1), (1, 2), LCEN, 2)
        bsizer.Add(self.msg1,       (0, 4), (1, 1), LCEN, 2)
        bsizer.Add(self.msg2,       (1, 4), (1, 1), LCEN, 2)
        bsizer.Add(self.msg3,       (2, 4), (1, 1), LCEN, 2)

        btnsizer = wx.BoxSizer(wx.HORIZONTAL)
        btnpanel = wx.Panel(bpanel)
        for ibtn, label in enumerate(("Start", "Pause", "Resume", "Abort", "Debug")):
            btn = add_button(btnpanel, label, size=(120, -1),
                             action=Closure(self.onCtrlScan, cmd=label))
            btnsizer.Add(btn, 0, CEN, 8)
        pack(btnpanel, btnsizer)

        ir = 3
        bsizer.Add(btnpanel,  (3, 0), (1, 4), wx.ALIGN_LEFT|wx.ALL, 1)

        bpanel.SetSizer(bsizer)
        bsizer.Fit(bpanel)
        sizer.Add(bpanel, 0, wx.ALIGN_LEFT|wx.ALL, 3)
        self.SetSizer(sizer)
        sizer.Fit(self)
        self._icon = None


    def onInitTimer(self, evt=None):
        # print 'on init ', self.larch_status, self.epics_status, time.ctime()
        if self.larch_status == 0:
            self.ini_larch_thread = Thread(target=self.init_larch)
            self.ini_larch_thread.start()

        if self.epics_status == 0:
            self.ini_epics_thread = Thread(target=self.connect_epics)
            self.ini_epics_thread.start()

        if (self.epics_status == 1 and self.larch_status == 1):
            time.sleep(0.05)
            self.ini_larch_thread.join()
            self.ini_epics_thread.join()
            for inb, span in self.scanpanels.values():
                span.initialize_positions()
            self.inittimer.Stop()
            if atGSECARS():
                wx.CallAfter(self.onShowPlot)
                wx.CallAfter(self.onEditMacro)

            self.statusbar.SetStatusText('', 0)
            self.statusbar.SetStatusText('Ready', 1)

    def init_larch(self):
        self.larch_status = -1
        self._larch = LarchScanDBServer(self.scandb)
        self._larch.set_symbol('_sys.wx.wxapp', wx.GetApp())
        self._larch.set_symbol('_sys.wx.parent', self)
        
        for inb, span in self.scanpanels.values():
            span.larch = self._larch
        self.statusbar.SetStatusText('Larch Ready')
        self.larch_status = 1

        try:
            fico = os.path.join(larch_site_config.sys_larchdir, 
                                'bin', ICON_FILE)
            self._icon = wx.Icon(fico, wx.BITMAP_TYPE_ICO)
            self.SetIcon(self._icon)
        except:
            print "No icon Set"
            pass


    @EpicsFunction
    def connect_epics(self):
        t0 = time.time()
        for pv in self.scandb.getall('pvs'):
            name = normalize_pvname(pv.name)
            self.pvlist[name] = epics.PV(name)
        self.epics_status = 1
        time.sleep(0.05)
        self.statusbar.SetStatusText('Epics Ready')

    def generate_scan(self, scanname=None, debug=False):
        """generate scan definition from current values on GUI
        return scanname, scan_dict
        """
        if scanname is None:
            scanname = time.strftime("__%b%d_%H:%M:%S__")

        scan = self.nb.GetCurrentPage().generate_scan_positions()
        sdb = self.scandb
        fname = self.filename.GetValue()
        scan['filename'] = fname

        scan['pos_settle_time'] = float(sdb.get_info('pos_settle_time', default=0.))
        scan['det_settle_time'] = float(sdb.get_info('det_settle_time', default=0.))
        scan['rois'] = json.loads(sdb.get_info('rois', default='[]'))

        scan['detectors'] = []
        scan['counters']  = []
        if 'extra_pvs' not in scan:
            scan['extra_pvs'] = []
        for det in sdb.select('scandetectors', use=1):
            opts = json.loads(det.options)
            opts['label']  = det.name
            opts['prefix'] = det.pvname
            opts['kind']   = det.kind
            opts['notes']  = det.notes
            scan['detectors'].append(opts)

        for ct in sdb.select('scancounters', use=1):
            scan['counters'].append((ct.name, ct.pvname))

        for ep in sdb.select('extrapvs', use=1):
            scan['extra_pvs'].append((ep.name, ep.pvname))

        if debug:
            return (scanname,  scan)

        # check if this is identical to previous scan
        scan_is_new = True
        if self.last_scanname not in (None, ''):
            try:
                lastscan = json.loads(sdb.get_scandef(self.last_scanname).text)
                scan_is_new = not compare_scans(scan, lastscan, verbose=False)
            except:
                lastscan = ''
                scan_is_new = True
        if scan_is_new:
            sdb.add_scandef(scanname, text=json.dumps(scan), type=scan['type'])
            sdb.commit()
            self.last_scanname = scanname
        return self.last_scanname, scan

    def onSetNScans(self,  value=1, **kws):
        wid = getattr(self, 'nscans', None)
        if wid is not None:
            nscans   = int(self.nscans.GetValue())
            self.scandb.set_info('nscans', nscans)
        
    def onStartScan(self, evt=None):
        sname, dat = self.generate_scan()
        fname    = self.filename.GetValue()
        nscans   = int(self.nscans.GetValue())
        comments = self.user_comms.GetValue()

        self.scandb.set_info('request_abort', 0)
        self.scandb.set_info('request_pause', 0)
        self.scandb.set_info('nscans', nscans)
            
        fmt = "do_%s('%s', filename='%s', comments='%s', nscans=%i)" 

        command = 'scan'
        if dat['type'].lower() == 'slew':
            command = 'slewscan'
            nscans = 1

        command = fmt % (command, sname, fname, comments, nscans)
        self.scandb.add_command(command)
        self.statusbar.SetStatusText('Waiting....', 0)
        self.scan_started = False
        self.scantimer.Start(100)

    def onDebugScan(self, evt=None):
        scanname, dat = self.generate_scan()
        fname = self.filename.GetValue()
        #for key, val in dat.items():
        #    print ' {} = {} '.format(key, val)

        sname = fix_filename('%s.ini' % scanname)
        fout = open(sname, 'w')
        fout.write("%s\n" % json.dumps(dat))
        fout.close()
        print 'wrote %s' % sname

    def onScanTimer(self, evt=None):
        try:
            self.statusbar.SetStatusText(self.scandb.get_info('scan_message'), 0)
        except:
            pass

        status = self.scandb.get_info('scan_status')
        if status == 'running' and not self.scan_started:
            self.scan_started = True

        if status == 'idle' and self.scan_started:
            self.scan_started = False
            fname = self.scandb.get_info('filename')
            self.filename.SetValue(new_filename(fname))
            self.scantimer.Stop()


    def onCtrlScan(self, evt=None, cmd=''):
        cmd = cmd.lower()
        if cmd == 'start':
            self.onStartScan()
        elif cmd == 'debug':
            self.onDebugScan()
        elif cmd == 'abort':
            self.scandb.set_info('request_abort', 1)
        elif cmd == 'pause':
            self.scandb.set_info('request_pause', 1)
        elif cmd == 'resume':
            self.scandb.set_info('request_pause', 0)

    def createMenus(self):
        self.menubar = wx.MenuBar()
        # file
        fmenu = wx.Menu()
        add_menu(self, fmenu, "Read Scan Definition\tCtrl+O",
                 "Read Scan Defintion", self.onReadScanDef)

        add_menu(self, fmenu, "Save Scan Definition\tCtrl+S",
                 "Save Scan Definition", self.onSaveScanDef)

        add_menu(self, fmenu, "Read old scan (.scn) File",
                 "Read old scan (.scn) file", self.onReadOldScanFile)
        fmenu.AppendSeparator()

        add_menu(self, fmenu,'Change &Working Folder\tCtrl+W',
                 "Choose working directory",  self.onFolderSelect)
        add_menu(self, fmenu,'Show Plot Window',
                 "Show Window for Plotting Scan", self.onShowPlot)

        fmenu.AppendSeparator()
        add_menu(self, fmenu, "Quit\tCtrl+Q",
        "Quit program", self.onClose)

        # options
        pmenu = wx.Menu()
        add_menu(self, pmenu, "Scan Definitions\tCtrl+D",
                 "Manage Saved Scans", self.onEditScans)


        add_menu(self, pmenu, "Select ROIs\tCtrl+R",
                 "Select MCA ROIs", self.onEditROIs)

        add_menu(self, pmenu, "General Settings",
                 "General Setup", self.onEditSettings)

        add_menu(self, pmenu, "Extra PVs",
                 "Setup Extra PVs to save with scan", self.onEditExtraPVs)

        pmenu.AppendSeparator()
        add_menu(self, pmenu, "Configure Detectors",
                 "Setup Detectors and Counters", self.onEditDetectors)
        add_menu(self, pmenu, "Configure Positioners",
                 "Setup Motors and Positioners", self.onEditPositioners)


        # Sequences
        smenu = wx.Menu()
        add_menu(self, smenu, "Sequences",
                 "Run Sequences of Scans",  self.onEditSequences)
        add_menu(self, smenu, "Edit Macro",
                  "Edit Macro",  self.onEditMacro)

        # help
        hmenu = wx.Menu()
        add_menu(self, hmenu, "&About",
                  "More information about this program",  self.onAbout)

        self.menubar.Append(fmenu, "&File")
        self.menubar.Append(pmenu, "&Setup")
        self.menubar.Append(smenu, "Macro")
        self.menubar.Append(hmenu, "&Help")
        self.SetMenuBar(self.menubar)

    def onAbout(self,evt):
        dlg = wx.MessageDialog(self, self._about,"About Epics StepScan",
                               wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    def onClose(self, evt=None):

        ret = popup(self, "Really Quit?", "Exit Epics Scan?",
                    style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION)
        if ret == wx.ID_YES:
            for child in self.subframes.values():
                try:
                    child.Destroy()
                except:
                    pass
            self.Destroy()

    def show_subframe(self, name, frameclass):
        shown = False
        if name in self.subframes:
            try:
                self.subframes[name].Raise()
                shown = True
            except:
                del self.subframes[name]
        if not shown:
            self.subframes[name] = frameclass(self, _larch=self._larch)
            if self._icon is not None:
                self.subframes[name].SetIcon(self._icon)

    def onShowPlot(self, evt=None):
        self.show_subframe('plot', ScanViewerFrame)

    def onEditPositioners(self, evt=None):
        self.show_subframe('pos', PositionerFrame)

    def onEditExtraPVs(self, evt=None):
        self.show_subframe('pvs', ExtraPVsFrame)

    def onEditDetectors(self, evt=None):
        self.show_subframe('det', DetectorFrame)

    def onEditROIs(self, evt=None):
        self.show_subframe('rois', ROIFrame)

    def onEditScans(self, evt=None):
        self.show_subframe('scan', ScandefsFrame)
        current_nb = self.nb.GetSelection()
        self.subframes['scan'].nb.SetSelection(current_nb)

    def onEditSettings(self, evt=None):
        self.show_subframe('settings', SettingsFrame)

    def onEditSequences(self, evt=None):
        self.show_subframe('sequences', SequencesFrame)

    def onEditMacro(self, evt=None):
        self.show_subframe('macro', MacroFrame)

    def set_workdir(self, basedir=None):
        """set working dir"""
        if basedir is None:
            basedir = self.scandb.get_info('user_folder')
        basedir = str(basedir)
        fileroot = str(get_fileroot())
        if basedir.startswith(fileroot):
            basedir = basedir[len(fileroot):]
            print 'trimmed basedir to ', basedir
        self.scandb.set_info('user_folder', basedir)
        fullpath = os.path.join(fileroot, basedir)
        fullpath = fullpath.replace('\\', '/').replace('//', '/')
        try:
            os.chdir(fullpath)
        except:
            print("ScanApp: Could not set working directory to %s " % fullpath)
        print("ScanApp working folder: %s " % os.getcwd())
        
    def onFolderSelect(self,evt):
        style = wx.DD_DIR_MUST_EXIST|wx.DD_DEFAULT_STYLE

        dlg = wx.DirDialog(self, "Select Working Directory:", os.getcwd(),
                           style=style)

        if dlg.ShowModal() == wx.ID_OK:
            basedir = os.path.abspath(str(dlg.GetPath())).replace('\\', '/')
            self.set_workdir(basedir=basedir)

        dlg.Destroy()

    def onSaveScanDef(self, evt=None):
        dlg = wx.TextEntryDialog(self, "Scan Name:",
                                 "Enter Name for this Scan", "")
        dlg.SetValue(self.last_scanname)
        sname = None
        if dlg.ShowModal() == wx.ID_OK:
            sname =  dlg.GetValue()
        dlg.Destroy()
        if sname is not None:
            scannames = [s.name for s in self.scandb.select('scandefs')]
            if sname in scannames:
                _ok = wx.ID_NO
                if self.scandb.get_info('scandefs_verify_overwrite',
                                        as_bool=True, default=1):
                    _ok =  popup(self,
                                 "Overwrite Scan Definition '%s'?" % sname,
                                 "Overwrite Scan Definition?",
                                 style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION)

                if (_ok == wx.ID_YES):
                    print 'Deleting Scan Def ', sname
                    self.scandb.del_scandef(sname)
                    print 'Deleted Scan Def ', sname
                else:
                    sname = ''
            if len(sname) > 0:
                name, scan = self.generate_scan(scanname=sname)
                thisscan = self.scandb.get_scandef(name)
                

                self.statusbar.SetStatusText("Saved scan '%s'" % sname)
            else:
                self.statusbar.SetStatusText("Could not overwrite scan '%s'" % sname)

        if len(sname) > 0:
            self.last_scanname = sname

    def onReadScanDef(self, evt=None):
        _autotypes = self.scandb.get_info('scandefs_load_showauto',
                                          as_bool=True, default=0)
        _alltypes  = self.scandb.get_info('scandefs_load_showalltypes',
                                          as_bool=True, default=0)
        stype = None
        if not _alltypes:
            inb =  self.nb.GetSelection()
            for key, val in self.scanpanels.items():
                if val[0] == inb:
                    stype = key

        snames = []
        for sdef in self.scandb.getall('scandefs', orderby='last_used_time'):
            if ((_alltypes or stype == sdef.type) and
                (_autotypes or not sdef.name.startswith('__'))):
                snames.append(sdef.name)

        snames.reverse()
        dlg = wx.SingleChoiceDialog(self, "Select Scan Definition:",
                                    "Select Scan Definition", snames)
        dlg.SetMinSize((575, 400))
        sname = None
        if dlg.ShowModal() == wx.ID_OK:
            sname =  dlg.GetStringSelection()
        dlg.Destroy()

        if sname is not None:
            self.load_scan(sname)


    def onReadOldScanFile(self, evt=None):
        "read old scan file"

        wcard = 'Scan files (*.scn)|*.scn|All files (*.*)|*.*'
        dlg = wx.FileDialog(self,
                            message="Open old scan file",
                            wildcard=wcard,
                            style=wx.OPEN|wx.CHANGE_DIR)

        scanfile = None
        if dlg.ShowModal() == wx.ID_OK:
            scanfile = os.path.abspath(dlg.GetPath())
        dlg.Destroy()

        if scanfile is None:
            return
        try:
            scandict = read_oldscanfile(scanfile)
        except:
            scandict = {'type': None}

        stype = scandict['type'].lower()
        if stype in self.scanpanels:
            inb, span = self.scanpanels[stype]
            self.nb.SetSelection(inb)
            span.load_scandict(scandict)


    def load_scan(self, scanname):
        """load scan definition from dictionary, as stored
        in scandb scandef.text field
        """
        self.statusbar.SetStatusText("Read Scan '%s'" % scanname)

        sdb = self.scandb
        scan = json.loads(sdb.get_scandef(scanname).text)

        sdb.set_info('det_settle_time', scan['det_settle_time'])
        sdb.set_info('pos_settle_time', scan['pos_settle_time'])

        if 'rois' in scan:
            sdb.set_info('rois', json.dumps(scan['rois']))

        ep = [x.pvname for x in sdb.select('extrapvs')]
        for name, pvname in scan['extra_pvs']:
            if pvname not in ep:
                self.scandb.add_extrapv(name, pvname)

        for detdat in scan['detectors']:
            det = sdb.get_detector(detdat['label'])
            if det is None:
                name   = detdat.pop('label')
                prefix = detdat.pop('prefix')
                dkind  = detdat.pop('kind')
                use = True
                if 'use' in detdat:
                    use = detdat.pop('use')
                opts   = json.dumps(detdat)
                sdb.add_detector(name, prefix,
                                 kind=dkind,
                                 options=opts,
                                 use=use)
            else:
                det.prefix = detdat.pop('prefix')
                det.dkind  = detdat.pop('kind')
                det.use = True
                if 'use' in detdat:
                    det.use  = detdat.pop('use')
                det.options = json.dumps(detdat)

        if 'positioners' in scan:
            for data in scan['positioners']:
                name = data[0]
                pos = self.scandb.get_positioner(name)
                name = data[0]
                drivepv, readpv = data[1]
                if pos is None:
                    sdb.add_positioner(name, drivepv,
                                       readpv=readpv)
                else:
                    pos.drivepv = drivepv
                    pos.readpv = readpv

        # now fill in page
        self.last_scanname = scanname
        stype = scan['type'].lower()
        if stype in self.scanpanels:
            inb, span = self.scanpanels[stype]
            self.nb.SetSelection(inb)
            span.load_scandict(scan)


class ScanApp(wx.App, wx.lib.mixins.inspection.InspectionMixin):
    def __init__(self, dbname='TestScan.db', server='sqlite', host=None,
                 port=None, user=None, password=None, create=True, **kws):

        self.scan_opts = dict(dbname=dbname, server=server, host=host,
                              port=port, create=create, user=user,
                              password=password)
        self.scan_opts.update(kws)
        wx.App.__init__(self)

    def OnInit(self):
        self.Init()
        frame = ScanFrame(**self.scan_opts)
        frame.Show()
        self.SetTopWindow(frame)
        return True
