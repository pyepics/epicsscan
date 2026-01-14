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

import epics
from epics.wx import DelayedEpicsCallback, EpicsFunction

from ..macro_kernel import MacroKernel

from wxmplot import PlotFrame, PlotPanel
from ..datafile import StepScanData
from ..scandb import ScanDB
from ..file_utils import fix_filename, fix_varname

from .gui_utils import (SimpleText, FloatCtrl, pack, add_button,
                        add_menu, add_choice, add_menu, check, hline,
                        CEN, RIGHT, LEFT, FRAMESTYLE, Font, hms, popup, GUIColors)

CEN |=  wx.ALL
FILE_WILDCARDS = "Scan Data Files(*.0*,*.dat,*.xdi)|*.0*;*.dat;*.xdi|All files (*.*)|*.*"
FNB_STYLE = flat_nb.FNB_NO_X_BUTTON|flat_nb.FNB_SMART_TABS|flat_nb.FNB_NO_NAV_BUTTONS


PRE_OPS = ('', 'log', '-log', 'deriv', '-deriv', 'deriv(log', 'deriv(-log')
ARR_OPS = ('+', '-', '*', '/')

def randname(n=6):
    "return random string of n (default 6) lowercase letters"
    return ''.join([chr(randrange(26)+97) for i in range(n)])

CURSCAN= '< Current Scan >'

class ScanViewerFrame(wx.Frame):
    _about = """Scan Viewer,  Matt Newville <newville @ cars.uchicago.edu>  """
    TIME_MSG = 'Point %i/%i, Time Remaining ~ %s, Status=%s'

    def __init__(self, parent, dbname=None, server='sqlite',
                 host=None, port=None, user=None, password=None,
                 create=True, mkernel=None, scandb=None, **kws):

        wx.Frame.__init__(self, None, -1, style=FRAMESTYLE)
        title = "Epics Step Scan Viewer"
        self.parent = parent

        self.scandb = getattr(parent, 'scandb', None)
        self.mkernel = mkernel

        # print("LIVE viewer: ", self.mkernel, self.scandb)
        # print("LIVE: ", self.mkernel.get_symbol('_scandb'))

        if self.scandb is None and dbname is not None:
            self.scandb = ScanDB(dbname=dbname, server=server, host=host,
                                 user=user, password=password, port=port,
                                 create=create)


        if self.mkernel is None:
            self.mkernel = MacroKernel()
        self.mkernel('deriv = diff')

        self.plotdata = {'1': 1, '1.0': 1, '0.0': 0, '0': 0}
        self.plotinfo = {}
        self.last_cpt = -1
        self.force_newplot = False
        self.scan_inprogress = False
        self.last_plot_update = 0.0
        self.need_column_update = True
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
        try:
            curfile   = fix_filename(self.get_info('filename', default='.'))
            sdata     = self.scandb.get_scandata()

            scan_stat = self.get_info('scan_status', default='unknown')
            msg       = self.get_info('scan_progress', default='unknown')
        except:
            logging.exception("No Scan at ScanTime")
            return
        if msg is None:
            return
        npts = -1
        try:
            for s in sdata:
                n = len(s.data)
                if npts == -1:
                    npts = n
                elif n > 0:
                    npts = min(npts, n)
        except:
            npts = -2
        if npts <= 1 or msg.lower().startswith('preparing'):
            self.need_column_update = True

        do_newplot = False
        # print("npts ", npts, self.need_column_update)
        if ((curfile != self.live_scanfile) or
            (npts > 0 and self.need_column_update)):
            self.scan_inprogress = True
            self.moveto_btn.Disable()
            do_newplot = True
            self.live_scanfile = curfile
            self.title.SetLabel(curfile)
            if len(sdata)>1:
                self.set_column_names(sdata)
            self.need_column_update = False

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

        if not (self.scan_inprogress or do_newplot):
            return

        for row in sdata:
            dat = row.data
            if self.scandb_server == 'sqlite':
                dat = json.loads(dat.replace('{', '[').replace('}', ']'))
            dat = np.array(dat)
            if len(dat) > npts:
                dat = dat[:npts]
            self.plotdata[row.name] = dat
        # print("Set plot data ", self.plotdata.keys(), npts, self.live_cpt, do_newplot)

        if ((npts > 1 and npts != self.live_cpt)  or
            (time.time() - self.last_plot_update) > 15.0):
            if do_newplot:
                self.force_newplot = True
            self.onPlot(npts=npts)
            self.last_plot_update = time.time()
        self.live_cpt = npts

    def set_column_names(self, sdata):
        """set column names from values read from scandata table"""
        if len(sdata) < 1:
            return

        self.plotinfo = {'units': {}, 'pvnames': {}, 'notes': {}}
        xcols, ycols, y2cols = [], [], []
        for s in sdata:
            self.plotinfo['units'][s.name] = s.units
            self.plotinfo['pvnames'][s.name] = s.pvname
            self.plotinfo['notes'][s.name] = s.notes
            ycols.append(s.name)
            if s.notes.lower().startswith('pos'):
                xcols.append(s.name)

        self.total_npts = self.get_info('scan_total_points', default=0, as_int=True)
        self.live_cpt = -1


        y2cols = ycols[:] + ['1.0', '0.0', '']
        xarr_old = self.xarr.GetStringSelection()
        self.xarr.SetItems(xcols)
        ix = xcols.index(xarr_old) if xarr_old in xcols else 0
        self.xarr.SetSelection(ix)

        n0 = len(y2cols) - 1
        cols_lower = [yc.lower() for yc in y2cols]
        roinames = json.loads(self.get_info('rois', default='[]'))
        col_roi = col_i0 = 2
        if len(roinames) > 0:
            sumname = fix_varname('Sum_' + roinames[-1]).lower()
            col_roi = cols_lower.index(sumname) if sumname in cols_lower else n0
        for i0name in ('monitor', 'mon', 'io', 'i0'):
            if i0name in cols_lower:
                col_i0 = cols_lower.index(i0name)

        defs = [(col_roi, col_i0), (n0, n0)]
        for i in range(2):
            for j in range(2):
                ycur = self.yarr[i][j].GetStringSelection()
                iy = defs[i][j]
                if ycur not in (None, '', 'None') and ycur in y2cols:
                    iy = y2cols.index(ycur)
                self.yarr[i][j].SetItems(y2cols)
                self.yarr[i][j].SetSelection(iy)
        time.sleep(0.5)

    def createMainPanel(self):
        mainpanel = wx.Panel(self)
        mainsizer = wx.BoxSizer(wx.VERTICAL)
        panel = wx.Panel(mainpanel)
        self.SetBackgroundColour(GUIColors.bg)
        self.yops = [[],[]]
        self.yarr = [[],[]]
        arr_kws= {'choices':[], 'size':(200, -1), 'action':self.onPlot}

        self.title = SimpleText(panel, 'initializing...',
                                font=Font(13), colour='#880000')
        self.xarr = add_choice(panel, **arr_kws)
        for i in range(2):
            self.yarr[0].append(add_choice(panel, **arr_kws))
            self.yarr[1].append(add_choice(panel, **arr_kws))

        for opts, sel, wid in ((PRE_OPS, 0, 125),
                               (ARR_OPS, 3,  80)):
            arr_kws['choices'] = opts
            arr_kws['size'] = (wid, -1)
            self.yops[0].append(add_choice(panel, default=sel, **arr_kws))
            self.yops[1].append(add_choice(panel, default=sel, **arr_kws))

        # place widgets
        sizer = wx.GridBagSizer(3, 3)
        sizer.Add(self.title,                  (0, 1), (1, 6), LEFT, 2)
        sizer.Add(SimpleText(panel, '  X ='),  (1, 0), (1, 1), CEN, 0)
        sizer.Add(self.xarr,                   (1, 3), (1, 1), RIGHT, 0)

        ir = 1
        for i in range(2):
            ir += 1
            label = '  Y%i =' % (i+1)
            sizer.Add(SimpleText(panel, label),  (ir, 0), (1, 1), CEN, 0)
            sizer.Add(self.yops[i][0],           (ir, 1), (1, 1), CEN, 0)
            sizer.Add(SimpleText(panel, '('),    (ir, 2), (1, 1), CEN, 0)
            sizer.Add(self.yarr[i][0],           (ir, 3), (1, 1), CEN, 0)
            sizer.Add(self.yops[i][1],           (ir, 4), (1, 1), CEN, 0)
            sizer.Add(self.yarr[i][1],           (ir, 5), (1, 1), CEN, 0)
            sizer.Add(SimpleText(panel, ')'),    (ir, 6), (1, 1), LEFT, 0)
        ir += 1
        sizer.Add(hline(panel),   (ir, 0), (1, 7), CEN|wx.GROW|wx.ALL, 0)
        pack(panel, sizer)

        self.plotpanel = PlotPanel(mainpanel, size=(520, 550), fontsize=8)
        self.plotpanel.cursor_callback = self.onLeftDown
        self.plotpanel.messenger = self.write_message
        self.plotpanel.canvas.figure.set_facecolor((0.98,0.98,0.97))
        self.plotpanel.unzoom     = self.unzoom

        btnsizer = wx.StdDialogButtonSizer()
        btnpanel = wx.Panel(mainpanel)
        self.moveto_btn = add_button(btnpanel, 'Move To Position', action=self.onMoveTo)

        btnsizer.Add(add_button(btnpanel, 'Pause Scan', action=self.onPause))
        btnsizer.Add(add_button(btnpanel, 'Resume Scan', action=self.onResume))
        btnsizer.Add(add_button(btnpanel, 'Abort Scan', action=self.onAbort))
        btnsizer.Add(add_button(btnpanel, 'Unzoom Plot', action=self.unzoom))
        btnsizer.Add(self.moveto_btn)
        pack(btnpanel, btnsizer)

        mainsizer.Add(panel,   0, LEFT|wx.EXPAND, 2)
        mainsizer.Add(self.plotpanel, 1, wx.GROW|wx.ALL, 1)
        mainsizer.Add(btnpanel, 0, wx.GROW|wx.ALL, 1)

        pack(mainpanel, mainsizer)
        return mainpanel


    def onMoveTo(self, evt=None):
        pvname = self.plotinfo['pvnames'].get(self.x_label, None)

        if pvname is not None and self.x_cursor is not None:
            msg = f" Move PV {pvname.strip()}\n to {self.x_label.strip()} = {self.x_cursor:.4f}"
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

    def onLeftDown(self, x=None, y=None, **kws):
        self.x_cursor = x

    def onPlot(self, evt=None, npts=None):
        """draw plot of newest data"""
        # print("onPlot ", npts)
        if npts is None:
            npts = 0
        new_plot = self.force_newplot or npts < 3

        if self.plotinfo.get('units', None) is None:
            # print("onPlot no units")
            return

        x  = self.xarr.GetStringSelection()
        arrx = self.plotdata.get(x, None)
        if arrx is None:
            logging.exception("no array data for plotting")
            # print("onPlot no x ", x, arrx)
            return

        self.x_label = x
        xlabel = x
        popts = {'labelfontsize': 8, 'xlabel': x,
                 'marker':'o', 'markersize':4}

        xunits = self.plotinfo['units'].get(x, None)
        if xunits is not None:
            xlabel = f'{xlabel} ({xunits})'

        nroot = 'lplt_b'
        def make_array(wids, iy):
            op1 = self.yops[iy][0].GetStringSelection()
            op2 = self.yops[iy][1].GetStringSelection()
            y1 = self.yarr[iy][0].GetStringSelection()
            y2 = self.yarr[iy][1].GetStringSelection()

            label = y1
            expr = f'{nroot}{iy}_1'
            if y2 != '':
                expr = f"{nroot}{iy}_1{op2}{nroot}{iy}_2"
                label = f"{label}{op2}{y2}"

            if op1 != '':
                dend = ')' if '(' in op1 else ''
                expr  = f"{op1}({expr}){dend}"
                label = f"{op1}({label}){dend}"
            return y1, y2, expr, label

        y1, y2, expr, ylabel = make_array(self.yops, 0)
        if y1 in ('0', '1', '', None) or len(y1) < 0:
            return
        self.mkernel.set_symbol(f'{nroot}0_1', self.plotdata.get(y1, 1.0))
        if y2 not in ('', None):
            self.mkernel.set_symbol(f'{nroot}0_2', self.plotdata.get(y2, 1.0))

        self.mkernel.run(f"{nroot}_p1 = {expr}")

        arry1 = self.mkernel.get_symbol(f"{nroot}_p1")

        try:
            npts = min(len(arrx), len(arry1))
        except:
            logging.exception("empty array data for plotting")
            return

        y1, y2, expr2, y2label = make_array(self.yops, 1)
        arry2 = None
        if y1 not in ('0', '1', '', None) and len(y1) > 0 and expr2 != '':
            self.mkernel.set_symbol(f'{nroot}1_1', self.plotdata.get(y1, 1))
            if y2 not in ('1', '', None):
                self.mkernel.set_symbol(f'{nroot}1_2', self.plotdata.get(y2, 1))

            self.mkernel.run(f"{nroot}_p2 = {expr2}")
            arry2 = self.mkernel.get_symbol(f"{nroot}_p2")

            n2pts = npts
            try:
                n2pts = min(len(arrx), len(arry1), len(arry2))
                arry2 = np.array(arry2[:n2pts])
            except:
                pass
            npts = n2pts

        arry1 = np.array(arry1[:npts])
        arrx  = np.array(arrx[:npts])

        path, fname = os.path.split(self.live_scanfile)
        popts.update({'title': fname, 'xlabel': xlabel,
                      'ylabel': ylabel, 'y2label': y2label})
        if len(arrx) < 2 or len(arry1) < 2:
            return

        ppnl = self.plotpanel
        if new_plot:
            # print("Will Plot ", len(arrx), len(arry1), arry1)
            ppnl.conf.zoom_lims = []
            ppnl.plot(arrx, arry1,
                      label= f"{fname}: {ylabel}", **popts)
            if arry2 is not None:
                ppnl.oplot(arrx, arry2, side='right',
                           label= f"{fname}: {y2label}", **popts)
            xmin, xmax = min(arrx), max(arrx)
            ppnl.axes.set_xlim((xmin, xmax), emit=True)
            ppnl.canvas.draw()
        else:
            ppnl.set_xlabel(xlabel)
            ppnl.set_ylabel(ylabel)
            ppnl.update_line(0, arrx, arry1, draw=True,
                             update_limits=True)
            ax = ppnl.axes
            ppnl.user_limits[ax] = (min(arrx),  max(arrx),
                                    min(arry1), max(arry1))

            if arry2 is not None:
                ppnl.set_y2label(y2label)
                ppnl.update_line(1, arrx, arry2, side='right',
                                 draw=True, update_limits=True)
                ax = ppnl.get_right_axes()
                ppnl.user_limits[ax] = (min(arrx), max(arrx),
                                        min(arry2), max(arry2))

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
