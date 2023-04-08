import sys
import time
import json
import wx
import wx.lib.scrolledpanel as scrolled
from functools import partial
from collections import OrderedDict
from ..detectors import DET_DEFAULT_OPTS, AD_FILE_PLUGINS

from .gui_utils import (GUIColors, set_font_with_children, YesNo,
                        add_button, add_choice, pack, check, Font,
                        SimpleText, FloatCtrl, okcancel, add_subtitle,
                        CEN, RIGHT, LEFT, FRAMESTYLE)

from ..utils import strip_quotes

from epics import caget
from epics.wx import EpicsFunction

DET_CHOICES = ('scaler', 'tetramm', 'xspress3', 'struck',
               'mca', 'multimca', 'areadetector')

AD_CHOICES = ['None'] + list(AD_FILE_PLUGINS)

class ROIFrame(wx.Frame):
    """Select ROIS"""
    pvnames_xmap = {'pref': '%smca1.R',   'name': 'NM'}
    pvnames_xsp3 = {'pref': '%sMCA1ROI:', 'name': ':Name'}
    def __init__(self, parent, det=None, scandb=None, _larch=None):
        self.parent = parent
        self.scandb = parent.scandb if scandb is None else scandb
        title = "Select ROIs"
        wx.Frame.__init__(self, None, -1, 'Epics Scanning: Select ROIs',
                          style=FRAMESTYLE)
        self.SetFont(Font(10))
        self.build_dialog(parent)

    @EpicsFunction
    def connect_epics(self):
        curr = self.current_rois
        iroi = 0
        names = self.pvnames_xmap
        if 'xspress' in self.det.name:
            names = self.pvnames_xsp3
        prefix = self.prefix
        if prefix.endswith('.VAL'):
            prefix = prefix[:-4]
        pref = names['pref'] % prefix
        for i in range(self.nrois):
            pvname = "%s%i%s" % (pref, i+1, names['name'])
            # print("ROIS ",  i, names['name'], pvname)
            nm = caget(pvname)
            if len(nm.strip()) > 0:
                check = self.wids[i]
                check.SetLabel('  %s' % nm)
                check.SetValue(nm.lower() in curr)
                check.Enable()

    def build_dialog(self, parent):
        self.SetBackgroundColour(GUIColors.bg)
        roistring =  self.scandb.get_info('rois', default='[]').replace("'", '"')
        self.current_rois = [str(s.lower()) for s in json.loads(roistring)]
        self.det = None
        for det in self.scandb.get_rows('scandetectors', order_by='id'):
            dname = det.kind.lower().strip()
            if det.use == 1 and ('xsp' in dname or 'mca' in dname):
                self.det = det
                break
        #--#
        if self.det is None:
            return

        sizer = wx.GridBagSizer(2, 2)
        sizer.SetHGap(2)
        sizer.SetVGap(2)
        # title row
        irow = 0
        txt =SimpleText(self, ' Use ROI', minsize=(150, -1), style=LEFT)
        sizer.Add(txt, (0, 0),   (1, 1), LEFT, 2)
        txt =SimpleText(self, ' Use ROI', minsize=(150, -1), style=LEFT)
        sizer.Add(txt, (0, 1),   (1, 1), LEFT, 2)
        txt =SimpleText(self, ' Use ROI', minsize=(150, -1), style=LEFT)
        sizer.Add(txt, (0, 2),   (1, 1), LEFT, 2)


        self.wids = []
        self.prefix = self.det.pvname
        self.nrois  = 48 # int(json.loads(self.det.options).get('nrois', 48))
        ncols = 3
        nrows = 16 # self.nrois//ncols
        col = 0
        for i in range(self.nrois):
            icol = i //nrows
            irow = 1 + i % nrows
            use = check(self, default=False, label=' <unused>', size=(150, -1))
            use.Disable()
            self.wids.append(use)
            sizer.Add(use, (irow, icol), (1, 1), LEFT, 2)

        irow = nrows+1
        sizer.Add(wx.StaticLine(self, size=(475, -1), style=wx.LI_HORIZONTAL),
                  (irow, 0), (1, 4), CEN, 2)
        irow += 1
        sizer.Add(okcancel(self, self.onOK, self.onClose),
                  (irow, 0), (1, 3), LEFT, 2)


        pack(self, sizer)
        wx.CallAfter(self.connect_epics)
        self.SetSize((475, 525))
        self.Show()
        self.Raise()

    def onOK(self, event=None):
        rois = []
        for use in self.wids:
            if use.Enabled and use.IsChecked():
                rois.append(use.GetLabel().strip())
        roistring =  json.dumps(rois)
        self.scandb.set_info('rois', roistring)
        self.Destroy()

    def onClose(self, event=None):
        self.Destroy()


class DetectorDetailsFrame(wx.Frame):
    """Full list of detector settings"""
    def __init__(self, parent, det=None):
        self.parent = parent
        self.scandb = parent.scandb
        self.det = det
        title = "Settings for '%s'" % (det.name)
        wx.Frame.__init__(self, None, -1, title, style=FRAMESTYLE)
        self.SetFont(Font(8))
        self.build_dialog(parent)

    def build_dialog(self, parent):
        self.SetBackgroundColour(GUIColors.bg)

        self.SetFont(parent.GetFont())
        sizer = wx.GridBagSizer(3, 2)
        sizer.SetHGap(2)
        sizer.SetVGap(2)
        # title row
        i = 0
        for titleword in (' Setting ', 'Value'):
            txt =SimpleText(self, titleword,
                            minsize=(100, -1),   style=RIGHT)
            sizer.Add(txt, (0, i), (1, 1), LEFT, 1)
            i += 1

        sizer.Add(wx.StaticLine(self, size=(250, -1),
                                style=wx.LI_HORIZONTAL),
                  (1, 0), (1, 4), CEN, 0)

        self.wids = {}
        prefix = self.det.pvname
        kind   = self.det.kind
        opts   = DET_DEFAULT_OPTS.get(kind, {})
        opts.update(json.loads(self.det.options))
        optkeys = list(opts.keys())
        optkeys.sort()
        irow = 2
        for key in optkeys:
            if key in ('use', 'kind', 'label'):
                continue
            val = opts[key]
            label = key
            for short, longw in (('_', ' '),
                                 ('chan', 'channels'),
                                 ('mcas', 'MCAs'),
                                 ('rois', 'ROIs')):
                label = label.replace(short, longw)

            if label.startswith('n'):
                label = '# of %s' % (label[1:])
            label = label.title()
            label = SimpleText(self, label, style=LEFT)
            val = strip_quotes(val)

            if key.lower() == 'file_plugin':
                wid = add_choice(self, AD_CHOICES, default=1)
                if val in AD_CHOICES:
                    wid.SetStringSelection(val)
            elif val in (True, False, 'Yes', 'No'):
                defval = val in (True, 'Yes')
                wid = check(self, default=defval)
            elif isinstance(val, (int, float)):
                wid = FloatCtrl(self, value=val, size=(150, -1))
            else:
                wid = wx.TextCtrl(self, value=val, size=(150, -1))
            sizer.Add(label, (irow, 0), (1, 1), LEFT,  2)
            sizer.Add(wid,   (irow, 1), (1, 1), RIGHT,  2)
            self.wids[key] = wid
            irow  += 1

        sizer.Add(wx.StaticLine(self, size=(250, -1), style=wx.LI_HORIZONTAL),
                  (irow, 0), (1, 4), CEN, 0)

        sizer.Add(okcancel(self, self.onOK, self.onClose),
                  (irow+1, 0), (1, 3), LEFT, 1)
        self.Bind(wx.EVT_CLOSE, self.onClose)
        self.SetMinSize((225, 350))
        pack(self, sizer)
        self.Show()
        self.Raise()


    def onOK(self, event=None):
        opts = {}
        for key, wid in self.wids.items():
            if isinstance(wid, wx.TextCtrl):
                val = wid.GetValue()
                try:
                    val = float(val)
                except:
                    pass
            elif isinstance(wid, wx.Choice):
                val =  wid.GetStringSelection()
            elif isinstance(wid, wx.CheckBox):
                val =  wid.IsChecked()
            elif isinstance(wid, YesNo):
                val =  {0:False, 1:True}[wid.GetSelection()]
            opts[key] = val

        self.det.options = json.dumps(opts)
        self.onClose()

    def onClose(self, event=None):
        self.parent.detailframe = None
        self.Destroy()

class DetectorFrame(wx.Frame) :
    """Frame to Setup Scan Detectors"""
    def __init__(self, parent, pos=(-1, -1), scandb=None, _larch=None):
        self.parent = parent
        self.scandb = parent.scandb if scandb is None else scandb
        self.detailframe = None

        self.detectors = self.scandb.get_rows('scandetectors', order_by='id')
        self.counters = self.scandb.get_rows('scancounters', order_by='id')

        wx.Frame.__init__(self, None, -1, 'Epics Scanning: Detector Setup',
                          style=FRAMESTYLE)

        self.SetFont(Font(9))

        sizer = wx.GridBagSizer(3, 2)
        sizer.SetHGap(2)
        sizer.SetVGap(2)
        panel = scrolled.ScrolledPanel(self) # , size=(675, 625))
        self.SetMinSize((650, 625))
        panel.SetBackgroundColour(GUIColors.bg)

        # title row
        title = SimpleText(panel, 'Detector Setup',  font=Font(13),
                           minsize=(130, -1),
                           colour=GUIColors.title, style=LEFT)

        sizer.Add(title,        (0, 0), (1, 1), LEFT, 2)

        desc = wx.StaticText(panel, -1, label='Detector Settling Time (sec): ',
                             size=(180, -1))

        self.settle_time = wx.TextCtrl(panel, size=(75, -1),
                            value=self.scandb.get_info('det_settle_time', '0.001'))
        sizer.Add(desc,              (1, 0), (1, 2), CEN,  3)
        sizer.Add(self.settle_time,  (1, 2), (1, 2), LEFT, 3)

        ir = 2
        sizer.Add(add_subtitle(panel, 'Available Detectors'),
                  (ir, 0),  (1, 5),  LEFT, 0)

        ir +=1
        sizer.Add(SimpleText(panel, label='Label',  size=(125, -1)),
                  (ir, 0), (1, 1), LEFT, 1)
        sizer.Add(SimpleText(panel, label='PV prefix', size=(175, -1)),
                  (ir, 1), (1, 1), LEFT, 1)
        sizer.Add(SimpleText(panel, label='Use?'),
                  (ir, 2), (1, 1), LEFT, 1)
        sizer.Add(SimpleText(panel, label='Kind',     size=(80, -1)),
                  (ir, 3), (1, 1), LEFT, 1)
        sizer.Add(SimpleText(panel, label='Details',  size=(60, -1)),
                  (ir, 4), (1, 1), LEFT, 1)
        sizer.Add(SimpleText(panel, label='Erase?',  size=(60, -1)),
                  (ir, 5), (1, 1), LEFT, 1)

        self.widlist = []
        for det in self.detectors:
            if det.use is None:
                det.use = 0
            ir +=1
            dkind = strip_quotes(det.kind)
            dkind  = det.kind.title().strip()
            desc   = wx.TextCtrl(panel, value=det.name,   size=(125, -1))
            pvctrl = wx.TextCtrl(panel, value=det.pvname, size=(175, -1))
            use    = check(panel, default=det.use)
            detail = add_button(panel, 'Edit', size=(60, -1),
                                action=partial(self.onDetDetails, det=det))
            kind = add_choice(panel, DET_CHOICES, size=(110, -1))
            kind.SetStringSelection(dkind)
            erase  = YesNo(panel, defaultyes=False)
            sizer.Add(desc,   (ir, 0), (1, 1),  CEN, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LEFT, 1)
            sizer.Add(use,    (ir, 2), (1, 1), LEFT, 1)
            sizer.Add(kind,   (ir, 3), (1, 1), LEFT, 1)
            sizer.Add(detail, (ir, 4), (1, 1), LEFT, 1)
            sizer.Add(erase,  (ir, 5), (1, 1), LEFT, 1)

            self.widlist.append(('old_det', det, desc, pvctrl, use, kind, erase))

        # select a new detector
        for i in range(1):
            ir +=1
            desc   = wx.TextCtrl(panel, value='',   size=(125, -1))
            pvctrl = wx.TextCtrl(panel, value='',   size=(175, -1))
            use    = check(panel, default=False)
            kind = add_choice(panel, DET_CHOICES, size=(110, -1))
            kind.SetStringSelection(DET_CHOICES[0])
            sizer.Add(desc,   (ir, 0), (1, 1), CEN, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LEFT, 1)
            sizer.Add(use,    (ir, 2), (1, 1), LEFT, 1)
            sizer.Add(kind,   (ir, 3), (1, 1), LEFT, 1)
            self.widlist.append(('new_det', None, desc, pvctrl, use, kind, False))

        ir += 1
        sizer.Add(add_subtitle(panel, 'Additional Counters'),
                  (ir, 0),  (1, 5),  LEFT, 1)

        ###
        ir += 1
        sizer.Add(SimpleText(panel, label='Label',  size=(125, -1)),
                  (ir, 0), (1, 1), LEFT, 1)
        sizer.Add(SimpleText(panel, label='PV name', size=(175, -1)),
                  (ir, 1), (1, 1), LEFT, 1)
        sizer.Add(SimpleText(panel, label='Use?'),
                  (ir, 2), (1, 1), LEFT, 1)
        sizer.Add(SimpleText(panel, label='Erase?', size=(80, -1)),
                  (ir, 3), (1, 2), LEFT, 1)

        for counter in self.counters:
            if counter.use is None: counter.use = 0
            desc   = wx.TextCtrl(panel, -1, value=counter.name, size=(125, -1))
            pvctrl = wx.TextCtrl(panel, value=counter.pvname,  size=(175, -1))
            use    = check(panel, default=counter.use)
            erase  = YesNo(panel, defaultyes=False)
            ir +=1
            sizer.Add(desc,   (ir, 0), (1, 1), CEN, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LEFT, 1)
            sizer.Add(use,    (ir, 2), (1, 1), LEFT, 1)
            sizer.Add(erase,  (ir, 3), (1, 1), LEFT, 1)
            self.widlist.append(('old_counter', counter, desc,
                                 pvctrl, use, None, erase))

        for i in range(2):
            desc   = wx.TextCtrl(panel, -1, value='', size=(125, -1))
            pvctrl = wx.TextCtrl(panel, value='', size=(175, -1))
            use    = check(panel, default=False)
            ir +=1
            sizer.Add(desc,   (ir, 0), (1, 1), CEN, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LEFT, 1)
            sizer.Add(use,    (ir, 2), (1, 1), LEFT, 1)
            self.widlist.append(('new_counter', None, desc,
                                 pvctrl, use, None, False))
        ir += 1
        sizer.Add(wx.StaticLine(panel, size=(350, 3), style=wx.LI_HORIZONTAL),
                  (ir, 0), (1, 4), LEFT|wx.EXPAND, 3)
        ###
        ir += 1
        sizer.Add(okcancel(panel, self.onOK, self.onClose),
                  (ir, 0), (1, 3), LEFT, 1)

        pack(panel, sizer)
        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)

        self.Bind(wx.EVT_CLOSE, self.onClose)
        pack(self, mainsizer)
        self.Show()
        self.Raise()

    def onDetDetails(self, evt=None, det=None, **kws):
        if self.detailframe is None:
            self.detailframe = DetectorDetailsFrame(self, det=det)

    def onOK(self, event=None):
        self.scandb.set_info('det_settle_time', float(self.settle_time.GetValue()))
        for w in self.widlist:
            wtype, obj, name, pvname, use, kind, erase = w
            if erase not in (None, False):
                erase = erase.GetSelection()
            else:
                erase = False

            use    = 1 if use.IsChecked() else 0
            name   = name.GetValue().strip()
            pvname = pvname.GetValue().strip()
            if pvname.endswith('.VAL'):
                pvname = pvname[:-4]

            if len(name) < 1 or len(pvname) < 1:
                continue
            # print("DET onOK: ",  wtype, name, pvname, use)

            if kind is None:
                try:
                    kind = kind.GetStringSelection()
                except:
                    continue
                #             if erase and obj is not None:
                #                 delete = self.scandb.del_detector
                #                 if 'counter' in wtype:
                #                     delete = self.scan.del_counter
                #                 delete(obj.name)
            if wtype=='old_det' and obj is not None:
                print("SET DET ", name, pvname, use)
                self.scandb.update('scandetectors', where={'name': name},
                                   use=use, pvname=pvname)
            elif wtype=='new_det':
                opts = json.dumps(DET_DEFAULT_OPTS.get(kind, {}))
                self.scandb.add_detector(name, pvname, kind,
                                         options=opts, use=use)
            elif 'counter' in wtype:
                self.scandb.add_counter(name, pvname, use=use)

        self.Destroy()

    def onClose(self, event=None):
        self.Destroy()
