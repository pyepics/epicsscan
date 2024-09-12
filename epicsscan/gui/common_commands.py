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

from .gui_utils import (SimpleText, FloatCtrl, HyperText,
                        pack, add_choice, add_button,  check, CEN, LEFT, RIGHT)

from ..scandb import InstrumentDB
from ..utils import normalize_pvname

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
    def __init__(self, parent, scandb=None, pos=(-1, -1), size=(750, 725), mkernel=None):
        self.parent = parent
        self.scandb = parent.scandb if scandb is None else scandb
        self.mkernel = parent.mkernel if mkernel is None else mkernel
        self.mkernel.load_macros()
        self.macros = self.mkernel.get_macros()

        labstyle = LEFT|wx.ALL
        font11 = wx.Font(11, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        font12 = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")

        wx.Frame.__init__(self, None, -1,
                          'Epics Scanning: Common Commands Admin Page',  size=size)

        panel = scrolled.ScrolledPanel(self, size=size)
        panel.SetMinSize(size)
        self.SetFont(font11)
        self.SetBackgroundColour('#F0F0E8')

        sizer = wx.GridBagSizer(1, 1)
        irow = 1
        sizer.Add(SimpleText(panel,
                             'WARNING: Consult Beamline Staff Before Making Changes',
                             size=(600, -1),
                             style=labstyle, font=font12),
                  (irow, 0), (1, 5), labstyle)

        irow += 2
        sizer.Add(SimpleText(panel, 'Command Name', size=(200, -1),
                             style=labstyle, font=font12),
                  (irow, 0), (1, 1), labstyle)
        sizer.Add(SimpleText(panel, 'Display?', size=(125, -1),
                             style=labstyle, font=font12),
                  (irow, 1), (1, 1), labstyle)
        sizer.Add(SimpleText(panel, 'Order ', size=(125, -1),
                             style=labstyle, font=font12),
                  (irow, 2), (1, 1), labstyle)
        sizer.Add(SimpleText(panel, 'Arguments Hints', size=(250, -1),
                             style=labstyle, font=font12),
                  (irow, 3), (1, 1), labstyle)

        irow += 1
        sizer.Add(wx.StaticLine(panel, size=(625, 3),
                                style=wx.LI_HORIZONTAL|wx.GROW), (irow, 0), (1, 5))

        irow += 1
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

            sizer.Add(text,    (irow, 0), (1, 1), labstyle, 1)
            sizer.Add(display, (irow, 1), (1, 1), labstyle, 1)
            sizer.Add(zorder,  (irow, 2), (1, 1), labstyle, 1)
            sizer.Add(argstxt, (irow, 3), (1, 1), labstyle, 1)
            sizer.Add(wx.StaticLine(panel, size=(700, 1), style=wx.LI_HORIZONTAL|wx.GROW),
                      (irow+1, 0), (1, 5))
            irow += 2

        self.newcmd_order = FloatCtrl(panel, value=1000, minval=0,
                                        maxval=1000000, precision=0, size=(75, -1))
        self.newcmd_args = wx.TextCtrl(panel, value='', size=(300, -1))
        self.newcmd_name = wx.TextCtrl(panel, value='', size=(300, -1))

        irow += 1
        sizer.Add(SimpleText(panel, "Add new command (must be defined):",
                             size=(500, -1)),
                  (irow, 0), (1, 4), labstyle, 1)
        irow += 1
        sizer.Add(SimpleText(panel, "Name:", size=(175, -1), style=labstyle),
                  (irow, 0), (1, 1), labstyle, 1)
        sizer.Add(self.newcmd_name, (irow, 1), (1, 3), labstyle, 1)
        irow += 1
        sizer.Add(SimpleText(panel, "Arguments:", size=(175, -1), style=labstyle),
                  (irow, 0), (1, 1), labstyle, 1)
        sizer.Add(self.newcmd_args, (irow, 1), (1, 3), labstyle, 1)
        irow += 1
        sizer.Add(SimpleText(panel, "Order:", size=(175, -1), style=labstyle),
                  (irow, 0), (1, 1), labstyle, 1)
        sizer.Add(self.newcmd_order, (irow, 1), (1, 3), labstyle, 1)

        irow += 1
        sizer.Add(wx.StaticLine(panel, size=(700, 2),
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
                self.scandb.update('common_commands', where={'name': wname}, **vals)

        newcmd_name = self.newcmd_name.GetValue().strip()
        if len(newcmd_name) > 0 and newcmd_name not in self.cmds:
            newcmd_args  = self.newcmd_args.GetValue().strip()
            newcmd_order = self.newcmd_order.GetValue()
            self.scandb.add_common_commands(newcmd_name, newcmd_args, show=True,
                                            display_order=newcmd_order)
        self.scandb.add_command("load_macros()")

    def onDone(self, event=None):
        self.Destroy()


class CommonCommandsFrame(wx.Frame):
    """Edit/Manage/Execute Common Commands from the
    Common_Commands Table
    """
    def __init__(self, parent, scandb=None, pos=(-1, -1), size=(700, 625), mkernel=None):
        self.parent = parent
        self.scandb = parent.scandb if scandb is None else scandb
        self.instdb = InstrumentDB(scandb)

        self.mkernel = parent.mkernel if mkernel is None else mkernel
        self.mkernel.load_macros()
        macros = self.mkernel.get_macros()

        labstyle  = LEFT|wx.ALL
        font11 = wx.Font(11, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        font12 = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")

        wx.Frame.__init__(self, None, -1,
                          'Epics Scanning: Common Commands',  size=size)

        panel = scrolled.ScrolledPanel(self, size=size)
        panel.SetMinSize(size)
        self.SetFont(font11)
        self.SetBackgroundColour('#F0F0E8')

        sizer = wx.GridBagSizer(1, 1)

        irow = 0
        sizer.Add(SimpleText(panel, 'Click on Command Name to Add to Macro Text',
                             size=(400, -1), style=labstyle, font=font12),
                  (irow, 0), (1, 4), labstyle)
        irow += 1
        sizer.Add(SimpleText(panel, 'Command Name', size=(200, -1),
                             style=labstyle, font=font12), (irow, 0), (1, 1), labstyle)
        sizer.Add(SimpleText(panel, 'Arguments', size=(200, -1),
                             style=labstyle, font=font12), (irow, 1), (1, 5), labstyle)

        irow += 1
        sizer.Add(wx.StaticLine(panel, size=(700, 1), style=wx.LI_HORIZONTAL|wx.GROW), (irow, 0), (1, 5))

        irow += 1
        self.wids  = {}
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
            opts = dict(size=(150, -1))
            for i in range(5):
                arg = args[i].strip()
                if arg in ('', None):
                    break
                label, arg = arg.split(':')
                if label == 'use_signature':
                    arg = ''
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
                if label == 'use_signature':
                    pname = SimpleText(panel, "Note: will insert example as comment", size=(250,-1))
                    sizer.Add(pname,  (irow, 2*i+1), (1, 2), labstyle, 2)
                else:
                    pname = SimpleText(panel, "%s=" % label, size=(75,-1), style=LEFT)
                    sizer.Add(pname,  (irow, 2*i+1), (1, 1), labstyle, 2)
                    sizer.Add(arg,    (irow, 2*i+2), (1, 1), labstyle, 2)
                _wids.append((label, arg))
            self.wids[cmd.name] = _wids
            sizer.Add(wx.StaticLine(panel, size=(700, 1), style=wx.LI_HORIZONTAL|wx.GROW),
                      (irow+1, 0), (1, 5))
            irow += 2

        sizer.Add(wx.StaticLine(panel, size=(700, 3),
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
        editor = self.parent.get_editor()
        if editor is None:
            return

        args = []
        macsig = self.wids[label][0]
        cmd = "%s()" % (label)
        for pname, wid in self.wids[label][1:]:
            val = None
            if pname == 'use_signature':
                cmd = '#%s' % macsig
            else:
                if hasattr(wid, 'GetValue'):
                    val = str(wid.GetValue())
                elif hasattr(wid, 'GetStringSelection'):
                    val = wid.GetStringSelection()
                if val is not None:
                    try:
                        val = float(val)
                    except:
                        val = repr(val)
                    args.append("%s=%s" % (pname, val))
                cmd = "%s(%s)" % (label, ', '.join(args))
        try:
            editor.AppendText("%s\n" % cmd)
        except:
            print("No editor ?")
