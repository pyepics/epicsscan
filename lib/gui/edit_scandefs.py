import sys
import time

import json
import wx
import wx.lib.agw.flatnotebook as flat_nb

import wx.lib.scrolledpanel as scrolled
import  wx.grid as gridlib

from .gui_utils import (GUIColors, set_font_with_children, YesNo,
                        add_button, pack, SimpleText, check, okcancel,
                        add_subtitle, Font, LCEN, CEN, RCEN, FRAMESTYLE)

RCEN |= wx.ALL
LCEN |= wx.ALL
CEN  |= wx.ALL

ALL_CEN =  wx.ALL|wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL
FNB_STYLE = flat_nb.FNB_NO_X_BUTTON|flat_nb.FNB_SMART_TABS|flat_nb.FNB_NO_NAV_BUTTONS

SCANTYPES = ('linear', 'mesh', 'slew', 'xafs')

def buttonrow(panel, onOK=None, onCancel=None):
    btnsizer = wx.StdDialogButtonSizer()
    _ok = wx.Button(panel, wx.ID_OK)
    _no = wx.Button(panel, wx.ID_CANCEL)
    panel.Bind(wx.EVT_BUTTON, onOK,     _ok)
    panel.Bind(wx.EVT_BUTTON, onCancel, _no)
    _ok.SetDefault()
    btnsizer.AddButton(_ok)
    btnsizer.AddButton(_no)
    btnsizer.Realize()
    return btnsizer

def sort_data(dat, sort_col=None, reverse=False):
    if sort_col is None:
        sort_col = len(dat[0])- 2
    # print('SORT ', sort_col, reverse)
    data = sorted(dat, key=lambda x: x[sort_col])
    if reverse:
        data = list(reversed(data))
    # for x in data: print( x)
    return data



class GenericDataTable(gridlib.PyGridTableBase):
    def __init__(self, scandb, stype='linear'):
        gridlib.PyGridTableBase.__init__(self)
        self.scandb = scandb
        self.type = stype.lower()
        self.data = []
        self.scans = []
        self.colLabels = []
        self.dataTypes = []
        self.widths = []        
        self.colReadOnly = []

    def onApplyChanges(self):
        "apply changes -- deletes and renames"
        scandat = {}
        for scan in self.scandb.getall('scandefs'):
            if scan.type.lower().startswith(self.type.lower()):
                mtime = scan.modify_time.strftime("%Y-%b-%d %H:%M")
                utime = scan.last_used_time.strftime("%Y-%b-%d %H:%M")
                scandat[scan.name] =  (scan.id, (mtime, utime))
        
        for dat in self.data:
            name, delOK = dat[0], dat[-1]
            xtime = (dat[-3], dat[-2])
            if delOK == 1 and name in scandat:
                try:
                    self.scandb.del_scandef(scanid=scandat[name][0])
                except:
                    pass
            else:
                for key, val in scandat.items():
                    if xtime == val[1] and key != name:
                        try:
                            self.scandb.rename_scandef(val[0], name)
                        except:
                            pass
                        time.sleep(0.1)
                        

    def onLoadScan(self, row):
        thisscan = self.data[row]
        for scan in self.scandb.getall('scandefs'):
            if (scan.type.lower().startswith(self.type.lower()) and
                scan.name.lower() == thisscan[0].lower()):
                return scan.name
        return ''
    

    def GetNumberRows(self):     return len(self.data) + 1
    def GetNumberCols(self):     return len(self.data[0])
    def GetColLabelValue(self, col):    return self.colLabels[col]
    def GetTypeName(self, row, col):     return self.dataTypes[col]

    def IsEmptyCell(self, row, col):
        try:
            return not self.data[row][col]
        except IndexError:
            return True

    def GetValue(self, row, col):
        try:
            return self.data[row][col]
        except IndexError:
            return ''

    def SetValue(self, row, col, value):
        def innerSetValue(row, col, value):
            try:
                self.data[row][col] = value
            except IndexError:
                pass 
        innerSetValue(row, col, value) 

    def CanGetValueAs(self, row, col, typeName):
        colType = self.dataTypes[col].split(':')[0]
        if typeName == colType:
            return True
        else:
            return False

    def CanSetValueAs(self, row, col, typeName):
        return self.CanGetValueAs(row, col, typeName)



class LinearScanDataTable(GenericDataTable):
    def __init__(self, scans, scandb, stype='Linear'):
        GenericDataTable.__init__(self, scandb, stype)

        self.colLabels = [' Scan Name ', ' Positioner ', ' # Points ',
                          ' Created ', ' Last Used ', ' Erase? ']
        self.dataTypes = [gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_NUMBER,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_BOOL]
        self.set_data(scans)

    def set_data(self, scans, sort_col=None, reverse=False):
        self.scans = scans[::-1]
        _dat = []
        self.widths = [150, 100, 80, 125, 125, 60]
        self.colReadOnly = [False, True, True, True, True, False]
        for scan in self.scans:
            if len(scan.name) < 1:
                continue
            sdat = json.loads(scan.text)
            axis = sdat['positioners'][0][0]
            npts = sdat['positioners'][0][4]
            mtime = scan.modify_time.strftime("%Y-%b-%d %H:%M")
            utime = scan.last_used_time.strftime("%Y-%b-%d %H:%M")
            _dat.append([scan.name, axis, npts, mtime, utime, 0])
        self.data = sort_data(_dat, sort_col=sort_col, reverse=reverse)
                    
                        
class MeshScanDataTable(GenericDataTable):
    def __init__(self, scans, scandb, stype='Mesh'):
        GenericDataTable.__init__(self, scandb, stype)

        self.colLabels = [' Scan Name ', ' Inner Positioner ',
                          ' Outer Positioner ', ' # Points ',
                          ' Created ', ' Last Used ', ' Erase? ']

        self.dataTypes = [gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_NUMBER,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_BOOL]
        self.set_data(scans)

    def set_data(self, scans, sort_col=None, reverse=False):
        self.scans = scans[::-1]
        _dat = []
        self.widths = [150, 100, 100, 80, 125, 125, 60]
        self.colReadOnly = [False, True, True, True, True, True, False]
        for scan in self.scans:
            sdat  = json.loads(scan.text)
            axis0 = sdat['inner'][0]
            axis1 = sdat['outer'][0]
            npts  = int(sdat['outer'][4]) * int(sdat['inner'][4])
            mtime = scan.modify_time.strftime("%Y-%b-%d %H:%M")
            utime = scan.last_used_time.strftime("%Y-%b-%d %H:%M")
            _dat.append([scan.name, axis0, axis1, npts, mtime, utime, 0])
        self.data = sort_data(_dat, sort_col=sort_col, reverse=reverse)


class SlewScanDataTable(GenericDataTable):
    def __init__(self, scans, scandb, stype='Slew'):
        GenericDataTable.__init__(self, scandb, stype)

        self.colLabels = [' Scan Name ', ' Inner Positiner ',
                          ' Outer Positioner ', ' # Points ',
                          ' Created ', ' Last Used ', ' Erase? ']
        self.dataTypes = [gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_NUMBER,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_BOOL]
        self.set_data(scans)
        
    def set_data(self, scans, sort_col=None, reverse=False):
        self.scans = scans[::-1]
        _dat = []
        self.widths = [150, 100, 100, 80, 125, 125, 60]
        self.colReadOnly = [False, True, True, True, True, True, False]
        for scan in self.scans:
            sdat  = json.loads(scan.text)
            axis0 = sdat['inner'][0]
            axis1 = 'None'
            npts  = int(sdat['inner'][4])
            if sdat['dimension'] > 1:
                axis1 = sdat['outer'][0]
                npts *= int(sdat['outer'][4])
            mtime = scan.modify_time.strftime("%Y-%b-%d %H:%M")
            utime = scan.last_used_time.strftime("%Y-%b-%d %H:%M")
            _dat.append([scan.name, axis0, axis1, npts, mtime, utime, 0])
        self.data = sort_data(_dat, sort_col=sort_col, reverse=reverse)
        
        
class XAFSScanDataTable(GenericDataTable):
    def __init__(self, scans, scandb, stype='XAFS'):
        GenericDataTable.__init__(self, scandb, stype)

        self.colLabels = [' Scan Name ', ' E0 ', ' # Regions', ' # Points ',
                          ' Created ', ' Last Used ', ' Erase? ']
        self.dataTypes = [gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_FLOAT + ':9,2',
                          gridlib.GRID_VALUE_NUMBER,
                          gridlib.GRID_VALUE_NUMBER,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_STRING,
                          gridlib.GRID_VALUE_BOOL]
        self.set_data(scans)

    def set_data(self, scans, sort_col=None, reverse=False):
        self.scans = scans[::-1]
        _dat = []
        self.widths = [150, 80, 80, 80, 125, 125, 60]
        self.colReadOnly = [False, True, True, True, True, True, False]
        for scan in self.scans:
            sdat  = json.loads(scan.text)
            e0   = sdat['e0']
            nreg = len(sdat['regions'])
            npts = 1 - nreg
            for ireg in range(nreg):
                npts += sdat['regions'][ireg][2]
            mtime = scan.modify_time.strftime("%Y-%b-%d %H:%M")
            utime = scan.last_used_time.strftime("%Y-%b-%d %H:%M")
            _dat.append([scan.name, e0, nreg, npts, mtime, utime, 0])
        self.data = sort_data(_dat, sort_col=sort_col, reverse=reverse)


class ScandefsFrame(wx.Frame) :
    """Edit Scan Definitions"""
    def __init__(self, parent, pos=(-1, -1)):

        self.parent = parent
        self.scandb = parent.scandb
        wx.Frame.__init__(self, None, -1,
                          'Epics Scanning: Scan Definitions',
                          style=FRAMESTYLE)

        self.SetFont(Font(10))
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.reverse_sort = False
        
        self.SetMinSize((740, 600))
        self.colors = GUIColors()
        panel = scrolled.ScrolledPanel(self)
        panel.SetBackgroundColour(self.colors.bg)
        self.nb = flat_nb.FlatNotebook(panel, wx.ID_ANY, agwStyle=FNB_STYLE)
        self.nb.SetBackgroundColour('#FAFCFA')
        self.SetBackgroundColour('#FAFCFA')
        
        sizer.Add(SimpleText(panel, 'Scan Definitions',
                             font=Font(13),
                             colour=self.colors.title, style=LCEN),
                  0, LCEN, 5)

        allscans = {}
        for t in SCANTYPES:
            allscans[t] = []

        for this in self.scandb.getall('scandefs',
                                       orderby='last_used_time'):
            if this.type is None:
                self.scandb.del_scandef(scanid=this.id)
                continue
            allscans[this.type].append(this)
            utime = this.last_used_time.strftime("%Y-%b-%d %H:%M")
            
        self.tables = {}
        self.nblabels = []
        for pname, creator in (('Linear', LinearScanDataTable),
                               ('Mesh',   MeshScanDataTable),
                               ('Slew',   SlewScanDataTable),
                               ('XAFS',   XAFSScanDataTable)):
            tgrid = gridlib.Grid(panel)
            tgrid.SetBackgroundColour('#FAFAF8')            
            table = creator(allscans[pname.lower()], self.scandb, stype=pname)
            tgrid.SetTable(table, True)
            self.tables[pname.lower()] = table
            self.nb.AddPage(tgrid, "%s Scans" % pname)
            self.nblabels.append((pname.lower(), tgrid))
            
            nrows = tgrid.GetNumberRows()
            for icol, wid in enumerate(table.widths):
                tgrid.SetColMinimalWidth(icol, wid)
                tgrid.SetColSize(icol, wid)
                for irow in range(nrows-1):
                    tgrid.SetReadOnly(irow, icol, table.colReadOnly[icol])
            tgrid.SetRowLabelSize(1)
            tgrid.SetMargins(1,1)
            tgrid.HideRow(nrows-1)
            
            
        self.nb.SetSelection(0)
        sizer.Add(self.nb, 1, wx.ALL|wx.EXPAND, 5)

        bpanel = wx.Panel(panel)
        bsizer = wx.BoxSizer(wx.HORIZONTAL)
        bsizer.Add(add_button(bpanel, label='Load Selected Scan', action=self.onLoad))
        bsizer.Add(add_button(bpanel, label='Apply Changes',      action=self.onApply))
        bsizer.Add(add_button(bpanel, label='Sort Column',        action=self.onSort))
        bsizer.Add(add_button(bpanel, label='Done',               action=self.onDone))

        pack(bpanel, bsizer)
        sizer.Add(bpanel, 0, LCEN, 5)
        
        pack(panel, sizer)
        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)
        self.Show()
        self.Raise()

    def onRefresh(self, evt=None):
        allscans = {}
        for t in SCANTYPES:
            allscans[t] = []

        for this in self.scandb.select('scandefs',
                                       orderby='last_used_time'):
            if len(this.name.strip()) > 0:
                allscans[this.type].append(this)
                utime = this.last_used_time.strftime("%Y-%b-%d %H:%M")
            
        for pname in SCANTYPES:
            pname = pname.lower()
            self.tables[pname].set_data(allscans[pname])
            
        inb  = self.nb.GetSelection()
        self.nb.SetSelection(inb)
        self.Refresh()

    def onApply(self, event=None):
        inb =  self.nb.GetSelection()
        label, thisgrid = self.nblabels[inb]
        self.tables[label].onApplyChanges()
        time.sleep(0.01)
        scans  = self.scandb.select('scandefs')
        self.onRefresh()

    def onSort(self, event=None):
        inb =  self.nb.GetSelection()
        label, thisgrid = self.nblabels[inb]
        icol = thisgrid.GetGridCursorCol()
        irow = thisgrid.GetGridCursorRow()
        all = dir(thisgrid)
        tab = self.tables[label]
        tab.set_data(tab.scans, sort_col=icol, reverse=self.reverse_sort)
        self.reverse_sort = not self.reverse_sort
        self.Refresh()

        
    def onDone(self, event=None):
        self.Destroy()
            
    def onLoad(self, event=None):
        inb =  self.nb.GetSelection()
        label, thisgrid = self.nblabels[inb]
        label = label.lower()
        irow = thisgrid.GetGridCursorRow()
        scanpanel = self.parent.scanpanels[label][1]
        
        scanname = self.tables[label].onLoadScan(irow)
        scanpanel.load_scan(scanname)
        self.parent.nb.SetSelection(inb)
