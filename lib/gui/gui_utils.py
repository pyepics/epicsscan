#!/usr/bin/env python
# epics/wx/utils.py
"""
This is a collection of general purpose utility functions and classes,
especially useful for wx functionality
"""
import wx
import os
import array

import numpy
HAS_NUMPY = True

from wxutils import (fix_filename, FileOpen, FileSave, SelectWorkdir, TextCtrl,
                     SimpleText, HyperText, YesNo, FloatCtrl, hms, Font, HLine,
                     LEFT, RIGHT, CEN, FRAMESTYLE, LTEXT, GUIColors)

import wx.dataview as dv
import wx.lib.agw.flatnotebook as flat_nb

LEFT |= wx.ALL
RIGHT |= wx.ALL
CEN |= wx.ALL
LTEXT = wx.ST_NO_AUTORESIZE|wx.ALIGN_CENTER

FNB_STYLE = flat_nb.FNB_NO_X_BUTTON|flat_nb.FNB_SMART_TABS|flat_nb.FNB_NO_NAV_BUTTONS|flat_nb.FNB_NODRAG
DVSTYLE = dv.DV_VERT_RULES|dv.DV_ROW_LINES|dv.DV_MULTIPLE

class GUIColors(object):
    """a container for colour attributes
         bg
         nb_active
         nb_area
         nb_text
         nb_activetext
         title
         pvname
    """
    bg        = wx.Colour(240,240,230)
    nb_active = wx.Colour(254,254,195)
    nb_bg     = wx.Colour(252,252,250)
    nb_area   = wx.Colour(250,250,245)
    nb_text   = wx.Colour(10,10,180)
    nb_activetext = wx.Colour(80,10,10)
    title     = wx.Colour(80,10,10)
    pvname    = wx.Colour(10,10,80)

def cmp(a, b):
    return (a>b)-(b<a)

def set_font_with_children(widget, font, dsize=None):
    cfont = widget.GetFont()
    font.SetWeight(cfont.GetWeight())
    if dsize == None:
        dsize = font.PointSize - cfont.PointSize
    else:
        font.PointSize = cfont.PointSize + dsize
    widget.SetFont(font)
    for child in widget.GetChildren():
        set_font_with_children(child, font, dsize=dsize)


def add_subtitle(panel, text, colour='#222288'):
    p = wx.Panel(panel)
    s = wx.BoxSizer(wx.HORIZONTAL)
    s.Add(wx.StaticLine(p, size=(50, 5), style=wx.LI_HORIZONTAL), 0, LEFT, 5)
    s.Add(SimpleText(p, text,  colour=colour),  0, LEFT, 5)
    pack(p, s)
    return p

def okcancel(panel, onOK=None, onCancel=None):
    btnsizer = wx.StdDialogButtonSizer()
    _ok = wx.Button(panel, wx.ID_OK)
    _no = wx.Button(panel, wx.ID_CANCEL)
    panel.Bind(wx.EVT_BUTTON, onOK,     _ok)
    panel.Bind(wx.EVT_BUTTON, onCancel, _no)
    _ok.SetDefault()
    btnsizer.AddButton(_ok)
    btnsizer.AddButton(_no)
    btnsizer.Realize()
    return btnsizer


class HideShow(wx.Choice):
    def __init__(self, parent, default=True, size=(100, -1)):
        wx.Choice.__init__(self, parent, -1, size=size)
        self.choices = ('Hide', 'Show')
        self.Clear()
        self.SetItems(self.choices)
        try:
            default = int(default)
        except:
            default = 0
        self.SetSelection(default)

class check(wx.CheckBox):
    def __init__(self, parent, default=True, label=None, action=None, **kws):
        if label is None:
            label = ''
        wx.CheckBox.__init__(self, parent, -1, label=label, **kws)
        self.SetValue({True: 1, False:0}[default])
        if action is not None:
            self.Bind(wx.EVT_CHECKBOX, action)


def make_steps(prec=3, tmin=0, tmax=10, base=10, steps=(1, 2, 5)):
    """make a list of 'steps' to use for a numeric ComboBox
    returns a list of floats, such as
        [0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.00, 2.00...]
    """
    steplist = []
    power = -prec
    step = tmin
    while True:
        decade = base**power
        for step in (j*decade for j in steps):
            if step > 0.99*tmin and step <= tmax and step not in steplist:
                steplist.append(step)
        if step >= tmax:
            break
        power += 1
    return steplist

def set_sizer(panel, sizer=None, style=wx.VERTICAL, fit=False):
    """ utility for setting wx Sizer  """
    if sizer is None:
        sizer = wx.BoxSizer(style)
    panel.SetAutoLayout()
    panel.SetSizer(sizer)
    if fit:
        sizer.Fit(panel)

def set_float(val, default=0):
    """ utility to set a floating value,
    useful for converting from strings """
    out = None
    if not val in (None, ''):
        try:
            out = float(val)
        except ValueError:
            return None
        if HAS_NUMPY:
            if numpy.isnan(out):
                out = default
        else:
            if not(out > 0) and not(out<0) and not(out==0):
                out = default
    return out

def pack(window, sizer, expand=1.1):
    "simple wxPython pack function"
    tsize =  window.GetSize()
    msize =  window.GetMinSize()
    window.SetSizer(sizer)
    sizer.Fit(window)
    nsize = (10*int(expand*(max(msize[0], tsize[0])/10)),
             10*int(expand*(max(msize[1], tsize[1])/10.)))
    window.SetSize(nsize)


def add_button(parent, label, size=(-1, -1), action=None):
    "add simple button with bound action"
    thisb = wx.Button(parent, label=label, size=size)
    if hasattr(action, '__call__'):
        parent.Bind(wx.EVT_BUTTON, action, thisb)
    return thisb

def add_menu(parent, menu, label='', text='', action=None):
    "add submenu"
    wid = wx.NewId()
    menuitem = menu.Append(wid, label, text)
    if hasattr(action, '__call__'):
        parent.Bind(wx.EVT_MENU, action, menuitem)

def add_choice(panel, choices, default=0, action=None, **kws):
    "add simple button with bound action"
    c = wx.Choice(panel, -1,  choices=choices, **kws)
    c.Select(default)
    c.Bind(wx.EVT_CHOICE, action)
    return c

def popup(parent, message, title, style=None):
    """
    generic popup message dialog, returns
    output of MessageDialog.ShowModal()
    """
    if style is None:
        style = wx.OK|wx.ICON_INFORMATION
    dlg = wx.MessageDialog(parent, message, title, style)
    ret = dlg.ShowModal()
    dlg.Destroy()
    return ret

def hline(parent, size=(700, 3)):
    return wx.StaticLine(parent, size=size, style=wx.LI_HORIZONTAL|wx.GROW)

def empty_bitmap(width, height, value=255):
    """return empty wx.BitMap"""
    data = array.array('B', [value]*3*width*height)
    return wx.BitmapFromBuffer(width, height, data)


class Closure:
    """A very simple callback class to emulate a closure (reference to
    a function with arguments) in python.

    This class holds a user-defined function to be executed when the
    class is invoked as a function.  This is useful in many situations,
    especially for 'callbacks' where lambda's are quite enough.
    Many Tkinter 'actions' can use such callbacks.

    >>>def my_action(x=None):
    ...    print('my action: x = ', x)
    >>>c = Closure(my_action,x=1)
    ..... sometime later ...
    >>>c()
     my action: x = 1
    >>>c(x=2)
     my action: x = 2

    based on Command class from J. Grayson's Tkinter book.
    """
    def __init__(self, func=None, *args, **kws):
        self.func  = func
        self.kws   = kws
        self.args  = args

    def __call__(self,  *args, **kws):
        self.kws.update(kws)
        if hasattr(self.func, '__call__'):
            self.args = args
            return self.func(*self.args, **self.kws)


class TextInput(wx.TextCtrl):
    "simple text control"
    def __init__(self, parent, value, action=None,
                 font=None, colour=None, bgcolour=None,
                 style=CEN,  **kws):

        wx.TextCtrl.__init__(self, parent, -1,
                               label=label, style=style, **kws)
