import sys
import time

import wx
import wx.lib.scrolledpanel as scrolled

from .gui_utils import (GUIColors, set_font_with_children, YesNo,
                        add_button, add_subtitle, okcancel, Font,
                        pack, SimpleText, LEFT, CEN, RIGHT,
                        FRAMESTYLE)

class PositionerFrame(wx.Frame) :
    """Frame to Setup Scan Positioners"""
    def __init__(self, parent, pos=(-1, -1), scandb=None, mkernel=None):

        self.parent = parent
        self.scandb = parent.scandb if scandb is None else scandb

        wx.Frame.__init__(self, None, -1, 'Epics Scanning: Positioners Setup',
                          style=FRAMESTYLE)

        self.SetFont(Font(9))
        sizer = wx.GridBagSizer(3, 2)
        panel = scrolled.ScrolledPanel(self)
        self.SetMinSize((625, 750))
        panel.SetBackgroundColour(GUIColors.bg)

        # title row
        title = SimpleText(panel, 'Positioners Setup',  font=Font(13),
                           colour=GUIColors.title, style=LEFT)

        sizer.Add(title,     (0, 0), (1, 3), LEFT, 5)


        desc = wx.StaticText(panel, -1, label='Positioner Settling Time (sec): ',
                             size=(180, -1))

        self.settle_time = wx.TextCtrl(panel, size=(75, -1),
                            value=self.scandb.get_info('pos_settle_time', '0.001'))
        sizer.Add(desc,              (1, 1), (1, 2), LEFT,  1)
        sizer.Add(self.settle_time,  (1, 3), (1, 1), LEFT, 1)


        ir = 2
        sizer.Add(SimpleText(panel, 'Linear/Mesh Scan Positioners',
                             size=(250,-1), style=LEFT),
                  (ir, 0),  (1, 4),  LEFT, 1)
        ir += 1
        sizer.Add(SimpleText(panel, label='Description', size=(180, -1)),
                  (ir, 0), (1, 1), RIGHT, 1)
        sizer.Add(SimpleText(panel, label='Drive PV', size=(180, -1)),
                  (ir, 1), (1, 1), RIGHT, 1)
        sizer.Add(SimpleText(panel, label='Readback PV', size=(180, -1)),
                  (ir, 2), (1, 1), LEFT, 1)
        sizer.Add(SimpleText(panel, label='Erase?', size=(80, -1)),
                  (ir, 3), (1, 1), LEFT, 1)

        self.widlist = []
        poslist = []
        for pos in self.scandb.get_rows('scanpositioners'):
            poslist.append(pos.name)
            desc   = wx.TextCtrl(panel, -1, value=pos.name, size=(180, -1))
            pvctrl = wx.TextCtrl(panel, value=pos.drivepv,  size=(180, -1))
            rdctrl = wx.TextCtrl(panel, value=pos.readpv,  size=(180, -1))
            delpv  = YesNo(panel, defaultyes=False, size=(80, -1))
            ir +=1
            sizer.Add(desc,   (ir, 0), (1, 1), RIGHT, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LEFT, 1)
            sizer.Add(rdctrl, (ir, 2), (1, 1), LEFT, 1)
            sizer.Add(delpv,  (ir, 3), (1, 1), LEFT, 1)
            self.widlist.append(('line', pos, desc, pvctrl, rdctrl, delpv))

        for i in range(2):
            desc   = wx.TextCtrl(panel, -1, value='', size=(180, -1))
            pvctrl = wx.TextCtrl(panel, value='', size=(180, -1))
            rdctrl = wx.TextCtrl(panel, value='', size=(180, -1))
            ir +=1
            sizer.Add(desc,   (ir, 0), (1, 1), RIGHT, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LEFT, 1)
            sizer.Add(rdctrl, (ir, 2), (1, 1), LEFT, 1)
            self.widlist.append(('line', None, desc, pvctrl, rdctrl, None))

        # xafs
        ir += 1
        sizer.Add(SimpleText(panel, 'Positioner for XAFS Scans',
                             size=(250, -1), style=LEFT),
                  (ir, 0),  (1, 4),  LEFT, 1)

        energy = self.scandb.get_info('xafs_energy')
        desc   = wx.StaticText(panel, -1, label='Energy Positioner', size=(180, -1))
        pvctrl = wx.Choice(panel, choices=poslist, size=(180, -1))
        pvctrl.SetStringSelection(energy)
        ir +=1
        sizer.Add(desc,   (ir, 0), (1, 1), RIGHT, 1)
        sizer.Add(pvctrl, (ir, 1), (1, 2), LEFT, 1)
        self.widlist.append(('xafs', None, desc, pvctrl, None, None))

        # slew scans
        ir += 1
        sizer.Add(SimpleText(panel, 'Slew Scan Positioners',
                             size=(250, -1), style=LEFT),
                  (ir, 0),  (1, 4),  LEFT, 1)

        for pos in self.scandb.get_rows('slewscanpositioners'):
            desc   = wx.TextCtrl(panel, -1, value=pos.name, size=(180, -1))
            pvctrl = wx.TextCtrl(panel, value=pos.drivepv,  size=(180, -1))
            rdctrl = wx.TextCtrl(panel, value=pos.readpv,  size=(180, -1))
            delpv  = YesNo(panel, defaultyes=False, size=(80, -1))
            ir +=1
            sizer.Add(desc,   (ir, 0), (1, 1), RIGHT, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LEFT, 1)
            sizer.Add(rdctrl, (ir, 2), (1, 1), LEFT, 1)
            sizer.Add(delpv,  (ir, 3), (1, 1), LEFT, 1)
            self.widlist.append(('slew', pos, desc, pvctrl, rdctrl, delpv))

        for i in range(1):
            desc   = wx.TextCtrl(panel, -1, value='', size=(180, -1))
            pvctrl = wx.TextCtrl(panel, value='', size=(180, -1))
            rdctrl = wx.TextCtrl(panel, value='', size=(180, -1))
            ir +=1
            sizer.Add(desc,   (ir, 0), (1, 1), RIGHT, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LEFT, 1)
            sizer.Add(rdctrl, (ir, 2), (1, 1), LEFT, 1)
            self.widlist.append(('slew', None, desc, pvctrl, rdctrl, None))

        ir += 1
        sizer.Add(wx.StaticLine(panel, size=(350, 3), style=wx.LI_HORIZONTAL),
                  (ir, 0), (1, 4), LEFT, 3)
        #
        ir += 1
        sizer.Add(okcancel(panel, self.onOK, self.onClose),
                  (ir, 0), (1, 2), LEFT, 1)

        pack(panel, sizer)
        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)

        pack(self, mainsizer)
        self.Show()
        self.Raise()


    def onOK(self, event=None):
        self.scandb.set_info('pos_settle_time',
                             float(self.settle_time.GetValue()))
        for w in self.widlist:
            wtype, obj, name, drivepv, readpv, erase = w
            if wtype == 'xafs':
                name = drivepv.GetStringSelection()
                energy = self.scandb.set_info('xafs_energy', name)
                continue
            if erase is not None:
                erase = erase.GetSelection()
            else:
                erase = False
            name    = name.GetValue().strip()
            drivepv = drivepv.GetValue().strip()
            if len(name) < 1 or len(drivepv) < 1:
                continue

            readpv  = readpv.GetValue().strip()
            if len(readpv) < 1:
                readpv = drivepv

            tablename = 'slewscanpositioners' if wtype == 'slew' else 'scanpositioners'
            if obj is None:
                if wtype == 'line':
                    self.scandb.add_positioner(name, drivepv, readpv=readpv)
                elif wtype == 'slew':
                    self.scandb.add_slewpositioner(name, drivepv, readpv=readpv)
            elif erase:
                self.scandb.delete_rows(tablename, where={'id': obj.id})
            else:
                self.scandb.update(tablename, where={'id': obj.id},
                                   name=name, use=1, drivepv=drivepv, readpv=readpv)


        for page in self.parent.nb.pagelist:
            if hasattr(page, 'update_positioners'):
                page.update_positioners()
                # print("updated positioners for ", page)
        self.Destroy()


    def onClose(self, event=None):
        self.Destroy()
