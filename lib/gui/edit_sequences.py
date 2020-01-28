import sys
import time
from datetime import datetime, timedelta
import wx
import wx.lib.scrolledpanel as scrolled

from collections import OrderedDict, namedtuple

from .gui_utils import (GUIColors, set_font_with_children, YesNo, popup,
                        add_button, pack, SimpleText, check, okcancel,
                        add_subtitle, Font, LCEN, CEN, RCEN, FRAMESTYLE)

RCEN |= wx.ALL
LCEN |= wx.ALL
CEN  |= wx.ALL

# import wx.grid as gridlib

import wx.dataview as dv

LEFT = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
CEN  = wx.ALIGN_CENTER|wx.ALIGN_CENTER_VERTICAL|wx.ALL

builtin_macros = """ (text = '<builtin>')
  name              arguments
  ca_put            'PVName:str, Value:str'
  ca_get            'PVName:str, OutputValue:str'
  do_scan           'ScanName:enum, OutputFile:str, Nrepeat:int'
  move_instrument   'InstName:enum, PosName:enum'
  move_sample       'SampleName:enum'
  scan_at           'ScanName:enum, SampleName:enum'
"""

def cmp(a, b): return (a>b)-(b<a)

CommandRow = namedtuple('CommandRow', ('command', 'status', 'reqtime',
                                       'updatetime', 'order', 'id'))

DVSTYLE = dv.DV_VERT_RULES|dv.DV_ROW_LINES|dv.DV_MULTIPLE

def tfmt(dt):
    return dt.strftime("%b-%d %H:%M")

class ScanSequenceModel(dv.DataViewIndexListModel):
    def __init__(self, scandb):
        self.scandb = scandb
        self.commands = {}
        self.data = []
        self.read_data()
        dv.DataViewIndexListModel.__init__(self, len(self.data))

    def read_data(self):
        yesterday = datetime.now() - timedelta(hours=24.5)
        self.data = []
        self.commands = {}
        for cmd in self.scandb.get_commands(requested_since=yesterday):
            self.commands[cmd.id] = cmd
            self.data.append((cmd.command,
                              self.scandb.status_names[cmd.status_id],
                              tfmt(cmd.request_time),
                              tfmt(cmd.modify_time),
                              repr(cmd.id)))

        print('read %d commands' % len(self.data))
        print('Last command : ', cmd.id, cmd)


    def cancel_item(self, item):
        cmd_id = int(self.GetValue(item, 4))
        self.scandb.cancel_command(cmd_id)

    def move_item(self, item, direction='up'):
        cmd_id = int(self.GetValue(item, 4))
        status = self.GetValue(item, 1)
        if status != 'requested':
            print('can only move requested commands')
            return
        runorder = self.command[cmd_id].run_order
        other = None
        if direction == 'up':
            o = -1e23
            for cid, cmd in commands.items():
                if cmd.run_order > o and cmd.run_order < runorder:
                    o = cmd.run_order
                    other = cmd
        else:
            o = 1e23
            for cid, cmd in commands.items():
                if cmd.run_order < o and cmd.run_order > runorder:
                    o = cmd.run_order
                    other = cmd
        if other is not None:
            cmd = self.command[cmd_id]
            print("Swap ", cmd, other)
            self.scandb.set_command_run_order(other.run_order, cmd.id)
            self.scandb.set_command_run_order(cmd.run_order, other.id)
            self.scandb.commit()
        self.read_data()

    def GetColumnType(self, col):
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

    def GetAttrByRow(self, row, col, attr):
        """set row/col attributes (color, etc)"""
        status = self.data[row][1]
        cname = self.data[row][0]
        # print("GettAttrByRow ", row, col, attr, status, cname, type(status))
        if status == 'finished':
            attr.SetColour('#222222')
            attr.SetBackgroundColour('#DDDD00')
            attr.SetBold(False)
            return True
        elif status == 'aborted':
            attr.SetColour('#880000')
            attr.SetBold(False)
            return True
        elif status == 'canceled':
            attr.SetColour('#880000')
            attr.SetBackgroundColour('#DDDD00')
            attr.SetBold(False)
            # attr.SetStrikethrough()
            return True
        elif status in ('running', 'starting'):
            attr.SetColour('#007733')
            attr.SetBold(True)
            return True
        elif status in ('requested', ):
            attr.SetColour('#000099')
            attr.SetBold(False)
            return True
        return False

    def Compare(self, item1, item2, col, ascending):
        """help for sorting data"""
        if not ascending: # swap sort order?
            item2, item1 = item1, item2
        row1 = self.GetRow(item1)
        row2 = self.GetRow(item2)
        if col == 0:
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

class ScanSequenceFrame(wx.Frame) :
    """Edit/Manage/Run/View Sequences"""

    def __init__(self, parent, scandb, pos=(-1, -1), size=(800, 400), _larch=None):
        self.parent = parent
        self.scandb = scandb
        self.last_refresh = time.monotonic() - 100.0
        self.cmdid = 0
        self.cmdstatus = ''

        style    = wx.DEFAULT_FRAME_STYLE|wx.TAB_TRAVERSAL
        labstyle  = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
        rlabstyle = wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
        tstyle    = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL

        self.Font10=wx.Font(10, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        titlefont = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")

        wx.Frame.__init__(self, None, -1,
                          'Epics Scanning: Command Sequence',  size=size)

        self.SetFont(self.Font10)
        spanel = scrolled.ScrolledPanel(self, size=(800, 425))
        self.colors = GUIColors()
        spanel.SetBackgroundColour(self.colors.bg)
        self.dvc = dv.DataViewCtrl(spanel, style=DVSTYLE)
        self.dvc.SetMinSize((725, 250))

        self.model = ScanSequenceModel(self.scandb)
        self.dvc.AssociateModel(self.model)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.dvc, 1, wx.ALIGN_LEFT|wx.ALL|wx.GROW)
        pack(spanel, sizer)

        spanel.SetupScrolling()

        bpan = wx.Panel(self)
        bsiz = wx.BoxSizer(wx.HORIZONTAL)
        bsiz.Add(add_button(bpan, label='Abort Current Command', action=self.onAbort))
        bsiz.Add(add_button(bpan, label='Cancel Selected',    action=self.onCancelSelected))
        bsiz.Add(add_button(bpan, label='Cancel All',         action=self.onCancelAll))
        bsiz.Add(add_button(bpan, label='Move Selected Up',   action=self.onMoveUp))
        bsiz.Add(add_button(bpan, label='Move Selected Down', action=self.onMoveDown))
        bsiz.Add(add_button(bpan, label='Refresh',            action=self.onRefresh))

        pack(bpan, bsiz)

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(spanel, 1, wx.GROW|wx.ALL, 1)
        mainsizer.Add(bpan, 0, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)

        for icol, dat in enumerate((('Command',      420),
                                    ('Status',       120),
                                    ('Requested',    120),
                                    ('Last Updated', 120),
                                    ('ID',            80))):
            title, width = dat
            self.dvc.AppendTextColumn(title, icol, width=width)
            col = self.dvc.Columns[icol]
            col.Sortable = title != 'Command'
            col.Alignment = wx.ALIGN_LEFT
        self.dvc.EnsureVisible(self.model.GetItem(len(self.model.data)-1))

        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onTimer, self.timer)
        # self.timer.Start(250)
        self.Show()
        self.Raise()

    def onTimer(self, event=None, **kws):
        now = time.monotonic()
        cmdid  = int(self.scandb.get_info('current_command_id'))
        status = self.scandb.get_info('scan_status')

        if ((cmdid != self.cmdid) or
            (status != self.cmdstatus) or
            ((now - self.last_refresh) > 300)):
            self.onRefresh()
            self.cmdid = cmdid
            self.cmdstatus = status

    def onMoveUp(self, event=None):
        if self.dvc.HasSelection():
            self.model.move_item(self.dvc.GetSelection(), direction='up')
            self.Refresh()

    def onMoveDown(self, event=None):
        if self.dvc.HasSelection():
            self.model.move_item(self.dvc.GetSelection(), direction='down')
            self.Refresh()

    def onCancelSelected(self, event=None):
        if self.dvc.HasSelection():
            self.model.cancel_item(self.dvc.GetSelection())
            self.Refresh()

    def onCancelAll(self, event=None):
        self.scandb.cancel_remaining_commands()
        self.onAbort()

    def onAbort(self, event=None):
        self.scandb.set_info('request_abort', 1)
        self.scandb.commit()
        time.sleep(1.0)

    def onRefresh(self, event=None):
        print("Refresh: " , time.ctime())
        self.model.read_data()
        self.Refresh()
        self.last_refresh = time.monotonic()

    def onDone(self, event=None):
        self.parent.Destroy()
