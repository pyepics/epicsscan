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
from __future__ import print_function
import os
import sys
import time
import shutil
import numpy as np
import json
import socket
from collections import OrderedDict
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

from ..xafs_scan import XAFS_Scan

from ..file_utils import new_filename, nativepath, fix_filename

from ..scandb import ScanDB

from .scan_panels import (LinearScanPanel, MeshScanPanel,
                          SlewScanPanel,   XAFSScanPanel)

from ..larch_interface import LarchScanDBServer, larch
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

is_wxPhoenix = 'phoenix' in wx.PlatformInfo

def compare_scans(scan1, scan2, verbose=False):
    "compare dictionary for 2 scans"

    REQ_COMPS = ('pos_settle_time', 'det_settle_time', 'dwelltime', 'type',
                 'detectors', 'counters')

    OPT_COMPS = ('positioners', 'inner', 'outer', 'dimension', 'elem',
                 'e0', 'is_relative', 'regions', 'energy_drive',
                 'max_time')

    def equal(this, other):
        if verbose: print(' comp? ', this, other)
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
            out = (len(this) == len(other))
            if out:
                for thisitem, otheritem in zip(this, other):
                    out = out and equal(thisitem, otheritem)
            return out
        elif isinstance(this, dict):
            out = (len(this) == len(other))
            if out:
                for thisitem in this:
                    out = out and equal(this[thisitem], other[thisitem])
                    return out
        return this == other

    for comp in REQ_COMPS:
        try:
            if not equal(scan1[comp], scan2[comp]):
                return False
        except:
            return False

    for comp in OPT_COMPS:
        if comp in scan1:
            try:
                if not equal(scan1[comp], scan2[comp]):
                    return False
            except:
                return False
    return True


class ScanFrame(wx.Frame):
    _about = """StepScan GUI
  Matt Newville <newville @ cars.uchicago.edu>
  """
    def __init__(self, **kws):
        # dbname='Test.db', server='sqlite', host=None,
        #          user=None, password=None, port=None, create=True,  

        wx.Frame.__init__(self, None, -1, style=FRAMESTYLE, **kws)

        self.pvlist = {}
        self.SetSize((775, 625))
        self.subframes = {}
        self._larch = None

        self.last_scanname = ''
        self.scan_started = False

        self.scandb = ScanDB()

        print(' Connected ScanDB  ', self.scandb.engine)

        self.Bind(wx.EVT_CLOSE, self.onClose)

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

        self._larch = LarchScanDBServer(self.scandb)
        self._larch.set_symbol('_sys.wx.wxapp', wx.GetApp())
        self._larch.set_symbol('_sys.wx.parent', self)
        self.statusbar.SetStatusText('Larch Ready')

        try:
            fico = os.path.join(larch.site_config.larchdir,
                                'icons', ICON_FILE)
            self._icon = wx.Icon(fico, wx.BITMAP_TYPE_ICO)
            self.SetIcon(self._icon)
        except:
            pass

        for span in self.scanpanels:
            span.initialize_positions()
            span.larch = self._larch

        self.statusbar.SetStatusText('', 0)
        self.statusbar.SetStatusText('Ready', 1)
        self.onFolderSelect()

        self.onShowPlot()
        self.onEditMacro()
        self.connect_epics()
        # self.restart_server()


    def createMainPanel(self):
        self.SetTitle("Epics Scans")
        self.SetSize((750, 750))
        self.SetFont(Font(10))

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.nb = flat_nb.FlatNotebook(self, wx.ID_ANY, agwStyle=FNB_STYLE)
        self.nb.SetSize((750, 600))
        self.nb.SetBackgroundColour('#FCFCFA')
        self.SetBackgroundColour('#F0F0E8')

        self.scanpanels = []
        self.scanpanel_types = []
        self.scanpanels_nid = {}
        inb  = 0
        # Notebooks   scantype   title   panel
        creators = {'slew': SlewScanPanel,
                    'xafs': XAFSScanPanel,
                    'linear': LinearScanPanel}
        self.notebooks = (('slew', 'Map Scans'),
                          ('xafs', 'XAFS Scans'),
                          ('linear', 'Linear Scans'))

        for stype, title in self.notebooks:
            span = creators[stype](self, scandb=self.scandb,
                                   pvlist=self.pvlist)
            self.nb.AddPage(span, title, True)
            self.scanpanels.append(span)
            self.scanpanel_types.append(stype)

        self.nb.SetSelection(0)
        sizer.Add(self.nb, 1, wx.ALL|wx.EXPAND)
        sizer.Add(wx.StaticLine(self, size=(675, 3),
                                style=wx.LI_HORIZONTAL), 0, wx.EXPAND)

        btnsizer = wx.BoxSizer(wx.HORIZONTAL)
        btnpanel = wx.Panel(self)
        # bnames = ("Start", "Abort", "Pause", "Resume", "Debug")
        bnames = ("Start", "Abort", "Pause", "Resume")
        for ibtn, label in enumerate(bnames):
            btn = add_button(btnpanel, "%s Scan" % label, size=(120, -1),
                             action=Closure(self.onCtrlScan, cmd=label))
            btnsizer.Add(btn, 0, CEN, 8)
        pack(btnpanel, btnsizer)

        sizer.Add(btnpanel, 0, wx.ALIGN_LEFT|wx.ALL, 3)
        self.SetSizer(sizer)
        sizer.Fit(self)
        self.nb.SetSize((750, 675))
        self.SetSize((775, 700))
        self._icon = None


    @EpicsFunction
    def connect_epics(self):
        for pv in self.scandb.getall('pv'):
            name = normalize_pvname(pv.name)
            if len(name)>0:
                self.pvlist[name] = epics.PV(name)
            time.sleep(0.01)
        # print("PVs connected")
        self.statusbar.SetStatusText('Epics Ready')

    def generate_scan(self, scanname=None, debug=False, force_save=False):
        """generate scan definition from current values on GUI
        return scanname, scan_dict
        """
        if scanname is None:
            scanname = time.strftime("__%b%d_%H:%M:%S__")

        scan = self.nb.GetCurrentPage().generate_scan_positions()
        sdb = self.scandb
        # fname = self.filename.GetValue()
        # scan['filename'] = fname

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

        # for ep in sdb.select('extrapvs', use=1):
        #    scan['extra_pvs'].append((ep.name, ep.pvname))

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

        if scan_is_new or force_save:
            name_exists = sdb.get_scandef(scanname) is not None
            if name_exists:
                count = 0
                while name_exists and count < 25:
                    count += 1
                    time.sleep(0.25)
                    scanname = time.strftime("__%b%d_%H:%M:%S__") + ('%d' % count)
                    name_exists = sdb.get_scandef(scanname) is not None
            if name_exists:
                print("Cannot find a scan name... something is wrong with ScanDB")
            else:
                sdb.add_scandef(scanname, text=json.dumps(scan),
                                type=scan['type'])
                sdb.commit()
            self.last_scanname = scanname
        return self.last_scanname, scan

    def onStartScan(self, evt=None):
        sname, scan = self.generate_scan(force_save=False)
        fname  = scan.get('filename', 'scan.001')
        nscans = int(scan.get('nscans', 1))
        comments = scan.get('comments', '')
        self.scandb.set_info('scan_progress', 'preparing scan')
        self.scandb.set_info('request_abort', 0)
        self.scandb.set_info('request_pause', 0)
        self.scandb.set_info('nscans', nscans)


        fmt = "do_%s('%s', filename='%s', nscans=%i, comments='''%s''')"

        command = 'scan'
        if scan['type'].lower() == 'slew':
            command = 'slewscan'
            nscans = 1

        command = fmt % (command, sname, fname, nscans, comments)
        self.scandb.add_command(command)
        self.statusbar.SetStatusText('Waiting....', 0)

        self.scan_started = False
        self.scantimer.Start(100)

    def onDebugScan(self, evt=None):
        sname, scan = self.generate_scan(force_save=False)
        print("DEBUG generated scan name  ", sname)
        fname  = scan.get('filename', 'scan.001')
        nscans = int(scan.get('nscans', 1))
        comments = scan.get('comments', '')

        self.scandb.set_info('request_abort', 0)
        self.scandb.set_info('request_pause', 0)
        self.scandb.set_info('nscans', nscans)

        fmt = "do_%s('%s', filename='%s', nscans=%i, comments='''%s''')"

        command = 'scan'
        if scan['type'].lower() == 'slew':
            command = 'slewscan'
            nscans = 1

        command = fmt % (command, sname, fname, nscans, comments)
        print("would do command: ", command)
        dfname = fix_filename('%s.ini' % sname)
        fout = open(dfname, 'w')
        fout.write("%s\n" % json.dumps(scan))
        fout.close()

    def onScanTimer(self, evt=None):
        try:
            prog =self.scandb.get_info('scan_progress')
            self.statusbar.SetStatusText(prog, 0)
        except:
            print("no scan info scan_progress")
            pass

        status = self.scandb.get_info('scan_status')
        if status == 'running' and not self.scan_started:
            self.scan_started = True

        if status == 'idle' and self.scan_started:
            self.scan_started = False
            fname = self.scandb.get_info('filename')
            scanpage = self.nb.GetCurrentPage()
            scanpage.filename.SetValue(new_filename(fname))
            self.scantimer.Stop()


    def onCtrlScan(self, evt=None, cmd=''):
        cmd = cmd.lower()
        if cmd.startswith('start'):
            self.onStartScan()
        elif cmd.startswith('debug'):
            self.onDebugScan()
        elif cmd.startswith('abort'):
            self.scandb.set_info('request_abort', 1)
        elif cmd.startswith('pause'):
            self.scandb.set_info('request_pause', 1)
        elif cmd.startswith('resume'):
            self.scandb.set_info('request_pause', 0)
        time.sleep(0.5)

    def createMenus(self):
        self.menubar = wx.MenuBar()
        menu_dat = OrderedDict()
        menu_dat['&File'] = (("Read Scan Definition\tCtrl+O",
                              "Read Scan Defintion", self.onReadScanDef),
                             ("Save Scan Definition\tCtrl+S",
                              "Save Scan Definition", self.onSaveScanDef),
                             ("<separator>", "", None),
                             ("Quit\tCtrl+Q",
                              "Quit program", self.onClose))

        menu_dat['Setup'] = (("General Settings",
                              "General Setup", self.onEditSettings),
                             ('Change &Working Folder\tCtrl+W',
                              "Choose working directory",  self.onFolderSelect),
                             ('Show Plot Window\tCtrl+P',
                              "Show Window for Plotting Scan", self.onShowPlot),
                             ("Show Macro/Command Window\tCtrl+M",
                              "Edit Macros, Run Commands",  self.onEditMacro),
                             ("Restart Scan Server",
                              "Try to Restart Server",  self.onRestartServer),
                             )


        menu_dat['Scans'] = (("Scan Definitions\tCtrl+D",
                              "Browsn and Manage Saved Scans", self.onEditScans),
                             ("Show Sequences and Scan Queue",
                               "Show Scans Queue",  self.onEditSequences))


        menu_dat['Positioners'] = (("Configure",
                                    "Setup Motors and Positioners", self.onEditPositioners),
                                   ("Extra PVs",
                                    "Setup Extra PVs to save with scan", self.onEditExtraPVs))

        menu_dat['Detectors'] = (("Configure",
                                  "Setup Detectors and Counters", self.onEditDetectors),
                                 ("Select ROIs\tCtrl+R",
                                  "Select MCA ROIs", self.onEditROIs))

        menu_dat['&Help'] = (("About",
                               "More information about this program",  self.onAbout),)

        for key, dat in menu_dat.items():
            menu = wx.Menu()
            for label, helper, callback in dat:
                if label.startswith('<separ'):
                    menu.AppendSeparator()
                else:
                    add_menu(self, menu, label, helper, callback)
            self.menubar.Append(menu, key)
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
            self.scantimer.Stop()
            for child in self.subframes.values():
                try:
                    child.onClose()
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
        self.subframes['scan'].nb.SetSelection(self.nb.GetSelection())

    def onEditSettings(self, evt=None):
        self.show_subframe('settings', SettingsFrame)

    def onEditSequences(self, evt=None):
        self.show_subframe('sequences', SequencesFrame)

    def onEditMacro(self, evt=None):
        self.show_subframe('macro', MacroFrame)

    def onRestartServer(self, evt=None):
        try:
            self.scandb.add_command("restart_scanserver")
        except:
            pass

    def set_workdir(self, basedir=None):
        """set working dir"""
        if basedir is None:
            basedir = self.scandb.get_info('user_folder')
        basedir = str(basedir)

        fileroot = self.scandb.get_info('server_fileroot')
        if os.name == 'nt':
            fileroot = self.scandb.get_info('windows_fileroot')
        if fileroot is None:
            fileroot = ''

        if basedir.startswith(fileroot):
            basedir = basedir[len(fileroot):]
        self.scandb.set_info('user_folder', basedir)
        fullpath = os.path.join(fileroot, basedir)
        if os.name == 'nt' and ':' in fullpath[:4]:
            fullpath = fullpath.replace(':', ':/')
        fullpath = fullpath.replace('\\', '/').replace('//', '/')

        try:
            os.chdir(fullpath)
        except:
            print("ScanApp: Could not set working directory to %s " % fullpath)

    def onFolderSelect(self, evt=None):
        style = wx.DD_DIR_MUST_EXIST|wx.DD_DEFAULT_STYLE

        dlg = wx.DirDialog(self, "Select Working Directory:", os.getcwd(),
                           style=style)

        if dlg.ShowModal() == wx.ID_OK:
            basedir = os.path.abspath(str(dlg.GetPath())).replace('\\', '/')
            self.set_workdir(basedir=basedir)

            pref, username = os.path.split(basedir)
            try:
                self.scandb.add_command("set_user_name('%s')"% username)
            except:
                pass
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
                    self.scandb.del_scandef(sname)

                else:
                    sname = ''
            if len(sname) > 0:
                name, scan = self.generate_scan(scanname=sname, force_save=True)
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
            stype = self.scanpanel_types[self.nb.GetSelection()]
        snames = []
        for sdef in self.scandb.getall('scandefs', orderby='last_used_time'):
            if sdef.type is None:
                continue
            if ((_alltypes or stype in sdef.type) and
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
                            style=wx.FD_OPEN|wx.FD_CHANGE_DIR)

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
        iscan = self.scanpanel_types.index(stype)
        self.nb.SetSelection(iscan)
        self.scanpanels[iscan].load_scandict(scan)

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
        if 'extra_pvs' in scan:
            for name, pvname in scan['extra_pvs']:
                if pvname not in ep:
                    try:
                        self.scandb.add_extrapv(name, pvname)
                    except:
                        pass

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

        if 'positioners' in scan:
            for data in scan['positioners']:
                name = data[0]
                pos = self.scandb.get_positioner(name)
                name = data[0]
                drivepv, readpv = data[1]
                if pos is None:
                    sdb.add_positioner(name, drivepv,
                                       readpv=readpv)

        # now fill in page
        self.last_scanname = scanname
        stype = scan['type'].lower()
        if stype == 'qxafs':
            stype = 'xafs'
        iscan = self.scanpanel_types.index(stype)
        self.nb.SetSelection(iscan)
        self.scanpanels[iscan].load_scandict(scan)


class ScanApp(wx.App, wx.lib.mixins.inspection.InspectionMixin):
    def __init__(self, debug=False, **kws):
        self.debug = debug
        # , dbname='TestScan.db', server='sqlite', host=None,
        # port=None, user=None, password=None, create=True, debug=False, **kws):
        # self.debug = debug
        # self.scan_opts = dict(dbname=dbname, server=server, host=host,
        #                       port=port, create=create, user=user,
        #                       password=password)
        # self.scan_opts.update(kws)
        wx.App.__init__(self)

    def OnInit(self):
        self.Init()
        frame = ScanFrame() #**self.scan_opts)
        frame.Show()
        self.SetTopWindow(frame)
        if self.debug:
            self.ShowInspectionTool()
        return True
