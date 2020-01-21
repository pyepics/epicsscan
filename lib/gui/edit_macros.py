import os
import sys
import time
import logging
from sqlalchemy.sql import func as sqlfunc
from sqlalchemy import text
from datetime import datetime, timedelta
import wx
import wx.lib.scrolledpanel as scrolled
from wx.lib.editor import Editor

from collections import OrderedDict
import epics
from .gui_utils import (GUIColors, set_font_with_children, YesNo,
                        add_menu, add_button, add_choice, pack, SimpleText,
                        FileOpen, FileSave, popup, FloatCtrl,
                        FRAMESTYLE, Font)

from .common_commands  import CommonCommandsFrame, CommonCommandsAdminFrame

from ..scandb import InstrumentDB

import larch
from larch.wxlib.readlinetextctrl import ReadlineTextCtrl
LEFT = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
CEN  = wx.ALIGN_CENTER|wx.ALIGN_CENTER_VERTICAL|wx.ALL

ALL_EXP  = wx.ALL|wx.EXPAND
LEFT_CEN = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL

AUTOSAVE_FILE = 'macros_autosave.lar'
MACRO_HISTORY = 'scan_macro_history.lar'
LONG_AGO = datetime.now()-timedelta(2000)
COLOR_MSG  = '#0099BB'
COLOR_OK   = '#0000BB'
COLOR_WARN = '#BB9900'
COLOR_ERR  = '#BB0000'


class ScanDBMessageQueue(object):
    """ScanDB Messages"""
    def __init__(self, scandb):
        self.scandb = scandb
        self.cls, self.tab = scandb.get_table('messages')
        # get last ID
        out = scandb.query(sqlfunc.max(self.cls.id)).one()
        self.last_id = out[0]

    def get_new_messages(self):
        try:
            q = self.tab.select(whereclause=text("id>'%i'" % self.last_id))
        except TypeError:
            return [None]
        out = q.order_by(self.cls.id).execute().fetchall()
        if len(out) > 0:
            self.last_id = out[-1].id
        return out


class PosScanMacroBuilder(wx.Frame):
    """ transfer positions from offline microscope"""
    def __init__(self, parent, scandb=None):
        wx.Frame.__init__(self, None, -1,
                          title="Build Macro for Scans at Saved Positions")
        self.parent = parent
        self.scandb = scandb
        self.instdb = InstrumentDB(scandb)
        self.build_dialog()

    def build_dialog(self):
        # positions  = self.instdb.get_positionlist('IDE_SampleStage')
        instname = self.scandb.get_info('samplestage_instrument')
        if instname is None:
            instname = 'SampleStage'
        positions  = self.instdb.get_positionlist(instname)

        panel = scrolled.ScrolledPanel(self)
        self.checkboxes = OrderedDict()
        sizer = wx.GridBagSizer(len(positions)+5, 4)
        sizer.SetVGap(4)
        sizer.SetHGap(4)

        _nscans = ['%i'  %(i+1) for i in range(10)]

        self.scantype = add_choice(panel,  ('Maps', 'XAFS', 'Linear'),
                                 size=(100, -1),  action = self.onScanType)
        self.scantype.SetSelection(1)
        self.scanname = add_choice(panel,  [], size=(200, -1))
        self.pos_names = []
        self.wid_include = {}
        self.wid_nscans = {}

        bkws = dict(size=(95, -1))
        btn_insert = add_button(panel, "Insert Macro",  action=self.onInsert, **bkws)
        btn_all    = add_button(panel, "Select All",    action=self.onSelAll, **bkws)
        btn_none   = add_button(panel, "Select None",   action=self.onSelNone, **bkws)
        btn_done   = add_button(panel, "Close",         action=self.onClose, **bkws)

        brow = wx.BoxSizer(wx.HORIZONTAL)
        brow.Add(btn_all ,  0, ALL_EXP|wx.ALIGN_LEFT, 1)
        brow.Add(btn_none,  0, ALL_EXP|wx.ALIGN_LEFT, 1)
        brow.Add(btn_insert, 0, ALL_EXP|wx.ALIGN_LEFT, 1)
        brow.Add(btn_done, 0, ALL_EXP|wx.ALIGN_LEFT, 1)

        sizer.Add(brow,   (0, 0), (1, 4),  LEFT_CEN, 2)

        ir = 1
        sizer.Add(SimpleText(panel, 'Scan Type:'), (ir, 0), (1, 1),  LEFT_CEN, 2)
        sizer.Add(self.scantype,                   (ir, 1), (1, 1),  LEFT_CEN, 2)
        sizer.Add(SimpleText(panel, 'Scan Name:'), (ir, 2), (1, 1),  LEFT_CEN, 2)
        sizer.Add(self.scanname,                   (ir, 3), (1, 2),  LEFT_CEN, 2)

        ir += 1
        sizer.Add(SimpleText(panel, 'Position Name'), (ir, 0), (1, 2),  LEFT_CEN, 2)
        sizer.Add(SimpleText(panel, 'Include?'),      (ir, 2), (1, 1),  LEFT_CEN, 2)
        sizer.Add(SimpleText(panel, 'Nscans'),        (ir, 3), (1, 1),  LEFT_CEN, 2)

        ir += 1
        sizer.Add(wx.StaticLine(panel, size=(500, 2)),(ir, 0), (1, 4),  LEFT_CEN, 2)

        ir += 1
        for pname in positions:
            self.pos_names.append(pname)
            label = SimpleText(panel, "  %s  " % pname)
            cbox = self.wid_include[pname] = wx.CheckBox(panel, -1, "")
            cbox.SetValue(True)
            nscans = self.wid_nscans[pname] = add_choice(panel, _nscans, size=(50, -1))
            nscans.SetStringSelection('1')
            sizer.Add(label,  (ir, 0), (1, 2),  LEFT_CEN, 2)
            sizer.Add(cbox,   (ir, 2), (1, 1),  LEFT_CEN, 2)
            sizer.Add(nscans, (ir, 3), (1, 1), LEFT_CEN, 2)
            ir += 1

        sizer.Add(wx.StaticLine(panel, size=(500, 2)), (ir, 0), (1, 4),  LEFT_CEN, 2)

        pack(panel, sizer)

        panel.SetupScrolling()
        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1,  ALL_EXP|wx.GROW|wx.ALIGN_LEFT, 1)
        pack(self, mainsizer)
        self.SetMinSize((450, 550))
        self.SetSize((525, 600))
        self.Raise()
        self.Show()
        self.onScanType()

    def onSelAll(self, event=None):
        for cbox in self.wid_include.values():
            cbox.SetValue(True)

    def onSelNone(self, event=None):
        for cbox in self.wid_include.values():
            cbox.SetValue(False)

    def onScanType(self, event=None):
        sname = self.scantype.GetStringSelection().lower()
        scantype = 'linear'
        if 'xafs' in sname:
            scantype = 'xafs'
        elif 'map' in sname or 'slew' in sname:
            scantype = 'slew'
        cls, table = self.scandb.get_table('scandefs')
        q = table.select().where(table.c.type.ilike("%%%s%%" % scantype)).order_by('last_used_time')
        scannames = []
        for s in q.execute().fetchall():
            if not (s.name.startswith('__') and s.name.endswith('__')):
                scannames.append(s.name)
        scannames.reverse()
        self.scanname.Set(scannames)
        self.scanname.SetSelection(0)

    def onInsert(self, event=None):
        if self.instdb is None:
            return
        scanname = self.scanname.GetStringSelection()
        command = "pos_scan(%s, %s, number=%s)"
        buff = ["#start auto-generated macro"]
        for pname in self.pos_names:
            if self.wid_include[pname].IsChecked():
                nscans = self.wid_nscans[pname].GetStringSelection()
                buff.append( command % (repr(pname), repr(scanname), nscans))
        buff.append("#end auto-generated macro")
        buff.append("")
        self.parent.editor.AppendText("\n".join(buff))

    def onClose(self, event=None):
        self.Destroy()

class PosXRDMacroBuilder(wx.Frame):
    """ transfer positions from offline microscope"""
    def __init__(self, parent, scandb=None):
        wx.Frame.__init__(self, None, -1,
                          title="Build Macro for XRD at Saved Positions")
        self.parent = parent
        self.scandb = scandb
        self.instdb = InstrumentDB(scandb)
        self.build_dialog()

    def build_dialog(self):
        # positions  = self.instdb.get_positionlist('IDE_SampleStage')
        instname = self.scandb.get_info('samplestage_instrument')
        if instname is None:
            instname = 'SampleStage'
        positions  = self.instdb.get_positionlist(instname)
        panel = scrolled.ScrolledPanel(self)
        self.checkboxes = OrderedDict()
        sizer = wx.GridBagSizer(len(positions)+5, 4)
        sizer.SetVGap(4)
        sizer.SetHGap(4)

        _nscans = ['%i'  %(i+1) for i in range(10)]

        self.dwelltime = FloatCtrl(panel, precision=1, value=10,
                                   minval=0.5, maxval=10000, size=(75, -1))

        self.pos_names = []
        self.wid_include = {}
        self.wid_nscans = {}

        bkws = dict(size=(95, -1))
        btn_insert = add_button(panel, "Insert Macro",  action=self.onInsert, **bkws)
        btn_all    = add_button(panel, "Select All",    action=self.onSelAll, **bkws)
        btn_none   = add_button(panel, "Select None",   action=self.onSelNone, **bkws)
        btn_done   = add_button(panel, "Close",         action=self.onClose, **bkws)

        brow = wx.BoxSizer(wx.HORIZONTAL)
        brow.Add(btn_all ,  0, ALL_EXP|wx.ALIGN_LEFT, 1)
        brow.Add(btn_none,  0, ALL_EXP|wx.ALIGN_LEFT, 1)
        brow.Add(btn_insert, 0, ALL_EXP|wx.ALIGN_LEFT, 1)
        brow.Add(btn_done, 0, ALL_EXP|wx.ALIGN_LEFT, 1)

        sizer.Add(brow,   (0, 0), (1, 4),  LEFT_CEN, 2)

        ir = 1
        sizer.Add(SimpleText(panel, 'Dwell Time:'), (ir, 0), (1, 1),  LEFT_CEN, 2)
        sizer.Add(self.dwelltime,                   (ir, 1), (1, 1),  LEFT_CEN, 2)

        ir += 1
        sizer.Add(SimpleText(panel, 'Position Name'), (ir, 0), (1, 2),  LEFT_CEN, 2)
        sizer.Add(SimpleText(panel, 'Include?'),      (ir, 2), (1, 1),  LEFT_CEN, 2)

        ir += 1
        sizer.Add(wx.StaticLine(panel, size=(500, 2)),(ir, 0), (1, 4),  LEFT_CEN, 2)

        ir += 1
        for pname in positions:
            self.pos_names.append(pname)
            label = SimpleText(panel, "  %s  " % pname)
            cbox = self.wid_include[pname] = wx.CheckBox(panel, -1, "")
            cbox.SetValue(True)
            sizer.Add(label,  (ir, 0), (1, 2),  LEFT_CEN, 2)
            sizer.Add(cbox,   (ir, 2), (1, 1),  LEFT_CEN, 2)
            ir += 1

        sizer.Add(wx.StaticLine(panel, size=(500, 2)), (ir, 0), (1, 4),  LEFT_CEN, 2)

        pack(panel, sizer)

        panel.SetupScrolling()
        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1,  ALL_EXP|wx.GROW|wx.ALIGN_LEFT, 1)
        pack(self, mainsizer)
        self.SetMinSize((450, 550))
        self.SetSize((525, 600))
        self.Raise()
        self.Show()

    def onSelAll(self, event=None):
        for cbox in self.wid_include.values():
            cbox.SetValue(True)

    def onSelNone(self, event=None):
        for cbox in self.wid_include.values():
            cbox.SetValue(False)

    def onInsert(self, event=None):
        if self.instdb is None:
            return
        dtime = self.dwelltime.GetValue()
        command = "xrd_at('%s', t=%.1f)"
        buff = ["#start auto-generated macro"]
        for pname in self.pos_names:
            if self.wid_include[pname].IsChecked():
                buff.append( command % (pname, dtime))
        buff.append("#end auto-generated macro")
        buff.append("")
        self.parent.editor.AppendText("\n".join(buff))

    def onClose(self, event=None):
        self.Destroy()

class MacroFrame(wx.Frame) :
    """Edit/Manage Macros (Larch Code)"""
    output_colors = {'error_message': COLOR_ERR,
                     'scan_message':COLOR_OK}
    output_fields = ('error_message', 'scan_message')

    info_mapping = {'File Name': 'filename',
                    'Current Command': 'current_command',
                    'Status': 'scan_status',
                    'Progress': 'scan_progress',
                    'Timestamp': 'heartbeat'}

    def __init__(self, parent, pos=(-1, -1), _larch=None):

        self.parent = parent
        self.scandb = parent.scandb
        self.subframes = {}
        self.winfo = OrderedDict()
        self.output_stats = {}
        self.last_heartbeat = LONG_AGO
        self.last_start_request = 0
        for key in self.output_fields:
            self.output_stats[key] = LONG_AGO

        wx.Frame.__init__(self, None, -1,  title='Epics Scanning: Macro',
                          style=FRAMESTYLE)

        self.SetFont(Font(10))
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.createMenus()

        self.db_messages = ScanDBMessageQueue(self.scandb)

        self.colors = GUIColors()
        self.SetBackgroundColour(self.colors.bg)

        self.editor = wx.TextCtrl(self, -1, size=(550, 250),
                                  style=wx.TE_MULTILINE|wx.TE_RICH2)
        self.editor.SetBackgroundColour('#FFFFFF')

        text = """## Edit Macro text here\n#\n"""
        self.editor.SetValue(text)
        self.editor.SetInsertionPoint(len(text)-2)
        self.ReadMacroFile(AUTOSAVE_FILE)

        sfont = wx.Font(11,  wx.SWISS, wx.NORMAL, wx.BOLD, False)
        self.output = wx.TextCtrl(self, -1,  '## Output Buffer\n', size=(550, 250),
                                  style=wx.TE_MULTILINE|wx.TE_RICH|wx.TE_READONLY)
        self.output.CanCopy()
        self.output.SetInsertionPointEnd()
        self.output.SetDefaultStyle(wx.TextAttr('black', 'white', sfont))

        sizer.Add(self.make_info(),    0, wx.ALIGN_LEFT, 3)
        sizer.Add(self.make_buttons(), 0, wx.ALIGN_LEFT, 3)
        sizer.Add(self.editor, 1, CEN|wx.GROW|wx.ALL, 3)
        sizer.Add(self.output, 1, CEN|wx.GROW|wx.ALL, 3)


        sizer.Add(self.InputPanel(),  0, border=2,
                  flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL|wx.EXPAND)

        self._stimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_info, self._stimer)
        self._stimer.Start(500)

        self.Bind(wx.EVT_CLOSE, self.onClose)
        self.SetMinSize((600, 520))
        pack(self, sizer)
        self.Show()
        self.Raise()

    def reload_macros(self):
        self.scandb.add_command('load_macros()')

    def update_info(self, evt=None):
        paused = self.scandb.get_info('request_pause', as_bool=True)

        for key, attr in self.info_mapping.items():
            val = str(self.scandb.get_info(attr, '--'))
            if key in self.winfo:
                self.winfo[key].SetLabel(val)
            if key == 'Status':
                if not paused and val.lower().startswith('idle'):
                    self.start_btn.Enable()
                else:
                    self.start_btn.Disable()

        for msg in self.db_messages.get_new_messages():
            if msg is not None:
                self.writeOutput(msg.text, color=COLOR_MSG, with_nl=False)

        for key in self.output_fields:
            row = self.scandb.get_info(key, full_row=True)
            mtime = self.output_stats.get(key, LONG_AGO)
            if row.modify_time > mtime:
                self.output_stats[key] = row.modify_time
                if len(row.value) > 0:
                    self.writeOutput(row.value,
                                     color=self.output_colors.get(key, None))

        row = self.scandb.get_info('heartbeat', full_row=True)
        if row.modify_time > self.last_heartbeat:
            self.last_heartbeat = row.modify_time
        col = COLOR_OK
        if self.last_heartbeat < datetime.now()-timedelta(seconds=15):
            col = COLOR_WARN
        if self.last_heartbeat < datetime.now()-timedelta(seconds=120):
            col = COLOR_ERR
        self.winfo['Timestamp'].SetForegroundColour(col)

    def make_info(self):
        panel = wx.Panel(self)
        sizer = wx.GridBagSizer(8, 4)

        self.winfo = OrderedDict()
        opts1 = {'label':' '*99, 'colour': COLOR_OK, 'size': (425, -1),
                 'minsize': (375, -1), 'style': wx.ALIGN_LEFT}
        opts2 = {'label':' '*50, 'colour': COLOR_OK, 'size': (275, -1),
                 'minsize': (200, -1), 'style': wx.ALIGN_LEFT}
        self.winfo['File Name']       = SimpleText(panel, **opts1)
        self.winfo['Current Command'] = SimpleText(panel, **opts1)
        self.winfo['Progress']   = SimpleText(panel, **opts1)
        self.winfo['Status']     = SimpleText(panel, **opts2)
        self.winfo['Timestamp']  = SimpleText(panel, **opts2)

        irow, icol = 0, 0
        for attr in ('Status', 'Timestamp'):
            lab  = SimpleText(panel, "%s:" % attr, size=(120, -1))
            sizer.Add(lab,               (irow, icol),   (1, 1), LEFT, 1)
            sizer.Add(self.winfo[attr],  (irow, icol+1), (1, 1), LEFT, 1)
            icol +=2

        irow += 1
        for attr in ('Current Command', 'File Name', 'Progress'):
            lab  = SimpleText(panel, "%s:" % attr, size=(120, -1))
            sizer.Add(lab,               (irow, 0), (1, 1), LEFT, 1)
            sizer.Add(self.winfo[attr],  (irow, 1), (1, 3), LEFT, 1)
            irow += 1

        pack(panel, sizer)
        return panel

    def make_buttons(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.start_btn  = add_button(panel, label='Start',  action=self.onStart)
        self.pause_btn  = add_button(panel, label='Pause',  action=self.onPause)
        self.resume_btn = add_button(panel, label='Resume',  action=self.onResume)
        # self.abort_btn  = add_button(panel, label='Abort Command',  action=self.onAbort)
        self.cancel_btn = add_button(panel, label='Abort Macro', action=self.onCancelAll)
        self.restart_btn = add_button(panel, label='Restart Server',
                                      action=self.onRestartServer)

        sizer.Add(self.start_btn,  0, wx.ALIGN_LEFT, 2)
        sizer.Add(self.pause_btn,  0, wx.ALIGN_LEFT, 2)
        sizer.Add(self.resume_btn, 0, wx.ALIGN_LEFT, 2)
        # sizer.Add(self.abort_btn,  0, wx.ALIGN_LEFT, 2)
        sizer.Add(self.cancel_btn, 0, wx.ALIGN_LEFT, 2)
        sizer.Add(self.restart_btn, 0, wx.ALIGN_LEFT, 2)
        pack(panel, sizer)
        return panel

    def createMenus(self):
        self.menubar = wx.MenuBar()
        # file
        fmenu = wx.Menu()
        add_menu(self, fmenu, "Read Macro\tCtrl+R",
                 "Read Macro", self.onReadMacro)

        add_menu(self, fmenu, "Save Macro\tCtrl+S",
                 "Save Macro", self.onSaveMacro)

        fmenu.AppendSeparator()
        add_menu(self, fmenu, "Quit\tCtrl+Q",
                 "Quit Macro", self.onClose)

        # options
        pmenu = wx.Menu()
        add_menu(self, pmenu, "Common Commands",
                 "Common Commands", self.onCommonCommands)
        add_menu(self, pmenu, "Position Scans",
                 "Position Scans", self.onBuildPosScan)
        add_menu(self, pmenu, "XRD at Position",
                 "XRD at Position", self.onBuildPosXRD)
        pmenu.AppendSeparator()
        add_menu(self, pmenu, "Admin Common Commands",
                 "Admin Common Commands", self.onCommonCommandsAdmin)

        self.menubar.Append(fmenu, "&File")
        self.menubar.Append(pmenu, "Insert Commands")
        self.SetMenuBar(self.menubar)

    def InputPanel(self):
        panel = wx.Panel(self, -1)
        self.prompt = wx.StaticText(panel, -1, ' >>>', size = (30,-1),
                                    style=wx.ALIGN_CENTER|wx.ALIGN_RIGHT)
        self.histfile = os.path.join(larch.site_config.usr_larchdir, MACRO_HISTORY)
        self.input = ReadlineTextCtrl(panel, -1,  '', size=(525,-1),
                                      historyfile=self.histfile,
                                      style=wx.ALIGN_LEFT|wx.TE_PROCESS_ENTER)

        self.input.Bind(wx.EVT_TEXT_ENTER, self.onText)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        sizer.Add(self.prompt,  0, wx.BOTTOM|wx.CENTER)
        sizer.Add(self.input,   1, wx.ALIGN_LEFT|wx.ALIGN_CENTER|wx.EXPAND)
        panel.SetSizer(sizer)
        sizer.Fit(panel)
        return panel

    def onText(self, event=None):
        text = event.GetString().strip()
        if len(text) < 1:
            return
        self.input.Clear()
        self.input.AddToHistory(text)
        out = self.scandb.add_command(text)
        self.scandb.commit()
        time.sleep(0.01)
        self.writeOutput(text)

    def writeOutput(self, text, color=None, with_nl=True):
        pos0 = self.output.GetLastPosition()
        if with_nl and not text.endswith('\n'):
            text = '%s\n' % text
        self.output.WriteText(text)
        if color is not None:
            style = self.output.GetDefaultStyle()
            bgcol = style.GetBackgroundColour()
            sfont = style.GetFont()
            pos1  = self.output.GetLastPosition()
            self.output.SetStyle(pos0, pos1, wx.TextAttr(color, bgcol, sfont))
        self.output.SetInsertionPoint(self.output.GetLastPosition())
        self.output.Refresh()

    def show_subframe(self, name, frameclass):
        shown = False
        if name in self.subframes:
            try:
                self.subframes[name].Raise()
                shown = True
            except:
                del self.subframes[name]
        if not shown:
            self.subframes[name] = frameclass(self, scandb=self.scandb)

    def onBuildPosScan(self, event=None):
        self.show_subframe('buildposmacro', PosScanMacroBuilder)

    def onBuildPosXRD(self, event=None):
        self.show_subframe('buildxrdsmacro', PosXRDMacroBuilder)

    def onCommonCommands(self, evt=None):
        self.show_subframe('commands', CommonCommandsFrame)        

    def onCommonCommandsAdmin(self, evt=None):
        self.show_subframe('commands_admin', CommonCommandsAdminFrame)        

    def onReadMacro(self, event=None):
        wcard = 'Scan files (*.lar)|*.lar|All files (*.*)|*.*'
        fname = FileOpen(self, "Read Macro from File",
                         default_file='macro.lar',
                         wildcard=wcard)
        if fname is not None:
            self.ReadMacroFile(fname)

    def ReadMacroFile(self, fname):
        if os.path.exists(fname):
            try:
                text = open(fname, 'r').read()
            except:
                logging.exception('could not read MacroFile %s' % fname)
            finally:
                self.editor.SetValue(text)
                self.editor.SetInsertionPoint(len(text)-2)

    def onSaveMacro(self, event=None):
        wcard = 'Scan files (*.lar)|*.lar|All files (*.*)|*.*'
        fname = FileSave(self, 'Save Macro to File',
                         default_file='macro.lar', wildcard=wcard)
        fname = os.path.join(os.getcwd(), fname)
        if fname is not None:
            if os.path.exists(fname):
                ret = popup(self, "Overwrite Macro File '%s'?" % fname,
                            "Really Overwrite Macro File?",
                            style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION)
                if ret != wx.ID_YES:
                    return
            self.SaveMacroFile(fname)

    def SaveMacroFile(self, fname):
        try:
            fh = open(fname, 'w')
            fh.write('%s\n' % self.editor.GetValue())
            fh.close()
        except:
            print('could not save MacroFile %s' % fname)

    def onStart(self, event=None):
        now = time.time()
        if (now - self.last_start_request) < 5.0:
            print( "double clicked start?")
            return
        self.last_start_request = now
        self.start_btn.Disable()
        lines = self.editor.GetValue().split('\n')
        self.scandb.set_info('request_pause',  1)

        for lin in lines:
            if '#' in lin:
                icom = lin.index('#')
                lin = lin[:icom]
            lin = lin.strip()
            if len(lin) > 0:
                self.scandb.add_command(lin)
        self.scandb.commit()
        self.scandb.set_info('request_abort',  0)
        self.scandb.set_info('request_pause',  0)

    def onPause(self, event=None):
        self.scandb.set_info('request_pause', 1)
        self.scandb.commit()
        self.pause_btn.Disable()
        self.start_btn.Disable()
        self.resume_btn.SetBackgroundColour("#D1D122")

    def onResume(self, event=None):
        self.scandb.set_info('request_pause', 0)
        self.scandb.commit()
        self.pause_btn.Enable()
        fg = self.pause_btn.GetBackgroundColour()
        self.resume_btn.SetBackgroundColour(fg)


    def onAbort(self, event=None):
        self.scandb.set_info('request_abort', 1)
        self.scandb.commit()
        time.sleep(1.0)

    def onCancelAll(self, event=None):
        self.onPause()
        self.scandb.set_info('request_abort', 1)
        self.scandb.cancel_remaining_commands()
        time.sleep(1.0)
        self.onResume()

    def onRestartServer(self, event=None):
        self.onPause()
        self.scandb.cancel_remaining_commands()
        self.onAbort()
        time.sleep(0.5)
        self.onResume()
        print(" on restart server ")
        epv = self.scandb.get_info('epics_status_prefix', default=None)
        if epv is not None:
            shutdownpv = epics.PV(epv + 'Shutdown')
            time.sleep(.1)
            print("Shutdown PV ", shutdownpv)
            shutdownpv.put(1)

    def onClose(self, event=None):
        self.SaveMacroFile(AUTOSAVE_FILE)
        self._stimer.Stop()

        time.sleep(0.25)
        self.input.SaveHistory(self.histfile)
        time.sleep(0.25)
        self.Destroy()
