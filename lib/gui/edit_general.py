#
# general parameter frame
import sys
import time
from functools import partial
import wx
import wx.lib.scrolledpanel as scrolled

from .gui_utils import (GUIColors, add_button, pack, SimpleText, TextCtrl,
                        HLine, check, okcancel, add_subtitle, LEFT, Font)

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
        sizer.Add(HLine(self, size=(600, 3)), (1, 0), (1, 3), LEFT)
        ir = 2

        expt_data = {}
        for row in scandb.get_info(prefix='experiment_', order_by='display_order',
                                   full_row=True):
            value = row.value
            if value is None:
                value = ''
            expt_data[row.key] = (row.value, row.notes)
        self.wids = {}
        for key, dat in expt_data.items():
            ir += 1
            val, desc = dat
            if val is None or len(val) < 1:
                val = ''
            if desc is None or len(desc) < 1:
                desc = key
            desc = ' %s:  '% desc
            label = SimpleText(self, desc, size=(225, -1), style=LEFT)
            ctext = TextCtrl(self, value=val, size=(250, -1),
                             action=partial(self.onSetValue, label=key))
            self.wids[key] = ctext
            sizer.Add(label, (ir, 0),  (1, 1), LEFT)
            sizer.Add(ctext, (ir, 1),  (1, 1), LEFT)
        pack(self, sizer)

    def onSetValue(self, value, label=None, **kws):
        if label is not None and len(label) > 0:
            self.scandb.set_info(label, value)

    def onPanelExposed(self, evt=None):
        for row in self.scandb.get_info(prefix='experiment_', full_row=True):
            if row.key in self.wids:
                self.wids[row.key].SetValue(row.value)


class SettingsFrame(wx.Frame) :
    """Frame for Setup General Settings:
    DB Connection, Settling Times, Extra PVs
    """
    def __init__(self, parent, pos=(-1, -1), scandb=None, _larch=None):
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
                    ctrl = wx.TextCtrl(panel, value=val,  size=(250, -1))
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
