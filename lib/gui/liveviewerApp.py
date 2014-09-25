#!/usr/bin/env python
"""
GUI for displaying live plots of column data from StepScan Data objects

Principle features:
   frame for plot a file, with math on right/left columns
   fitting frame for simple peak fits
   simple XAS processing (normalization)
"""
import os
import time
import shutil
import json
import numpy as np
from random import randrange

import wx
import wx.lib.agw.flatnotebook as flat_nb
import wx.lib.scrolledpanel as scrolled
import wx.lib.mixins.inspection
from wx._core import PyDeadObjectError

import epics
from epics.wx import DelayedEpicsCallback, EpicsFunction

from larch import Interpreter, use_plugin_path, isParameter
from larch.fitting import fit_report

use_plugin_path('math')
from fitpeak import fit_peak

from wxmplot import PlotFrame, PlotPanel
from ..datafile import StepScanData
from ..scandb import ScanDB
from ..file_utils import fix_filename, fix_varname

from .gui_utils import (SimpleText, FloatCtrl, Closure, pack, add_button,
                        add_menu, add_choice, add_menu, check, hline,
                        CEN, RCEN, LCEN, FRAMESTYLE, Font, hms)

CEN |=  wx.ALL
FILE_WILDCARDS = "Scan Data Files(*.0*,*.dat,*.xdi)|*.0*;*.dat;*.xdi|All files (*.*)|*.*"
FNB_STYLE = flat_nb.FNB_NO_X_BUTTON|flat_nb.FNB_SMART_TABS|flat_nb.FNB_NO_NAV_BUTTONS


PRE_OPS = ('', 'log', '-log', 'deriv', '-deriv', 'deriv(log', 'deriv(-log')
ARR_OPS = ('+', '-', '*', '/')

def randname(n=6):
    "return random string of n (default 6) lowercase letters"
    return ''.join([chr(randrange(26)+97) for i in range(n)])


CURSCAN, SCANGROUP = '< Current Scan >', 'scandat'

class ScanViewerFrame(wx.Frame):
    _about = """Scan Viewer,  Matt Newville <newville @ cars.uchicago.edu>  """
    TIME_MSG = 'Point %i/%i, Time Remaining ~ %s, Status=%s'

    def __init__(self, parent, dbname=None, server='sqlite', host=None,
                 port=None, user=None, password=None, create=True, **kws):

        wx.Frame.__init__(self, None, -1, style=FRAMESTYLE)
        title = "Epics Step Scan Viewer"
        self.parent = parent
        self.scandb = getattr(parent, 'scandb', None)
        if self.scandb is None and dbname is not None:
            self.scandb = ScanDB(dbname=dbname, server=server, host=host,
                                 user=user, password=password, port=port,
                                 create=create)
        self.larch = None
        self.lgroup = None
        self.force_newplot = False
        self.scan_inprogress = False
        self.last_column_update = 0.0
        self.need_column_update = True
        self.SetTitle(title)
        self.SetSize((750, 750))
        self.SetFont(Font(9))
        self.createMainPanel()
        self.createMenus()
        self.statusbar = self.CreateStatusBar(2, 0)
        self.statusbar.SetStatusWidths([-3, -1])
        statusbar_fields = ["Initializing....", " "]
        for i in range(len(statusbar_fields)):
            self.statusbar.SetStatusText(statusbar_fields[i], i)

        if self.scandb is not None:
            self.get_info  = self.scandb.get_info
            self.scandb_server = self.scandb.server
            self.live_scanfile = None
            self.live_cpt = -1
            self.total_npts = 1
            self.scantimer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.onScanTimer, self.scantimer)
            self.scantimer.Start(250)

        self.Show()
        self.Raise()

    def onScanTimer(self, evt=None,  **kws):
        if self.lgroup is None:
            return
        try:
            curfile   = fix_filename(self.get_info('filename'))
            sdata     = self.scandb.get_scandata()
            scan_stat = self.get_info('scan_status')
            msg       = self.get_info('scan_message')
        except:
            print 'Scan ? '
            return
        
        try:
            npts = len(sdata[-1].data)
        except:
            npts = 0
        if npts <= 0 or msg.lower().startswith('preparing'):
            self.need_column_update = True
        
        cmd = self.scandb.get_mostrecent_command()
        try:
            cmd_stat = cmd.status.name.lower()
        except AttributeError:
            cmd_stat = 'unknown'

        do_newplot = False
        
        if ((curfile != self.live_scanfile) or
            (npts > 0 and npts < 10 and self.need_column_update)):
            self.need_column_update = False
            self.scan_inprogress = True            
            do_newplot = True
            self.live_scanfile = curfile
            self.title.SetLabel(curfile)
            self.set_column_names(sdata)
            
        elif msg.lower().startswith('scan complete') and self.scan_inprogress:
            self.scan_inprogress = False
            do_newplot = True

        self.SetStatusText(msg)

        if (not self.scan_inprogress and
            not do_newplot and
            npts == self.live_cpt):
            return

        for row in sdata:
            dat = row.data
            if self.scandb_server == 'sqlite':
                dat = json.loads(dat.replace('{', '[').replace('}', ']'))
            setattr(self.lgroup, fix_varname(row.name), np.array(dat))

        if npts > 1 and npts != self.live_cpt:
            if do_newplot:
                self.force_newplot = True
            self.onPlot(npts=npts)
        self.live_cpt = npts


    def set_column_names(self, sdata):
        """set column names from values read from scandata table"""
        self.lgroup.array_units = [fix_varname(s.units) for s in sdata]
        self.total_npts = self.get_info('scan_total_points', as_int=True)
        self.live_cpt = -1
        xcols, ycols, y2cols = [], [], []
        for s in sdata:
            nam = fix_varname(s.name)
            ycols.append(nam)
            if s.notes.lower().startswith('pos'):
                xcols.append(nam)

        y2cols = ycols[:] + ['1.0', '0.0', '']
        xarr_old = self.xarr.GetStringSelection()
        self.xarr.SetItems(xcols)

        ix = xcols.index(xarr_old) if xarr_old in xcols else 0
        self.xarr.SetSelection(ix)
        for i in range(2):
            for j in range(3):
                yold = self.yarr[i][j].GetStringSelection()
                idef, cols = 0, y2cols
                if i == 0 and j == 0:
                    idef, cols = 1, ycols
                self.yarr[i][j].SetItems(cols)
                iy = cols.index(yold) if yold in cols else idef
                self.yarr[i][j].SetSelection(iy)

    def createMainPanel(self):
        wx.CallAfter(self.init_larch)
        mainpanel = wx.Panel(self)
        mainsizer = wx.BoxSizer(wx.VERTICAL)
        panel = wx.Panel(mainpanel)

        self.yops = [[],[]]
        self.yarr = [[],[]]
        arr_kws= {'choices':[], 'size':(120, -1), 'action':self.onPlot}

        self.title = SimpleText(panel, 'initializing...',
                                font=Font(13), colour='#880000')
        self.xarr = add_choice(panel, **arr_kws)
        for i in range(3):
            self.yarr[0].append(add_choice(panel, **arr_kws))
            self.yarr[1].append(add_choice(panel, **arr_kws))

        for opts, sel, wid in ((PRE_OPS, 0, 100), (ARR_OPS, 3, 60),
                               (ARR_OPS, 3, 60)):
            arr_kws['choices'] = opts
            arr_kws['size'] = (wid, -1)
            self.yops[0].append(add_choice(panel, default=sel, **arr_kws))
            self.yops[1].append(add_choice(panel, default=sel, **arr_kws))

        # place widgets
        sizer = wx.GridBagSizer(5, 10)
        sizer.Add(self.title,                  (0, 1), (1, 6), LCEN, 2)
        sizer.Add(SimpleText(panel, '  X ='), (1, 0), (1, 1), CEN, 0)
        sizer.Add(self.xarr,                   (1, 3), (1, 1), RCEN, 0)

        ir = 1
        for i in range(2):
            ir += 1
            label = '  Y%i =' % (i+1)
            sizer.Add(SimpleText(panel, label),  (ir, 0), (1, 1), CEN, 0)
            sizer.Add(self.yops[i][0],           (ir, 1), (1, 1), CEN, 0)
            sizer.Add(SimpleText(panel, '[('),   (ir, 2), (1, 1), CEN, 0)
            sizer.Add(self.yarr[i][0],           (ir, 3), (1, 1), CEN, 0)
            sizer.Add(self.yops[i][1],           (ir, 4), (1, 1), CEN, 0)
            sizer.Add(self.yarr[i][1],           (ir, 5), (1, 1), CEN, 0)
            sizer.Add(SimpleText(panel, ')'),    (ir, 6), (1, 1), LCEN, 0)
            sizer.Add(self.yops[i][2],           (ir, 7), (1, 1), CEN, 0)
            sizer.Add(self.yarr[i][2],           (ir, 8), (1, 1), CEN, 0)
            sizer.Add(SimpleText(panel, ']'),    (ir, 9), (1, 1), LCEN, 0)
        ir += 1
        sizer.Add(hline(panel),   (ir, 0), (1, 12), CEN|wx.GROW|wx.ALL, 0)
        pack(panel, sizer)


        self.plotpanel = PlotPanel(mainpanel, size=(520, 550),
                                   axissize=(0.18, 0.18, 0.70, 0.70),
                                   fontsize=8)

        self.plotpanel.messenger = self.write_message
        self.plotpanel.canvas.figure.set_facecolor((0.98,0.98,0.97))
        self.plotpanel.unzoom     = self.unzoom
        self.plotpanel.popup_menu = None
        
        btnsizer = wx.StdDialogButtonSizer()
        btnpanel = wx.Panel(mainpanel)
        btnsizer.Add(add_button(btnpanel, 'Pause', action=self.onPause))
        btnsizer.Add(add_button(btnpanel, 'Resume', action=self.onResume))
        btnsizer.Add(add_button(btnpanel, 'Abort', action=self.onAbort))
        btnsizer.Add(add_button(btnpanel, 'Unzoom', action=self.unzoom))
        pack(btnpanel, btnsizer)

        mainsizer.Add(panel,   0, LCEN|wx.EXPAND, 2)
        mainsizer.Add(self.plotpanel, 1, wx.GROW|wx.ALL, 1)
        mainsizer.Add(btnpanel, 0, wx.GROW|wx.ALL, 1)

        pack(mainpanel, mainsizer)
        return mainpanel

    def onPause(self, evt=None):
        self.scandb.set_info('request_pause', 1)

    def onResume(self, evt=None):
        self.scandb.set_info('request_pause', 0)

    def onAbort(self, evt=None):
        self.scandb.set_info('request_abort', 1)

    def CreateFitPanel(self, parent):
        p = panel = wx.Panel(parent)
        self.fit_model   = add_choice(panel, size=(100, -1),
                                      choices=('Gaussian', 'Lorentzian',
                                               'Voigt', 'Linear', 'Quadratic',
                                               'Step', 'Rectangle',
                                               'Exponential'))
        self.fit_bkg = add_choice(panel, size=(100, -1),
                                  choices=('None', 'constant', 'linear', 'quadtratic'))
        self.fit_step = add_choice(panel, size=(100, -1),
                                  choices=('linear', 'error function', 'arctan'))

        self.fit_report = wx.StaticText(panel, -1, "", (180, 200))
        sizer = wx.GridBagSizer(10, 4)
        sizer.Add(SimpleText(p, 'Fit Model: '),           (0, 0), (1, 1), LCEN)
        sizer.Add(self.fit_model,                         (0, 1), (1, 1), LCEN)

        sizer.Add(SimpleText(p, 'Background: '),          (1, 0), (1, 1), LCEN)
        sizer.Add(self.fit_bkg,                           (1, 1), (1, 1), LCEN)

        sizer.Add(SimpleText(p, 'Step Function Form: '),  (2, 0), (1, 1), LCEN)
        sizer.Add(self.fit_step,                          (2, 1), (1, 1), LCEN)
        sizer.Add(add_button(panel, 'Show Fit', size=(100, -1),
                             action=self.onFitPeak),       (3, 0), (1, 1), LCEN)
        sizer.Add(self.fit_report,                         (0, 2), (4, 2), LCEN, 3)
        pack(panel, sizer)
        return panel

    def CreateXASPanel(self, parent):
        p = panel = wx.Panel(parent)
        self.xas_autoe0   = check(panel, default=True, label='auto?')
        self.xas_autostep = check(panel, default=True, label='auto?')
        self.xas_op       = add_choice(panel, size=(95, -1),
                                       choices=('Raw Data', 'Pre-edged',
                                                'Normalized', 'Flattened'))
        self.xas_e0   = FloatCtrl(panel, value  = 0, precision=3, size=(95, -1))
        self.xas_step = FloatCtrl(panel, value  = 0, precision=3, size=(95, -1))
        self.xas_pre1 = FloatCtrl(panel, value=-200, precision=1, size=(95, -1))
        self.xas_pre2 = FloatCtrl(panel, value= -30, precision=1, size=(95, -1))
        self.xas_nor1 = FloatCtrl(panel, value=  30, precision=1, size=(95, -1))
        self.xas_nor2 = FloatCtrl(panel, value= 300, precision=1, size=(95, -1))
        self.xas_vict = add_choice(panel, size=(50, -1), choices=('0', '1', '2', '3'))
        self.xas_nnor = add_choice(panel, size=(50, -1), choices=('0', '1', '2', '3'))
        self.xas_vict.SetSelection(1)
        self.xas_nnor.SetSelection(2)
        sizer = wx.GridBagSizer(10, 4)

        sizer.Add(SimpleText(p, 'Plot XAS as: '),         (0, 0), (1, 1), LCEN)
        sizer.Add(SimpleText(p, 'E0 : '),                 (1, 0), (1, 1), LCEN)
        sizer.Add(SimpleText(p, 'Edge Step: '),           (2, 0), (1, 1), LCEN)
        sizer.Add(SimpleText(p, 'Pre-edge range: '),      (3, 0), (1, 1), LCEN)
        sizer.Add(SimpleText(p, 'Normalization range: '), (4, 0), (1, 1), LCEN)

        sizer.Add(self.xas_op,                 (0, 1), (1, 1), LCEN)
        sizer.Add(self.xas_e0,                 (1, 1), (1, 1), LCEN)
        sizer.Add(self.xas_step,               (2, 1), (1, 1), LCEN)
        sizer.Add(self.xas_pre1,               (3, 1), (1, 1), LCEN)
        sizer.Add(SimpleText(p, ':'),          (3, 2), (1, 1), LCEN)
        sizer.Add(self.xas_pre2,               (3, 3), (1, 1), LCEN)
        sizer.Add(self.xas_nor1,               (4, 1), (1, 1), LCEN)
        sizer.Add(SimpleText(p, ':'),          (4, 2), (1, 1), LCEN)
        sizer.Add(self.xas_nor2,               (4, 3), (1, 1), LCEN)

        sizer.Add(self.xas_autoe0,             (1, 2), (1, 2), LCEN)
        sizer.Add(self.xas_autostep,           (2, 2), (1, 2), LCEN)

        sizer.Add(SimpleText(p, 'Victoreen:'), (3, 4), (1, 1), LCEN)
        sizer.Add(self.xas_vict,               (3, 5), (1, 1), LCEN)
        sizer.Add(SimpleText(p, 'PolyOrder:'), (4, 4), (1, 1), LCEN)
        sizer.Add(self.xas_nnor,               (4, 5), (1, 1), LCEN)

        pack(panel, sizer)
        return panel

    def onFitPeak(self, evt=None):
        gname = self.groupname
        if self.dtcorr.IsChecked():
            print 'fit needs to dt correct!'

        dtext = []
        model = self.fit_model.GetStringSelection().lower()
        dtext.append('Fit Model: %s' % model)
        bkg =  self.fit_bkg.GetStringSelection()
        if bkg == 'None':
            bkg = None
        if bkg is None:
            dtext.append('No Background')
        else:
            dtext.append('Background: %s' % bkg)

        step = self.fit_step.GetStringSelection().lower()
        if model in ('step', 'rectangle'):
            dtext.append('Step form: %s' % step)
        lgroup =  getattr(self.larch.symtable, gname)
        x = lgroup.arr_x
        y = lgroup.arr_y1
        pgroup = fit_peak(x, y, model, background=bkg, step=step,
                          _larch=self.larch)
        text = fit_report(pgroup.params, _larch=self.larch)
        dtext.append('Parameters: ')
        for pname in dir(pgroup.params):
            par = getattr(pgroup.params, pname)
            if isParameter(par):
                ptxt = "    %s= %.4f" % (par.name, par.value)
                if (hasattr(par, 'stderr') and par.stderr is not None):
                    ptxt = "%s(%.4f)" % (ptxt, par.stderr)
                dtext.append(ptxt)

        dtext = '\n'.join(dtext)

        text = fit_report(pgroup.params, _larch=self.larch)
        self.fit_report.SetLabel(dtext)

    def xas_process(self, gname, plotopts):
        """ process (pre-edge/normalize) XAS data from XAS form, overwriting
        larch group '_y1_' attribute to be plotted
        """
        print 'Process XAS ', gname
        out = self.xas_op.GetStringSelection().lower() # raw, pre, norm, flat
        if out.startswith('raw'):
            return plotopts

        preopts = {'group': gname, 'e0': None, 'step': None}

        lgroup = getattr(self.larch.symtable, gname)

        if self.dtcorr.IsChecked():
            print 'need to dt correct!'

        if not self.xas_autoe0.IsChecked():
            xmin, xmax = min(lgroup.arr_x),  max(lgroup.arr_x)
            e0 = self.xas_e0.GetValue()
            if e0 < xmax and e0 > xmin:
                preopts['e0'] = e0

        if not self.xas_autostep.IsChecked():
            preopts['step'] = self.xas_step.GetValue()

        preopts['pre1']  = self.xas_pre1.GetValue()
        preopts['pre2']  = self.xas_pre2.GetValue()
        preopts['norm1'] = self.xas_nor1.GetValue()
        preopts['norm2'] = self.xas_nor2.GetValue()

        preopts['nvict'] = self.xas_vict.GetSelection()
        preopts['nnorm'] = self.xas_nnor.GetSelection()

        preopts = ", ".join(["%s=%s" %(k, v) for k,v in preopts.items()])
        preedge_cmd = "pre_edge(%s._x1_, %s._y1_, %s)" % (gname, gname, preopts)

        self.larch(preedge_cmd)

        self.xas_e0.SetValue(lgroup.e0)
        self.xas_step.SetValue(lgroup.edge_step)

        if out.startswith('pre'):
            self.larch('%s._y1_ = %s.norm * %s.edge_step' % (gname, gname, gname))
        elif out.startswith('norm'):
            self.larch('%s._y1_ = %s.norm' % (gname, gname))
        elif out.startswith('flat'):
            self.larch('%s._y1_ = %s.flat' % (gname, gname))

        return plotopts

    def init_larch(self):
        t0 = time.time()
        from larch.wxlib import inputhook
        self.larch = Interpreter()
        self.larch.symtable.set_symbol('_sys.wx.wxapp', wx.GetApp())
        self.larch.symtable.set_symbol('_sys.wx.parent', self)
        self.larch('%s = group(filename="%s")' % (SCANGROUP, CURSCAN))
        self.larch('_sys.localGroup = %s)' % (SCANGROUP))
        self.lgroup =  getattr(self.larch.symtable, SCANGROUP)
        self.SetStatusText('ready')
        self.title.SetLabel('')

    def write_message(self, s, panel=0):
        """write a message to the Status Bar"""
        self.SetStatusText(s, panel)

    def onPlot(self, evt=None, npts=None):
        """drow plot of newest data"""

        new_plot = self.force_newplot or npts < 3
        lgroup, gname = self.lgroup, SCANGROUP

        ix = self.xarr.GetSelection()
        x  = self.xarr.GetStringSelection()
        xlabel = x
        popts = {'labelfontsize': 8, 'xlabel': x}
        try:
            xunits = lgroup.array_units[ix]
            xlabel = '%s (%s)' % (xlabel, xunits)
        except:
            pass

        def make_array(wids, iy):
            gn  = SCANGROUP
            op1 = self.yops[iy][0].GetStringSelection()
            op2 = self.yops[iy][1].GetStringSelection()
            op3 = self.yops[iy][2].GetStringSelection()
            yy1 = self.yarr[iy][0].GetStringSelection()
            yy2 = self.yarr[iy][1].GetStringSelection()
            yy3 = self.yarr[iy][2].GetStringSelection()

            if yy1 in ('0', '1', '', None) or len(yy1) < 0:
                return '', ''
            label = yy1
            expr = "%s.%s"  % (gn, yy1)

            if yy2 != '':
                label = "%s%s%s" % (label, op2, yy2)
                expr = "%s%s" % (expr, op2)
                if yy2 in ('1.0', '0.0'):
                    expr = "%s%s" % (expr, yy2)
                else:
                    expr = "%s%s.%s"  % (expr, gn, yy2)

            if yy3 != '':
                label = "(%s)%s%s" % (label, op3, yy3)
                expr = "(%s)%s" % (expr, op3)                
                if yy3 in ('1.0', '0.0'):
                    expr = "%s%s"  % (expr, yy3)                
                else:
                    expr = "%s%s.%s" % (expr, gn, yy3)

            if op1 != '':
                label = "%s(%s)" % (op1, label)
                expr  = "%s(%s)" % (op1, expr)
            return label, expr

        ylabel, yexpr = make_array(self.yops, 0)
        if yexpr == '':
            return
        self.larch("%s.arr_x = %s.%s" % (gname, gname, x))
        self.larch("%s.arr_y1 = %s"   % (gname, yexpr))
        try:
            npts = min(len(lgroup.arr_x), len(lgroup.arr_y1))
        except AttributeError:
            return

        y2label, y2expr = make_array(self.yops, 1)
        if y2expr != '':
            self.larch("%s.arr_y2 = %s" % (gname, y2expr))
            n2pts = npts
            try:
                n2pts = min(len(lgroup.arr_x), len(lgroup.arr_y1),
                            len(lgroup.arr_y2))
                lgroup.arr_y2 = np.array( lgroup.arr_y2[:n2pts])
            except:
                y2expr = ''
            npts = n2pts
            print "MAKE Y2EXPR NPTS ", npts

        lgroup.arr_y1 = np.array( lgroup.arr_y1[:npts])
        lgroup.arr_x  = np.array( lgroup.arr_x[:npts])

        path, fname = os.path.split(self.live_scanfile)
        popts.update({'title': fname, 'xlabel': xlabel,
                      'ylabel': ylabel, 'y2label': y2label})

        ppnl = self.plotpanel
        if new_plot:
            ppnl.plot(lgroup.arr_x, lgroup.arr_y1,
                      label= "%s: %s" % (fname, ylabel), **popts)
            if y2expr != '':
                ppnl.oplot(lgroup.arr_x, lgroup.arr_y2, side='right',
                           label= "%s: %s" % (fname, y2label), **popts)
            ppnl.canvas.draw()
        else:
            ppnl.set_xlabel(xlabel)
            ppnl.set_ylabel(ylabel)
            ppnl.update_line(0, lgroup.arr_x, lgroup.arr_y1, draw=True,
                             update_limits=True)
            ax = ppnl.axes
            ppnl.user_limits[ax] = (min(lgroup.arr_x),  max(lgroup.arr_x),
                                    min(lgroup.arr_y1), max(lgroup.arr_y1))

#             xlo, xhi = min(lgroup.arr_x), max(lgroup.arr_x)
#             ylo, yhi = min(lgroup.arr_y1), max(lgroup.arr_y1)
#             ppnl.conf.set_trace_datarange([xlo, xhi, ylo, yhi], 0)
# 
#             for ax in ppnl.fig.get_axes():
#                 ppnl.data_range[ax] = [xlo, xhi, ylo, yhi]
#                 ax.set_xlim((xlo, xhi),  emit=True)
#                 ax.set_ylim((ylo, yhi), emit=True)

            ### 
            if y2expr != '':
                ppnl.set_y2label(y2label)
                ppnl.update_line(1, lgroup.arr_x, lgroup.arr_y2, side='right',
                                 draw=True, update_limits=True)
                ax = ppnl.get_right_axes()
                ppnl.user_limits[ax] = (min(lgroup.arr_x), max(lgroup.arr_x),
                                        min(lgroup.arr_y2), max(lgroup.arr_y2))

        self.force_newplot = False
        

    def createMenus(self):
        self.menubar = wx.MenuBar()
        #
        fmenu = wx.Menu()
        pmenu = wx.Menu()
        fmenu.AppendSeparator()
        add_menu(self, fmenu, "&Quit\tCtrl+Q", "Quit program", self.onClose)

        self.menubar.Append(fmenu, "&File")

        fmenu.AppendSeparator()
        add_menu(self, fmenu, "&Copy\tCtrl+C",  "Copy to Clipboard", self.onClipboard)
        add_menu(self, fmenu, "&Save\tCtrl+S", "Save Figure",   self.onSaveFig)
        add_menu(self, fmenu, "&Print\tCtrl+P", "Print Figure", self.onPrint)
        add_menu(self, fmenu, "Page Setup", "Print Page Setup", self.onPrintSetup)
        add_menu(self, fmenu, "Preview", "Print Preview",       self.onPrintPreview)
        #

        add_menu(self, pmenu, "Configure\tCtrl+K",
                 "Configure Plot", self.onConfigurePlot)
        add_menu(self, pmenu, "Unzoom\tCtrl+Z", "Unzoom Plot", self.unzoom)
        pmenu.AppendSeparator()
        add_menu(self, pmenu, "Toggle Legend\tCtrl+L",
                 "Toggle Legend on Plot", self.onToggleLegend)
        add_menu(self, pmenu, "Toggle Grid\tCtrl+G",
                 "Toggle Grid on Plot", self.onToggleGrid)

        self.menubar.Append(pmenu, "Plot Options")
        self.SetMenuBar(self.menubar)

    def onClipboard(self, evt=None):
        self.plotpanel.canvas.Copy_to_Clipboard(evt)

    def onSaveFig(self, evt=None):
        self.plotpanel.save_figure(event=evt,
                                   transparent=True, dpi=300)

    def onPrint(self, evt=None):
        self.plotpanel.Print(evet)

    def onPrintSetup(self, evt=None):
        self.plotpanel.PrintSetup(evt)

    def onPrintPreview(self, evt=None):
        self.plotpanel.PrintPreview(evt)

    def onConfigurePlot(self, evt=None):
        self.plotpanel.configure(evt)

    def unzoom(self, event=None, **kwargs):
        ppnl = self.plotpanel
        ppnl.zoom_lims = []
        ppnl.set_viewlimits()
        self.force_newplot = True
        self.onPlot()

    def onToggleLegend(self, evt=None):
        self.plotpanel.toggle_legend(evt)

    def onToggleGrid(self, evt=None):
        self.plotpanel.toggle_grid(evt)

    def onAbout(self,evt):
        dlg = wx.MessageDialog(self, self._about,"About Epics StepScan",
                               wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    def onClose(self,evt):
        for obj in self.plotters:
            try:
                obj.Destroy()
            except:
                pass
        for nam in dir(self.larch.symtable._sys.wx):
            obj = getattr(self.larch.symtable._sys.wx, nam)
            del obj

        self.Destroy()

class ScanViewerApp(wx.App, wx.lib.mixins.inspection.InspectionMixin):
    def __init__(self, dbname=None, server='sqlite', host=None,
                 port=None, user=None, password=None, create=True, **kws):

        self.db_opts = dict(dbname=dbname, server=server, host=host,
                            port=port, create=create, user=user,
                            password=password)
        self.db_opts.update(kws)
        wx.App.__init__(self)

    def OnInit(self):
        self.Init()
        frame = ScanViewerFrame(self, **self.db_opts)
        frame.Show()
        self.SetTopWindow(frame)
        return True

if __name__ == "__main__":
    ViewerApp().MainLoop()
