import sys
import time

import json
import wx
import wx.lib.agw.flatnotebook as flat_nb

import wx.lib.scrolledpanel as scrolled
import wx.dataview as dv
from datetime import datetime
from .gui_utils import (GUIColors, set_font_with_children, YesNo, popup,
                        add_button, pack, SimpleText, check, okcancel,
                        add_subtitle, Font, LEFT, FRAMESTYLE,
                        FNB_STYLE)


class RenameDialog(wx.Dialog):
    """Rename a Scan Name"""
    msg = '''Rename Scan'''
    def __init__(self, parent, oldname):
        title = "Rename Scan '%s'" % (oldname)
        wx.Dialog.__init__(self, parent, title=title,
                        style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION)

        panel = wx.Panel(self)
        tlabel = SimpleText(panel, label='New name = ', size=(200, -1))
        self.newname =  wx.TextCtrl(panel, value=oldname, size=(175, -1))

        labstyle  = LEFT|wx.ALL
        sizer = wx.GridBagSizer(3, 2)

        sizer.Add(tlabel,       (0, 0), (1, 1), LEFT, 1)
        sizer.Add(self.newname, (0, 1), (1, 1), LEFT, 1)

        btnsizer = wx.StdDialogButtonSizer()
        btn_ok  = wx.Button(panel, wx.ID_OK)
        btn_cancel = wx.Button(panel, wx.ID_CANCEL)
        btn_ok.SetDefault()
        btnsizer.AddButton(btn_ok)
        btnsizer.AddButton(btn_cancel)
        btnsizer.Realize()
        sizer.Add(btnsizer, (1, 0), (1, 2),  wx.ALL, 1)
        pack(panel, sizer)
        sx= wx.BoxSizer(wx.VERTICAL)
        sx.Add(panel, 0, 0, 0)
        pack(self, sx)


class ScanDefModel(dv.DataViewIndexListModel):
    """ generic scandef model construct 2D data  list,
    override GetValueByRow and Compare methonds
    """
    def __init__(self, data, get_value=None, get_attr=None, compare=None):
        self._compare = compare
        self._getval  = get_value
        self._getattr = get_attr
        self.data = data
        dv.DataViewIndexListModel.__init__(self, len(data))

    def GetColumnType(self, col):  return "string"
    def SetValueByRow(self, value, row, col):    self.data[row][col] = value
    def GetColumnCount(self):    return len(self.data[0])
    def GetCount(self):          return len(self.data)

    def DeleteRows(self, rows):
        rows = list(rows)
        rows.sort(reverse=True)
        for row in rows:
            del self.data[row]
            self.RowDeleted(row)

    def AddRow(self, value):
        self.data.append(value)
        self.RowAppended()

    def GetValueByRow(self, row, col):
        if self._getval is not None:
            return self._getval(row, col)
        return self.data[row][col]

    def GetAttrByRow(self, row, col, attr):
        if self._getattr is not None:
            return self._getattr(row, col, attr)
        return False

    def Compare(self, item1, item2, col, ascending):
        if self._compare is not None:
            return self._compare(item1, item2, col, ascending)

        if not ascending: # swap sort order?
            item2, item1 = item1, item2
        row1 = self.GetRow(item1)
        row2 = self.GetRow(item2)
        return cmp(self.data[row1][col], self.data[row2][col])


class ScanDefPanel(wx.Panel):
    colLabels = (('Scan Name',  200),
                 ('Positioner', 100),
                 ('# Points',    80),
                 ('Created',    150),
                 ('Last Used',  150))
    scantype = 'linear'

    def __init__(self, parent, scandb):
        wx.Panel.__init__(self, parent)
        self.parent = parent
        self.scandb = scandb
        dvstyle = wx.BORDER_THEME|dv.DV_VERT_RULES|dv.DV_ROW_LINES|dv.DV_SINGLE
        self.dvc = dv.DataViewCtrl(self, style=dvstyle)
        self.ncols = 4
        self.show_dunder = False
        self.name_filter = None

        self.model = ScanDefModel(self.get_data(),
                                  get_value=self.model_get_value,
                                  get_attr=self.model_get_attr,
                                  compare=self.model_compare)

        self.dvc.AssociateModel(self.model)
        self.make_titles()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.dvc, 1, LEFT)
        self.dvc.SetMinSize((775, 450))

        bpanel = wx.Panel(self)
        bsizer = wx.BoxSizer(wx.HORIZONTAL)
        bsizer.Add(add_button(bpanel, label='Load Scan',   action=self.onLoad))
        bsizer.Add(add_button(bpanel, label='Rename Scan', action=self.onRename))
        bsizer.Add(add_button(bpanel, label='Erase Scan',  action=self.onErase))
        bsizer.Add(add_button(bpanel, label='Done',        action=self.onDone))

        pack(bpanel, bsizer)
        sizer.Add(bpanel, 0, LEFT, 5)
        self.SetAutoLayout(True)
        self.SetSizer(sizer)
        self.Fit()

    def refresh(self):
        self.model = None
        time.sleep(0.002)
        self.model = ScanDefModel(self.get_data(),
                                  get_value=self.model_get_value,
                                  get_attr=self.model_get_attr,
                                  compare=self.model_compare)

        self.dvc.AssociateModel(self.model)


    def make_titles(self):
        icol = 0
        for title, width in self.colLabels:
            self.dvc.AppendTextColumn(title, icol, width=width)
            col = self.dvc.Columns[icol]
            col.Sortable = True
            col.Alignment = wx.ALIGN_LEFT
            icol += 1

    def _getscans(self, orderby='last_used_time'):

        if self.name_filter is  None or len(self.name_filter) < 1:
            self.name_filter = ''

        self.name_filter.replace('*', '').lower()

        cls, table = self.scandb.get_table('scandefs')

        q = table.select().where(table.c.type.ilike("%%%s%%" % self.scantype))
        if self.name_filter not in (None, 'None', ''):
            q = q.where(table.c.name.ilike('%%%s%%' % self.name_filter))

        out = q.order_by(orderby).execute().fetchall()
        if not self.show_dunder:
            tmp = []
            for row in out:
                if not(row.name.startswith('__') and row.name.endswith('__')):
                    tmp.append(row)
            out = tmp
        return out

    def get_data(self):
        data = []
        for scan in self._getscans():
            sdat  = json.loads(scan.text)
            axis  = sdat['positioners'][0][0]
            npts  = sdat['positioners'][0][4]
            data.append([scan.name, axis, npts,
                         scan.modify_time, scan.last_used_time])
        try:
            self.ncols = len(data[0])
        except:
            self.ncols = 5
        return data

    def model_get_value(self, row, col):
        dat = self.model.data[row][col]
        if isinstance(dat, int):
            dat = "%d" % dat
        elif isinstance(dat, float):
            dat = "%.1f" % dat
        elif isinstance(dat, datetime):
            dat = dat.strftime("%Y-%b-%d %H:%M")
        return dat

    def model_get_attr(self, row, col, attr):
        if col > self.ncols - 3:
            attr.SetColour('blue')
            attr.SetBold(True)
            return True
        return False

    def model_compare(self, item1, item2, col, ascending):
        if not ascending:
            item2, item1 = item1, item2
        row1 = self.model.GetRow(item1)
        row2 = self.model.GetRow(item2)
        return cmp(self.model.data[row1][col],
                   self.model.data[row2][col])

    def onLoad(self, event=None):
        if self.dvc.HasSelection():
            row  = self.model.GetRow(self.dvc.GetSelection())
            name = self.model.data[row][0]
            self.parent.parent.load_scan(name)

    def onRename(self, event=None):
        if not self.dvc.HasSelection():
            return

        row  = self.model.GetRow(self.dvc.GetSelection())
        name = self.model.data[row][0]

        dlg = RenameDialog(self, name)
        if dlg.ShowModal() != wx.ID_OK:
            return

        cls, table = self.scandb.get_table('scandefs')

        newname = dlg.newname.GetValue()
        tmpscans = self.scandb.query(table).filter(cls.name==newname).all()
        if tmpscans is not None and len(tmpscans) > 0:
            ret = popup(self, "Scan definition '%s' already in use" % newname,
                "Scan definition in use!", style=wx.OK)
            return

        scans = self.scandb.query(table).filter(cls.name==name).all()
        if scans is not None:
            scan = scans[0]
            if scan.name == name and scan.type == self.scantype:
                self.scandb.rename_scandef(scan.id, newname)
            self.scandb.commit()
            self.model.SetValueByRow(newname, row, 0)

    def onErase(self, event=None):
        if not self.dvc.HasSelection():
            return
        row  = self.model.GetRow(self.dvc.GetSelection())
        name = self.model.data[row][0]
        ret = popup(self, "Erase scan definition '%s'?" % name,
                    "Really Erase Scan definition?",
                    style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION)
        if ret != wx.ID_YES:
            return

        cls, table = self.scandb.get_table('scandefs')
        scans = self.scandb.query(table).filter(cls.name==name).all()
        if scans is not None:
            scan = scans[0]
            if scan.name == name and scan.type == self.scantype:
                self.scandb.del_scandef(scanid=scan.id)
            self.scandb.commit()
            self.model.DeleteRows([row])

    def onDone(self, event=None):
        self.parent.Destroy()


class LinearScanDefs(ScanDefPanel):
    colLabels = (('Scan Name',  200),
                 ('Positioner', 100),
                 ('# Points',    80),
                 ('Created',    150),
                 ('Last Used',  150))
    scantype = 'linear'
    def __init__(self, parent, scandb):
        ScanDefPanel.__init__(self, parent, scandb)


class MeshScanDefs(ScanDefPanel):
    colLabels = (('Scan Name',  200),
                 ('Inner',       80),
                 ('Outer',       80),
                 ('# Points',    80),
                 ('Created',    150),
                 ('Last Used',  150))

    scantype = 'mesh'
    def __init__(self, parent, scandb):
        ScanDefPanel.__init__(self, parent, scandb)

    def get_data(self):
        data = []
        for scan in self._getscans():
            sdat  = json.loads(scan.text)
            inner = sdat['inner'][0]
            outer = sdat['outer'][0]
            npts  = int(sdat['outer'][4]) * int(sdat['inner'][4])
            data.append([scan.name, inner, outer, npts,
                         scan.modify_time, scan.last_used_time])

        try:
            self.ncols = len(data[0])
        except:
            self.ncols = 6

        return data

class SlewScanDefs(ScanDefPanel):
    colLabels = (('Scan Name',  200),
                 ('Inner',       80),
                 ('Outer',       80),
                 ('# Points',    80),
                 ('Created',    150),
                 ('Last Used',  150))
    scantype = 'slew'
    def __init__(self, parent, scandb):
        ScanDefPanel.__init__(self, parent, scandb)

    def get_data(self):
        data = []
        for scan in self._getscans():
            sdat  = json.loads(scan.text)
            inner = sdat['inner'][0]
            npts  = int(sdat['inner'][4])
            outer = 'None'
            if sdat['dimension'] > 1:
                outer  = sdat['outer'][0]
                npts *= int(sdat['outer'][4])
            data.append([scan.name, inner, outer, npts,
                         scan.modify_time, scan.last_used_time])
        try:
            self.ncols = len(data[0])
        except:
            self.ncols = 6

        return data

class XAFSScanDefs(ScanDefPanel):
    colLabels = (('Scan Name',  200),
                 ('E0  ',        80),
                 ('# Regions',   80),
                 ('# Points',    80),
                 ('Created',    150),
                 ('Last Used',  150))

    scantype = 'xafs'
    def __init__(self, parent, scandb):
        ScanDefPanel.__init__(self, parent, scandb)

    def get_data(self):
        data = []
        for scan in self._getscans():
            sdat = json.loads(scan.text)
            e0   = sdat['e0']
            nreg = len(sdat['regions'])
            npts = 1 - nreg
            for ireg in range(nreg):
                npts += sdat['regions'][ireg][2]
            data.append([scan.name, e0, nreg, npts,
                         scan.modify_time, scan.last_used_time])
        try:
            self.ncols = len(data[0])
        except:
            self.ncols = 6

        return data


class ScandefsFrame(wx.Frame) :
    """Edit Scan Definitions"""
    def __init__(self, parent, pos=(-1, -1), scandb=None, _larch=None):

        self.parent = parent
        self.scandb = parent.scandb if scandb is None else scandb
        wx.Frame.__init__(self, None, -1,
                          'Epics Scanning: Scan Definitions',
                          style=FRAMESTYLE)

        self.SetFont(Font(10))
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.reverse_sort = False

        self.SetMinSize((740, 600))
        panel = scrolled.ScrolledPanel(self)
        panel.SetBackgroundColour(GUIColors.bg)
        self.nb = flat_nb.FlatNotebook(panel, wx.ID_ANY, agwStyle=FNB_STYLE)

        self.nb.SetBackgroundColour('#FAFCFA')
        self.SetBackgroundColour('#FAFCFA')

        sizer.Add(SimpleText(panel, 'Scan Definitions',
                             font=Font(13),
                             colour=GUIColors.title, style=LEFT),
                  0, LEFT, 5)

        rsizer = wx.BoxSizer(wx.HORIZONTAL)

        self.searchstring = wx.TextCtrl(panel, -1, '', size=(225, -1),
                                        style=wx.TE_PROCESS_ENTER)
        self.searchstring.Bind(wx.EVT_TEXT_ENTER, self.onSearch)

        self.show_dunder = check(panel, default=False,
                                 label='Include auto-named scans',
                                 size=(40, -1))
        self.show_dunder.Bind(wx.EVT_CHECKBOX,self.onToggleDunder)

        rsizer.Add(SimpleText(panel, "Filter: ",
                             font=Font(12), style=LEFT), 0, LEFT, 5)
        rsizer.Add(self.searchstring, 1, LEFT, 2)

        rsizer.Add(add_button(panel, label='Apply', size=(70, -1),
                              action=self.onSearch), 0, LEFT, 3)
        rsizer.Add(add_button(panel, label='Clear',  size=(70, -1),
                              action=self.onClearSearch), 0, LEFT, 3)

        rsizer.Add(self.show_dunder, 1, LEFT, 6)
        sizer.Add(rsizer)

        self.tables = []
        self.nblabels = []
        creators = {'xafs': XAFSScanDefs,
                   'slew': SlewScanDefs,
                   'linear': LinearScanDefs}
        for stype, title in self.parent.notebooks:
            table = creators[stype](self, self.scandb)
            self.tables.append(table)
            self.nb.AddPage(table, title)
            self.nblabels.append((stype, table))

        self.nb.SetSelection(0)
        sizer.Add(self.nb, 1, wx.ALL|wx.EXPAND, 5)

        pack(panel, sizer)
        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)
        self.Show()
        self.Raise()

    def onSearch(self, event=None):
        for tab in self.tables:
            tab.name_filter = event.GetString().strip().lower()
            tab.refresh()

    def onClearSearch(self, event=None):
        self.searchstring.SetValue('')
        for tab in self.tables:
            tab.name_filter = ''
            tab.refresh()

    def onToggleDunder(self,event):
        for tab in self.tables:
            tab.show_dunder = event.IsChecked()
            tab.refresh()
