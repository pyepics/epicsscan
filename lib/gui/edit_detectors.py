
import sys
import time
import json
import wx
import wx.lib.scrolledpanel as scrolled

from ..ordereddict import OrderedDict
from ..detectors import DET_DEFAULT_OPTS, AD_FILE_PLUGINS

from .gui_utils import (GUIColors, set_font_with_children, YesNo, Closure,
                        add_button, add_choice, pack, check, Font,
                        SimpleText, FloatCtrl, okcancel, add_subtitle,
                        LCEN, CEN, RCEN, LEFT, FRAMESTYLE)

from ..utils import strip_quotes

from epics import caget
from epics.wx import EpicsFunction

LCEN  |= wx.ALL
RCEN  |= wx.ALL
CEN  |= wx.ALL

DET_CHOICES = ('scaler', 'xspress3', 'mca', 'multimca', 'areadetector')
AD_CHOICES = ['None'] + list(AD_FILE_PLUGINS)

class ROIFrame(wx.Frame):
    """Select ROIS"""
    def __init__(self, parent, det=None, _larch=None):
        self.parent = parent
        self.scandb = parent.scandb
        title = "Select ROIs"
        wx.Frame.__init__(self, None, -1, 'Epics Scanning: Select ROIs',
                          style=FRAMESTYLE)
        self.SetFont(Font(8))
        self.build_dialog(parent)

    @EpicsFunction
    def connect_epics(self):
        curr = self.current_rois
        iroi = 0
        pref = "%smca1.R" % self.prefix
        for i in range(self.nrois):
            nm = caget("%s%iNM" % (pref, i))
            hi = caget("%s%iHI" % (pref, i))
            if len(nm.strip()) > 0 and hi > 0:
                self.wids[i][0].SetLabel('  %s ' % nm)
                self.wids[i][1].SetValue(nm.lower() in curr)
                self.wids[i][1].Enable()

    def build_dialog(self, parent):
        self.colors = GUIColors()
        self.SetBackgroundColour(self.colors.bg)
        roistring =  self.scandb.get_info('rois', default='[]').replace("'", '"')
        self.current_rois = [str(s.lower()) for s in json.loads(roistring)]
        self.det = None
        for det in self.scandb.getall('scandetectors', orderby='id'):
            dname = det.kind.lower().strip()
            if det.use == 1 and ('xsp' in dname or 'mca' in dname):
                self.det = det
                break
        #--#
        if self.det is None:
            return

        sizer = wx.GridBagSizer(20, 4)
        # title row
        irow = 0
        txt =SimpleText(self, ' ROI', minsize=(80, -1), style=LEFT)
        sizer.Add(txt, (0, 0),   (1, 1), LCEN, 1)
        txt =SimpleText(self, ' ROI', minsize=(80, -1), style=LEFT)
        sizer.Add(txt, (0, 2),   (1, 1), LCEN, 1)
        txt =SimpleText(self, ' Use?', minsize=(40, -1), style=LEFT)
        sizer.Add(txt, (0, 1),   (1, 1), LCEN, 1)
        txt =SimpleText(self, ' Use?', minsize=(40, -1), style=LEFT)
        sizer.Add(txt, (0, 3),   (1, 1), LCEN, 1)

        self.wids = []
        self.prefix = self.det.pvname
        self.nrois  = int(json.loads(self.det.options).get('nrois', 32))
        nrows = self.nrois/2
        col = 0
        for i in range(self.nrois):
            lab = SimpleText(self, ' <unused>', minsize=(80, -1))
            use = check(self, default=False)
            use.Disable()
            self.wids.append((lab, use))
            if i ==  nrows:
                col = 2
                irow = irow - nrows
            irow += 1
            sizer.Add(lab, (irow, col),   (1, 1), LCEN, 0)
            sizer.Add(use, (irow, col+1), (1, 1), LEFT, 0)

        irow += 1
        sizer.Add(wx.StaticLine(self, size=(350, -1), style=wx.LI_HORIZONTAL),
                  (irow, 0), (1, 4), CEN, 0)
        irow += 1
        sizer.Add(okcancel(self, self.onOK, self.onClose),
                  (irow, 0), (1, 3), LCEN, 0)
        pack(self, sizer)
        wx.CallAfter(self.connect_epics)
        self.SetSize((325, 700))
        self.Show()
        self.Raise()

    def onOK(self, event=None):
        rois = []
        for (label, use) in self.wids:
            if use.Enabled and use.IsChecked():
                rois.append(label.GetLabel().strip())
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
        self.colors = GUIColors()
        self.SetBackgroundColour(self.colors.bg)

        self.SetFont(parent.GetFont())
        sizer = wx.GridBagSizer(10, 3)

        # title row
        i = 0
        for titleword in (' Setting ', 'Value'):
            txt =SimpleText(self, titleword,
                            minsize=(100, -1),   style=RCEN)
            sizer.Add(txt, (0, i), (1, 1), LCEN, 1)
            i += 1

        sizer.Add(wx.StaticLine(self, size=(250, -1),
                                style=wx.LI_HORIZONTAL),
                  (1, 0), (1, 4), CEN, 0)

        self.wids = {}
        prefix = self.det.pvname
        opts   = json.loads(self.det.options)
        optkeys = opts.keys()
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
            label = SimpleText(self, label, style=LCEN)
            val = strip_quotes(val)

            if val in (True, False, 'Yes', 'No'):
                defval = val in (True, 'Yes')
                wid = check(self, default=defval)
            elif key.lower() == 'file_plugin':
                wid = add_choice(self, AD_CHOICES, default=1)
            elif isinstance(val, (int, float)):
                wid = FloatCtrl(self, value=val, size=(150, -1))
            else:
                wid = wx.TextCtrl(self, value=val, size=(150, -1))

            sizer.Add(label, (irow, 0), (1, 1), LCEN,  2)
            sizer.Add(wid,   (irow, 1), (1, 1), RCEN,  2)
            self.wids[key] = wid
            irow  += 1

        sizer.Add(wx.StaticLine(self, size=(250, -1), style=wx.LI_HORIZONTAL),
                  (irow, 0), (1, 4), CEN, 0)

        sizer.Add(okcancel(self, self.onOK, self.onClose),
                  (irow+1, 0), (1, 3), LCEN, 1)
        wx.EVT_CLOSE(self, self.onClose)        
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
    def __init__(self, parent, pos=(-1, -1), _larch=None):
        self.parent = parent
        self.scandb = parent.scandb
        self.detailframe = None

        self.detectors = self.scandb.getall('scandetectors', orderby='id')
        self.counters = self.scandb.getall('scancounters', orderby='id')

        wx.Frame.__init__(self, None, -1, 'Epics Scanning: Detector Setup',
                          style=FRAMESTYLE)

        self.SetFont(Font(9))

        sizer = wx.GridBagSizer(12, 5)
        panel = scrolled.ScrolledPanel(self) # , size=(675, 625))
        self.SetMinSize((650, 625))
        self.colors = GUIColors()
        panel.SetBackgroundColour(self.colors.bg)

        # title row
        title = SimpleText(panel, 'Detector Setup',  font=Font(13),
                           minsize=(130, -1),
                           colour=self.colors.title, style=LCEN)

        sizer.Add(title,        (0, 0), (1, 1), LCEN, 2)

        desc = wx.StaticText(panel, -1, label='Detector Settling Time (sec): ',
                             size=(180, -1))

        self.settle_time = wx.TextCtrl(panel, size=(75, -1),
                            value=self.scandb.get_info('det_settle_time', '0.001'))
        sizer.Add(desc,              (1, 0), (1, 2), CEN,  3)
        sizer.Add(self.settle_time,  (1, 2), (1, 2), LCEN, 3)

        ir = 2
        sizer.Add(add_subtitle(panel, 'Available Detectors'),
                  (ir, 0),  (1, 5),  LCEN, 0)

        ir +=1
        sizer.Add(SimpleText(panel, label='Label',  size=(125, -1)),
                  (ir, 0), (1, 1), LCEN, 1)
        sizer.Add(SimpleText(panel, label='PV prefix', size=(175, -1)),
                  (ir, 1), (1, 1), LCEN, 1)
        sizer.Add(SimpleText(panel, label='Use?'),
                  (ir, 2), (1, 1), LCEN, 1)
        sizer.Add(SimpleText(panel, label='Kind',     size=(80, -1)),
                  (ir, 3), (1, 1), LCEN, 1)
        sizer.Add(SimpleText(panel, label='Details',  size=(60, -1)),
                  (ir, 4), (1, 1), LCEN, 1)
        sizer.Add(SimpleText(panel, label='Erase?',  size=(60, -1)),
                  (ir, 5), (1, 1), LCEN, 1)

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
                                action=Closure(self.onDetDetails, det=det))
            kind = add_choice(panel, DET_CHOICES, size=(110, -1))
            kind.SetStringSelection(dkind)
            erase  = YesNo(panel, defaultyes=False)
            sizer.Add(desc,   (ir, 0), (1, 1),  CEN, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LCEN, 1)
            sizer.Add(use,    (ir, 2), (1, 1), LCEN, 1)
            sizer.Add(kind,   (ir, 3), (1, 1), LCEN, 1)
            sizer.Add(detail, (ir, 4), (1, 1), LCEN, 1)
            sizer.Add(erase,  (ir, 5), (1, 1), LCEN, 1)

            self.widlist.append(('old_det', det, desc, pvctrl, use, kind, erase))

        # select a new detector
        for i in range(2):
            ir +=1
            desc   = wx.TextCtrl(panel, value='',   size=(125, -1))
            pvctrl = wx.TextCtrl(panel, value='',   size=(175, -1))
            use    = check(panel, default=True)
            kind = add_choice(panel, DET_CHOICES, size=(110, -1))
            kind.SetStringSelection(DET_CHOICES[0])
            sizer.Add(desc,   (ir, 0), (1, 1), CEN, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LCEN, 1)
            sizer.Add(use,    (ir, 2), (1, 1), LCEN, 1)
            sizer.Add(kind,   (ir, 3), (1, 1), LCEN, 1)
            self.widlist.append(('new_det', None, desc, pvctrl, use, kind, False))

        ir += 1
        sizer.Add(add_subtitle(panel, 'Additional Counters'),
                  (ir, 0),  (1, 5),  LCEN, 1)

        ###
        ir += 1
        sizer.Add(SimpleText(panel, label='Label',  size=(125, -1)),
                  (ir, 0), (1, 1), LCEN, 1)
        sizer.Add(SimpleText(panel, label='PV name', size=(175, -1)),
                  (ir, 1), (1, 1), LCEN, 1)
        sizer.Add(SimpleText(panel, label='Use?'),
                  (ir, 2), (1, 1), LCEN, 1)
        sizer.Add(SimpleText(panel, label='Erase?', size=(80, -1)),
                  (ir, 3), (1, 2), LCEN, 1)

        for counter in self.counters:
            if counter.use is None: counter.use = 0
            desc   = wx.TextCtrl(panel, -1, value=counter.name, size=(125, -1))
            pvctrl = wx.TextCtrl(panel, value=counter.pvname,  size=(175, -1))
            use    = check(panel, default=counter.use)
            erase  = YesNo(panel, defaultyes=False)
            ir +=1
            sizer.Add(desc,   (ir, 0), (1, 1), CEN, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LCEN, 1)
            sizer.Add(use,    (ir, 2), (1, 1), LCEN, 1)
            sizer.Add(erase,  (ir, 3), (1, 1), LCEN, 1)
            self.widlist.append(('old_counter', counter, desc,
                                 pvctrl, use, None, erase))

        for i in range(2):
            desc   = wx.TextCtrl(panel, -1, value='', size=(125, -1))
            pvctrl = wx.TextCtrl(panel, value='', size=(175, -1))
            use    = check(panel, default=True)
            ir +=1
            sizer.Add(desc,   (ir, 0), (1, 1), CEN, 1)
            sizer.Add(pvctrl, (ir, 1), (1, 1), LCEN, 1)
            sizer.Add(use,    (ir, 2), (1, 1), LCEN, 1)
            self.widlist.append(('new_counter', None, desc,
                                 pvctrl, use, None, False))
        ir += 1
        sizer.Add(wx.StaticLine(panel, size=(350, 3), style=wx.LI_HORIZONTAL),
                  (ir, 0), (1, 4), LCEN|wx.EXPAND, 3)
        ###
        ir += 1
        sizer.Add(okcancel(panel, self.onOK, self.onClose),
                  (ir, 0), (1, 3), LCEN, 1)

        pack(panel, sizer)
        panel.SetupScrolling()

        mainsizer = wx.BoxSizer(wx.VERTICAL)
        mainsizer.Add(panel, 1, wx.GROW|wx.ALL, 1)

        wx.EVT_CLOSE(self, self.onClose)
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

            use    = use.IsChecked()
            name   = name.GetValue().strip()
            pvname = pvname.GetValue().strip()

            if len(name) < 1 or len(pvname) < 1:
                continue
            # print wtype, obj, name, pvname, use

            if kind is not None:
                kind = kind.GetStringSelection()
            if erase and obj is not None:
                delete = self.scandb.del_detector
                if 'counter' in wtype:
                    delete = self.scan.del_counter
                delete(obj.name)
            elif obj is not None:
                # print ' -> use ', use, int(use), obj, obj.use
                obj.use    = int(use)
                obj.name   = name
                obj.pvname = pvname
                if kind is not None:
                    obj.kind   = kind
            elif 'det' in wtype:
                opts = json.dumps(DET_DEFAULT_OPTS.get(kind, {}))
                self.scandb.add_detector(name, pvname, kind,
                                         options=opts, use=int(use))
            elif 'counter' in wtype:
                self.scandb.add_counter(name, pvname, use=int(use))

        self.Destroy()

    def onClose(self, event=None):
        self.Destroy()

