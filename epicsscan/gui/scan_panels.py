#!/usr/bin/env python
"""
GUI Panels for setting up positioners for different scan types.
Current scan types:
    Linear Scans
    Mesh Scans (2d maps)
    XAFS Scans
    Fly Scans (optional)
"""
import time
import json
from functools import partial
import wx
import wx.lib.scrolledpanel as scrolled
import numpy as np
import epics
from epics.wx import EpicsFunction, PVText, PVStaticText

from .gui_utils import (GUIColors, SimpleText, FloatCtrl, HyperText,
                        pack, add_choice, hms, check, LEFT, RIGHT,
                        CEN, add_button)

from ..utils import normalize_pvname
from ..xafs_scan import etok, ktoe, XAFS_Scan
from ..scan import StepScan
from ..positioner import Positioner
from ..detectors import Counter

# Max number of points in scan
MAX_NPTS = 8000

LINWID = 700
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


class GenericScanPanel(scrolled.ScrolledPanel):
    __name__ = 'genericScan'

    def __init__(self, parent, scandb=None, pvlist=None, macro_kernel=None,
                 title='?', size=(800, 425), style=wx.GROW|wx.TAB_TRAVERSAL):
        self.scantype = 'linear'
        self.scandb = scandb
        self.pvlist = pvlist
        self.mkernel = macro_kernel
        self.parent = parent
        scrolled.ScrolledPanel.__init__(self, parent,
                                        size=size, style=style,
                                        name=self.__name__)
        self.Font13 = wx.Font(13, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        self.Font12 = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        self.sizer = wx.GridBagSizer(2, 2)
        self.SetBackgroundColour(GUIColors.bg)
        self.scantime = -1.0
        self.get_positioners()
        self._initialized = False # used to shunt events while creating windows

    def get_positioners(self):
        self.pospvs = {'None': ('', '')}
        self.poslist = ['None']
        for pos in self.scandb.get_positioners():
            self.poslist.append(pos.name)
            self.pospvs[pos.name] = (pos.drivepv, pos.readpv)

        self.slewlist = []
        for pos in self.scandb.get_slewpositioners():
            self.slewlist.append(pos.name)

    def load_scandict(self, scan):
        """meant to be overwritten"""
        pass

    def update_positioners(self):
        """meant to be overwritten"""
        self.get_positioners()

    def hline(self, size=(700, 3)):
        return wx.StaticLine(self, size=size,
                             style=wx.LI_HORIZONTAL|wx.GROW)

    def onSetNScans(self,  value=1, **kws):
        wid = getattr(self, 'nscans', None)
        if wid is not None:
            nscans   = int(self.nscans.GetValue())
            self.scandb.set_info('nscans', nscans)

    def add_startscan(self, with_nscans=True):
        # add bottom panel with "Start Scan")
        bpanel = wx.Panel(self)
        bpanel.SetBackgroundColour(GUIColors.bg)
        bsizer = wx.GridBagSizer(2, 2)
        self.nscans = None
        self.filename = wx.TextCtrl(bpanel, -1,
                                    self.scandb.get_info('filename', default=''),
                                    size=(450, -1))

        self.user_comms = wx.TextCtrl(bpanel, -1, "", style=wx.TE_MULTILINE,
                                      size=(450, 75))

        ir = 0
        if with_nscans:
            self.nscans = FloatCtrl(bpanel, precision=0, value=1,
                                    minval=1, maxval=99999, size=(45, -1),
                                    action=self.onSetNScans)
            bsizer.Add(SimpleText(bpanel, "Number of Scans:"), (ir, 0), (1, 1), LEFT)
            bsizer.Add(self.nscans,     (ir, 1), (1, 1), LEFT, 2)
            ir += 1

        bsizer.Add(SimpleText(bpanel, "File Name:"), (ir, 0),   (1, 1), LEFT)
        bsizer.Add(self.filename,                    (ir, 1),   (1, 3), LEFT)

        ir += 1
        bsizer.Add(SimpleText(bpanel, "Comments:"),  (ir, 0), (1, 1), LEFT)
        bsizer.Add(self.user_comms,                  (ir, 1), (2, 3), LEFT)

        ir += 2

        start_btn = add_button(bpanel, "Start Scan", size=(120, -1),
                               action=partial(self.parent.onCtrlScan, cmd='Start'))

        abort_btn = add_button(bpanel, "Abort Scan", size=(120, -1),
                               action=partial(self.parent.onCtrlScan, cmd='Abort'))


        pause_btn = add_button(bpanel, "Pause Scan", size=(120, -1),
                               action=partial(self.parent.onCtrlScan, cmd='Pause'))

        resume_btn = add_button(bpanel, "Resume Scan", size=(120, -1),
                               action=partial(self.parent.onCtrlScan, cmd='Resume'))

        bsizer.Add(start_btn,                  (ir, 0), (1, 1), LEFT)
        bsizer.Add(abort_btn,                  (ir, 1), (1, 1), LEFT)
        bsizer.Add(pause_btn,                  (ir, 2), (1, 1), LEFT)
        bsizer.Add(resume_btn,                 (ir, 3), (1, 1), LEFT)

        bpanel.SetSizer(bsizer)
        bsizer.Fit(bpanel)
        return bpanel


    def set_scan_message(self, text, timeout=30):
        self.scan_message.SetLabel(text)
        self.scanmsg_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.remove_scan_message, self.scanmsg_timer)
        self.scanmsg_timer.Start(int(timeout*1000.0))

    def remove_scan_message(self, evt=None):
        self.scan_message.SetLabel(" ")
        self.scanmsg_timer.Stop()

    def setStepNpts(self, wids, label, fix_npts=False):
        "set step / npts for start/stop/step/npts list of widgets"
        start = wids[0].GetValue()
        stop  = wids[1].GetValue()
        step = wids[2].GetValue()
        if label == 'npts' or fix_npts:
            npts = max(2, wids[3].GetValue())
        else:
            try:
                npts = max(2, 1 + int(0.1 + abs(stop-start)/abs(step)))
            except ZeroDivisionError:
                npts = 3
        npts = min(npts, MAX_NPTS)
        wids[2].SetValue((stop-start)/(npts-1), act=False)
        if not fix_npts:
            try:
                wids[3].SetValue(npts, act=False)
            except AttributeError:
                pass

    def setScanTime(self):
        "set estimated scan time"
        dtime = (float(self.dwelltime.GetValue()) +
                 float(self.scandb.get_info('pos_settle_time', default=0)) +
                 float(self.scandb.get_info('det_settle_time', default=0)))
        for p in self.pos_settings:
            if hasattr(p[6], 'GetValue'):
                dtime *= float(p[6].GetValue())
        self.scantime = dtime
        self.est_time.SetLabel(hms(dtime))

    def top_widgets(self, title, dwell_prec=3, dwell_value=1, with_absrel=True):
        self.absrel_value = 0
        self.absrel = add_choice(self, ('Absolute', 'Relative'),
                                 size=(100, -1),
                                 action = self.onAbsRel)
        self.absrel.SetSelection(self.absrel_value)
        if not with_absrel:
            self.absrel.Disable()

        self.dwelltime = FloatCtrl(self, precision=dwell_prec,
                                   value=dwell_value,
                                   act_on_losefocus=True,
                                   minval=0, size=(80, -1),
                                   action=partial(self.onVal,
                                                  label='dwelltime'))

        self.est_time  = SimpleText(self, '  00:00:00  ')
        titlex =  SimpleText(self, " %s" % title, style=LEFT,
                             size=(250, -1),
                             font=self.Font13, colour='#880000')
        alabel = SimpleText(self, ' Mode: ', size=(60, -1))
        dlabel = SimpleText(self, ' Time/Point (sec):')
        tlabel = SimpleText(self, ' Estimated Scan Time:  ')

        sizer = self.sizer

        sizer.Add(titlex,         (0, 0), (1, 3), LEFT,  3)
        sizer.Add(tlabel,         (0, 4), (1, 2), RIGHT, 3)
        sizer.Add(self.est_time,  (0, 6), (1, 2), CEN,   3)
        sizer.Add(alabel,         (1, 0), (1, 1), LEFT,  3)
        sizer.Add(self.absrel,    (1, 1), (1, 1), LEFT,  3)
        sizer.Add(dlabel,         (1, 2), (1, 2), RIGHT, 3)
        sizer.Add(self.dwelltime, (1, 4), (1, 2), LEFT,  3)
        # return next row for sizer
        return 2

    def StartStopStepNpts(self, i, with_npts=True, initvals=(-1,1,1,3), precision=4):
        s0, s1, ds, ns = initvals
        opts = {'precision': precision, 'act_on_losefocus': True, 'size': (85, -1)}
        start = FloatCtrl(self, action=partial(self.onVal, index=i, label='start'),
                          value=s0, **opts)
        stop  = FloatCtrl(self, action=partial(self.onVal, index=i, label='stop'),
                          value=s1, **opts)
        step  = FloatCtrl(self, action=partial(self.onVal, index=i, label='step'),
                          value=ds, **opts)
        if with_npts:
            opts['size'] = (75, -1)
            opts['precision'] = 0
            npts  = FloatCtrl(self, action=partial(self.onVal, index=i, label='npts'),
                              value=ns,  **opts)
        else:
            npts  = wx.StaticText(self, -1, size=(85, -1), label=' ')
        return start, stop, step, npts

    def onVal(self, index=0, label=None, value=None, **kws):
        pass

    @EpicsFunction
    def update_position_from_pv(self, index, name=None):
        if not hasattr(self, 'pos_settings'):
            return
        if name is None:
            name = self.pos_settings[index][0].GetStringSelection()

        wids = self.pos_settings[index]
        # clear current widgets for this row
        wid2 = wids[2]
        wid2pv = wids[2].pv
        this_wid = wid2.GetId()
        if wid2pv is not None:
            keys = list(wid2pv.callbacks.keys())
            for icb in keys:
                ccb = wid2pv.callbacks[icb]
                if ccb[1].get('wid', None) == this_wid:
                    try:
                        wid2pv.remove_callback(index=icb)
                    except:
                        pass

        for i in (1, 2):
            wids[i].SetLabel('')
        if name == 'None':
            for i in (3, 4, 5, 6):
                wids[i].Disable()
            return
        for i in (3, 4, 5, 6):
            wids[i].Enable()

        try:
            pvnames = list(self.pospvs[name])
        except:
            return

        if len(pvnames[0]) < 1:
            return
        pvnames[0] = normalize_pvname(pvnames[0])
        pvnames[1] = normalize_pvname(pvnames[1])
        for pvn in pvnames:
            if pvn not in self.pvlist:
                self.pvlist[pvn] = epics.PV(pvn)
                time.sleep(0.01)
                self.pvlist[pvn].connect()

        unitspv = pvnames[1][:-4] + '.EGU'
        has_unitspv = unitspv in self.pvlist
        if not has_unitspv:
            self.pvlist[unitspv]  = epics.PV(unitspv)

        mpv  = self.pvlist[pvnames[1]]
        units = mpv.units
        if has_unitspv:
            units  = self.pvlist[unitspv].get()

        hlim = mpv.upper_disp_limit
        llim = mpv.lower_disp_limit
        if hlim == llim:
            hlim = llim = None
        if hasattr(self, 'absrel') and (1 == self.absrel.GetSelection()): # relative
            hlim = hlim - mpv.value
            llim = llim - mpv.value
        if units is None:
            units = ''
        wids[1].SetLabel(units)
        wids[2].SetPV(mpv)
        # wids[2].SetBackgroundColour(self.bgcol)
        for i in (3, 4):
            wids[i].SetMin(llim)
            wids[i].SetMax(hlim)
            wids[i].SetPrecision(mpv.precision)

    def onAbsRel(self, evt=None):
        "generic abs/rel"
        if evt.GetSelection() == self.absrel_value:
            return
        self.absrel_value = evt.GetSelection()
        for index, wids in enumerate(self.pos_settings):
            if wids[3].Enabled:
                try:
                    offset = float(wids[2].GetLabel())
                except:
                    offset = 0.0
                # now relative (was absolute)
                if 1 == self.absrel.GetSelection():
                    offset = -offset
                wids[3].SetMin(wids[3].GetMin() + offset)
                wids[3].SetMax(wids[3].GetMax() + offset)
                wids[4].SetMin(wids[4].GetMin() + offset)
                wids[4].SetMax(wids[4].GetMax() + offset)

                wids[3].SetValue(offset + wids[3].GetValue(), act=False)
                wids[4].SetValue(offset + wids[4].GetValue(), act=False)
                self.update_position_from_pv(index)

    def initialize_positions(self):
        if hasattr(self, 'pos_settings'):
            for index in range(len(self.pos_settings)):
                self.update_position_from_pv(index)

    def use_scandb(self, scandb):
        pass

    def generate_scan_positions(self):
        print('Def generate scan ', self.__name__)

class StepScanPanel(GenericScanPanel):
    """ Step Scan """
    __name__ = 'StepScan'

    def __init__(self, parent, **kws):
        GenericScanPanel.__init__(self, parent, **kws)
        self.scantype = 'linear'
        sizer = self.sizer
        ir = self.top_widgets('Linear Step Scan')

        sizer.Add(self.hline(), (ir, 0), (1, 8), LEFT)
        ir += 1
        for ic, txt in enumerate((" Role", " Positioner", " Units",
                                  " Current", " Start",
                                  " Stop", " Step", " Npts")):
            s  = CEN
            if txt == " Npts":
                s = LEFT
            sizer.Add(wx.StaticText(self, -1, label=txt),
                      (ir, ic), (1, 1), s, 2)

        self.pos_settings = []
        fsize = (95, -1)
        for i in range(3):
            lab = ' Follow'
            pchoices = self.poslist[:]
            idefault = 0
            if i == 0:
                lab = ' Lead'
                pchoices = pchoices[1:]
                idefault = 1
            pos = add_choice(self, pchoices, size=(100, -1),
                             action=partial(self.onPos, index=i))
            pos.SetSelection(idefault)
            role  = wx.StaticText(self, -1, label=lab)
            units = wx.StaticText(self, -1, label='', size=(40, -1),
                                  style=CEN)
            cur   = PVStaticText(self, pv=None, size=(100, -1),
                                 style=CEN)
            start, stop, step, npts = self.StartStopStepNpts(i, with_npts=(i==0))
            self.pos_settings.append((pos, units, cur, start, stop, step, npts))
            if i > 0:
                start.Disable()
                stop.Disable()
                step.Disable()
                npts.Disable()
            ir += 1
            sizer.Add(role,  (ir, 0), (1, 1), wx.ALL, 2)
            sizer.Add(pos,   (ir, 1), (1, 1), wx.ALL, 2)
            sizer.Add(units, (ir, 2), (1, 1), wx.ALL, 2)
            sizer.Add(cur,   (ir, 3), (1, 1), wx.ALL, 2)
            sizer.Add(start, (ir, 4), (1, 1), wx.ALL, 2)
            sizer.Add(stop,  (ir, 5), (1, 1), wx.ALL, 2)
            sizer.Add(step,  (ir, 6), (1, 1), wx.ALL, 2)
            sizer.Add(npts,  (ir, 7), (1, 1), wx.ALL, 2)

        bot_panel = self.add_startscan(with_nscans=True)

        self.scan_message = SimpleText(self, " ", style=LEFT, size=(500, -1),
                                       font=self.Font12, colour='#991111')

        ir +=1
        self.sizer.Add(self.scan_message, (ir,   0), (1, 8), LEFT)
        self.sizer.Add(self.hline(),      (ir+1, 0), (1, 8), LEFT)
        self.sizer.Add(bot_panel,         (ir+2, 0), (1, 8), LEFT|wx.ALL)

        pack(self, self.sizer)
        self.SetupScrolling()
        self._initialized = True
        self.update_position_from_pv(0)

    def load_scandict(self, scan):
        """load scan for linear scan from scan dictionary
        as stored in db, or passed to stepscan"""
        self.dwelltime.SetValue(scan['dwelltime'])
        if hasattr(self, 'absrel'):
            self.absrel.SetSelection(0)
        for i in (1, 2):
            pos, units, cur, start, stop, step, npts = self.pos_settings[i]
            pos.SetSelection(0)
            start.Disable()
            stop.Disable()
            step.Disable()
            npts.Disable()
            self.update_position_from_pv(i)

        for i, posdat in enumerate(scan['positioners']):
            pos, units, cur, start, stop, step, npts = self.pos_settings[i]
            pos.SetStringSelection(posdat[0])
            start.SetValue(posdat[2])
            stop.SetValue(posdat[3])
            if hasattr(npts, 'SetValue'):
                npts.SetValue(posdat[4])
            self.update_position_from_pv(i)

    def update_positioners(self):
        """meant to be overwritten"""
        self.get_positioners()
        for irow, row in enumerate(self.pos_settings):
            thispos = row[0]
            cur = thispos.GetStringSelection()
            thispos.Clear()
            if irow == 0:
                thispos.SetItems(self.poslist[1:])
            else:
                thispos.SetItems(self.poslist)
            if cur in self.poslist:
                thispos.SetStringSelection(cur)
            else:
                thispos.SetSelection(0)

    def onVal(self, index=0, label=None, value=None, **kws):
        if not self._initialized: return
        npts = self.pos_settings[0][6]
        wids = list(self.pos_settings[index][3:])

        if index == 0:
            self.setStepNpts(wids, label)
            for index, w in enumerate(self.pos_settings[1:]):
                if w[3].Enabled:
                    wids = list(w[3:])
                    wids[3] =  npts
                    self.setStepNpts(wids, label, fix_npts=True)
        else:
            wids[3] = npts
            self.setStepNpts(wids, label, fix_npts=True)
        self.setScanTime()

    def onPos(self, evt=None, index=0):
        self.update_position_from_pv(index)

    def use_scandb(self, scandb):
        self.get_positioners()
        if hasattr(self, 'pos_settings'):
            for i, wids in enumerate(self.pos_settings):
                a = wids[0].GetStringSelection()
                wids[0].Clear()
                #if i > 0: and 'None' not in self.poslist:
                #    poslist.insert(0, 'None')
                wids[0].SetItems(self.poslist)
                wids[0].SetStringSelection(a)

    def generate_scan_positions(self):
        "generate linear scan"
        s = {'type': 'linear',
             'dwelltime':  float(self.dwelltime.GetValue()),
             'scantime': self.scantime,
             'positioners': [],
             'filename': self.filename.GetValue(),
             'comments': self.user_comms.GetValue(),
             'nscans': 1
             }

        if self.nscans is not None:
            s['nscans'] = int(self.nscans.GetValue())

        is_relative = 0
        if hasattr(self, 'absrel'):
            is_relative =  self.absrel.GetSelection()

        for i, wids in enumerate(self.pos_settings):
            pos, u, cur, start, stop, dx, wnpts = wids
            if i == 0:
                npts = wnpts.GetValue()
            if start.Enabled:
                name = pos.GetStringSelection()
                pvnames = self.pospvs[name]
                p1 = start.GetValue()
                p2 = stop.GetValue()
                if is_relative:
                    try:
                        off = float(cur.GetLabel())
                    except:
                        off = 0
                    p1 += off
                    p2 += off
                s['positioners'].append((name, pvnames, p1, p2, npts))
        return s

class XAFSScanPanel(GenericScanPanel):
    """xafs  scan """
    __name__ = 'XAFSScan'
    edges_list = ('K', 'L3', 'L2', 'L1', 'M5')
    units_list = ('eV', u'1/\u212B')

    def __init__(self, parent, **kws):
        kws['size'] = (800, 425)
        GenericScanPanel.__init__(self, parent, **kws)
        self.scantype = 'xafs'
        self.reg_settings = []
        self.ev_units = []

        sizer = self.sizer
        ir = self.top_widgets('XAFS Scan')
        sizer.Add(self.hline(),  (ir, 0), (1, 8), LEFT)

        nregs = self.nregs_wid.GetValue()
        ir += 1
        sizer.Add(self.make_e0panel(),   (ir,   0), (1, 8), LEFT)
        ir += 1

        sizer.Add(self.hline(),    (ir, 0), (1, 8), LEFT)
        ir += 1
        for ic, lab in enumerate((" Region", " Start", " Stop", " Step",
                                  " Npts", " Time (s)", " Units")):
            sizer.Add(SimpleText(self, lab),  (ir, ic), (1, 1), LEFT, 2)

        for i, reg in enumerate((('Pre-Edge', (-100, -10, 5,  19)),
                                 ('XANES',    (-10,   10, 0.25,  81)),
                                 ('XAFS1',    ( 10,  200, 2,  96)),
                                 ('XAFS2',    (200,  500, 3, 101)),
                                 # ('XAFS3',    (500,  900, 4, 101))
                                 ) ):

            label, initvals = reg
            ir += 1
            reg   = wx.StaticText(self, -1, size=(100, -1), label=' %s' % label)
            start, stop, step, npts = self.StartStopStepNpts(i, initvals=initvals)
            dtime = FloatCtrl(self, size=(70, -1), value=1, minval=0,
                              precision=3,
                              action=partial(self.onVal, index=i, label='dtime'))

            if i < 2:
                units = wx.StaticText(self, -1, size=(30, -1), label=self.units_list[0])
            else:
                units = add_choice(self, self.units_list,
                                   action=partial(self.onVal, label='units', index=i))
            self.ev_units.append(True)
            # dtime.Disable()
            self.reg_settings.append((start, stop, step, npts, dtime, units))
            if i >= nregs:
                start.Disable()
                stop.Disable()
                step.Disable()
                npts.Disable()
                dtime.Disable()
                units.Disable()
            sizer.Add(reg,   (ir, 0), (1, 1), wx.ALL, 5)
            sizer.Add(start, (ir, 1), (1, 1), wx.ALL, 2)
            sizer.Add(stop,  (ir, 2), (1, 1), wx.ALL, 2)
            sizer.Add(step,  (ir, 3), (1, 1), wx.ALL, 2)
            sizer.Add(npts,  (ir, 4), (1, 1), wx.ALL, 2)
            sizer.Add(dtime, (ir, 5), (1, 1), wx.ALL, 2)
            sizer.Add(units, (ir, 6), (1, 1), wx.ALL, 2)


        self.kwtimechoice = add_choice(self, ('0', '1', '2', '3'), size=(70, -1),
                                     action=partial(self.onVal, label='kwpow'))

        self.kwtimemax = FloatCtrl(self, precision=3, value=0, minval=0,
                                   size=(65, -1),
                                   action=partial(self.onVal, label='kwtime'))

        ir += 1
        sizer.Add(SimpleText(self, "k-weight time of last region:"),  (ir, 1,), (1, 2), CEN, 3)
        sizer.Add(self.kwtimechoice, (ir, 3), (1, 1), LEFT, 2)
        sizer.Add(SimpleText(self, "Max Time:"),  (ir, 4,), (1, 1), CEN, 3)
        sizer.Add(self.kwtimemax, (ir, 5), (1, 1), LEFT, 2)
        # self.kwtimemax.Disable()
        # self.kwtimechoice.Disable()

        bot_panel = self.add_startscan(with_nscans=True)

        self.scan_message = SimpleText(self, " ", style=LEFT, size=(500, -1),
                                       font=self.Font12, colour='#991111')

        ir +=1
        self.sizer.Add(self.scan_message, (ir,   0), (1, 8), LEFT)
        self.sizer.Add(self.hline(),      (ir+1, 0), (1, 8), LEFT)
        self.sizer.Add(bot_panel,         (ir+2, 0), (1, 8), LEFT)

        pack(self, self.sizer)
        self.SetupScrolling()
        self._initialized = True
        self.update_position_from_pv(0)

        self.inittimer = wx.Timer(self)
        self.initcounter = 0
        self.Bind(wx.EVT_TIMER, self.display_energy, self.inittimer)
        self.inittimer.Start(100)

    def load_scandict(self, scan):
        """load scan for XAFS scan from scan dictionary
        as stored in db, or passed to stepscan"""

        # self.kwtimemax.SetValue(scan['max_time'])
        # self.kwtimechoice.SetSelection(scan['time_kw'])

        elem = scan.get('elem', None)
        if elem:
            self.elemchoice.SetStringSelection(elem)
        edge = scan.get('edge', None)
        if edge:
            self.edgechoice.SetStringSelection(edge)
        self.e0.SetValue(scan['e0'])
        self.absrel_value = 0
        if hasattr(self, 'absrel'):
            self.absrel_value = {True:1, False:0}[scan['is_relative']]
            self.absrel.SetSelection(self.absrel_value)

        nregs = len(scan['regions'])
        self.nregs_wid.SetValue(nregs)
        for ireg, reg in enumerate(self.reg_settings):
            if ireg < nregs:
                for wid in reg: wid.Enable()
            else:
                for wid in reg: wid.Disable()

        dtimes = []
        for ireg, reg in enumerate(scan['regions']):
            start, stop, step, npts, dtime, units = self.reg_settings[ireg]
            # set units first!
            this_units = reg[4]
            if hasattr(units, 'SetStringSelection'):
                if this_units in self.units_list:
                    units.SetStringSelection(reg[4])
                else:
                    units.SetSelection(1)

                self.ev_units[ireg] = (reg[4].lower().startswith('ev'))

            start.SetValue(reg[0])
            stop.SetValue(reg[1])
            npts.SetValue(reg[2])
            dtime.SetValue(reg[3])
            dtimes.append(reg[3])
            if ireg == 0:
                self.dwelltime.SetValue(reg[3])

        self.kwtimemax.SetValue(scan['max_time'])
        self.kwtimechoice.SetSelection(scan['time_kw'])

        # is this a step or continuous scan?
        scanmode = scan.get('scanmode', None)
        dtimes_vary = (max(dtimes) - min(dtimes)) > 0.1
        qxafs_ttime = float(self.scandb.get_info('qxafs_time_threshold', default=0))
        if scanmode is None:
            step_xafs = (max(dtimes) > qxafs_ttime or dtimes_vary)
        else:
            step_xafs = 'step' in scanmode
        self.qxafs.SetValue(not step_xafs)
        for ireg, reg in enumerate(scan['regions']):
            start, stop, step, npts, dtime, units = self.reg_settings[ireg]
            # if start.Enabled:
            #     dtime.Enable(step_xafs)
        # self.kwtimemax.Enable(step_xafs)
        # self.kwtimechoice.Enable(step_xafs)

        # make sure HERFD detector follows the checkbox
        det_name = self.scandb.get_info('xas_herfd_detector', None)
        use_herfd = False
        for det in self.scandb.get_detectors():
            if det.name == det_name:
                use_herfd = det.use
        self.use_herfd.SetValue(use_herfd)

        self.setScanTime()

    def setScanTime(self):
        "set Scan Time for XAFS Scan"
        etime = (float(self.scandb.get_info('pos_settle_time', default=0)) +
                 float(self.scandb.get_info('det_settle_time', default=0)))
        etime = etime + 0.25  # estimate time to move energy positioner
        dtime = 0.0
        kwt_max = float(self.kwtimemax.GetValue())
        kwt_pow = float(self.kwtimechoice.GetStringSelection())
        dtimes = []
        for reg in self.reg_settings:
            nx = float(reg[3].GetValue())
            dx = float(reg[4].GetValue())
            if reg[4].Enabled:
                dtimes.append((nx, dx))

        # qxafs: ignore settling time and k-weighting of time
        if self.qxafs.IsChecked():
            etime  = 0
            kwt_pow = 0

        if kwt_pow != 0:
            nx, dx = dtimes.pop()
            _vtime = (kwt_max-dx)*(1.0/(nx-1))**kwt_pow
            for i in range(int(nx)):
                dtime += (dx+etime)+ _vtime*(i**kwt_pow)

        for nx, dx in dtimes:
            dtime += nx*(dx + etime)
        self.scantime = dtime
        self.est_time.SetLabel(hms(dtime))

    def top_widgets(self, title, dwell_prec=3, dwell_value=1):
        "XAFS top widgets"
        self.absrel = add_choice(self, ('Absolute', 'Relative'),
                                 size=(150, -1), action=self.onAbsRel)
        self.absrel_value = 1
        self.absrel.SetSelection(1)

        self.use_herfd = check(self, default=False,
                               label='Collect HERFD ROIs',
                               action=self.onUseHERFD)

        idgap_scan = self.scandb.get_info('qxafs_use_gapscan', as_bool=True)
        self.gap_scan = check(self, default=idgap_scan,
                              label='ID Gap Scan',
                              action=self.onUseGapScan)

        qxafs_default = self.scandb.get_info('qxafs_continuous', default=False, as_bool=True)
        self.qxafs = check(self, default=qxafs_default,
                           label='Continuous Scan', action=self.onQXAFS)

        qxafs_time_threshold = float(self.scandb.get_info('qxafs_time_threshold',
                                                          default=0))
        if dwell_value < qxafs_time_threshold:
            self.qxafs.SetValue(True)

        self.dwelltime = FloatCtrl(self, precision=dwell_prec,
                                   value=dwell_value,
                                   act_on_losefocus=True,
                                   minval=0, size=(60, -1),
                                   action=partial(self.onVal,
                                                  label='dwelltime'))

        self.est_time  = SimpleText(self, '  00:00:00  ')
        self.nregs_wid = FloatCtrl(self, precision=0, value=3,
                                   minval=1, maxval=4,
                                   size=(40, -1),  act_on_losefocus=True,
                                   action=partial(self.onVal, label='nreg'))
        nregs = self.nregs_wid.GetValue()

        titlex  =  SimpleText(self, " %s" % title, style=LEFT,
                              size=(250, -1),
                              font=self.Font13, colour='#880000')


        olabel = SimpleText(self, ' Options:', size=(70, -1))
        alabel = SimpleText(self, ' Mode: ', size=(60, -1))
        dlabel = SimpleText(self, ' Time/Pt (s):')
        tlabel = SimpleText(self, ' Estimated Scan Time:  ')
        rlabel = SimpleText(self, ' # Regions: ')

        sizer = self.sizer

        sizer.Add(titlex,         (0, 0), (1, 3), LEFT,  3)
        sizer.Add(tlabel,         (0, 4), (1, 2), RIGHT, 3)
        sizer.Add(self.est_time,  (0, 6), (1, 2), CEN,   3)

        sizer.Add(olabel,         (1, 0), (1, 1), LEFT,  3)
        sizer.Add(self.qxafs,     (1, 1), (1, 1), LEFT,  3)
        sizer.Add(self.gap_scan,  (1, 2), (1, 2), LEFT,  3)
        sizer.Add(self.use_herfd, (1, 4), (1, 2), LEFT,  3)

        sizer.Add(alabel,         (2, 0), (1, 1), LEFT,  3)
        sizer.Add(self.absrel,    (2, 1), (1, 1), LEFT,  3)
        sizer.Add(rlabel,         (2, 2), (1, 1), RIGHT, 3)
        sizer.Add(self.nregs_wid, (2, 3), (1, 1), LEFT,  3)
        sizer.Add(dlabel,         (2, 4), (1, 1), RIGHT, 3)
        sizer.Add(self.dwelltime, (2, 5), (1, 1), LEFT,  3)

        # return next row for sizer
        return 3

    def make_e0panel(self):
        p = wx.Panel(self)
        p.SetBackgroundColour(GUIColors.bg)
        s = wx.BoxSizer(wx.HORIZONTAL)
        self.e0 = FloatCtrl(p, precision=2, value=7112.0, minval=0, maxval=1e7,
                            size=(80, -1), act_on_losefocus=True,
                            action=partial(self.onVal, label='e0'))

        self.elemchoice = add_choice(p, ELEM_LIST,
                                     action=self.onEdgeChoice, size=(70, -1))
        self.elemchoice.SetStringSelection('Fe')

        self.edgechoice = add_choice(p, self.edges_list, size=(75, -1),
                                     action=self.onEdgeChoice)

        s.Add(SimpleText(p, " Edge Energy:", size=(110, -1),
                         style=LEFT), 0, CEN, 2)
        s.Add(self.e0,   0, LEFT, 2)
        s.Add(SimpleText(p, "  Element: "), 0, LEFT, 3)
        s.Add(self.elemchoice,              0, LEFT, 3)
        s.Add(SimpleText(p, "  Edge: "),    0, LEFT, 3)
        s.Add(self.edgechoice,              0, LEFT, 3)
        s.Add(SimpleText(p, "   Energy: ", size=(120, -1),
                         style=LEFT), 0, CEN, 2)
        self.energy_pv = PVStaticText(p, pv=None, size=(90, -1),
                                      style=CEN)
        s.Add(self.energy_pv, 0, CEN, 2)
        pack(p, s)
        return p

    @EpicsFunction
    def display_energy(self, evt=None):
        enpos = str(self.scandb.get_info('xafs_energy', 'Energy'))
        pos = self.scandb.get_positioner(enpos)
        self.initcounter += 1
        # self.onEdgeChoice()
        if pos is None and self.initcounter > 10:
            self.inittimer.Stop()
        if pos is not None:
            en_pvname = pos.readpv
            if en_pvname in self.pvlist and self.energy_pv.pv is None:
                self.energy_pv.SetPV(self.pvlist[en_pvname])
                self.inittimer.Stop()

    def getUnits(self, index):
        un = self.reg_settings[index][5]
        if hasattr(un, 'GetStringSelection'):
            return un.GetStringSelection()
        else:
            return un.GetLabel()

    def onVal(self, evt=None, index=0, label=None, value=None, **kws):
        "XAFS onVal"
        if not self._initialized:
            return
        wids = self.reg_settings[index]
        units = self.getUnits(index)
        ev_units = self.ev_units[index]

        #enpos = str(self.scandb.get_info('xafs_energy'))
        #pos = self.scandb.get_positioner(enpos)
        #en_pvname = str(pos.readpv)
        #if en_pvname in self.pvlist and self.energy_pv.pv is None:
        #    self.energy_pv.SetPV(self.pvlist[en_pvname])
        e0_off = 0
        qxafs_time_threshold = float(self.scandb.get_info('qxafs_time_threshold',
                                                          default=0))
        if 0 == self.absrel.GetSelection(): # absolute
            e0_off = self.e0.GetValue()

        if label == 'dwelltime':
            for wid in self.reg_settings:
                wid[4].SetValue(value)

            self.qxafs.SetValue(value < qxafs_time_threshold)
        elif label == 'dtime':
            equal_times = True
            for ireg, reg in enumerate(self.reg_settings):
                if reg[4].Enabled:
                    rtime = float(reg[4].GetValue())
                    equal_times = equal_times and abs(value -rtime)  < 0.01

            self.qxafs.SetValue(not equal_times)
        elif label == 'nreg':
            nregs = value
            for ireg, reg in enumerate(self.reg_settings):
                for wid in reg:
                    wid.Enable(ireg < nregs)
            self.Refresh()

        elif label == 'units':
            if units == self.units_list[0] and not ev_units: # was 1/A, convert to eV
                wids[0].SetValue(ktoe(wids[0].GetValue()) + e0_off)
                wids[1].SetValue(ktoe(wids[1].GetValue()) + e0_off)
                wids[2].SetValue(2.0)
            elif units != self.units_list[0] and ev_units: # was eV, convert to 1/A
                wids[0].SetValue(etok(wids[0].GetValue() - e0_off))
                wids[1].SetValue(etok(wids[1].GetValue() - e0_off))
                wids[2].SetValue(0.05)
            self.ev_units[index] = (units == self.units_list[0])
            self.setStepNpts(wids, label)

        if label in ('start', 'stop', 'step', 'npts'):
            self.setStepNpts(wids, label)
            if label == 'stop' and index < len(self.reg_settings)-1:
                nunits = self.getUnits(index+1)
                if nunits != units:
                    if units == 'eV':
                        value = etok(value - e0_off)
                    else:
                        value = ktoe(value) + e0_off
                self.reg_settings[index+1][0].SetValue(value, act=False)
                self.setStepNpts(self.reg_settings[index+1], label)
            elif label == 'start' and index > 0:
                nunits = self.getUnits(index-1)
                if nunits != units:
                    if units == 'eV':
                        value = etok(value - e0_off)
                    else:
                        value = ktoe(value) + e0_off
                self.reg_settings[index-1][1].SetValue(value, act=False)
                self.setStepNpts(self.reg_settings[index-1], label)
        self.setScanTime()

    def onQXAFS(self, evt=None):
        """continuous/step scans """
        # note: save qxafs selection, because setting the
        # per-region time may auto-set the qxafs selection to 'step'
        use_qxafs = evt.IsChecked()
        dtime = float(self.dwelltime.GetValue())
        equal_times = True
        for ireg, reg in enumerate(self.reg_settings):
            if reg[1].Enabled:
                #reg[4].Enable(not use_qxafs)
                #if not use_qxafs:
                reg[4].SetValue(dtime)

        # self.kwtimemax.Enable(not use_qxafs)
        # self.kwtimechoice.Enable(not use_qxafs)
        self.qxafs.SetValue(use_qxafs)

        self.setScanTime()

    def onUseHERFD(self, evt=None):
        det_name = self.scandb.get_info('xas_herfd_detector', None)
        self.scandb.use_detector(det_name, use=self.use_herfd.IsChecked())

    def onUseGapScan(self, evt=None):
        val = 1 if self.gap_scan.IsChecked() else 0
        self.scandb.set_info('qxafs_use_gapscan', val)

    def onAbsRel(self, evt=None):
        """xafs abs/rel"""
        offset = 0
        if 1 == self.absrel.GetSelection() and self.absrel_value == 0:
            # was absolute, now in relative
            offset = -self.e0.GetValue()
            self.absrel_value = 1
        elif 0 == self.absrel.GetSelection() and self.absrel_value == 1:
            # was relative, now absolute
            offset = self.e0.GetValue()
            self.absrel_value = 0
        for index, wids in enumerate(self.reg_settings):
            units = self.getUnits(index)
            if units == 'eV':
                for ix in range(2):
                    wids[ix].SetValue(wids[ix].GetValue() + offset, act=False)


    def onEdgeChoice(self, evt=None):
        edge = self.edgechoice.GetStringSelection()
        elem = self.elemchoice.GetStringSelection()
        if self.mkernel is not None:
            e0val = self.mkernel.run("xray_edge('%s', '%s')" % (elem, edge))
            self.e0.SetValue(e0val[0])
            self.set_scan_message("Warning: Check ROIs for '%s %sa' (use Ctrl-R)" % (elem, edge))

    def generate_scan_positions(self):
        "generate xafs scan"
        enpos = str(self.scandb.get_info('xafs_energy', 'Energy'))
        enpos = self.scandb.get_positioner(enpos)
        scantype = 'xafs'
        scanmode = 'step'
        if self.qxafs.IsChecked():
            scanmode = 'slew'
        s = {'type': scantype,
             'scanmode': scanmode,
             'e0': self.e0.GetValue(),
             'elem':  self.elemchoice.GetStringSelection(),
             'edge':  self.edgechoice.GetStringSelection(),
             'dwelltime':  float(self.dwelltime.GetValue()),
             'is_relative': 1==self.absrel.GetSelection(),
             'max_time': self.kwtimemax.GetValue(),
             'time_kw': int(self.kwtimechoice.GetSelection()),
             'energy_drive': enpos.drivepv,
             'energy_read': enpos.readpv,
             'extra_pvs': json.loads(enpos.extrapvs),
             'scantime': self.scantime,
             'regions': [],
             'filename': self.filename.GetValue(),
             'comments': self.user_comms.GetValue(),
             'nscans': 1
             }

        # make sure HERFD detector follows the checkbox
        hdet_name = self.scandb.get_info('xas_herfd_detector', default=None)
        if hdet_name not in (None, 0, 'None', '0'):
            self.scandb.use_detector(hdet_name, use=self.use_herfd.IsChecked())

        if self.nscans is not None:
            s['nscans'] = int(self.nscans.GetValue())

        for index, wids in enumerate(self.reg_settings):
            start, stop, step, npts, dtime, units =  wids
            if start.Enabled:
                p1 = start.GetValue()
                p2 = stop.GetValue()
                np = npts.GetValue()
                dt = dtime.GetValue()
                un = self.getUnits(index)
                s['regions'].append((p1, p2, np, dt, un))
        return s

class MeshScanPanel(GenericScanPanel):
    """ mesh / 2-d step scan """
    __name__ = 'MeshScan'
    def __init__(self, parent, **kws):
        GenericScanPanel.__init__(self, parent, **kws)
        sizer = self.sizer
        self.scantype = 'mesh'
        ir = self.top_widgets('Mesh Scan (Slow Map)')
        sizer.Add(self.hline(), (ir, 0), (1, 8), LEFT)
        ir += 1

        for ic, lab in enumerate((" Loop", " Positioner", " Units",
                                  " Current", " Start", " Stop", " Step", " Npts")):
            s  = CEN
            if lab == " Npts":
                s = LEFT
            sizer.Add(SimpleText(self, lab), (ir, ic), (1, 1), s, 2)

        self.pos_settings = []
        pchoices = [p.name for p in self.scandb.get_positioners()]
        fsize = (95, -1)
        for i, label in enumerate((" Inner ", " Outer ")):
            lab = wx.StaticText(self, -1, label=label)
            pos = add_choice(self, pchoices, size=(100, -1),
                             action=partial(self.onPos, index=i))
            pos.SetSelection(i)
            units = wx.StaticText(self, -1, size=(40, -1), label='')
            cur   = PVStaticText(self, pv=None, size=(100, -1),
                                 style=CEN)
            start, stop, step, npts = self.StartStopStepNpts(i,
                                                    initvals=(-1, 1, 0.1, 11))

            self.pos_settings.append((pos, units, cur, start, stop, step, npts))
            ir += 1
            sizer.Add(lab,   (ir, 0), (1, 1), wx.ALL, 2)
            sizer.Add(pos,   (ir, 1), (1, 1), wx.ALL, 2)
            sizer.Add(units, (ir, 2), (1, 1), wx.ALL, 2)
            sizer.Add(cur,   (ir, 3), (1, 1), wx.ALL, 2)
            sizer.Add(start, (ir, 4), (1, 1), wx.ALL, 2)
            sizer.Add(stop,  (ir, 5), (1, 1), wx.ALL, 2)
            sizer.Add(step,  (ir, 6), (1, 1), wx.ALL, 2)
            sizer.Add(npts,  (ir, 7), (1, 1), wx.ALL, 2)



        bot_panel = self.add_startscan(with_nscans=True)

        self.scan_message = SimpleText(self, " ", style=LEFT, size=(500, -1),
                                       font=self.Font12, colour='#991111')
        ir += 1
        self.sizer.Add(self.scan_message, (ir,   0), (1, 8), LEFT)
        self.sizer.Add(self.hline(),      (ir+1, 0), (1, 8), LEFT)
        self.sizer.Add(bot_panel,         (ir+2, 0), (1, 8), LEFT)

        pack(self, self.sizer)
        self.SetupScrolling()
        self._initialized = True
        self.update_position_from_pv(0)

    def load_scandict(self, scan):
        """load scan for mesh scan from scan dictionary
        as stored in db, or passed to stepscan"""

        self.dwelltime.SetValue(scan['dwelltime'])
        self.absrel.SetSelection(0)
        for irow, name in ((0, 'inner'), (1, 'outer')):
            pos, units, cur, start, stop, step, npts = self.pos_settings[irow]
            posdat = scan[name]
            pos.SetStringSelection(posdat[0])
            start.SetValue(posdat[2])
            stop.SetValue(posdat[3])
            npts.SetValue(posdat[4])
            self.update_position_from_pv(irow)

        for det in scan['detectors']:
            print(det)

    def update_positioners(self):
        """meant to be overwritten"""
        self.get_positioners()

        for irow, row in enumerate(self.pos_settings):
            thispos = row[0]
            cur = thispos.GetStringSelection()
            thispos.Clear()
            thispos.SetItems(self.poslist[1:])
            if cur in self.poslist:
                thispos.SetStringSelection(cur)
            else:
                thispos.SetSelection(0)

    def onVal(self, index=0, label=None, value=None, **kws):
        if not self._initialized: return
        if label in ('start', 'stop', 'step', 'npts'):
            self.setStepNpts(self.pos_settings[index][3:], label)
        self.setScanTime()

    def onPos(self, evt=None, index=0):
        self.update_position_from_pv(index)

    def use_scandb(self, scandb):
        self.get_positioners()
        if hasattr(self, 'pos_settings'):
            for i, wids in enumerate(self.pos_settings):
                a = wids[0].GetStringSelection()
                wids[0].Clear()
                wids[0].SetItems(self.poslist)
                wids[0].SetStringSelection(a)

    def generate_scan_positions(self):
        "generate mesh scan"
        s = {'type': 'mesh',
             'dwelltime':  float(self.dwelltime.GetValue()),
             'scantime': self.scantime,
             'inner': [],
             'outer': [],
             'filename': self.filename.GetValue(),
             'comments': self.user_comms.GetValue(),
             'nscans': 1    }

        is_relative =  self.absrel.GetSelection()
        for i, wids in enumerate(self.pos_settings):
            pos, u, cur, start, stop, dx, wnpts = wids
            npts = wnpts.GetValue()
            name = pos.GetStringSelection()
            xpos = self.scandb.get_positioner(name)
            pvnames = (xpos.drivepv, xpos.readpv)
            p1 = start.GetValue()
            p2 = stop.GetValue()
            if is_relative:
                p1 += float(cur.GetLabel())
                p2 += float(cur.GetLabel())
            mname = 'inner'
            if i > 0: mname = 'outer'
            s[mname] = [name, pvnames, p1, p2, npts]
        return s

class Slew2DScanPanel(GenericScanPanel):
    """  2-d slew scan """
    __name__ = 'SlewScan'
    def __init__(self, parent, **kws):
        GenericScanPanel.__init__(self, parent, **kws)
        self.scantype = 'slew'
        sizer = self.sizer

        self.dwelltime = FloatCtrl(self, precision=1, value=10,
                                   act_on_losefocus=True,
                                   minval=0, maxval=2000, size=(100, -1),
                                   action=partial(self.onVal,
                                                  label='dwelltime'))

        self.dimchoice = add_choice(self, ('1', '2'), action = self.onDim)
        self.dimchoice.SetStringSelection('2')
        self.est_time  = SimpleText(self, '  00:00:00  ')
        titlex =  SimpleText(self, " Map & Slew Scans", style=LEFT,
                             size=(250, -1),
                             font=self.Font13, colour='#880000')
        dlabel = SimpleText(self, ' Time/Point (millisec):')
        tlabel = SimpleText(self, ' Estimated Scan Time:  ')

        sizer.Add(titlex,         (0, 0), (1, 3), LEFT,  3)
        sizer.Add(tlabel,         (0, 4), (1, 2), RIGHT, 3)
        sizer.Add(self.est_time,  (0, 6), (1, 2), CEN,   3)
        sizer.Add(dlabel,         (1, 0), (1, 2), RIGHT, 3)
        sizer.Add(self.dwelltime, (1, 2), (1, 2), LEFT,  3)
        sizer.Add(SimpleText(self, ' Dimension:'), (1, 4), (1, 1), CEN)
        sizer.Add(self.dimchoice,                  (1, 5), (1, 2), CEN)

        ir = 2


        sizer.Add(self.hline(), (ir, 0), (1, 8), LEFT)
        ir += 1
        for ic, lab in enumerate((" Loop", " Positioner", " Units",
                                  " Current", " Start", " Stop", " Step", " Npts")):
            s  = CEN
            if lab == " Npts":
                s = LEFT
            # if lab == "Current": s = RIGHT
            sizer.Add(SimpleText(self, lab), (ir, ic), (1, 1), s, 2)

        self.pos_settings = []
        fsize = (95, -1)
        for i, label in enumerate((" Inner ", " Outer ")):
            lab = wx.StaticText(self, -1, label=label)
            pchoices = [p.name for p in self.scandb.get_positioners()]
            if i == 0:
                pchoices = [p.name for p in self.scandb.get_slewpositioners()]

            pos = add_choice(self, pchoices, size=(100, -1),
                             action=partial(self.onPos, index=i))
            pos.SetSelection(i)
            units = wx.StaticText(self, -1, size=(40, -1), label='',
                                  style=CEN)
            cur   = PVStaticText(self, pv=None, size=(100, -1),
                                 style=CEN)
            start, stop, step, npts = self.StartStopStepNpts(i, precision=5,
                                            initvals=(-0.25, 0.25, 0.002, 251))
            self.pos_settings.append((pos, units, cur, start, stop, step, npts))
            ir += 1
            sizer.Add(lab,   (ir, 0), (1, 1), wx.ALL, 2)
            sizer.Add(pos,   (ir, 1), (1, 1), wx.ALL, 2)
            sizer.Add(units, (ir, 2), (1, 1), wx.ALL, 2)
            sizer.Add(cur,   (ir, 3), (1, 1), wx.ALL, 2)
            sizer.Add(start, (ir, 4), (1, 1), wx.ALL, 2)
            sizer.Add(stop,  (ir, 5), (1, 1), wx.ALL, 2)
            sizer.Add(step,  (ir, 6), (1, 1), wx.ALL, 2)
            sizer.Add(npts,  (ir, 7), (1, 1), wx.ALL, 2)

        ir += 1

        zfm = self.scandb.get_info('zero_finemotors_beforemap',
                                   as_bool=True, default=0)
        self.zfmchoice = check(self, default=zfm,
                               label='Zero Fine Motors before Map?',
                               action=self.onZeroFineMotors)

        self.use_xrd = check(self, default=False,
                             label='Collect XRD with Map?',
                             action=self.onSelectXRD)

        sizer.Add(self.zfmchoice, (ir, 1), (1, 3), wx.ALL, 2)

        ir += 1
        sizer.Add(self.use_xrd, (ir, 1), (1, 3), wx.ALL, 2)

        ir += 1
        sizer.Add(SimpleText(self, 'Select from Common Square Maps:'),
                  (ir, 0), (1, 5), wx.ALL, 2)

        jrow = 0
        jcol = 0
        lsizer = wx.GridBagSizer(3, 2)
        lpanel = wx.Panel(self)

        for mapname in (u' 50 x 50 \u03bcm', u'100 x 100 \u03bcm',
                        u'200 x 200 \u03bcm', u'300 x 300 \u03bcm',
                        u'400 x 400 \u03bcm', u'500 x 500 \u03bcm',
                        u'600 x 600 \u03bcm', u'800 x 800 \u03bcm',
                        '1 x 1 mm', '2 x 2 mm'):
            link = HyperText(lpanel, mapname,
                             action=partial(self.onDefinedMap,
                                            label=mapname))
            lsizer.Add(link, (jrow, jcol), (1, 1), wx.ALL, 7)
            jcol += 1
            if jcol > 4:
                jrow += 1
                jcol = 0

        ir += 1
        pack(lpanel, lsizer)
        sizer.Add(lpanel, (ir, 1), (2, 7), wx.ALL, 2)

        bot_panel = self.add_startscan(with_nscans=False)

        self.scan_message = SimpleText(self, " ", style=LEFT, size=(500, -1),
                                       font=self.Font12, colour='#991111')
        ir +=2
        self.sizer.Add(self.scan_message, (ir,   0), (1, 8), LEFT)
        self.sizer.Add(self.hline(),      (ir+1, 0), (1, 8), LEFT)
        self.sizer.Add(bot_panel,         (ir+2, 0), (1, 8), LEFT)

        pack(self, self.sizer)
        self.SetupScrolling()
        self._initialized = True
        self.update_position_from_pv(0)


    def onDefinedMap(self, label=None, event=None):
        words = label.split()
        size  = int(words[0])
        units = words[-1]
        if units == u'\u03bcm': size *= 0.001
        halfsize = size/2.0
        for irow, name in ((0, 'inner'), (1, 'outer')):
            pos, units, cur, start, stop, step, npts = self.pos_settings[irow]
            start.SetValue(-halfsize)
            stop.SetValue(halfsize)

    def load_scandict(self, scan):
        """load scan for mesh scan from scan dictionary
        as stored in db, or passed to stepscan"""
        self.dwelltime.SetValue(1000*scan['dwelltime'])
        self.dimchoice.SetStringSelection('%i' % (scan['dimension']))
        if hasattr(self, 'absrel'):
            try:
                self.absrel.SetSelection(0)
            except:
                pass
        for irow, name in ((0, 'inner'), (1, 'outer')):
            pos, units, cur, start, stop, step, npts = self.pos_settings[irow]
            posdat = scan[name]
            if len(posdat) > 0:
                pos.SetStringSelection(posdat[0])
                start.SetValue(posdat[2])
                stop.SetValue(posdat[3])
                npts.SetValue(posdat[4])
                self.update_position_from_pv(irow)

        xrd_det_name = self.scandb.get_info('xrdmap_detector', None)
        use_xrd = False
        for det in scan['detectors']:
            if det['label'] == xrd_det_name:
                use_xrd = True
        self.use_xrd.SetValue(use_xrd)


    def update_positioners(self):
        """meant to be overwritten"""
        self.get_positioners()
        for irow, row in enumerate(self.pos_settings):
            thispos = row[0]
            cur = thispos.GetStringSelection()
            thispos.Clear()
            plist = self.poslist[2:]
            if irow == 0:
                plist = self.slewlist
            thispos.SetItems(plist)
            if cur in plist:
                thispos.SetStringSelection(cur)
            else:
                thispos.SetSelection(0)

    def onVal(self, index=0, label=None, value=None, **kws):
        if not self._initialized: return
        if label in ('start', 'stop', 'step', 'npts'):
            self.setStepNpts(self.pos_settings[index][3:], label)
        self.setScanTime()

    def onDim(self, evt=None):
        wids = self.pos_settings[1]
        self.update_position_from_pv(0)
        if self.dimchoice.GetSelection() == 0: # 1-d
            for i in (1, 2):
                wids[i].SetLabel('')
            for i in (3, 4, 5, 6):
                wids[i].Disable()
        else:
            for i in (3, 4, 5, 6): wids[i].Enable()
            self.update_position_from_pv(1)

    def onZeroFineMotors(self, evt=None):
        zfm = self.zfmchoice.IsChecked()
        self.scandb.set_info('zero_finemotors_beforemap', int(zfm))

    def onSelectXRD(self, evt=None):
        det_name = self.scandb.get_info('xrdmap_detector', None)
        self.scandb.use_detector(det_name, use=self.use_xrd.IsChecked())

    def onPos(self, evt=None, index=0):
        self.update_position_from_pv(index)

    def use_scandb(self, scandb):
        self.get_positioners()
        inner = self.pos_settings[0][0]
        outer = self.pos_settings[1][0]
        for wid, vals in ((inner, self.slewlist), (outer, self.poslist)):
            a = wid.GetStringSelection()
            wid.Clear()
            wid.SetItems(vals)
            wid.SetStringSelection(a)

    def setScanTime(self):
        "set estimated scan time, addig overhead of 1 sec per row"
        dtime = float(0.001*self.dwelltime.GetValue())
        ninner = float(self.pos_settings[0][6].GetValue())
        dtime  = 1.0 + dtime*ninner
        if 1 == self.dimchoice.GetSelection(): # Note : this means a 2-d scan!
            dtime *= float(self.pos_settings[1][6].GetValue())

        self.scantime = dtime
        self.est_time.SetLabel(hms(dtime))

    def generate_scan_positions(self):
        "generate slew scan"
        s = {'type': 'slew',
             'dwelltime':  float(0.001*self.dwelltime.GetValue()),
             'dimension': 1+self.dimchoice.GetSelection(),
             'scantime': self.scantime,
             'inner': [],
             'outer': [],
             'filename': self.filename.GetValue(),
             'comments': self.user_comms.GetValue(),
             'nscans': 1    }

        # make sure XRD detector follows the XRD checkbox
        det_name = self.scandb.get_info('xrdmap_detector', None)
        if det_name is not None:
            self.scandb.use_detector(det_name, use=self.use_xrd.IsChecked())

        #xrd_det_name = self.scandb.get_info('xrdmap_detector', None)

        for i, wids in enumerate(self.pos_settings):
            pos, u, cur, start, stop, dx, wnpts = wids
            if start.Enabled:
                npts = wnpts.GetValue()
                name = pos.GetStringSelection()
                xpos = self.scandb.get_positioner(name)
                pvnames = (xpos.drivepv, xpos.readpv)
                p1 = start.GetValue()
                p2 = stop.GetValue()
                mname = 'outer'
                if i == 0:
                    mname = 'inner'
                    if p1 > p2:  # force inner scan to be from low to high
                        p1, p2 = p2, p1
                        start.SetValue(p1)
                        stop.SetValue(p2)
                s[mname] = [name, pvnames, p1, p2, npts]
        return s

class Slew1DScanPanel(GenericScanPanel):
    """ 1-d slew scan """
    __name__ = 'Slew1dScan'
    def __init__(self, parent, **kws):
        GenericScanPanel.__init__(self, parent, **kws)
        self.scantype = 'slew1d'
        sizer = self.sizer

        ir = self.top_widgets('1-D Slew Scan', with_absrel=False,
                              dwell_value=0.050)

        sizer.Add(self.hline(), (ir, 0), (1, 8), LEFT)
        ir += 1
        for ic, lab in enumerate(("  ", " Positioner", " Units",
                                  " Current", " Start", " Stop", " Step", " Npts")):
            sty  = LEFT if lab == " Npts" else CEN
            sizer.Add(SimpleText(self, lab), (ir, ic), (1, 1), sty, 2)

        fsize = (95, -1)
        pchoices = []
        scan_positioners = [p.name for p in self.scandb.get_positioners()]
        if 'Time' in scan_positioners:
            pchoices.append('Time')
        pchoices.extend([p.name for p in self.scandb.get_slewpositioners()])

        pos = add_choice(self, pchoices, size=(125, -1), action=self.onPos)
        pos.SetSelection(0)
        units = wx.StaticText(self, -1, size=(40, -1), label='',
                              style=CEN)
        cur   = PVStaticText(self, pv=None, size=(100, -1),
                             style=CEN)
        start, stop, step, npts = self.StartStopStepNpts(0,
                    initvals=(-0.25, 0.25, 0.002, 251))
        self.pos_settings = [(pos, units, cur, start, stop, step, npts)]
        ir += 1

        lab = wx.StaticText(self, -1, label=' ')
        sizer.Add(lab,   (ir, 0), (1, 1), wx.ALL, 2)
        sizer.Add(pos,   (ir, 1), (1, 1), wx.ALL, 2)
        sizer.Add(units, (ir, 2), (1, 1), wx.ALL, 2)
        sizer.Add(cur,   (ir, 3), (1, 1), wx.ALL, 2)
        sizer.Add(start, (ir, 4), (1, 1), wx.ALL, 2)
        sizer.Add(stop,  (ir, 5), (1, 1), wx.ALL, 2)
        sizer.Add(step,  (ir, 6), (1, 1), wx.ALL, 2)
        sizer.Add(npts,  (ir, 7), (1, 1), wx.ALL, 2)

        ir += 1

        # zfm = self.scandb.get_info('zero_finemotors_beforemap',
        #                            as_bool=True, default=0)
        # self.zfmchoice = check(self, default=zfm,
        #                        label='Zero Fine Motors before Scan?',
        #                        action=self.onZeroFineMotors)
        # sizer.Add(self.zfmchoice, (ir, 1), (1, 3), wx.ALL, 2)

        bot_panel = self.add_startscan(with_nscans=False)

        self.scan_message = SimpleText(self, " ", style=LEFT, size=(500, -1),
                                       font=self.Font12, colour='#991111')
        ir +=2
        self.sizer.Add(self.scan_message, (ir,   0), (1, 8), LEFT)
        self.sizer.Add(self.hline(),      (ir+1, 0), (1, 8), LEFT)
        self.sizer.Add(bot_panel,         (ir+2, 0), (1, 8), LEFT)

        pack(self, self.sizer)
        self.SetupScrolling()
        self._initialized = True
        self.update_position_from_pv(0)


    def load_scandict(self, scan):
        """load scan for mesh scan from scan dictionary
        as stored in db, or passed to stepscan"""
        self.dwelltime.SetValue(scan['dwelltime'])
        if hasattr(self, 'absrel'):
            self.absrel.SetSelection(0)

        pos, units, cur, start, stop, step, npts = self.pos_settings[0]
        posdat = scan['inner']
        if len(posdat) > 0:
            pos.SetStringSelection(posdat[0])
            start.SetValue(posdat[2])
            stop.SetValue(posdat[3])
            npts.SetValue(posdat[4])
            self.update_position_from_pv(0)

    def update_positioners(self):
        """meant to be overwritten"""
        self.get_positioners()
        for irow, row in enumerate(self.pos_settings):
            thispos = row[0]
            cur = thispos.GetStringSelection()
            thispos.Clear()
            plist = self.poslist[2:]
            if irow == 0:
                plist = self.slewlist
            thispos.SetItems(plist)
            if cur in plist:
                thispos.SetStringSelection(cur)
            else:
                thispos.SetSelection(0)

    def onVal(self, index=0, label=None, value=None, **kws):
        if not self._initialized: return
        if label in ('start', 'stop', 'step', 'npts'):
            self.setStepNpts(self.pos_settings[index][3:], label)
        self.setScanTime()

    def onZeroFineMotors(self, evt=None):
        zfm = self.zfmchoice.IsChecked()
        self.scandb.set_info('zero_finemotors_beforemap', int(zfm))

    def onPos(self, evt=None, index=0):
        # def update_position_from_pv(self, index, name=None):
        self.update_position_from_pv(0)

    def use_scandb(self, scandb):
        self.get_positioners()
        wid = self.pos_settings[0][0]
        a = wid.GetStringSelection()
        wid.Clear()
        wid.SetItems(self.slewlist)
        wid.SetStringSelection(a)

    def setScanTime(self):
        "set estimated scan time, addig overhead of 1 sec per row"
        dtime = float(self.dwelltime.GetValue())
        ninner = float(self.pos_settings[0][6].GetValue())
        dtime  = 1.0 + dtime*ninner

        self.scantime = dtime
        self.est_time.SetLabel(hms(dtime))

    def generate_scan_positions(self):
        "generate slew scan"
        s = {'type': 'slew1d',
             'dwelltime':  float(self.dwelltime.GetValue()),
             'dimension': 1,
             'scantime': self.scantime,
             'inner': [],
             'outer': [],
             'filename': self.filename.GetValue(),
             'comments': self.user_comms.GetValue(),
             'nscans': 1  }


        for i, wids in enumerate(self.pos_settings):
            pos, u, cur, start, stop, dx, wnpts = wids
            if start.Enabled:
                npts = wnpts.GetValue()
                name = pos.GetStringSelection()
                xpos = self.scandb.get_positioner(name)
                pvnames = (xpos.drivepv, xpos.readpv)
                p1 = start.GetValue()
                p2 = stop.GetValue()
                mname = 'inner'
                if p1 > p2:  # force inner scan to be from low to high
                    p1, p2 = p2, p1
                    start.SetValue(p1)
                    stop.SetValue(p2)
                s[mname] = [name, pvnames, p1, p2, npts]
        return s
