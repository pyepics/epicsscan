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

import wx.grid as gridlib

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

CommandRow = namedtuple('CommandRow', ('command', 'status', 'reqtime',
                                       'updatetime', 'order', 'id'))

DVSTYLE = dv.DV_VERT_RULES|dv.DV_ROW_LINES|dv.DV_MULTIPLE

def tfmt(dt):
    return dt.strftime("%b-%d %H:%M")

class SequencesFrame(wx.Frame) :
    """Edit/Manage/Run/View Sequences"""

    def __init__(self, parent, scandb, pos=(-1, -1), size=(800, 400), _larch=None):
        self.parent = parent
        self.scandb = scandb

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
        self.cmdlist = dv.DataViewListCtrl(spanel, style=DVSTYLE)
        self.cmdlist.SetMinSize((725, 250))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.cmdlist, 1, wx.ALIGN_LEFT|wx.ALL|wx.GROW)
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
        self.Show()
        self.Raise()

        self.make_titles()
        self.fill_rows()
        self.Show()
        self.Raise()

    def make_titles(self):
        cols = (('Command',      420),
                ('Status',       120),
                ('Requested',    120),
                ('Last Updated', 120),
                ('ID',            80))

        for icol, dat in enumerate(cols):
            title, width = dat
            self.cmdlist.AppendTextColumn(title, width=width)

            col = self.cmdlist.Columns[icol]
            col.Sortable = title != 'Command'
            col.Alignment = wx.ALIGN_LEFT

    def fill_rows(self, event=None, **kws):
        self.cmdlist.DeleteAllItems()
        self.commands = {}
        yesterday = datetime.now() - timedelta(hours=45)

        for cmd in self.scandb.get_commands(requested_since=yesterday):
            self.commands[cmd.id] = cmd
            status = self.scandb.status_names[cmd.status_id]
            rtime  = tfmt(cmd.request_time)
            mtime  = tfmt(cmd.modify_time)
            cmdstr = cmd.command
            self.cmdlist.AppendItem((cmd.command, status, rtime, mtime,
                                     repr(cmd.id)))

    def get_row(self, irow):
        return self.commands[int(self.cmdlist.GetValue(irow, 4))]

    def onMoveUp(self, event=None):
        if self.cmdlist.HasSelection():
            irow = self.cmdlist.GetSelectedRow()
            row = self.get_row(irow)
            prow = self.get_row(irow-1) if irow > 0 else None
            print("Move Up: ", row, prow)


    def onMoveDown(self, event=None):
        if self.cmdlist.HasSelection():
            irow = self.cmdlist.GetSelectedRow()
            row = self.get_row(irow)
            orow = self.get_row(irow+1) if irow < len(self.commands)-1 else None
            print("Move Down: ", row, orow)

    def onAbort(self, event=None):
        self.scandb.set_info('request_abort', 1)
        self.scandb.commit()
        time.sleep(1.0)


    def onCancelSelected(self, event=None):
        if self.cmdlist.HasSelection():
            row  = self.cmdlist.GetSelectedRow()

    def onCancelAll(self, event=None):
        self.scandb.cancel_remaining_commands()
        self.onAbort()

    def onRefresh(self, event=None):
        self.fill_rows()

    def onAbortOLD(self, event=None):
        if self.cmdlist.HasSelection():
            row  = self.cmdlist.GetSelectedRow()

    def onAbortAll(self, event=None):
        if self.cmdlist.HasSelection():
            row  = self.cmdlist.GetSelectedRow()

    def onShow(self, event=None):
        if self.cmdlist.HasSelection():
            row  = self.cmdlist.GetSelectedRow()

    def onDone(self, event=None):
        self.parent.Destroy()
