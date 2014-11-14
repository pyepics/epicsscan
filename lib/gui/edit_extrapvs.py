import sys
import time
import wx
import wx.lib.scrolledpanel as scrolled

from .gui_utils import (GUIColors, set_font_with_children, YesNo,
                        add_button, pack, SimpleText, check, okcancel,
                        add_subtitle, Font, LCEN, CEN, RCEN,
                        FRAMESTYLE)

RCEN |= wx.ALL
LCEN |= wx.ALL
CEN  |= wx.ALL

class ExtraPVsFrame(wx.Frame) :
    """Set Extra PVs"""
    def __init__(self, parent, pos=(-1, -1), _larch=None):
        self.parent = parent
        self.scandb = parent.scandb

        wx.Frame.__init__(self, None, -1, 'Epics Scanning: Extra PVs Setup',
                          style=FRAMESTYLE)

        self.SetFont(Font(9))
        sizer = wx.GridBagSizer(10, 5)
        panel = scrolled.ScrolledPanel(self)
        self.SetMinSize((525, 550))
        self.colors = GUIColors()
        panel.SetBackgroundColour(self.colors.bg)

        # title row
        title = SimpleText(panel, 'Extra PVs Setup',  font=Font(13),
                           colour=self.colors.title, style=LCEN)

        sizer.Add(title,        (0, 0), (1, 3), LCEN, 5)

        ir = 1
        sizer.Add(SimpleText(panel, label='PV Name', size=(200, -1)),
                  (ir, 0), (1, 1), LCEN, 2)
        sizer.Add(SimpleText(panel, label='Description', size=(200, -1)),
                  (ir, 1), (1, 1), LCEN, 2)
        sizer.Add(SimpleText(panel, label='Use?'),
                  (ir, 2), (1, 1), LCEN, 2)
        sizer.Add(SimpleText(panel, label='Erase?', size=(60, -1)),
                  (ir, 3), (1, 1), LCEN, 2)

        self.widlist = []
        for this in self.scandb.getall('extrapvs'):
            pvctrl = wx.TextCtrl(panel, value=this.pvname,  size=(200, -1))
            desc   = wx.TextCtrl(panel, -1, value=this.name, size=(200, -1))
            usepv  = check(panel, default=this.use)
            delpv  = YesNo(panel, defaultyes=False)

            ir +=1
            sizer.Add(pvctrl, (ir, 0), (1, 1), RCEN, 2)
            sizer.Add(desc,   (ir, 1), (1, 1), LCEN, 2)
            sizer.Add(usepv,  (ir, 2), (1, 1), LCEN, 2)
            sizer.Add(delpv,  (ir, 3), (1, 1), LCEN, 2)
            self.widlist.append((this, pvctrl, desc, usepv, delpv))

        for i in range(3):
            pvctrl = wx.TextCtrl(panel, value='', size=(200, -1))
            desc   = wx.TextCtrl(panel, -1, value='', size=(200, -1))
            usepv  = check(panel, default=False)
            ir +=1
            sizer.Add(pvctrl,   (ir, 0), (1, 1), RCEN, 2)
            sizer.Add(desc, (ir, 1), (1, 1), LCEN, 2)
            sizer.Add(usepv,  (ir, 2), (1, 1), LCEN, 2)
            self.widlist.append((None, pvctrl, desc, usepv, None))

        ir += 1
        sizer.Add(wx.StaticLine(panel, size=(350, 3), style=wx.LI_HORIZONTAL),
                  (ir, 0), (1, 4), LCEN, 3)
        #
        ir += 1
        sizer.Add(okcancel(panel, self.onOK, self.onClose),
                  (ir, 0), (1, 2), LCEN, 3)

        pack(panel, sizer)

        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)
        pack(self, mainsizer)
        self.Show()
        self.Raise()


    def onOK(self, event=None):
        for w in self.widlist:
            obj, pvctrl, desc, usepv, erase = w
            if usepv is not None:
                usepv = usepv.IsChecked()
            else:
                usepv = True

            if erase is not None:
                erase = erase.GetSelection()
            else:
                erase = False
            name   = desc.GetValue().strip()
            pvname = pvctrl.GetValue().strip()
            if len(name) < 1 or len(pvname) < 1:
                continue
            if erase and obj is not None:
                self.scandb.del_extrapv(obj.name)
            elif obj is not None:
                obj.name = name
                obj.pvname = pvname
                obj.use  = int(usepv)
            elif obj is None:
                self.scandb.add_extrapv(name, pvname, use=usepv)

        self.scandb.commit()
        self.Destroy()


    def onClose(self, event=None):
        self.Destroy()
