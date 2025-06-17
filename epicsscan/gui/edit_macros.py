import os
import sys
import time
import logging
from sqlalchemy.sql import func as sqlfunc
from sqlalchemy import text
from datetime import datetime, timedelta
import wx
import wx.lib.agw.flatnotebook as flat_nb
import wx.lib.scrolledpanel as scrolled
from wx.lib.editor import Editor
import wx.dataview as dv

from collections import OrderedDict
from epics import Motor
from .gui_utils import (GUIColors, set_font_with_children, YesNo, check,
                        add_menu, add_button, add_choice, pack, SimpleText,
                        FileOpen, FileSave, popup, FloatCtrl, HLine,
                        FRAMESTYLE, Font, FNB_STYLE, LEFT, RIGHT, CEN, DVSTYLE, cmp)

from .common_commands  import CommonCommandsFrame, CommonCommandsAdminFrame
from .edit_sequences   import ScanSequenceFrame
from ..scandb import InstrumentDB

#import larch
# from larch.wxlib.readlinetextctrl import ReadlineTextCtrl


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
        self.tab = mtab = scandb.tables['messages']
        # get last ID
        rows = scandb.execute(mtab.select().order_by(mtab.c.id)).fetchall()
        self.last_id = 0
        if len(rows) > 0:
            self.last_id = rows[-1].id

    def get_new_messages(self):
        try:
            query = self.tab.select().where(
                      self.tab.c.id > self.last_id).order_by(self.tab.c.id)
        except TypeError:
            return [None]
        rows = self.scandb.execute(query).fetchall()
        if len(rows) > 0:
            self.last_id = rows[-1].id
        return rows

def get_positionlist(scandb, instrument=None):
    """get list of positions for and instrument"""
    iname = instrument
    if iname is None:
        iname = scandb.get_info('samplestage_instrument', 'SampleStage')
    return InstrumentDB(scandb).get_positionlist(iname, reverse=True)

class PositionCommandModel(dv.DataViewIndexListModel):
    def __init__(self, scandb):
        dv.DataViewIndexListModel.__init__(self, 0)
        self.scandb = scandb
        self.data = []
        self.nscans = 1
        self.detdist = -1
        self.posvals = {}
        self.read_data()

    def read_data(self):
        self.data = []
        for pos in get_positionlist(self.scandb):
            use, nscan, ddist = True, f"{int(self.nscans)}", f"{self.detdist:.1f}"
            if pos in self.posvals:
                use, nscan, ddist = self.posvals[pos]
            self.data.append([pos, use, nscan, ddist])
            self.posvals[pos] = [use, nscan, ddist]
        self.Reset(len(self.data))

    def set_nscans(self, val=1):
        self.nscans = val
        if isinstance(val, (float, int)):
            val = "%s" % int(val)
        for posname, dat in self.posvals.items():
            dat[1] = val
        self.read_data()

    def set_detdist(self, val=-1):
        self.detdist = val
        if isinstance(val, (float, int)):
            val = "%.1f" % float(val)
        for posname, dat in self.posvals.items():
            dat[2] = val
        self.read_data()

    def select_all(self, use=True):
        for posname, dat in self.posvals.items():
            dat[0] = use
        self.read_data()

    def select_above(self, item):
        itemname = self.GetValue(item, 0)
        use = True
        for posname, _use, _nx, _dd in self.data:
            self.posvals[posname][0] = use
            if posname == itemname:
                use = not use
        self.read_data()

    def GetColumnType(self, col):
        if col == 1:
            return "bool"
        return "string"

    def GetValueByRow(self, row, col):
        return self.data[row][col]

    def SetValueByRow(self, value, row, col):
        self.data[row][col] = value
        return True

    def GetColumnCount(self):
        return len(self.data[0])

    def GetCount(self):
        return len(self.data)

    def Compare(self, item1, item2, col, ascending):
        """help for sorting data"""
        if not ascending: # swap sort order?
            item2, item1 = item1, item2
        row1 = self.GetRow(item1)
        row2 = self.GetRow(item2)
        if col == 1:
            return cmp(int(self.data[row1][col]), int(self.data[row2][col]))
        else:
            return cmp(self.data[row1][col], self.data[row2][col])

    def DeleteRows(self, rows):
        rows = list(rows)
        rows.sort(reverse=True)
        for row in rows:
            del self.data[row]
            self.RowDeleted(row)

    def AddRow(self, value):
        self.data.append(value)
        self.RowAppended()

class PositionCommandFrame(wx.Frame) :
    """Edit/Manage/Run/View Sequences"""
    def __init__(self, parent, scandb, pos=(-1, -1), size=(675, 550), mkernel=None):
        self.parent = parent
        self.scandb = scandb

        detdist_motor = None
        _pos = scandb.get_info('experiment_xrfdet_posname', None)
        if _pos is not None:
            _row = scandb.get_positioner(_pos)
            if _row is not None:
                detdist_motor = Motor(_row.drivepv)
        self.detdist_motor = detdist_motor

        self.last_refresh = time.monotonic() - 100.0
        self.Font10=wx.Font(10, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        titlefont = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")

        wx.Frame.__init__(self, None, -1,
                          title="Data Collection Commands at Saved Positions",
                          style=FRAMESTYLE, size=size)

        self.dvc = dv.DataViewCtrl(self, style=DVSTYLE)
        self.dvc.SetMinSize((600, 350))

        self.SetFont(self.Font10)
        panel = wx.Panel(self, size=(650, -1))
        panel.SetBackgroundColour(GUIColors.bg)


        self.model = PositionCommandModel(self.scandb)
        self.dvc.AssociateModel(self.model)

        self.datatype = add_choice(panel, ['Scan', 'XRD'], size=(125, -1),
                                   action=self.onDataType)
        self.datatype.SetSelection(0)

        self.scantype = add_choice(panel,  ('Maps', 'XAFS', 'Linear'),
                                   size=(125, -1),  action = self.onScanType)
        self.scantype.SetSelection(1)

        self.scanname = add_choice(panel,  [], size=(250, -1))
        self.xrdtime = FloatCtrl(panel, value=10, minval=0, maxval=50000, precision=1)
        self.xrdtime.Disable()

        self.nscans  = FloatCtrl(panel, value=1,  minval=1, maxval=500, precision=0,
                                 action=self.onNScans)

        self.use_detdist = check(panel, default=True, label='Set XRF Detector Distance',
                                 action=self.onUseDetDistance)

        if detdist_motor is None:
            self.detdist = FloatCtrl(panel, value=75, minval=0, maxval=500, precision=1)
            self.detdist.Disable()
            self.use_detdist.SetValue(False)

        else:
            self.detdist = FloatCtrl(panel, value=detdist_motor.drive,
                                     minval=detdist_motor.low_limit,
                                     maxval=detdist_motor.high_limit,
                                     precision=1, action=self.onDetDist)
            self.detdist.Enable()

        sizer = wx.GridBagSizer(2, 2)

        irow = 0
        sizer.Add(add_button(panel, label='Select None', size=(125, -1),
                             action=self.onSelNone),
                  (irow, 0), (1, 1), LEFT, 2)
        sizer.Add(add_button(panel, label='Select All', size=(125, -1),
                             action=self.onSelAll),
                  (irow, 1), (1, 1), LEFT, 2)
        sizer.Add(add_button(panel, label='Select All Above Highlighted', size=(250, -1),
                             action=self.onSelAbove),
                  (irow, 2), (1, 2), LEFT, 2)

        irow += 1
        sizer.Add(SimpleText(panel, 'Command Type:'), (irow, 0), (1, 1), LEFT, 2)
        sizer.Add(self.datatype,                      (irow, 1), (1, 1), LEFT, 2)
        sizer.Add(SimpleText(panel, 'XRD Time (sec):'), (irow, 2), (1, 1), LEFT, 2)
        sizer.Add(self.xrdtime,                       (irow, 3), (1, 1), LEFT, 2)

        irow += 1
        sizer.Add(SimpleText(panel, 'Scan Type:'),    (irow, 0), (1, 1), LEFT, 2)
        sizer.Add(self.scantype,                      (irow, 1), (1, 1), LEFT, 2)
        sizer.Add(SimpleText(panel, 'Scan Name:'),    (irow, 2), (1, 1), LEFT, 2)
        sizer.Add(self.scanname,                      (irow, 3), (1, 1), LEFT, 2)

        irow += 1
        sizer.Add(self.use_detdist,                     (irow, 0), (1, 2), LEFT, 2)
        sizer.Add(SimpleText(panel, 'Det Distance:'),   (irow, 2), (1, 1), LEFT, 2)
        sizer.Add(self.detdist,                         (irow, 3), (1, 1), LEFT, 2)

        irow += 1
        sizer.Add(add_button(panel, label='Add Commands', size=(250, -1),
                             action=self.onInsert),
                  (irow, 0), (1, 2), LEFT, 2)
        sizer.Add(SimpleText(panel, 'Default # Scans:'),  (irow, 2), (1, 1), LEFT, 2)
        sizer.Add(self.nscans,                           (irow, 3), (1, 1), LEFT, 2)

        pack(panel, sizer)

        for icol, dat in enumerate((('Position Name',  350, 'text'),
                                    ('Include',        100, 'bool'),
                                    ('# Scans',        100, 'text'),
                                    ('XRF Det Distance', 150, 'text'))):

            label, width, dtype = dat
            method = self.dvc.AppendTextColumn
            mode = dv.DATAVIEW_CELL_EDITABLE
            if dtype == 'bool':
                method = self.dvc.AppendToggleColumn
                mode = dv.DATAVIEW_CELL_ACTIVATABLE
            kws = {}
            if icol > 0:
                kws['mode'] = mode
            method(label, icol, width=width, **kws)
            c = self.dvc.Columns[icol]
            c.Alignment = wx.ALIGN_LEFT
            c.Sortable = False

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel,    0, LEFT|wx.GROW, 1)
        mainsizer.Add(self.dvc, 1, LEFT|wx.GROW, 1)

        pack(self, mainsizer)
        self.dvc.EnsureVisible(self.model.GetItem(0))

        self.Bind(wx.EVT_CLOSE, self.onClose)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onTimer, self.timer)
        self.timer.Start(5000)
        wx.CallAfter(self.onScanType)
        self.Show()
        self.Raise()

    def onDataType(self, event=None):
        name = self.datatype.GetStringSelection().lower()
        self.xrdtime.Enable(name=='xrd')
        self.scantype.Enable(name=='scan')
        self.scanname.Enable(name=='scan')

    def onScanType(self, event=None):
        sname = self.scantype.GetStringSelection().lower()
        scantype = 'linear'
        if 'xafs' in sname:
            scantype = 'xafs'
        elif 'map' in sname or 'slew' in sname:
            scantype = 'slew'
            self.nscans.SetValue(1)
        tab = self.scandb.tables['scandefs']
        q = tab.select().where(tab.c.type.ilike("%%%s%%" % scantype)).order_by('last_used_time')
        scannames = []
        for s in self.scandb.execute(q).fetchall():
            if not (s.name.startswith('__') and s.name.endswith('__')):
                scannames.append(s.name)
        scannames.reverse()
        self.scanname.Set(scannames)
        self.scanname.SetSelection(0)

    def onInsert(self, event=None):
        editor = self.parent.get_editor()
        if editor is None:
            return

        datatype = self.datatype.GetStringSelection()
        buff = ["#commands added at positions"]
        if datatype.lower().startswith('xrd'):
            xrdtime =  self.xrdtime.GetValue()
            command = "xrd_at(%s, t=%.1f)"
            for posname, use, nscans, ddist in reversed(self.model.data):
                if use:
                    buff.append(command % (repr(posname), xrdtime))
        else:
            scanname = self.scanname.GetStringSelection()
            command = "pos_scan({posname:s}, {scanname:s}, number={nscans:s}"
            if self.use_detdist.IsChecked():
                command = command + ", xrfdet_z={ddist:s}"
            command = command + ')'
            for posname, use, nscans, ddist in reversed(self.model.data):
                if use:
                    buff.append(command.format(posname=repr(posname),
                                               scanname=repr(scanname),
                                               nscans=nscans, ddist=ddist))
        buff.append("#\n")
        try:
            editor.AppendText("\n".join(buff))
        except:
            print("No editor?")

    def onNScans(self, value=None, event=None):
        self.model.set_nscans(value)

    def onDetDist(self, value=None, event=None, **kws):
        self.model.set_detdist(value)

    def onUseDetDistance(self, event=None):
        self.detdist.Enable(self.use_detdist.IsChecked() and self.detdist_motor is not None)

    def onSelAll(self, event=None):
        self.model.select_all(True)

    def onSelNone(self, event=None):
        self.model.select_all(False)

    def onSelAbove(self, event=None):
        if self.dvc.HasSelection():
            self.model.select_above(self.dvc.GetSelection())

    def onClose(self, event=None):
        self.timer.Stop()
        time.sleep(1.0)
        self.Destroy()

    def onTimer(self, event=None, **kws):
        now = time.monotonic()
        poslist = get_positionlist(self.scandb)
        if len(self.model.data) != len(poslist):
            self.update()

    def update(self):
        self.model.set_nscans(int(self.nscans.GetValue()))
        self.model.set_detdist(self.detdist.GetValue())
        self.model.read_data()
        self.Refresh()
        self.dvc.EnsureVisible(self.model.GetItem(0))

class CommandsPanel(scrolled.ScrolledPanel):
    output_colors = {'error_message': COLOR_ERR,
                     'scan_message':COLOR_OK}
    output_fields = ('error_message', 'scan_message')
    info_mapping = {'FileName': 'filename',
                    'Command': 'current_command',
                    'Status': 'scan_status',
                    'Progress': 'scan_progress',
                    'Time': 'heartbeat',
                    'Nqueue': 'n_command_queue',
                    }

    def __init__(self, parent, scandb=None, pvlist=None, title='Settings',
                 size=(760, 380), style=wx.GROW|wx.TAB_TRAVERSAL):

        self.scandb = scandb
        self.output_stats = {}
        self.last_heartbeat = LONG_AGO
        self.last_start_request = 0
        for key in self.output_fields:
            self.output_stats[key] = LONG_AGO

        scrolled.ScrolledPanel.__init__(self, parent, size=size,
                                        name='Macro', style=style)

        self.Font13 = wx.Font(13, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        self.Font12 = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        self.SetBackgroundColour(GUIColors.bg)
        self._initialized = False # used to shunt events while creating windows
        self.SetFont(Font(9))

        self.db_messages = ScanDBMessageQueue(self.scandb)

        # title row
        title = SimpleText(self, 'Commands and Macros',  font=Font(13),
                           size=(250, -1),
                           colour=GUIColors.title, style=LEFT)

        info_panel = self.make_info_panel()

        self.editor = wx.TextCtrl(self, -1, size=(675, 225),
                                  style=wx.TE_MULTILINE|wx.TE_RICH2)
        self.editor.SetBackgroundColour('#FFFFFF')
        text = """# Edit Macro text here\n#\n"""
        self.editor.SetValue(text)
        self.editor.SetInsertionPoint(len(text)-2)

        buttonpanel = wx.Panel(self)
        buttonpanel.SetBackgroundColour(GUIColors.bg)
        bsizer = wx.BoxSizer(wx.HORIZONTAL)
        self.start_btn  = add_button(buttonpanel, label='Submit',  action=self.onStart)
        self.pause_btn  = add_button(buttonpanel, label='Pause',  action=self.onPause)
        self.resume_btn = add_button(buttonpanel, label='Resume',  action=self.onResume)
        self.cancel_btn = add_button(buttonpanel, label='Cancel All', action=self.onCancelAll)
        bsizer.Add(self.start_btn)
        bsizer.Add(self.pause_btn)
        bsizer.Add(self.resume_btn)
        bsizer.Add(self.cancel_btn)
        pack(buttonpanel, bsizer)

        sfont = wx.Font(11,  wx.SWISS, wx.NORMAL, wx.BOLD, False)
        self.output = wx.TextCtrl(self, -1,  '## Output Buffer\n', size=(675, 225),
                                  style=wx.TE_MULTILINE|wx.TE_RICH|wx.TE_READONLY)
        self.output.CanCopy()
        self.output.SetInsertionPointEnd()
        self.output.SetDefaultStyle(wx.TextAttr('black', 'white', sfont))

        input_panel = self.make_input_panel()
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(title, 0, LEFT)
        sizer.Add(info_panel,  0, LEFT|wx.ALL)
        sizer.Add(self.editor, 1, LEFT|wx.GROW)
        sizer.Add(buttonpanel, 0, LEFT, 2)
        sizer.Add(self.output, 1, LEFT|wx.GROW)
        sizer.Add(input_panel, 0, LEFT|wx.GROW, 2)

        self.SetBackgroundColour(GUIColors.bg)
        self._stimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_info, self._stimer)
        self._stimer.Start(500)

        pack(self, sizer)

    def make_input_panel(self):
        panel = wx.Panel(self)
        panel.SetBackgroundColour(GUIColors.bg)
        self.prompt = wx.StaticText(panel, -1, 'Command>', size = (95,-1),
                                    style=RIGHT)
        self.input = wx.TextCtrl(panel, value='', size=(525, -1),
                                 style=wx.TE_LEFT|wx.TE_PROCESS_ENTER)

        self.hist_buff = []
        self.hist_mark = 0
        self.input.Bind(wx.EVT_TEXT_ENTER, self.onText)
        if sys.platform == 'darwin':
            self.input.Bind(wx.EVT_KEY_UP,  self.onChar)
        else:
            self.input.Bind(wx.EVT_CHAR,  self.onChar)

        sizer = wx.BoxSizer(wx.HORIZONTAL)

        sizer.Add(self.prompt,  0, wx.BOTTOM|wx.CENTER)
        sizer.Add(self.input,   1, wx.ALIGN_LEFT|wx.EXPAND)
        panel.SetSizer(sizer)
        sizer.Fit(panel)
        return panel

    def onChar(self, event=None):
        key = event.GetKeyCode()

        entry  = self.input.GetValue().strip()
        pos = self.input.GetSelection()
        ctrl = event.ControlDown()

        if key == wx.WXK_RETURN and len(entry) > 0:
            pass
        if key in (wx.WXK_UP, wx.WXK_DOWN):
            if key == wx.WXK_UP:
                self.hist_mark = max(0, self.hist_mark-1)
            else:
                self.hist_mark += 1
            try:
                wx.CallAfter(self.set_input_text, self.hist_buff[self.hist_mark])
            except IndexError:
                wx.CallAfter(self.set_input_text, '')
        event.Skip()

    def set_input_text(self, text):
        self.input.SetValue(text)
        self.input.SetFocus()
        self.input.SetInsertionPointEnd()

    def AddToHistory(self, text=''):
        for tline in text.split('\n'):
            if len(tline.strip()) > 0:
                self.hist_buff.append(tline)
                self.hist_mark = len(self.hist_buff)

    def make_info_panel(self):
        sizer = wx.GridBagSizer(2, 2)
        panel = wx.Panel(self)
        panel.SetBackgroundColour(GUIColors.bg)

        self.winfo = OrderedDict()

        opts1 = {'label':' '*250, 'colour': COLOR_OK, 'size': (600, -1), 'style': LEFT}
        opts2 = {'label':' '*50, 'colour': COLOR_OK, 'size': (175, -1), 'style': LEFT}
        self.winfo['FileName'] = SimpleText(panel, **opts1)
        self.winfo['Command']  = SimpleText(panel, **opts1)
        self.winfo['Progress'] = SimpleText(panel, **opts1)
        self.winfo['Status']   = SimpleText(panel, **opts2)
        self.winfo['Time']     = SimpleText(panel, **opts2)
        self.winfo['Nqueue']   = SimpleText(panel, **opts2)

        stat_label  = SimpleText(panel, "Status:", size=(90, -1), style=LEFT)
        time_label  = SimpleText(panel, "Time:"  , size=(90, -1), style=LEFT)
        ncmd_label  = SimpleText(panel, "Pending Commands:"  , size=(180, -1), style=LEFT)
        sizer.Add(stat_label,            (0, 0), (1, 1), LEFT, 1)
        sizer.Add(self.winfo['Status'],  (0, 1), (1, 1), LEFT, 1)
        sizer.Add(time_label,            (0, 2), (1, 1), LEFT, 1)
        sizer.Add(self.winfo['Time'],    (0, 3), (1, 1), LEFT, 1)
        sizer.Add(ncmd_label,            (0, 4), (1, 1), LEFT, 1)
        sizer.Add(self.winfo['Nqueue'],   (0, 5), (1, 1), LEFT, 1)

        irow = 1
        for attr in ('Command', 'FileName', 'Progress'):
            lab  = SimpleText(panel, "%s:" % attr, size=(90, -1), style=LEFT)
            sizer.Add(lab,               (irow, 0), (1, 1), LEFT, 1)
            sizer.Add(self.winfo[attr],  (irow, 1), (1, 6), LEFT, 1)
            irow += 1
        pack(panel, sizer)
        return panel

    def update_info(self, evt=None):
        paused = self.scandb.get_info('request_pause', as_bool=True)

        for key, attr in self.info_mapping.items():
            val = str(self.scandb.get_info(attr, '--'))
            if key in self.winfo:
                self.winfo[key].SetLabel(val)

        # move_to_macro_editor = """
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
        self.winfo['Time'].SetForegroundColour(col)

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


    def onText(self, event=None):
        text = event.GetString().strip()
        if len(text) < 1:
            return
        self.input.Clear()
        # self.input.AddToHistory(text)
        out = self.scandb.add_command(text)
        time.sleep(0.01)
        self.writeOutput(text)
        self.AddToHistory(text)

    def onPanelExposed(self, evt=None):
        pass

    def onPause(self, event=None):
        self.scandb.set_info('request_pause', 1)
        self.pause_btn.Disable()
        self.resume_btn.SetBackgroundColour("#D1D122")

    def onResume(self, event=None):
        self.scandb.set_info('request_pause', 0)
        self.pause_btn.Enable()
        fg = self.pause_btn.GetBackgroundColour()
        self.resume_btn.SetBackgroundColour(fg)

    def onAbort(self, event=None):
        self.scandb.set_info('request_abort', 1)
        time.sleep(1.0)

    def onCancelAll(self, event=None):
        self.onPause()
        self.scandb.set_info('request_abort', 1)
        self.scandb.cancel_remaining_commands()
        time.sleep(1.0)
        self.onResume()

    def onStart(self, event=None):
        now = time.time()
        if (now - self.last_start_request) < 5.0:
            print( "double clicked start?")
            return
        self.last_start_request = now
        # self.start_btn.Disable()
        lines = self.editor.GetValue().split('\n')
        self.scandb.set_info('request_pause',  1)
        out = ['# macro submitted  %s' % (time.ctime())]
        for lin in lines:
            if lin.startswith('#'):
                out.append(lin)
            else:
                out.append('#%s' % lin)

            lin = lin.split('#', 1)[0].strip()
            if len(lin) > 0:
                self.scandb.add_command(lin)
        self.scandb.set_info('request_abort',  0)
        self.scandb.set_info('request_pause',  0)

        out = '\n'.join(out)
        self.editor.SetValue(out)
        self.editor.SetInsertionPoint(len(out)-1)
