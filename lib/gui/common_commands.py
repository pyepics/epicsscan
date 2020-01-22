#!/usr/bin/env python
"""
Common Commands Panel
"""
import os
import time
import subprocess
import wx
import wx.lib.scrolledpanel as scrolled

import numpy as np

from .gui_utils import (SimpleText, FloatCtrl, Closure, HyperText,
                        pack, add_choice, add_button,  check)

from ..scandb import InstrumentDB
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

if os.name == 'nt':
    EDITOR = 'C:/Program Files/Notepad++/notepad++.exe'
    LINESYN = '-n'
else:
    EDITOR = os.getenv('EDITOR', 'nano')
    LINESYN = '+'

class CommonCommandsAdminFrame(wx.Frame):
    """Manage Display of Common Commands from the Common_Commands Table
    """
    def __init__(self, parent, scandb, pos=(-1, -1), size=(750, 725), _larch=None):
        self.parent = parent
        self.scandb = scandb
        self._larch = parent.parent._larch
        self._larch.load_macros()
        self.macros = parent.parent._larch.get_macros()

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
        sizer.Add(SimpleText(panel, 'Arguments Hints', size=(250, -1),
                             style=labstyle, font=font12),
                  (0, 3), (1, 1), labstyle)

        sizer.Add(wx.StaticLine(panel, size=(625, 3),
                                style=wx.LI_HORIZONTAL|wx.GROW), (1, 0), (1, 5))

        irow = 2
        self.wids  = {}
        self.cmds = {}
        for icmd, cmd in enumerate(self.scandb.get_common_commands()):
            self.cmds[cmd.name] = (cmd.show, cmd.display_order, cmd.args)
            text = HyperText(panel, cmd.name, size=(195, -1), style=labstyle,
                             action=self.onCommand)
            text.SetFont(font11)

            macsig, macdoc, macobj = self.macros.get(cmd.name, (None, None, None))
            if macobj is not None:
                tip = " %s:\n%s line %d" % (macsig, macobj.__file__, macobj.lineno)
                text.SetToolTip(tip)
                
            
            display = check(panel, default=(cmd.show==1), label='', size=(100, -1))
            zorder = FloatCtrl(panel, value=cmd.display_order, minval=0,
                               maxval=1000000, precision=0, size=(75, -1))
            argstxt = wx.TextCtrl(panel, value=cmd.args, size=(300, -1))
            self.wids[cmd.name] = (display, zorder, argstxt)

            sizer.Add(text,    (irow, 0), (1, 1), labstyle, 2)
            sizer.Add(display, (irow, 1), (1, 1), labstyle, 2)
            sizer.Add(zorder,  (irow, 2), (1, 1), labstyle, 2)
            sizer.Add(argstxt, (irow, 3), (1, 1), labstyle, 2)
            irow += 1

        sizer.Add(wx.StaticLine(panel, size=(625, 3),
                                style=wx.LI_HORIZONTAL|wx.GROW), (irow, 0), (1, 5))
        irow += 1
        sizer.Add(add_button(panel, "Save Changes", size=(120, -1),
                             action=self.onOK),
                  (irow, 0), (1, 1))
        sizer.Add(add_button(panel, "Done", size=(120, -1),
                             action=self.onDone),
                  (irow, 1), (1, 1))

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
        macsig, macdoc, macobj = self.macros.get(label, (None, None, None))
        if macobj is None:
            return
        path, lineno = os.path.normpath(macobj.__file__), macobj.lineno
        subprocess.Popen([EDITOR, '%s%d'  % (LINESYN, lineno), path])                                   
                                   
        
    def onOK(self, event=None):
        for wname, wids in self.wids.items():
            show, order, args = [w.GetValue() for w in wids]
            cshow, corder, cargs = self.cmds[wname]
            vals = {}
            if show != cshow:
                vals['show'] = {True:1, False:0}[show]
            if order != corder:
                vals['display_order'] = order
            if args != cargs:
                vals['args'] = args

            if len(vals) > 0:
                self.scandb.update_where('common_commands',
                                         {'name': wname}, vals)
        self.scandb.commit()

    def onDone(self, event=None):
        self.Destroy()


class CommonCommandsFrame(wx.Frame):
    """Edit/Manage/Execute Common Commands from the
    Common_Commands Table
    """
    def __init__(self, parent, scandb, pos=(-1, -1), size=(700, 625), _larch=None):
        self.parent = parent
        self.scandb = scandb
        self.instdb = InstrumentDB(scandb)
        self._larch = parent.parent._larch
        self._larch.load_macros()
        macros = parent.parent._larch.get_macros()
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
                  (0, 1), (1, 5), labstyle)

        sizer.Add(wx.StaticLine(panel, size=(625, 3),
                                style=wx.LI_HORIZONTAL|wx.GROW), (1, 0), (1, 5))

        irow = 2
        self.wids  = {}
        self.scandb.commit()
        self.commands = self.scandb.get_common_commands()

        for icmd, cmd in enumerate(self.commands):
            if cmd.show == 0:
                continue
            macsig, macdoc, macobj = macros.get(cmd.name, (None, None, None))
            hlink = HyperText(panel, cmd.name, size=(195, -1),
                              style=labstyle, action=self.onCommand)
            hlink.SetFont(font11)
            if macdoc is None or len(macdoc) < 1:
                macdoc = cmd.notes
            if macsig is None:
                macsig = "%s()" % cmd.name
            tip = " %s:\n%s" % (macsig, macdoc)
            hlink.SetToolTip(tip)
            sizer.Add(hlink, (irow, 0), (1, 1), labstyle, 2)
            args = cmd.args.split('|') + ['']*10
            _wids = [macsig]
            opts = dict(size=(175, -1))
            for i in range(5):
                arg = args[i].strip()
                if arg in ('', None):
                    break
                label, arg = arg.split(':')
                if arg == '':
                    arg = SimpleText(panel, '', size=(125, -1))
                elif arg.startswith('float'):
                    dval, dmin, dmax, dprec = [float(x) for x in arg[5:].split(',')]
                    arg = FloatCtrl(panel, value=dval, precision=dprec,
                                    minval=dmin, maxval=dmax, **opts)
                elif arg.startswith('string'):
                    arg = wx.TextCtrl(panel, value=arg[6:].strip(), **opts)

                elif arg.startswith('enum'):
                    arg = add_choice(panel, arg[4:].split(','), default=0, **opts)
                elif arg.startswith('edge'):
                    arg = add_choice(panel, EDGE_LIST, default=0, **opts)
                elif arg.startswith('atsym'):
                    arg = add_choice(panel, ELEM_LIST, default=25, **opts)
                elif arg.startswith('inst_'):
                    poslist = list(reversed(self.instdb.get_positionlist(arg[5:])))
                    arg = add_choice(panel, poslist, default=0, **opts)
                pname = SimpleText(panel, "%s=" % label, size=(75,-1))
                sizer.Add(pname,  (irow, 2*i+1), (1, 1), labstyle, 2)
                sizer.Add(arg,    (irow, 2*i+2), (1, 1), labstyle, 2)
                _wids.append((label, arg))
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
        macsig = self.wids[label][0]
        for pname, wid in self.wids[label][1:]:
            val = None
            if hasattr(wid, 'GetValue'):
                val = str(wid.GetValue())
            elif hasattr(wid, 'GetStringSelection'):
                val = wid.GetStringSelection()
            if val is not None:
                try:
                    val = float(val)
                except:
                    val = repr(val)
                args.append("%s=%s" % (pname, val)
)
        cmd = "%s(%s)\n" % (label, ', '.join(args))
        self.parent.editor.AppendText(cmd)
