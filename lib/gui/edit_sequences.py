
import sys
import time
from datetime import datetime, timedelta
import wx
import wx.lib.scrolledpanel as scrolled

from ..ordereddict import OrderedDict
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

ACTIONS = ('Enable', 'Skip')

def tfmt(dt):
    return dt.strftime("%d/%b %H:%M:%S")

class SequencesFrame(wx.Frame) :
    """Edit/Manage/Run/View Sequences"""
    colLabels = (('ID',          50),
                 ('Status',      75),
                 ('Command',    375),
                 ('Requested',  125),
                 ('Modified',   125),
                 )

    def __init__(self, parent, pos=(-1, -1), size=(750, 275), _larch=None):
        self.parent = parent
        self.scandb = parent.scandb

        style    = wx.DEFAULT_FRAME_STYLE|wx.TAB_TRAVERSAL
        labstyle  = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
        rlabstyle = wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
        tstyle    = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL

        self.Font10=wx.Font(10, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        titlefont = wx.Font(13, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")

        wx.Frame.__init__(self, None, -1, 
                          'Epics Scanning: Command Sequence',  size=size)

        self.SetFont(self.Font10)

        spanel = scrolled.ScrolledPanel(self, size=(725, 325))
        self.colors = GUIColors()
        spanel.SetBackgroundColour(self.colors.bg)
        self.cmdlist = dv.DataViewListCtrl(spanel,
                                        style=dv.DV_VERT_RULES|dv.DV_ROW_LINES|dv.DV_SINGLE)

        self.cmdlist.SetMinSize((725, 250))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.cmdlist, 1, wx.ALIGN_LEFT|wx.ALL|wx.GROW)
        pack(spanel, sizer)
        
        spanel.SetupScrolling()

        bpanel = wx.Panel(self)
        bsizer = wx.BoxSizer(wx.HORIZONTAL)
        b1 = add_button(bpanel, label='Cancel Selected',  action=self.onCancel)
        b2 = add_button(bpanel, label='Abort Current',    action=self.onAbort)
        b3 = add_button(bpanel, label='Abort All',        action=self.onAbortAll)
        # b4 = add_button(bpanel, label='Show Details',     action=self.onShow)
        b5 = add_button(bpanel, label='Done',             action=self.onDone)

        bsizer.Add(b1)
        bsizer.Add(b2)
        bsizer.Add(b3)
        # bsizer.Add(b4)
        bsizer.Add(b5)
        pack(bpanel, bsizer)

        for b in (b1, b2, b3, b4, b5): b.Disable()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(spanel, 1, wx.GROW|wx.ALL, 1)
        mainsizer.Add(bpanel, 0, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)
        self.Show()
        self.Raise()

        self.make_titles()
        self.utimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.fill_rows, self.utimer)
        self.utimer.Start(10000)
        self.fill_rows()
        self.Show()
        self.Raise()

    def make_titles(self):
        for icol, dat in enumerate(self.colLabels):
            title, width = dat
            self.cmdlist.AppendTextColumn(title, width=width)
            col = self.cmdlist.Columns[icol]
            col.Sortable = True
            col.Alignment = wx.ALIGN_LEFT

    def fill_rows(self, event=None, **kws):
        self.cmdlist.DeleteAllItems()
        self.command_data = {}
        yesterday = datetime.now() - timedelta(hours=24)

        for cmd in self.scandb.get_commands(requested_since=yesterday):
            self.command_data[cmd.id] = cmd
            cmdid  = "%i" % cmd.id
            status = self.scandb.status_names[cmd.status_id]
            rtime  = tfmt(cmd.request_time)
            mtime  = tfmt(cmd.modify_time)
            cmdstr = cmd.command
            if (cmd.arguments not in (None, '') and
                cmd.output_file not in (None, '')):
                cmdstr = "%s('%s', '%s')" % (cmdstr, cmd.arguments, cmd.output_file)
            self.cmdlist.AppendItem((cmdid, status, cmdstr, rtime, mtime))

    def onCancel(self, event=None):
        print 'onCancel '
        if self.cmdlist.HasSelection():
            row  = self.cmdlist.GetSelectedRow()
            print 'selection ', row
            print 'cmd id ', self.cmdlist.GetStore().GetValueByRow(row, 0)

    def onAbort(self, event=None):
        print 'onAbort '
        if self.cmdlist.HasSelection():
            row  = self.cmdlist.GetSelectedRow()
            print 'selection ', row
            print 'cmd id ', self.cmdlist.GetStore().GetValueByRow(row, 0)

    def onAbortAll(self, event=None):
        print 'onAbort All '
        if self.cmdlist.HasSelection():
            row  = self.cmdlist.GetSelectedRow()
            print 'selection ', row
            print 'cmd id ', self.cmdlist.GetStore().GetValueByRow(row, 0)

    def onShow(self, event=None):
        print 'onshow '
        if self.cmdlist.HasSelection():
            row  = self.cmdlist.GetSelectedRow()
            print 'selection ', row
            print 'cmd id ', self.cmdlist.GetStore().GetValueByRow(row, 0)


    def onDone(self, event=None):
        self.parent.Destroy()
