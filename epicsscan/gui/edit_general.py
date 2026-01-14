#
# general parameter frame
import sys
import time
from functools import partial
import wx
import wx.lib.scrolledpanel as scrolled
import wx.dataview as dv

from .gui_utils import (GUIColors, add_button, pack, SimpleText, TextCtrl,
                        HLine, check, okcancel, add_subtitle, LEFT, Font, DVSTYLE)

class ExptSettingsModel(dv.DataViewIndexListModel):
    def __init__(self, scandb):
        dv.DataViewIndexListModel.__init__(self, 0)
        self.scandb = scandb
        self.data = []
        self.keys = {}
        self.read_data()

    def read_data(self):
        self.data = []
        expt_rows = self.scandb.get_info(prefix='experiment_',
                                    order_by='display_order', full_row=True)
        for name, row in expt_rows.items():
            value = row.value
            if value is None:
                value = ''
            self.data.append([row.notes, row.value])
            self.keys[row.notes] = row.key
        self.Reset(len(self.data))

    def GetColumnType(self, col):
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


class SettingsPanel(scrolled.ScrolledPanel):
    def __init__(self, parent, scandb=None, pvlist=None, title='Settings',
                 size=(760, 380), style=wx.GROW|wx.TAB_TRAVERSAL):

        self.scandb = scandb

        scrolled.ScrolledPanel.__init__(self, parent, size=size,
                                        name='Settings', style=style)

        self.Font13 = wx.Font(13, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        self.Font12 = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD, 0, "")
        self.sizer = wx.GridBagSizer(3, 2)
        self.SetBackgroundColour(GUIColors.bg)
        self._initialized = False # used to shunt events while creating windows

        self.SetFont(Font(9))
        sizer = wx.GridBagSizer(3, 2)

        # title row
        title = SimpleText(self, ' General Settings',  font=Font(13),
                           size=(250, -1),
                           colour=GUIColors.title, style=LEFT)
        sizer.Add(title,                      (0, 0), (1, 3), LEFT|wx.ALL)
        sizer.Add(HLine(self, size=(650, 3)), (1, 0), (1, 3), LEFT)

        self.dvc = dv.DataViewCtrl(self, style=DVSTYLE)
        self.dvc.SetMinSize((750, 500))

        self.model = ExptSettingsModel(self.scandb)
        self.dvc.AssociateModel(self.model)

        i = 0
        for  dat in (('Setting ', 250,  False),
                     ('Value',   490,   True)):
            label, width,  editable = dat
            mode = dv.DATAVIEW_CELL_INERT
            if editable:
                mode = dv.DATAVIEW_CELL_EDITABLE
            self.dvc.AppendTextColumn(label, i, width=width, mode=mode)
            c = self.dvc.Columns[i]
            c.Alignment = wx.ALIGN_LEFT
            c.Sortable = (i == 0)
            i +=1

        sizer.Add(self.dvc, (2, 0), (1, 3), LEFT|wx.GROW)

        sizer.Add(add_button(self, label='Save Settings', size=(175, -1),
                             action=self.onSetValues),
                          (3, 0), (1, 1), LEFT)
        sizer.Add(add_button(self, label='Re-Read Settings', size=(175, -1),
                             action=self.onReRead),
                          (3, 1), (1, 1), LEFT)

        pack(self, sizer)
        self.dvc.EnsureVisible(self.model.GetItem(0))

    def onReRead(self, event=None):
        self.model.read_data()
        self.Refresh()
        self.dvc.EnsureVisible(self.model.GetItem(0))

    def onSetValues(self, event=None, **kws):
        for notes, value in self.model.data:
            key = self.model.keys.get(notes, None)
            if key is not None:
                current = self.scandb.get_info(key, default=None)
                if current != value:
                    self.scandb.set_info(key, value)
        time.sleep(0.5)
        self.onReRead()

    def onPanelExposed(self, evt=None):
        self.onReRead()


class SettingsFrame(wx.Frame) :
    """Frame for Setup General Settings:
    DB Connection, Settling Times, Extra PVs
    """
    def __init__(self, parent, pos=(-1, -1), scandb=None, mkernel=None):
        self.parent = parent
        self.pvlist = parent.pvlist
        self.scandb = parent.scandb if scandb is None else scandb

        wx.Frame.__init__(self, None, -1,
                          'Epics Scanning Setup: General Settings',
                          style=wx.DEFAULT_FRAME_STYLE|wx.TAB_TRAVERSAL)

        self.SetFont(Font(9))
        sizer = wx.GridBagSizer(3, 2)

        panel = scrolled.ScrolledPanel(self)
        self.SetMinSize((550, 500))

        panel.SetBackgroundColour(GUIColors.bg)

        # title row
        title = SimpleText(panel, 'Options',  font=Font(13),
                           colour=GUIColors.title, style=LEFT)
        sizer.Add(title,    (0, 0), (1, 3), LEFT|wx.ALL, 2)
        ir = 0
        self.wids = {}
        for sect, vars in (('User Setup',
                            (('user_name', False),
                             ('user_folder', False),
                             ('experiment_id', False),
                             ('scangui_verify_quit', True))
                            ),
                           ('Scan Definitions',
                            (('scandefs_verify_overwrite', True),
                             ('scandefs_load_showalltypes', True),
                             ('scandefs_load_showauto', True))
                            )
                           ):

            ir += 1
            sizer.Add(add_subtitle(panel, '%s:' % sect),  (ir, 0),  (1, 4), LEFT, 1)
            for vname, as_bool in vars:
                row = self.scandb.get_info(vname, full_row=True)
                _desc = row.notes or vname
                desc = wx.StaticText(panel, -1, label="  %s: " % _desc, size=(300, -1))

                val = row.value
                if as_bool:
                    try:
                        val = bool(int(row.value))
                    except:
                        val = False
                    ctrl = check(panel, default=val)
                else:
                    ctrl = wx.TextCtrl(panel, value=val,  size=(350, -1))
                self.wids[vname] = ctrl
                ir += 1
                sizer.Add(desc,  (ir, 0), (1, 1), LEFT|wx.ALL, 1)
                sizer.Add(ctrl,  (ir, 1), (1, 1), LEFT|wx.ALL, 1)


        ir += 1
        sizer.Add(wx.StaticLine(panel, size=(350, 3), style=wx.LI_HORIZONTAL),
                  (ir, 0), (1, 4), LEFT|wx.ALL, 1)
        ir += 1
        sizer.Add(okcancel(panel, self.onOK, self.onClose),
                  (ir, 0), (1, 3), LEFT|wx.ALL, 1)

        pack(panel, sizer)

        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)

        pack(self, mainsizer)
        self.Show()
        self.Raise()

    def onOK(self, event=None):
        for setting, wid in self.wids.items():
            if isinstance(wid, wx.CheckBox):
                val = {True:1, False:0}[wid.IsChecked()]
            else:
                val = self.wids[setting].GetValue().strip()
            self.scandb.set_info(setting, val)
        self.Destroy()

    def onClose(self, event=None):
        self.Destroy()
