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

DVSTYLE = dv.DV_VERT_RULES|dv.DV_ROW_LINES|dv.DV_MULTIPLE

def cmp(a, b):
    return (a>b)-(b<a)

def tfmt(dt):
    return dt.strftime("%b-%d %H:%M")

class ScanSequenceModel(dv.DataViewIndexListModel):
    def __init__(self, scandb):
        dv.DataViewIndexListModel.__init__(self, 0)
        self.scandb = scandb
        self.commands = {}
        self.data = []
        self.read_data()

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
        self.Reset(len(self.data))            

    def cancel_item(self, item):
        cmd_id = int(self.GetValue(item, 4))
        self.scandb.cancel_command(cmd_id)

    def insert_before(self, item, cmdstring):
        cmd_id = int(self.GetValue(item, 4))
        status = self.GetValue(item, 1)
        if status != 'requested':
            print('can only insert before requested commands')
            return
        runorder = self.commands[cmd_id].run_order
        previous = None
        prun = -1e23
        for cid, cmd in self.commands.items():
            if cmd.run_order > prun and cmd.run_order < runorder:
                prun = cmd.run_order
                previous = cmd
        if previous is not None:
            if (runorder - prun) > 1:
                new_runorder = runorder - 1

            self.scandb.add_command(cmdstring)
            self.scandb.commit()
            time.sleep(0.1)
            recent = datetime.now() - timedelta(seconds=15)
            cmds = self.scandb.get_commands(requested_since=recent)
            cmdid = -1
            if len(cmds) > 0:
                cmdid = cmds[-1].id
            if cmdid > 0:
                self.scandb.set_command_run_order(new_runorder, cmdid)
            self.scandb.commit()
        self.read_data()
        
    def move_item(self, item, direction='up'):
        cmd_id = int(self.GetValue(item, 4))
        status = self.GetValue(item, 1)
        if status != 'requested':
            print('can only move requested commands')
            return
        runorder = self.commands[cmd_id].run_order
        other = None
        if direction == 'up':
            o = -1e23
            for cid, cmd in self.commands.items():
                if cmd.run_order > o and cmd.run_order < runorder:
                    o = cmd.run_order
                    other = cmd
        else:
            o = 1e23
            for cid, cmd in self.commands.items():
                if cmd.run_order < o and cmd.run_order > runorder:
                    o = cmd.run_order
                    other = cmd
        if other is not None:
            cmd = self.commands[cmd_id]
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
        if status == 'finished':
            attr.SetColour('#222222')
            attr.SetBold(False)
            return True
        elif status == 'aborted':
            attr.SetColour('#880000')
            attr.SetBold(False)
            return True
        elif status == 'canceled':
            attr.SetColour('#880000')
            attr.SetBold(False)
            return True
        elif status in ('running'):
            attr.SetColour('#008833')
            attr.SetBackgroundColour('#FFFFDD')            
            attr.SetBold(True)
            return True
        else:
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

    def __init__(self, parent, scandb, pos=(-1, -1), size=(850, 400), _larch=None):
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
        spanel = scrolled.ScrolledPanel(self, size=(850, 425))
        self.colors = GUIColors()
        spanel.SetBackgroundColour(self.colors.bg)
        self.dvc = dv.DataViewCtrl(spanel, style=DVSTYLE)
        self.dvc.SetMinSize((825, 250))

        self.model = ScanSequenceModel(self.scandb)
        self.dvc.AssociateModel(self.model)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.dvc, 1, wx.ALIGN_LEFT|wx.ALL|wx.GROW)
        pack(spanel, sizer)

        spanel.SetupScrolling()

        bpan = wx.Panel(self)
        bsiz = wx.BoxSizer(wx.HORIZONTAL)
        bsiz.Add(add_button(bpan, label='Abort Command',      action=self.onAbort))
        bsiz.Add(add_button(bpan, label='Cancel All',         action=self.onCancelAll))
        bsiz.Add(add_button(bpan, label='Cancel Selected',    action=self.onCancelSelected))
        bsiz.Add(add_button(bpan, label='Move Selected Up',   action=self.onMoveUp))
        bsiz.Add(add_button(bpan, label='Move Selected Down', action=self.onMoveDown))
        pack(bpan, bsiz)

        npan = wx.Panel(self)
        nsiz = wx.BoxSizer(wx.HORIZONTAL)
        self.cmd_insert = wx.TextCtrl(npan, value='<new command>', size=(400, -1))
        nsiz.Add(add_button(npan, label='Insert Before Selected:', action=self.onInsert))
        nsiz.Add(self.cmd_insert)
        pack(npan, nsiz)
        
        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(spanel, 1, wx.GROW|wx.ALL, 1)
        mainsizer.Add(bpan, 0, wx.GROW|wx.ALL, 1)
        mainsizer.Add(npan, 0, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)

        for icol, dat in enumerate((('Command',      500),
                                    ('Status',       100),
                                    ('Requested',    100),
                                    ('Last Updated', 100),
                                    ('ID',            75))):
            title, width = dat
            self.dvc.AppendTextColumn(title, icol, width=width)
            col = self.dvc.Columns[icol]
            col.Sortable = title != 'Command'
            col.Alignment = wx.ALIGN_LEFT
        self.dvc.EnsureVisible(self.model.GetItem(len(self.model.data)-1))

        self.Bind(wx.EVT_CLOSE, self.onClose)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onTimer, self.timer)
        self.timer.Start(900)
        self.Show()
        self.Raise()

    def onClose(self, event=None):
        self.timer.Stop()
        time.sleep(1.0)
        self.Destroy()

    def onTimer(self, event=None, **kws):
        now = time.monotonic()
        status = self.scandb.get_info('scan_status')

        recent = datetime.now() - timedelta(minutes=1)
        cmds = self.scandb.get_commands(requested_since=recent)
        cmdid = -1
        if len(cmds) > 0:
            cmdid = cmds[-1].id
        if cmdid < 0:
            cmdid  = int(self.scandb.get_info('current_command_id'))
        
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
            
    def onInsert(self, event=None):
        if self.dvc.HasSelection():
            val = self.cmd_insert.GetValue().strip()
            if len(val) > 0 and not (val.startswith('<') and val.endswith('>')):
                self.model.insert_before(self.dvc.GetSelection(), val)
            val = self.cmd_insert.SetValue('<new command>')
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
        self.model.read_data()
        self.Refresh()
        self.last_refresh = time.monotonic()
        self.dvc.EnsureVisible(self.model.GetItem(len(self.model.data)-1))

    def onDone(self, event=None):
        self.parent.Destroy()
