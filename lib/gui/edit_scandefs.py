import sys
import time

import json
import wx
import wx.lib.agw.flatnotebook as flat_nb

import wx.lib.scrolledpanel as scrolled
import wx.grid as gridlib
import wx.dataview as dv

from .gui_utils import (GUIColors, set_font_with_children, YesNo, popup,
                        add_button, pack, SimpleText, check, okcancel,
                        add_subtitle, Font, LCEN, CEN, RCEN, FRAMESTYLE)

RCEN |= wx.ALL
LCEN |= wx.ALL
CEN  |= wx.ALL

ALL_CEN =  wx.ALL|wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL
FNB_STYLE = flat_nb.FNB_NO_X_BUTTON|flat_nb.FNB_SMART_TABS|flat_nb.FNB_NO_NAV_BUTTONS

SCANTYPES = ('linear', 'mesh', 'slew', 'xafs')
SCANTYPES = ('linear', 'mesh', 'xafs')


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

        dvstyle = dv.DV_VERT_RULES|dv.DV_ROW_LINES|dv.DV_SINGLE
        self.wids = dv.DataViewListCtrl(self, style=dvstyle)

        self.make_titles()
        self.fill_rows()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.wids, 1, wx.ALIGN_LEFT)
        self.wids.SetMinSize((775, 400))

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
        for icol, dat in enumerate(self.colLabels):
            title, width = dat
            self.wids.AppendTextColumn(title,   width=width)
            col = self.wids.Columns[icol]
            col.Sortable = True
            col.Alignment = wx.ALIGN_LEFT

    def fill_rows(self):
        self.wids.DeleteAllItems()
        for scan in self.scandb.getall('scandefs',
                                       orderby='last_used_time'):
            if str(scan.type) != str(self.stype.lower()):
                continue
            sdat  = json.loads(scan.text)
            axis  = sdat['positioners'][0][0]
            npts  = sdat['positioners'][0][4]
            mtime = scan.modify_time.strftime("%Y-%b-%d %H:%M")
            utime = scan.last_used_time.strftime("%Y-%b-%d %H:%M")
            self.wids.AppendItem((scan.name, axis, "%d"%npts, mtime, utime))

    def onLoad(self, event=None):
        if self.wids.HasSelection():
            row  = self.wids.GetSelectedRow()
            name = self.wids.GetStore().GetValueByRow(row, 0)
            main = self.parent.parent.load_scan(name)

    def onRename(self, event=None):
        if not self.wids.HasSelection():
            return
        row  = self.wids.GetSelectedRow()
        name = self.wids.GetStore().GetValueByRow(row, 0)
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
            self.wids.GetStore().SetValueByRow(newname, row, 0)

    def onErase(self, event=None):
        if self.wids.HasSelection():
            return

        row  = self.wids.GetSelectedRow()
        name = self.wids.GetStore().GetValueByRow(row, 0)
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
            self.wids.GetStore().SetValueByRow(' ', row, 0)
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
        self.wids.DeleteAllItems()
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
            self.wids.AppendItem((scan.name, inner, outer, "%d"%npts, mtime, utime))

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
        self.wids.DeleteAllItems()
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
            self.wids.AppendItem((scan.name, inner, outer, "%d"%npts, mtime, utime))


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
        self.wids.DeleteAllItems()
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
            self.wids.AppendItem((scan.name, "%.1f"%e0, nreg, "%d"%npts, mtime, utime))


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

        self.tables = {}
        self.nblabels = []
        for pname, creator in (('Linear', LinearScanDefs),
                               ('Mesh',   MeshScanDefs),
                               # ('Slew',   SlewScanDefs),
                               ('XAFS',   XAFSScanDefs)):

            table = creator(self, self.scandb, stype=pname.lower())
            self.tables[pname.lower()] = table
            self.nb.AddPage(table, "%s Scans" % pname)
            self.nblabels.append((pname.lower(), table))

        self.nb.SetSelection(0)
        sizer.Add(self.nb, 1, wx.ALL|wx.EXPAND, 5)

#         bpanel = wx.Panel(panel)
#         bsizer = wx.BoxSizer(wx.HORIZONTAL)
#         bsizer.Add(add_button(bpanel, label='Done',   action=self.onDone))
#
#         pack(bpanel, bsizer)
#         sizer.Add(bpanel, 0, LCEN, 5)

        pack(panel, sizer)
        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)
        self.Show()
        self.Raise()
