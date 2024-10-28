import sys
import time
import wx
import wx.lib.scrolledpanel as scrolled
import wx.dataview as dv

from .gui_utils import (GUIColors, set_font_with_children, YesNo,
                        add_button, pack, SimpleText, check, okcancel,
                        add_subtitle, Font, LEFT, CEN, RIGHT,
                        FRAMESTYLE, DVSTYLE)

class ExtraPVsModel(dv.DataViewIndexListModel):
    def __init__(self, scandb):
        dv.DataViewIndexListModel.__init__(self, 0)
        self.scandb = scandb
        self.data = []
        self.mapping = {}
        self.read_data()

    def read_data(self):
        self.data = []
        for row in self.scandb.get_extrapvs():
            self.data.append([row.pvname, row.name, row.use==1, False])
            self.mapping[row.pvname] = row.id
        self.Reset(len(self.data))

    def GetColumnType(self, col):
        if col == 2:
            return "bool"
        return "string"

    def GetValueByRow(self, row, col):
        return self.data[row][col]

    def SetValueByRow(self, value, row, col):
        self.data[row][col] = value
        return True

    def GetColumnCount(self):
        return len(self.data[0])

    def GetCount(self):
        return len(self.data)

    def DeleteRows(self, rows):
        rows = list(rows)
        rows.sort(reverse=True)
        for row in rows:
            del self.data[row]
            self.RowDeleted(row)

    def AddRow(self, value):
        self.data.append(value)
        self.RowAppended()


class ExtraPVsFrame(wx.Frame) :
    """Set Extra PVs"""
    def __init__(self, parent, pos=(-1, -1), scandb=None, mkernel=None):
        self.parent = parent
        self.scandb = parent.scandb if scandb is None else scandb

        wx.Frame.__init__(self, None, -1, 'Epics Scanning: Extra PVs Setup',
                          style=FRAMESTYLE)

        self.SetFont(Font(9))
        sizer = wx.GridBagSizer(3, 2)
        panel = scrolled.ScrolledPanel(self)
        self.SetMinSize((700, 675))
        panel.SetBackgroundColour(GUIColors.bg)

        # title row
        title = SimpleText(panel, 'Extra PVs Setup',  font=Font(13),
                           colour=GUIColors.title, style=LEFT)

        sizer.Add(title,        (0, 0), (1, 3), LEFT, 5)

        self.dvc = dv.DataViewCtrl(panel, style=DVSTYLE)
        self.dvc.SetMinSize((700, 500))

        self.model = ExtraPVsModel(self.scandb)
        self.dvc.AssociateModel(self.model)

        i = 0
        for  dat in (('PV Name', 250,  False,  'text'),
                     ('Description',  300, True, 'text'),
                     ('Use ', 75,  True, 'bool'),
                     ('Erase ', 75, True, 'bool')):
            label, width, editable, dtype = dat
            add_col = self.dvc.AppendTextColumn
            mode = dv.DATAVIEW_CELL_EDITABLE
            if dtype == 'bool':
                add_col = self.dvc.AppendToggleColumn
                mode = dv.DATAVIEW_CELL_ACTIVATABLE
            if not editable:
                mode = dv.DATAVIEW_CELL_INERT

            add_col(label, i, width=width, mode=mode)
            c = self.dvc.Columns[i]
            c.Alignment = wx.ALIGN_LEFT
            c.Sortable = True
            i +=1

        sizer.Add(self.dvc, (1, 0), (1, 3), LEFT|wx.GROW)

        title = SimpleText(panel, 'Add PVs:',  font=Font(13),
                           colour=GUIColors.title, style=LEFT)

        sizer.Add(title,        (2, 0), (1, 3), LEFT, 5)

        pvnx = SimpleText(panel, 'PV Name:')
        pvdx = SimpleText(panel, 'Description:')

        ir = 3
        sizer.Add(pvnx,  (ir, 0), (1, 1), LEFT, 2)
        sizer.Add(pvdx,  (ir, 1), (1, 1), LEFT, 2)


        self.widlist = []
        for i in range(2):
             pvctrl = wx.TextCtrl(panel, value='', size=(250, -1))
             desc   = wx.TextCtrl(panel, -1, value='', size=(300, -1))
             ir +=1
             sizer.Add(pvctrl,  (ir, 0), (1, 1), LEFT, 2)
             sizer.Add(desc, (ir, 1), (1, 1), LEFT, 2)
             self.widlist.append((pvctrl, desc))

#         sizer.Add(SimpleText(panel, label='PV Name', size=(200, -1)),
#                   (ir, 0), (1, 1), LEFT, 2)
#         sizer.Add(SimpleText(panel, label='Description', size=(200, -1)),
#                   (ir, 1), (1, 1), LEFT, 2)
#         sizer.Add(SimpleText(panel, label='Use?'),
#                   (ir, 2), (1, 1), LEFT, 2)
#         sizer.Add(SimpleText(panel, label='Erase?', size=(60, -1)),
#                   (ir, 3), (1, 1), LEFT, 2)
#
#         self.widlist = []
#         self.current_extrapvs = {}
#         for this in self.scandb.get_rows('extrapvs'):
#             self.current_extrapvs[this.name] = this.pvname
#             pvctrl = wx.TextCtrl(panel, value=this.pvname,  size=(200, -1))
#             desc   = wx.TextCtrl(panel, -1, value=this.name, size=(200, -1))
#             usepv  = check(panel, default=this.use)
#             delpv  = YesNo(panel, defaultyes=False)
#
#             ir +=1
#             sizer.Add(pvctrl, (ir, 0), (1, 1), RIGHT, 2)
#             sizer.Add(desc,   (ir, 1), (1, 1), LEFT, 2)
#             sizer.Add(usepv,  (ir, 2), (1, 1), LEFT, 2)
#             sizer.Add(delpv,  (ir, 3), (1, 1), LEFT, 2)
#             self.widlist.append((this, pvctrl, desc, usepv, delpv))
#
#         for i in range(3):
#             pvctrl = wx.TextCtrl(panel, value='', size=(200, -1))
#             desc   = wx.TextCtrl(panel, -1, value='', size=(200, -1))
#             usepv  = check(panel, default=False)
#             ir +=1
#             sizer.Add(pvctrl,   (ir, 0), (1, 1), RIGHT, 2)
#             sizer.Add(desc, (ir, 1), (1, 1), LEFT, 2)
#             sizer.Add(usepv,  (ir, 2), (1, 1), LEFT, 2)
#             self.widlist.append((None, pvctrl, desc, usepv, None))
#
#         ir += 1
#         sizer.Add(wx.StaticLine(panel, size=(350, 3), style=wx.LI_HORIZONTAL),
#                   (ir, 0), (1, 4), LEFT, 3)
        #
        ir += 1
        sizer.Add(okcancel(panel, self.onOK, self.onClose),
                  (ir, 0), (1, 2), LEFT, 3)

        pack(panel, sizer)

        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)
        self.Show()
        self.Raise()

    def onOK(self, event=None):
        cur_data = {}
        pvnames = []
        for row in self.scandb.get_extrapvs():
            cur_data[row.id] = [row.pvname, row.name, row.use==1]

        for rowdat in self.model.data:
            pvname, name, use, erase = rowdat
            rowid = self.model.mapping[pvname]
            cur_row = cur_data.get(rowid, None)
            if cur_row is None:
                print("missing row?? ", rowid, rowdat)
            elif erase:
                self.scandb.delete_rows('extrapvs', where={'id': rowid})
            else:
                vals = {}
                if cur_row[0] != pvname:
                    vals['pvname'] = pvname
                if cur_row[1] != name:
                    vals['name'] = name
                if cur_row[2] != use:
                    vals['use'] = 1 if use else 0
                if len(vals) > 0:
                    print("update extrapvs ", rowid, cur_row, vals)
                    self.scandb.update('extrapvs', where={'id': rowid}, **vals)

        for row in self.scandb.get_extrapvs():
            pvnames.append(row.pvname)


        for w in self.widlist:
            pvctrl, desc = w
            name   = desc.GetValue().strip()
            pvname = pvctrl.GetValue().strip()
            if len(name) < 1 or len(pvname) < 1:
                continue
            if pvname in  pvnames:
                print('pvname already in table ', pvname)
            else:
                self.scandb.add_extrapv(name, pvname, use=1)

        self.model.read_data()
        self.Destroy()


    def onClose(self, event=None):
        self.Destroy()
