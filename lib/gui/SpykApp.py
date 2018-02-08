#!/usr/bin/env python
"""
SPyK: Killer Epics Scanning with Python.

"""
import os
import sys
import time
import glob
from collections import OrderedDict

import numpy as np
np.seterr(all='ignore')

from functools import partial

import wx
import wx.lib.agw.flatnotebook as flat_nb
import wx.lib.scrolledpanel as scrolled
import wx.lib.mixins.inspection

from wx.richtext import RichTextCtrl

is_wxPhoenix = 'phoenix' in wx.PlatformInfo

from wxutils import (SimpleText, pack, Button, HLine, FileSave,
                     Choice,  Check, MenuItem, GUIColors, GridPanel,
                     CEN, RCEN, LCEN, FRAMESTYLE, Font)

from larch import Interpreter, Group, site_config
from larch.larchlib import read_workdir, save_workdir

from larch.wxlib import (LarchPanel, LarchFrame, ColumnDataFileFrame, ReportFrame,
                         BitmapButton, FileCheckList, FloatCtrl, SetTip)

from larch.wxlib.larchframe import LarchWxShell, ReadlineTextCtrl

from larch_plugins.wx.icons import get_icon

from epicsscan import ScanDB


LCEN = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL
CEN |=  wx.ALL
FILE_WILDCARDS = "Data Files(*.0*,*.dat,*.xdi,*.prj)|*.0*;*.dat;*.xdi;*.prj|All files (*.*)|*.*"
FNB_STYLE = flat_nb.FNB_NO_X_BUTTON|flat_nb.FNB_NODRAG|flat_nb.FNB_NO_NAV_BUTTONS

ICON_FILE = 'larch.ico'

WORKDIR_FILE = 'spyk_workdir.dat'
TITLE = "Spyk: Killer Epics Scanning with Python"
BANNER = """
=============================================
   Spyk: Killer Epics Scanning with Python
   PyEpics + EpicsScans + Larch + Python
=============================================

"""


class SpykController():
    """
    class holding the Larch session and doing the
    processing work for Spyk
    """
    def __init__(self, wxparent, larch):
        self.wxparent = wxparent
        self.larch = larch
        self.symtable = self.larch.symtable
        self.symtable.set_symbol('_sys.wx.wxapp', wx.GetApp())
        self.symtable.set_symbol('_sys.wx.parent', self)
        self.scandb = None
        self.loaded_modules = {}

    def read_spykdb(self, path):
        self.scandb = ScanDB(dbname=path, server='sqlite')

    def load_macros(self, macro_dir=None, verbose=False):
        if self.scandb is None or self.larch is None:
            return

        server_root = self.scandb.get_info('server_fileroot') or '.'
        macro_folder = self.scandb.get_info('macro_folder') or '.'

        moduledir = os.path.join(server_root, macro_folder, 'macros')

        if not os.path.exists(moduledir):
            return

        _sys = self.symtable._sys
        if moduledir not in _sys.path:
            _sys.path.insert(0, moduledir)

        try:
            origdir = os.getcwd()
            os.chdir(moduledir)
            for name in glob.glob('*.lar'):
                time.sleep(0.025)
                modname = name[:-4]
                this_mtime = os.stat(name).st_mtime
                if modname in self.loaded_modules:
                    last_mtime = self.loaded_modules[modname]
                    if this_mtime < last_mtime:
                        continue

                self.larch.error = []
                if verbose:
                    print( 'importing module: ', modname)
                if modname in self.loaded_modules:
                    self.larch.run('reload(%s)' % modname)
                else:
                    self.larch.run('import %s' % modname)
                if len(self.larch.error) > 0:
                    emsg = '\n'.join(self.larch.error[0].get_error())
                    self.scandb.set_info('error_message', emsg)
                    print( '==Import Error %s/%s' % (modname, emsg))
                else:
                    if modname not in _sys.searchGroups:
                        _sys.searchGroups.append(modname)
                    self.loaded_modules[modname] = this_mtime
                    thismod  = self.symtable.get_symbol(modname)
                    _sys.searchGroupObjects.append(thismod)
            os.chdir(origdir)
        except OSError:
            pass
        return self.get_macros()

    def get_macros(self):
        """return an orderded dictionary of larch functions/procedures
        that are exposed to user for Scan macros

        These are taken from the _epics, _scan, and macros groups

        returned dictionary has function names as keys, and docstrings as values
        """
        macros = OrderedDict()
        symtab = self.symtable
        modlist = [symtab, symtab._epics, symtab._scan]
        for mod in self.loaded_modules:
            if hasattr(symtab, mod):
                modlist.append(getattr(symtab, mod))

        for group in modlist:
            for name in dir(group):
                obj = getattr(group, name)
                if callable(obj) and not name.startswith('_'):
                    doc  = obj.__doc__
                    if doc is None:
                        doc = ''
                        if hasattr(obj, '_signature'):
                            doc = obj._signature()
                    if 'PRIVATE' not in doc:
                        macros[name] = doc
        return macros


    def run_command(self, command, **kws):
        print("controller does command: ", command, kws)

class SpykShell():
    ps1 = 'Spyk >'
    ps2 = ' ... >'
    def __init__(self, wxparent=None,   writer=None, _larch=None,
                 prompt=None, historyfile=None, output=None, input=None):
        self._larch = _larch
        self.textstyle = None

        if _larch is None:
            self._larch  = Interpreter(historyfile=historyfile,
                                       writer=self)
            self._larch.run_init_scripts()

        self.symtable = self._larch.symtable
        self.prompt = prompt
        self.input  = input
        self.output = output

        self.set_textstyle(mode='text')
        self._larch("_sys.display.colors['text2'] = {'color': 'blue'}",
                    add_history=False)

        self._larch.add_plugin('wx', wxparent=wxparent)
        self.symtable.set_symbol('_builtin.force_wxupdate', False)
        self.symtable.set_symbol('_sys.wx.force_wxupdate', False)
        self.symtable.set_symbol('_sys.wx.wxapp', output)
        self.symtable.set_symbol('_sys.wx.parent', wx.GetApp().GetTopWindow())

        if self.output is not None:
            style = self.output.GetDefaultStyle()
            bgcol = style.GetBackgroundColour()
            sfont = style.GetFont()
            self.textstyle = wx.TextAttr('black', bgcol, sfont)

        self.SetPrompt(True)

        self.flush_timer = wx.Timer(wxparent)
        self.needs_flush = True
        wxparent.Bind(wx.EVT_TIMER, self.onFlushTimer, self.flush_timer)
        self.flush_timer.Start(500)

    def onUpdate(self, event=None):
        symtable = self.symtable
        if symtable.get_symbol('_builtin.force_wxupdate', create=True):
            app = wx.GetApp()
            evtloop = wx.EventLoop()
            while evtloop.Pending():
                evtloop.Dispatch()
            app.ProcessIdle()
        symtable.set_symbol('_builtin.force_wxupdate', False)


    def SetPrompt(self, complete):
        if self.prompt is None:
            return
        sprompt, scolor = self.ps1, '#000075'
        if not complete:
            sprompt, scolor = self.ps2, '#E00075'
        self.prompt.SetLabel(sprompt)
        self.prompt.SetForegroundColour(scolor)
        self.prompt.Refresh()

    def set_textstyle(self, mode='text'):
        if self.output is None:
            return

        display_colors = self._larch.symtable._sys.display.colors
        textattrs = display_colors.get(mode, {'color':'black'})
        color = textattrs['color']
        style = self.output.GetDefaultStyle()
        bgcol = style.GetBackgroundColour()
        sfont = style.GetFont()
        self.textstyle = wx.TextAttr(color, bgcol, sfont)

    def write(self, text, **kws):
        if self.output is None:
            sys.stdout.write(text)
            sys.stdout.flush()
        else:
            pos0 = self.output.GetLastPosition()
            self.output.WriteText(text)
            pos1 = self.output.GetLastPosition()
            self.output.SetStyle(pos0, pos1, self.textstyle)
            self.needs_flush = True

    def flush(self, *args):
        try:
            self.output.SetInsertionPoint(self.output.GetLastPosition())
        except:
            pass
        self.output.Refresh()
        self.output.Update()
        self.needs_flush = False

    def clear_input(self):
        self._larch.input.clear()
        self.SetPrompt(True)

    def onFlushTimer(self, event=None):
        if self.needs_flush:
            self.flush()

    def eval(self, text, add_history=True, **kws):
        if text is None:
            return
        if text.startswith('!'):
            return os.system(text[1:])

        else:
            if add_history:
                self.input.AddToHistory(text)
                self.write(">%s\n" % text)
            ret = self._larch.eval(text, add_history=add_history)
            if self._larch.error:
                self._larch.input.clear()
                self._larch.writer.set_textstyle('error')
                self._larch.show_errors()
                self._larch.writer.set_textstyle('text')
            elif ret is not None:
                self._larch.writer.write("%s\n" % repr(ret))
            self.SetPrompt(self._larch.input.complete)

class SpykFrame(wx.Frame):
    _about = """Spyk: Killer Epics Scanning with Python

    Matt Newville <newville @ cars.uchicago.edu>
    """
    def __init__(self, parent=None, size=(875, 550), fontsize=11,
                 dbname=None, historyfile='spyk_history.lar', **kws):

        self.parent = parent
        wx.Frame.__init__(self, parent, -1, size=size, style=FRAMESTYLE, **kws)
        self.SetTitle(TITLE)

        if not historyfile.startswith(site_config.usr_larchdir):
            historyfile = os.path.join(site_config.usr_larchdir,
                                       historyfile)

        self.createMainPanel(historyfile=historyfile)
        self.createMenus()
        self.statusbar = self.CreateStatusBar(3, 0)
        self.statusbar.SetStatusWidths([-2, -1, -1])
        statusbar_fields = ["Initializing Spyk", " ", " "]
        for i in range(len(statusbar_fields)):
            self.statusbar.SetStatusText(statusbar_fields[i], i)

        self.controller = SpykController(self, self.larch)

        read_workdir(WORKDIR_FILE)

        self.subframes = {}
        self.SetSize(size)
        self.SetFont(Font(fontsize))


    def onReadSpykDB(self, event=None):
        wildcard = 'Spyk DB file (*.sdb)|*.sdb|All files (*.*)|*.*'
        dlg = wx.FileDialog(self, message='Open Spyk Config File',
                            defaultDir=os.getcwd(),
                            wildcard=wildcard,
                            style=wx.FD_OPEN|wx.FD_CHANGE_DIR)
        path = None
        if dlg.ShowModal() == wx.ID_OK:
            path = os.path.abspath(dlg.GetPath()).replace('\\', '/')

        if os.path.exists(path):
            self.write_message('Reading Spyk DB ...')
            self.controller.read_spykdb(path)
            self.write_message('Loading Macros ...')
            macros = self.controller.load_macros()
            self.write_message('Ready')


    def init_larch(self):
        self.onReadSpykDB()
        self.write_message('ready')

    def write_message(self, s, panel=0):
        """write a message to the Status Bar"""
        self.SetStatusText(s, panel)

    def createMainPanel(self, historyfile='spyk_history.lar'):
        splitter  = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        splitter.SetMinimumPaneSize(250)

        self.info_panel = wx.Panel(splitter)

        # info panel
        isizer = wx.BoxSizer(wx.VERTICAL)
        s = wx.StaticText(self.info_panel, -1, ' Status info ',
                          size=(125,-1), style=LCEN)

        isizer.Add(s, 0, LCEN, 2)

        # output:
        self.output = wx.TextCtrl(splitter, -1,  '', size=(400, -1),
                                  style=wx.TE_MULTILINE|wx.TE_RICH|wx.TE_READONLY)
        self.output.CanCopy()
        self.output.SetInsertionPointEnd()

        splitter.SplitHorizontally(self.info_panel, self.output, 0.75)

        ipanel = wx.Panel(self, -1)

        self.prompt = wx.StaticText(ipanel, -1, 'Larch>', size=(65,-1),
                                    style=wx.ALIGN_CENTER|wx.ALIGN_RIGHT)

        self.input = ReadlineTextCtrl(ipanel, -1,  '', size=(525,-1),
                                      historyfile=historyfile,
                                      style=wx.ALIGN_LEFT|wx.TE_PROCESS_ENTER)

        self.input.Bind(wx.EVT_TEXT_ENTER, self.onText)
        isizer = wx.BoxSizer(wx.HORIZONTAL)
        isizer.Add(self.prompt,  0, wx.BOTTOM|wx.CENTER)
        isizer.Add(self.input,   1, wx.ALIGN_LEFT|wx.ALIGN_CENTER|wx.EXPAND)

        ipanel.SetSizer(isizer)
        isizer.Fit(ipanel)

        opts = dict(flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL|wx.EXPAND, border=2)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(splitter,  1, **opts)
        sizer.Add(ipanel, 0, **opts)

        self.SetSizer(sizer)

        self.larchshell = SpykShell(wxparent=self, historyfile=historyfile,
                                    prompt=self.prompt, output=self.output,
                                    input=self.input)

        self.larch = self.larchshell._larch
        self.larchshell.set_textstyle('text2')
        self.larchshell.write(BANNER)
        self.larchshell.set_textstyle('text')

        fico = os.path.join(site_config.larchdir, 'icons', ICON_FILE)
        if os.path.exists(fico):
            self.SetIcon(wx.Icon(fico, wx.BITMAP_TYPE_ICO))

        wx.CallAfter(self.init_larch)

    def onText(self, event=None):
        text =  event.GetString()
        self.input.Clear()
        if text.lower() in ('quit', 'exit', 'quit()', 'exit()'):
            self.onExit()
        else:
            wx.CallAfter(self.larchshell.eval, text)

    def createMenus(self):
        self.menubar = wx.MenuBar()
        fmenu = wx.Menu()
        MenuItem(self, fmenu, "&Open Script\tCtrl+O",
                 "Open Data File",  self.onReadScript)

        MenuItem(self, fmenu, "debug wx\tCtrl+I", "", self.showInspectionTool)
        MenuItem(self, fmenu, "&Quit\tCtrl+Q", "Quit program", self.onExit)


        hmenu = wx.Menu()
        MenuItem(self, hmenu, '&About',
                 'Information about this program',  self.onAbout)

        self.menubar.Append(fmenu, "&File")
        self.menubar.Append(hmenu, "&Help")
        self.SetMenuBar(self.menubar)
        self.Bind(wx.EVT_CLOSE,  self.onExit)

    def onReadScript(self, evt=None):
        print("onReadScript")


    def showInspectionTool(self, event=None):
        app = wx.GetApp()
        app.ShowInspectionTool()

    def onAbout(self,evt):
        dlg = wx.MessageDialog(self, self._about,
                               "About Spyk",
                               wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    def onExit(self, event=None, force=False):
        if force:
            ret = wx.ID_YES
        else:
            dlg = wx.MessageDialog(None, 'Really Quit?', 'Question',
                                   wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
            ret = dlg.ShowModal()

        if ret == wx.ID_YES:
            save_workdir('spyk_workdir.dat')
            self.input.SaveHistory()
            self.Destroy()
        else:
            try:
                event.Veto()
            except:
                pass

    def show_subframe(self, name, frameclass, **opts):
        shown = False
        if name in self.subframes:
            try:
                self.subframes[name].Raise()
                shown = True
            except:
                del self.subframes[name]
        if not shown:
            self.subframes[name] = frameclass(self, **opts)


class SpykApp(wx.App, wx.lib.mixins.inspection.InspectionMixin):
    def __init__(self, **kws):
        wx.App.__init__(self, **kws)

    def run(self):
        self.MainLoop()

    def createApp(self):
        frame = SpykFrame()
        frame.Show()
        self.SetTopWindow(frame)

    def OnInit(self):
        self.Init()
        self.createApp()
        return True

if __name__ == "__main__":
    SpykApp().run()
