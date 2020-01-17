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
                        pack, add_choice, hms, check)

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


class CommonCommandsFrame(wx.Frame):
    """Edit/Manage/Execute Common Commands from the
    Common_Commands Table
    """
    colLabels = (('Request ',     75, 'button'),
                 ('Command',     150, None),
                 ('Argument 1',  125, None), 
                 ('Argument 2',  125, None),
                 ('Description', 275, None))
    
    def __init__(self, parent, pos=(-1, -1), size=(650, 475), _larch=None):
        self.parent = parent
        style    = wx.DEFAULT_FRAME_STYLE|wx.TAB_TRAVERSAL
        labstyle  = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
        rlabstyle = wx.ALIGN_RIGHT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
        tstyle    = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL

        font11 = wx.Font(11, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        titlefont = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")

        wx.Frame.__init__(self, None, -1,
                          'Epics Scanning: Common Commands',  size=size)

        panel = scrolled.ScrolledPanel(self, size=(650, 400))
        panel.SetMinSize((650, 450))
        self.SetFont(font11)

        sizer = wx.GridBagSizer(3, 3)
        
        for icol, title, width in ((0, 'Add', 75),
                                   (1, 'Command Name', 200),
                                   (2, 'Argument 1', 175), 
                                   (3, 'Argument 2', 175)):
            sizer.Add(SimpleText(panel, title, size=(width, -1), style=labstyle,
                                 font=titlefont), (0, icol), (1, 1), labstyle)
        sizer.Add(wx.StaticLine(panel, size=(650, 3),
                                style=wx.LI_HORIZONTAL|wx.GROW), (1, 0), (1, 5))
        
        irow = 2
        self.wids  = []
        self.commands = self.scandb.get_common_commands()
        for icmd, cmd in enumerate(self.commands):
            dobtn = wx.Button(panel, label='Add', size=(75, -1))
            dobtn.Bind(wx.EVT_BUTTON, partial(self.onButton, index=icmd))
            name = SimpleText(panel, cmd.name, size=(175, -1), style=labstyle)
            name.SetToolTip(cmd.notes)

            sizer.Add(dobtn, (irow, 0), (1, 1), labstyle, 2)
            sizer.Add(name,  (irow, 1), (1, 1), labstyle, 2)
            
            args = cmd.args.split('|') + ['', '']
            _wids = []
            opts = dict(size=(150, -1))
            for i in range(2):
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
                sizer.Add(arg,  (irow, 2+i), (1, 1), labstyle, 2)
                _wids.append(arg)
            self.wids.append(_wids)
            irow += 1

        sizer.Add(wx.StaticLine(panel, size=(650, 3),
                                style=wx.LI_HORIZONTAL|wx.GROW), (irow, 0), (1, 5))
            
        
        pack(panel, sizer)

        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)

        self.Show()
        self.Raise()

    def onButton(self, evt=None, index=-1):
        cmd = self.commands[index].name
        args = []
        for wid in self.wids[index]:
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
        cmd = "%s(%s)" % (cmd, ', '.join(args))
        print("Add Command: ", cmd)
        # self.parent.scandb.add_command(cmd)
        
