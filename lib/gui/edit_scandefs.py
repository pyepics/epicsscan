import sys
import time

import json
import wx
import wx.lib.agw.flatnotebook as flat_nb

import wx.lib.scrolledpanel as scrolled
import wx.dataview as dv

from .gui_utils import (GUIColors, set_font_with_children, YesNo, popup,
                        add_button, pack, SimpleText, check, okcancel,
                        add_subtitle, Font, LCEN, CEN, RCEN, FRAMESTYLE)

RCEN |= wx.ALL
LCEN |= wx.ALL
CEN  |= wx.ALL

ALL_CEN =  wx.ALL|wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL
FNB_STYLE = flat_nb.FNB_NO_X_BUTTON|flat_nb.FNB_SMART_TABS|flat_nb.FNB_NO_NAV_BUTTONS|flat_nb.FNB_NODRAG

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

        labstyle  = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
        sizer = wx.GridBagSizer(10, 3)

        sizer.Add(tlabel,       (0, 0), (1, 1), LCEN, 1)
        sizer.Add(self.newname, (0, 1), (1, 1), LCEN, 1)

        btnsizer = wx.StdDialogButtonSizer()
        btn_ok  = wx.Button(panel, wx.ID_OK)
        btn_cancel = wx.Button(panel, wx.ID_CANCEL)
        btn_ok.SetDefault()
        btnsizer.AddButton(btn_ok)
        btnsizer.AddButton(btn_cancel)
        btnsizer.Realize()
        sizer.Add(btnsizer, (1, 0), (1, 2),  wx.ALIGN_CENTER_VERTICAL|wx.ALL, 1)
        pack(panel, sizer)
        sx= wx.BoxSizer(wx.VERTICAL)
        sx.Add(panel, 0, 0, 0)
        pack(self, sx)


class ScanDefModel(dv.PyDataViewIndexListModel):
    """ generic scandef model construct 2D data  list, 
    override GetValueByRow and Compare methonds
    """
    def __init__(self, data, get_value=None, get_attr=None, compare=None):
        self._compare = compare
        self._getval  = get_value
        self._getattr = get_attr
        self.data = data
        dv.PyDataViewIndexListModel.__init__(self, len(data))

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
        dat = self.data[row][col]
        if self._getval is not None:
            dat = self._getval(self.data, row, col)
        return dat

    def GetAttrByRow(self, row, col, attr):
        out = False
        if self._getattr is not None:
            out = self._getattr(row, col, attr)
        return out

    def Compare(self, item1, item2, col, ascending):
        if self._compare is not None:
            return self._compare(self.data, item1, item2, col, ascending)
        
        if not ascending: # swap sort order?
            item2, item1 = item1, item2
        row1 = self.GetRow(item1)
        row2 = self.GetRow(item2)
        if col == 2:
            return cmp(int(self.data[row1][col]), int(self.data[row2][col]))
        else:
            return cmp(self.data[row1][col], self.data[row2][col])


class ScanDefPanel(wx.Panel):
    colLabels = (('Scan Name',  175),
                 ('Positioner', 100),
                 ('# Points',    80),
                 ('Created',    150),
                 ('Last Used',  150))

    def __init__(self, parent, scandb, stype='linear'):
        wx.Panel.__init__(self, parent)
        self.parent = parent
        self.scandb = scandb
        self.stype  = stype.lower()

        dvstyle = wx.BORDER_THEME|dv.DV_VERT_RULES|dv.DV_ROW_LINES|dv.DV_SINGLE
        self.dvc = dv.DataViewCtrl(self, style=dvstyle)
        
        self.data  = self.get_data(scantype=stype)
        self.model = ScanDefModel(self.data, 
                                  get_value=self.model_get_value, 
                                  get_attr=self.model_get_attr,
                                  compare=self.model_compare)
        self.dvc.AssociateModel(self.model)
        self.make_titles()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.dvc, 1, wx.ALIGN_LEFT)
        self.dvc.SetMinSize((775, 400))

        bpanel = wx.Panel(self)
        bsizer = wx.BoxSizer(wx.HORIZONTAL)
        bsizer.Add(add_button(bpanel, label='Load Scan',   action=self.onLoad))
        bsizer.Add(add_button(bpanel, label='Rename Scan', action=self.onRename))
        bsizer.Add(add_button(bpanel, label='Erase Scan',  action=self.onErase))
        bsizer.Add(add_button(bpanel, label='Done',        action=self.onDone))

        pack(bpanel, bsizer)
        sizer.Add(bpanel, 0, LCEN, 5)
        self.SetAutoLayout(True)
        self.SetSizer(sizer)
        self.Fit()

    def make_titles(self):
        icol = 0
        for title, width in self.colLabels:
            self.dvc.AppendTextColumn(title, icol, width=width)
            col = self.dvc.Columns[icol]
            col.Sortable = True
            col.Alignment = wx.ALIGN_LEFT
            icol += 1

    def get_data(self, scantype='linear'):
        data = []
        for scan in self.scandb.getall('scandefs',
                                       orderby='last_used_time'):
            if str(scan.type) != str(scantype.lower()):
                continue
            sdat  = json.loads(scan.text)
            axis  = sdat['positioners'][0][0]
            npts  = sdat['positioners'][0][4]
            data.append([scan.name, axis, npts, 
                         scan.modify_time, scan.last_used_time])
        return data

    def model_get_value(self, data, row, col):  
        dat = data[row][col]
        if col == 2:
            dat = "%d" % dat
        elif col in (3, 4):
            dat = dat.strftime("%Y-%b-%d %H:%M")
        return dat

    def model_get_attr(self, row, col, attr):
        if col in (3, 4):
            attr.SetColour('blue')
            attr.SetBold(True)
            return True
        return False

    def model_compare(self, data, item1, item2, col, ascending):
        if not ascending: # swap sort order?
            item2, item1 = item1, item2
        row1 = self.model.GetRow(item1)
        row2 = self.model.GetRow(item2)
        if col == 2:
            return cmp(int(data[row1][col]), int(data[row2][col]))
        else:
            return cmp(data[row1][col], data[row2][col])

    def onLoad(self, event=None):
        if self.dvc.HasSelection():
            row  = self.dvc.GetSelectedRow()
            name = self.dvc.GetStore().GetValueByRow(row, 0)
            main = self.parent.parent.load_scan(name)

    def onRename(self, event=None):
        if not self.dvc.HasSelection():
            return
        row  = self.dvc.GetSelectedRow()
        name = self.dvc.GetStore().GetValueByRow(row, 0)
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
            if scan.name == name and scan.type == self.stype:
                self.scandb.rename_scandef(scan.id, newname)
            self.scandb.commit()
            self.dvc.GetStore().SetValueByRow(newname, row, 0)

    def onErase(self, event=None):
        if not self.dvc.HasSelection():
            return

        row  = self.dvc.GetSelectedRow()
        name = self.dvc.GetStore().GetValueByRow(row, 0)
        stype = self.stype
        ret = popup(self, "Erase scan definition '%s'?" % name,
                    "Really Erase Scan definition?",
                    style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION)
        if ret != wx.ID_YES:
            return

        cls, table = self.scandb.get_table('scandefs')
        scans = self.scandb.query(table).filter(cls.name==name).all()
        if scans is not None:
            scan = scans[0]
            if scan.name == name and scan.type == self.stype:
                self.scandb.del_scandef(scanid=scan.id)
            self.scandb.commit()
            self.dvc.GetStore().SetValueByRow(' ', row, 0)
            wx.CallAfter(self.fill_rows)

    def onDone(self, event=None):
        self.parent.Destroy()


class LinearScanDefs(ScanDefPanel):
    colLabels = (('Scan Name',  175),
                 ('Positioner', 100),
                 ('# Points',    80),
                 ('Created',    150),
                 ('Last Used',  150))

    def __init__(self, parent, scandb, stype='linear'):
        ScanDefPanel.__init__(self, parent, scandb, stype=stype)


class MeshScanDefs(ScanDefPanel):
    colLabels = (('Scan Name',  175),
                 ('Inner',      100),
                 ('Outer',      100),
                 ('# Points',    80),
                 ('Created',    150),
                 ('Last Used',  150))

    def __init__(self, parent, scandb, stype='mesh'):
        ScanDefPanel.__init__(self, parent, scandb, stype=stype)

    def fill_rows(self):
        self.dvc.DeleteAllItems()
        for scan in self.scandb.getall('scandefs',
                                       orderby='last_used_time'):
            if str(scan.type) != str(self.stype):
                continue
            sdat  = json.loads(scan.text)
            inner  = sdat['inner'][0]
            outer  = sdat['outer'][0]
            npts  = int(sdat['outer'][4]) * int(sdat['inner'][4])
            mtime = scan.modify_time.strftime("%Y-%b-%d %H:%M")
            utime = scan.last_used_time.strftime("%Y-%b-%d %H:%M")
            self.dvc.AppendItem((scan.name, inner, outer, "%d"%npts, mtime, utime))

class SlewScanDefs(ScanDefPanel):
    colLabels = (('Scan Name',  175),
                 ('Inner',      100),
                 ('Outer',      100),
                 ('# Points',    80),
                 ('Created',    150),
                 ('Last Used',  150))

    def __init__(self, parent, scandb, stype='slew'):
        ScanDefPanel.__init__(self, parent, scandb, stype=stype)

    def fill_rows(self):
        self.dvc.DeleteAllItems()
        for scan in self.scandb.getall('scandefs',
                                       orderby='last_used_time'):
            if str(scan.type) != str(self.stype):
                continue
            sdat  = json.loads(scan.text)
            inner = sdat['inner'][0]
            outer = 'None'
            npts  = int(sdat['inner'][4])
            if sdat['dimension'] > 1:
                outer  = sdat['outer'][0]
                npts *= int(sdat['outer'][4])
            mtime = scan.modify_time.strftime("%Y-%b-%d %H:%M")
            utime = scan.last_used_time.strftime("%Y-%b-%d %H:%M")
            self.dvc.AppendItem((scan.name, inner, outer, "%d"%npts, mtime, utime))


class XAFSScanDefs(ScanDefPanel):
    colLabels = (('Scan Name',  175),
                 ('E0  ',        80),
                 ('# Regions',   80),
                 ('# Points',    80),
                 ('Created',    150),
                 ('Last Used',  150))

    def __init__(self, parent, scandb, stype='xafs'):
        ScanDefPanel.__init__(self, parent, scandb, stype=stype)

    def fill_rows(self):
        self.dvc.DeleteAllItems()
        for scan in self.scandb.getall('scandefs',
                                       orderby='last_used_time'):
            if str(scan.type) != str(self.stype):
                continue
            sdat  = json.loads(scan.text)
            e0   = sdat['e0']
            nreg = len(sdat['regions'])
            npts = 1 - nreg
            for ireg in range(nreg):
                npts += sdat['regions'][ireg][2]
            mtime = scan.modify_time.strftime("%Y-%b-%d %H:%M")
            utime = scan.last_used_time.strftime("%Y-%b-%d %H:%M")
            self.dvc.AppendItem((scan.name, "%.1f"%e0, nreg, "%d"%npts, mtime, utime))


class ScandefsFrame(wx.Frame) :
    """Edit Scan Definitions"""
    def __init__(self, parent, pos=(-1, -1), _larch=None):

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

        self.tables = {}
        self.nblabels = []
        for pname, creator in (('Linear', LinearScanDefs),
                               # ('Slew',   SlewScanDefs),
                               # ('Mesh',   MeshScanDefs),
                               # ('XAFS',   XAFSScanDefs)
                           ):

            table = creator(self, self.scandb, stype=pname.lower())
            self.tables[pname.lower()] = table
            self.nb.AddPage(table, "%s Scans" % pname)
            self.nblabels.append((pname.lower(), table))

        self.nb.SetSelection(0)
        sizer.Add(self.nb, 1, wx.ALL|wx.EXPAND, 5)

        pack(panel, sizer)
        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)
        self.Show()
        self.Raise()
