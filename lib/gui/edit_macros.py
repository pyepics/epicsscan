import os
import sys
import time

import wx
import wx.lib.scrolledpanel as scrolled
from wx.lib.editor import Editor

from ..ordereddict import OrderedDict
from .gui_utils import (GUIColors, set_font_with_children, YesNo,
                        add_menu, add_button, pack, SimpleText,
                        FileOpen, FileSave, popup,
                        FRAMESTYLE, Font)

LEFT = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
CEN  = wx.ALIGN_CENTER|wx.ALIGN_CENTER_VERTICAL|wx.ALL

class MacroFrame(wx.Frame) :
    """Edit/Manage Macros (Larch Code)"""
    def __init__(self, parent, pos=(-1, -1)):

        self.parent = parent
        self.scandb = parent.scandb

        wx.Frame.__init__(self, None, -1,  title='Epics Scanning: Macro',
                          style=FRAMESTYLE)

        self.SetFont(Font(10))
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.createMenus()

        self.colors = GUIColors()
        self.SetBackgroundColour(self.colors.bg)

        self.editor = wx.TextCtrl(self, -1, size=(400, 400),
                                  style=wx.TE_MULTILINE|wx.TE_RICH2)
        self.editor.SetBackgroundColour('#FFFFFF')
        text = """# Edit Macro text here\n#\n \n"""

        self.editor.SetValue(text)
        self.editor.SetInsertionPoint(len(text)-2)

        sizer.Add(self.editor, 1, CEN|wx.GROW|wx.ALL, 3)


        sizer.Add(self.make_buttons(), 0, wx.ALIGN_LEFT, 3)
        self.SetMinSize((400, 400))
        pack(self, sizer)
        self.Show()
        self.Raise()

    def make_buttons(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(add_button(panel, label='Start',  action=self.onStart),
                  0, wx.ALIGN_LEFT, 2)
        sizer.Add(add_button(panel, label='Pause',  action=self.onPause),
                  0, wx.ALIGN_LEFT, 2)
        sizer.Add(add_button(panel, label='Resume',  action=self.onResume),
                  0, wx.ALIGN_LEFT, 2)
        sizer.Add(add_button(panel, label='Abort',  action=self.onAbort),
                  0, wx.ALIGN_LEFT, 2)

        sizer.Add(add_button(panel, label='Exit',   action=self.onClose),
                  0, wx.ALIGN_LEFT, 2)

        pack(panel, sizer)
        return panel

    def createMenus(self):
        self.menubar = wx.MenuBar()
        # file
        fmenu = wx.Menu()
        add_menu(self, fmenu, "Read Macro\tCtrl+R",
                 "Read Macro", self.onReadMacro)

        add_menu(self, fmenu, "Save Macro\tCtrl+S",
                 "Save Macro", self.onSaveMacro)

        fmenu.AppendSeparator()
        add_menu(self, fmenu, "Quit\tCtrl+Q",
                 "Quit Macro", self.onClose)

        # options
        pmenu = wx.Menu()
        add_menu(self, pmenu, "Insert Position Scan\tCtrl+P",
                 "Insert Position Scan", self.onInsertText)

        self.menubar.Append(fmenu, "&File")
        self.menubar.Append(pmenu, "Insert")
        self.SetMenuBar(self.menubar)

    def onInsertText(self, event=None):
        print 'Insert ', self.editor.GetInsertionPoint()
        print 'Last ',   self.editor.GetLastPosition()
        self.editor.WriteText('<Added text>')
        print 'Insert ', self.editor.GetInsertionPoint()


    def onReadMacro(self, event=None):
        wcard = 'Scan files (*.lar)|*.lar|All files (*.*)|*.*'
        fname = FileOpen(self, "Read Macro from File",
                         default_file='macro.lar',
                         wildcard=wcard)
        if fname is not None:
            try:
                text = open(fname, 'r').read()
                self.editor.SetValue(text)
            except:
                pass

    def onSaveMacro(self, event=None):
        wcard = 'Scan files (*.lar)|*.lar|All files (*.*)|*.*'
        fname = FileSave(self, 'Save Macro to File',
                         default_file='macro.lar', wildcard=wcard)
        if fname is not None:
            if os.path.exists(fname):
                ret = popup(self, "Overwrite Macro File '%s'?" % fname,
                            "Really Overwrite Macro File?",
                            style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION)
                if ret != wx.ID_YES:
                    return

                try:
                    fh = open(fname, 'w')
                    fh.write('%s\n' % self.editor.GetValue())
                    fh.close()
                except:
                    pass

    def onStart(self, event=None):
        print 'Macro Start'
        print self.editor.GetValue()
        #  self.scandb.commit()

    def onPause(self, event=None):
        print 'Macro Pause'
        print self.editor.GetValue()
        #  self.scandb.commit()

    def onResume(self, event=None):
        print 'Macro Resume'
        print self.editor.GetValue()
        #  self.scandb.commit()

    def onAbort(self, event=None):
        print 'Macro Abort'
        print self.editor.GetValue()
        #  self.scandb.commit()

    def onClose(self, event=None):
        self.Destroy()
