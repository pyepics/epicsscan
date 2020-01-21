#!/usr/bin/env python
"""
Common Commands Panel
"""
import time
import json
from functools import partial
import wx
import wx.lib.scrolledpanel as scrolled

import numpy as np
import epics
from epics.wx import EpicsFunction, PVText, PVStaticText

from .gui_utils import (SimpleText, FloatCtrl, Closure, HyperText,
                        pack, add_choice, add_button,  check)

from ..utils import normalize_pvname, atGSECARS

CEN = wx.ALIGN_CENTER|wx.ALIGN_CENTER_VERTICAL
LEFT = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL
RIGHT = wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL
LCEN  = wx.ALIGN_CENTER_VERTICAL|wx.ALIGN_LEFT
RCEN  = wx.ALIGN_CENTER_VERTICAL|wx.ALIGN_RIGHT
CCEN  = wx.ALIGN_CENTER_VERTICAL|wx.ALIGN_CENTER

LINWID = 700
# from ..scan_panels import ELEM_LIST
EDGE_LIST = ('K', 'L3', 'L2', 'L1', 'M5')
ELEM_LIST = ('H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na',
             'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar', 'K', 'Ca', 'Sc', 'Ti',
             'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge',
             'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo',
             'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te',
             'I', 'Xe', 'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm',
             'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Hf',
             'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb',
             'Bi', 'Po', 'At', 'Rn', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U',
             'Np', 'Pu', 'Am', 'Cm', 'Bk', 'Cf')


class CommonCommandsAdminFrame(wx.Frame):
    """Manage Display of Common Commands from the Common_Commands Table
    """
    def __init__(self, parent, scandb, pos=(-1, -1), size=(700, 625), _larch=None):
        self.parent = parent
        self.scandb = scandb

        labstyle  = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
        font11 = wx.Font(11, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        font12 = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")

        wx.Frame.__init__(self, None, -1,
                          'Epics Scanning: Common Commands Admin Page',  size=size)

        panel = scrolled.ScrolledPanel(self, size=size)
        panel.SetMinSize(size)
        self.SetFont(font11)

        sizer = wx.GridBagSizer(2, 2)
        
        sizer.Add(SimpleText(panel, 'Command Name', size=(200, -1),
                             style=labstyle, font=font12),
                  (0, 0), (1, 1), labstyle)
        sizer.Add(SimpleText(panel, 'Display?', size=(125, -1),
                             style=labstyle, font=font12),
                  (0, 1), (1, 1), labstyle)
        sizer.Add(SimpleText(panel, 'Order ', size=(125, -1),
                             style=labstyle, font=font12),
                  (0, 2), (1, 1), labstyle)
        sizer.Add(SimpleText(panel, 'Edit Hint and Arguments', size=(250, -1),
                             style=labstyle, font=font12),
                  (0, 3), (1, 1), labstyle)

        sizer.Add(wx.StaticLine(panel, size=(625, 3),
                                style=wx.LI_HORIZONTAL|wx.GROW), (1, 0), (1, 5))
        
        irow = 2
        self.wids  = {}
        self.commands = self.scandb.get_common_commands()
        for icmd, cmd in enumerate(self.commands):
            print(icmd, cmd)
            text = SimpleText(panel, cmd.name, size=(195, -1), style=labstyle)
            text.SetFont(font11)
            text.SetToolTip(cmd.notes)

            display = check(panel, default=(cmd.show==1), label='', size=(100, -1))
            zorder = FloatCtrl(panel, value=cmd.display_order, minval=0,
                               maxval=1000000, precision=1, size=(100, -1))
            editbtn = add_button(panel, "Edit", size=(120, -1),
                                 action=partial(self.onEditCommand, cmd=cmd.name))
            
            self.wids[cmd.name] = (display, zorder, editbtn)
            
            sizer.Add(text,    (irow, 0), (1, 1), labstyle, 2)
            sizer.Add(display, (irow, 1), (1, 1), labstyle, 2)
            sizer.Add(zorder,  (irow, 2), (1, 1), labstyle, 2)
            sizer.Add(editbtn, (irow, 3), (1, 1), labstyle, 2)
            irow += 1

        sizer.Add(wx.StaticLine(panel, size=(625, 3),
                                style=wx.LI_HORIZONTAL|wx.GROW), (irow, 0), (1, 5))
        irow += 1
        sizer.Add(add_button(panel, "OK", size=(120, -1),  action=self.onOK),
                  (irow, 0), (1, 2))

        pack(panel, sizer)
        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)
        self.Show()
        self.Raise()

    def onOK(self, event=None):
        print("admin commands OK")

    def onEditCommand(self, event=None, cmd=None):
        print("edit command ", cmd, self.wids[cmd])

class CommonCommandsFrame(wx.Frame):
    """Edit/Manage/Execute Common Commands from the
    Common_Commands Table
    """
    def __init__(self, parent, scandb, pos=(-1, -1), size=(700, 625), _larch=None):
        self.parent = parent
        self.scandb = scandb

        labstyle  = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
        font11 = wx.Font(11, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        font12 = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")

        wx.Frame.__init__(self, None, -1,
                          'Epics Scanning: Common Commands',  size=size)

        panel = scrolled.ScrolledPanel(self, size=size)
        panel.SetMinSize(size)
        self.SetFont(font11)

        sizer = wx.GridBagSizer(2, 2)
        
        sizer.Add(SimpleText(panel, 'Command Name', size=(200, -1),
                             style=labstyle, font=font12),
                  (0, 0), (1, 1), labstyle)
        sizer.Add(SimpleText(panel, 'Arguments', size=(200, -1),
                             style=labstyle, font=font12),
                  (0, 1), (1, 3), labstyle)

        sizer.Add(wx.StaticLine(panel, size=(625, 3),
                                style=wx.LI_HORIZONTAL|wx.GROW), (1, 0), (1, 5))
        
        irow = 2
        self.wids  = {}
        self.commands = self.scandb.get_common_commands()
        for icmd, cmd in enumerate(self.commands):
            hlink = HyperText(panel, cmd.name, size=(195, -1),
                              style=labstyle, action=self.onCommand)
            hlink.SetFont(font11)
            hlink.SetToolTip(cmd.notes)
            sizer.Add(hlink, (irow, 0), (1, 1), labstyle, 2)
            args = cmd.args.split('|') + ['']*10
            _wids = []
            opts = dict(size=(125, -1))
            for i in range(4):
                arg = args[i].strip()
                if arg == '':
                    arg = SimpleText(panel, '', **opts)
                elif arg.startswith('float_'):
                    dval, dmin, dmax, dprec = [float(x) for x in arg[6:].split(',')]
                    arg = FloatCtrl(panel, value=dval, precision=dprec,
                                    minval=dmin, maxval=dmax, **opts)
                elif arg.startswith('enum_'):
                    arg = add_choice(panel, arg[5:].split(','), default=0, **opts)
                elif arg.startswith('edge'):
                    arg = add_choice(panel, EDGE_LIST, default=0, **opts)
                elif arg.startswith('atsym'):
                    arg = add_choice(panel, ELEM_LIST, default=25, **opts)
                sizer.Add(arg,  (irow, i+1), (1, 1), labstyle, 2)
                _wids.append(arg)
            self.wids[cmd.name] = _wids
            irow += 1

        sizer.Add(wx.StaticLine(panel, size=(625, 3),
                                style=wx.LI_HORIZONTAL|wx.GROW), (irow, 0), (1, 5))
        pack(panel, sizer)
        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)
        self.Show()
        self.Raise()

    def onCommand(self, event=None, label=None):
        if label is None:
            return
        args = []
        for wid in self.wids[label]:
            val = None
            if hasattr(wid, 'GetValue'):
                val = str(wid.GetValue())
            elif hasattr(wid, 'GetStringSelection'):
                val = wid.GetStringSelection()
            if val is not None:
                try:
                    tval = float(val)
                except:
                    val = "'%s'" % val
                args.append(val)
        cmd = "%s(%s)\n" % (label, ', '.join(args))
        self.parent.editor.AppendText(cmd)
