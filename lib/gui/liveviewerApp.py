#!/usr/bin/env python
"""
GUI for displaying live plots of column data from StepScan Data objects

Principle features:
   frame for plot a file, with math on right/left columns
"""
import os
import time
import shutil
import json
import logging
import numpy as np
from random import randrange

import wx
import wx.lib.agw.flatnotebook as flat_nb
import wx.lib.scrolledpanel as scrolled
import wx.lib.mixins.inspection
try:
    from wx._core import PyDeadObjectError
except:
    PyDeadObjectError = Exception

import epics
from epics.wx import DelayedEpicsCallback, EpicsFunction

from ..larch_interface import LarchScanDBServer

from wxmplot import PlotFrame, PlotPanel
from ..datafile import StepScanData
from ..scandb import ScanDB
from ..file_utils import fix_filename, fix_varname

from .gui_utils import (SimpleText, FloatCtrl, Closure, pack, add_button,
                        add_menu, add_choice, add_menu, check, hline,
                        CEN, RCEN, LCEN, FRAMESTYLE, Font, hms, popup)

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

    def __init__(self, parent, dbname=None, server='sqlite', 
                 host=None, port=None, user=None, password=None,
                 create=True, _larch=None, scandb=None, **kws):

        wx.Frame.__init__(self, None, -1, style=FRAMESTYLE)
        title = "Epics Step Scan Viewer"
        self.parent = parent
        self.scandb = getattr(parent, 'scandb', None)
        if self.scandb is None and dbname is not None:
            self.scandb = ScanDB(dbname=dbname, server=server, host=host,
                                 user=user, password=password, port=port,
                                 create=create)
        self.larch = _larch
        if _larch is None:
            self.larch = LarchScanDBServer(self.scandb)

        self.lgroup = None
        self.larch.run("%s = group(filename='%s')" % (SCANGROUP, CURSCAN))
        self.larch.run("_sys.localGroup = %s" % (SCANGROUP))
        # self.larch.run("show(_sys)")
        self.lgroup =  self.larch.get_symbol(SCANGROUP)
        self.last_cpt = -1
        self.force_newplot = False
        self.scan_inprogress = False
        self.last_plot_update = 0.0
        self.need_column_update = True
        self.positioner_pvs = {}
        self.x_cursor = None
        self.x_label = None
        self.SetTitle(title)
        self.SetSize((800, 700))
        self.SetFont(Font(9))
        self.createMainPanel()
        self.createMenus()
        self.last_status_msg = None
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
            self.scantimer.Start(300)
        self.Bind(wx.EVT_CLOSE, self.onClose)
        self.Show()
        self.SetStatusText('ready')
        self.title.SetLabel('')
        self.Raise()

    def onScanTimer(self, evt=None,  **kws):
        if self.lgroup is None:
            return
        try:
            curfile   = fix_filename(self.get_info('filename'))
            sdata     = self.scandb.get_scandata()
            scan_stat = self.get_info('scan_status')
            msg       = self.get_info('scan_progress')
        except:
            logging.exception("No Scan at ScanTime")
            return
        if msg is None:
            return
        try:
            # npts = len(sdata[-1].data)
            nptsall = [len(s.data) for s in sdata]
            npts = min(nptsall)
        except:
            npts = 0
        if npts <= 0 or msg.lower().startswith('preparing'):
            self.need_column_update = True

        do_newplot = False

        if ((curfile != self.live_scanfile) or
            (npts > 0 and npts < 3 and self.need_column_update)):
            self.need_column_update = False
            self.scan_inprogress = True
            self.moveto_btn.Disable()
            do_newplot = True
            self.live_scanfile = curfile
            self.title.SetLabel(curfile)
            if len(sdata)>1:
                self.set_column_names(sdata)

        elif msg.lower().startswith('scan complete') and self.scan_inprogress:
            self.scan_inprogress = False
            self.moveto_btn.Enable()
            do_newplot = True
        elif msg.lower().startswith('scan abort'):
            self.moveto_btn.Enable()
            do_newplot = True

        if msg != self.last_status_msg:
            self.last_status_msg = msg
            self.SetStatusText(msg)

        # print(" Scan Timer ", do_newplot, npts)
        if not (self.scan_inprogress or do_newplot):
            # print 'Scan Timer no reason to plot', do_newplot, self.scan_inprogress
            return

        for row in sdata:
            dat = row.data
            if self.scandb_server == 'sqlite':
                dat = json.loads(dat.replace('{', '[').replace('}', ']'))
            dat = np.array(dat)
            if len(dat) > npts:
                dat = dat[:npts]
            setattr(self.lgroup, fix_varname(row.name), dat)

        if ((npts > 1 and npts != self.live_cpt)  or
            (time.time() - self.last_plot_update) > 15.0):
            if do_newplot:
                self.force_newplot = True
            self.onPlot(npts=npts)
            self.last_plot_update = time.time()
        self.live_cpt = npts
        # print(" Scan Timer ", do_newplot, npts)


    def set_column_names(self, sdata):
        """set column names from values read from scandata table"""
        if len(sdata) < 1:
            return
        try:
            self.lgroup.array_units = [fix_varname(s.units) for s in sdata]
        except:
            return
        self.total_npts = self.get_info('scan_total_points', as_int=True)
        self.live_cpt = -1
        xcols, ycols, y2cols = [], [], []
        self.positioner_pvs = {}
        for s in sdata:
            nam = fix_varname(s.name)
            ycols.append(nam)
            if s.notes.lower().startswith('pos'):
                xcols.append(nam)
                self.positioner_pvs[nam] = s.pvname
        # print("SET COLUMN NAMES", xcols, self.positioner_pvs)

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
                # print(i, j, yold, yold in cols)
                iy = cols.index(yold) if yold in cols else idef
                self.yarr[i][j].SetSelection(iy)
        time.sleep(0.75)


    def createMainPanel(self):
        mainpanel = wx.Panel(self)
        mainsizer = wx.BoxSizer(wx.VERTICAL)
        panel = wx.Panel(mainpanel)

        self.yops = [[],[]]
        self.yarr = [[],[]]
        arr_kws= {'choices':[], 'size':(150, -1), 'action':self.onPlot}

        self.title = SimpleText(panel, 'initializing...',
                                font=Font(13), colour='#880000')
        self.xarr = add_choice(panel, **arr_kws)
        for i in range(3):
            self.yarr[0].append(add_choice(panel, **arr_kws))
            self.yarr[1].append(add_choice(panel, **arr_kws))

        for opts, sel, wid in ((PRE_OPS, 0, 80),
                               (ARR_OPS, 3, 40),
                               (ARR_OPS, 3, 40)):
            arr_kws['choices'] = opts
            arr_kws['size'] = (wid, -1)
            self.yops[0].append(add_choice(panel, default=sel, **arr_kws))
            self.yops[1].append(add_choice(panel, default=sel, **arr_kws))

        # place widgets
        sizer = wx.GridBagSizer(5, 10)
        sizer.Add(self.title,                  (0, 1), (1, 6), LCEN, 2)
        sizer.Add(SimpleText(panel, '  X ='),  (1, 0), (1, 1), CEN, 0)
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


        self.plotpanel = PlotPanel(mainpanel, size=(520, 550), fontsize=8)
        self.plotpanel.cursor_callback = self.onLeftDown
        self.plotpanel.messenger = self.write_message
        self.plotpanel.canvas.figure.set_facecolor((0.98,0.98,0.97))
        self.plotpanel.unzoom     = self.unzoom
        # self.plotpanel.popup_menu = None

        btnsizer = wx.StdDialogButtonSizer()
        btnpanel = wx.Panel(mainpanel)
        self.moveto_btn = add_button(btnpanel, 'Move To Position', action=self.onMoveTo)

        btnsizer.Add(add_button(btnpanel, 'Pause Scan', action=self.onPause))
        btnsizer.Add(add_button(btnpanel, 'Resume Scan', action=self.onResume))
        btnsizer.Add(add_button(btnpanel, 'Abort Scan', action=self.onAbort))
        btnsizer.Add(add_button(btnpanel, 'Unzoom Plot', action=self.unzoom))
        btnsizer.Add(self.moveto_btn)
        pack(btnpanel, btnsizer)

        mainsizer.Add(panel,   0, LCEN|wx.EXPAND, 2)
        mainsizer.Add(self.plotpanel, 1, wx.GROW|wx.ALL, 1)
        mainsizer.Add(btnpanel, 0, wx.GROW|wx.ALL, 1)

        pack(mainpanel, mainsizer)
        return mainpanel


    def onMoveTo(self, evt=None):
        pvname = self.positioner_pvs.get(self.x_label, None)

        if pvname is not None and self.x_cursor is not None:
            msg = " Move To Position:\n  %s (%s) to %.4f " % (self.x_label,
                                                              pvname,
                                                              self.x_cursor)
            ret = popup(self, msg, "Move to Position?",
                        style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION)
            if ret == wx.ID_YES:
                epics.caput(pvname, self.x_cursor)

    def onPause(self, evt=None):
        self.scandb.set_info('request_pause', 1)

    def onResume(self, evt=None):
        self.scandb.set_info('request_pause', 0)

    def onAbort(self, evt=None):
        self.scandb.set_info('request_abort', 1)

    def write_message(self, s, panel=0):
        """write a message to the Status Bar"""
        self.SetStatusText(s, panel)

    def onLeftDown(self, x=None, y=None):
        self.x_cursor = x

    def onPlot(self, evt=None, npts=None):
        """draw plot of newest data"""
        if npts is None:
            npts = 0
        new_plot = self.force_newplot or npts < 3
        lgroup, gname = self.lgroup, SCANGROUP

        ix = self.xarr.GetSelection()
        x  = self.xarr.GetStringSelection()
        self.x_label = x
        xlabel = x
        popts = {'labelfontsize': 8, 'xlabel': x,
                 'marker':'o', 'markersize':4}

        try:
            xunits = lgroup.array_units[ix]
            xlabel = '%s (%s)' % (xlabel, xunits)
        except:
            logging.exception("No units at onPlot")
            return
        
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
                end = ''
                if '(' in op1: end = ')'
                label = "%s(%s)%s" % (op1, label, end)
                expr  = "%s(%s)%s" % (op1, expr, end)
            return label, expr

        ylabel, yexpr = make_array(self.yops, 0)
        if yexpr == '':
            return
        self.larch.run("%s.arr_x = %s.%s" % (gname, gname, x))
        self.larch.run("%s.arr_y1 = %s"   % (gname, yexpr))
        # print(" on Plot ", "%s.arr_y1 = %s"   % (gname, yexpr))
        # print(" on Plot ", len(lgroup.arr_x), len(lgroup.arr_y1))
        try:
            npts = min(len(lgroup.arr_x), len(lgroup.arr_y1))
        except AttributeError:
            logging.exception("Problem getting arrays")

        y2label, y2expr = make_array(self.yops, 1)
        if y2expr != '':
            self.larch.run("%s.arr_y2 = %s" % (gname, y2expr))
            n2pts = npts
            try:
                n2pts = min(len(lgroup.arr_x), len(lgroup.arr_y1),
                            len(lgroup.arr_y2))
                lgroup.arr_y2 = np.array( lgroup.arr_y2[:n2pts])
            except:
                y2expr = ''
            npts = n2pts

        lgroup.arr_y1 = np.array( lgroup.arr_y1[:npts])
        lgroup.arr_x  = np.array( lgroup.arr_x[:npts])

        path, fname = os.path.split(self.live_scanfile)
        popts.update({'title': fname, 'xlabel': xlabel,
                      'ylabel': ylabel, 'y2label': y2label})
        if len(lgroup.arr_x) < 2 or len(lgroup.arr_y1) < 2:
            return

        if len(lgroup.arr_x) != len(lgroup.arr_y1):
            print( 'data length mismatch ', len(lgroup.arr_x), len(lgroup.arr_y1))
            return
        ppnl = self.plotpanel
        if new_plot:
            ppnl.conf.zoom_lims = []
            ppnl.plot(lgroup.arr_x, lgroup.arr_y1,
                      label= "%s: %s" % (fname, ylabel), **popts)
            if y2expr != '':
                ppnl.oplot(lgroup.arr_x, lgroup.arr_y2, side='right',
                           label= "%s: %s" % (fname, y2label), **popts)
            xmin, xmax = min(lgroup.arr_x), max(lgroup.arr_x)
            ppnl.axes.set_xlim((xmin, xmax), emit=True)
            ppnl.canvas.draw()
        else:
            ppnl.set_xlabel(xlabel)
            ppnl.set_ylabel(ylabel)
            ppnl.update_line(0, lgroup.arr_x, lgroup.arr_y1, draw=True,
                             update_limits=True)
            ax = ppnl.axes
            ppnl.user_limits[ax] = (min(lgroup.arr_x),  max(lgroup.arr_x),
                                    min(lgroup.arr_y1), max(lgroup.arr_y1))

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
        omenu = wx.Menu()

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

        add_menu(self, omenu, "Enable Move To Position", "Force Enable of Move To Position",
                 self.onForceEnableMoveTo)

        add_menu(self, pmenu, "Force Replot\tCtrl+F", "Replot", self.onForceReplot)

        add_menu(self, pmenu, "Configure\tCtrl+K",
                 "Configure Plot", self.onConfigurePlot)
        add_menu(self, pmenu, "Unzoom\tCtrl+Z", "Unzoom Plot", self.unzoom)
        pmenu.AppendSeparator()
        add_menu(self, pmenu, "Toggle Legend\tCtrl+L",
                 "Toggle Legend on Plot", self.onToggleLegend)
        add_menu(self, pmenu, "Toggle Grid\tCtrl+G",
                 "Toggle Grid on Plot", self.onToggleGrid)

        self.menubar.Append(omenu, "Options")
        self.menubar.Append(pmenu, "Plot")
        self.SetMenuBar(self.menubar)

    def onForceEnableMoveTo(self, evt=None):
        self.moveto_btn.Enable()

    def onForceReplot(self, evt=None):
        self.force_newplot = True
        self.onPlot()

    def onClipboard(self, evt=None):
        self.plotpanel.canvas.Copy_to_Clipboard(evt)

    def onSaveFig(self, evt=None):
        self.plotpanel.save_figure(event=evt,
                                   transparent=True, dpi=300)

    def onPrint(self, evt=None):
        self.plotpanel.Print(evt)

    def onPrintSetup(self, evt=None):
        self.plotpanel.PrintSetup(evt)

    def onPrintPreview(self, evt=None):
        self.plotpanel.PrintPreview(evt)

    def onConfigurePlot(self, evt=None):
        self.plotpanel.configure(evt)

    def unzoom(self, event=None, **kwargs):
        ppnl = self.plotpanel
        ppnl.conf.zoom_lims = []
        ppnl.user_limits = {}
        ppnl.user_limits[ppnl.axes] = (None, None, None, None)
        ppnl.user_limits[ppnl.get_right_axes()] = (None, None, None, None)
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

    def onClose(self, evt=None):
        self.scantimer.Stop()
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
