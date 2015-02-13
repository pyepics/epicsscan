import os
import sys
import time
import logging

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

AUTOSAVE_FILE = 'macros_autosave.lar'

class MacroFrame(wx.Frame) :
    """Edit/Manage Macros (Larch Code)"""
    def __init__(self, parent, pos=(-1, -1), _larch=None):

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
        self.ReadMacroFile(AUTOSAVE_FILE)

        
        sizer.Add(self.editor, 1, CEN|wx.GROW|wx.ALL, 3)


        sizer.Add(self.make_buttons(), 0, wx.ALIGN_LEFT, 3)
        wx.EVT_CLOSE(self, self.onClose)
        self.SetMinSize((460, 480))
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
        self.editor.WriteText('<Added text>')

    def onReadMacro(self, event=None):
        wcard = 'Scan files (*.lar)|*.lar|All files (*.*)|*.*'
        fname = FileOpen(self, "Read Macro from File",
                         default_file='macro.lar',
                         wildcard=wcard)
        if fname is not None:
            self.ReadMacroFile(fname)

    def ReadMacroFile(self, fname):
        if os.path.exists(fname):
            try:
                text = open(fname, 'r').read()
            except:
                logging.exception('could not read MacroFile %s' % fname)
            finally:
                self.editor.SetValue(text)
                self.editor.SetInsertionPoint(len(text)-2)
            
    def onSaveMacro(self, event=None):
        wcard = 'Scan files (*.lar)|*.lar|All files (*.*)|*.*'
        fname = FileSave(self, 'Save Macro to File',
                         default_file='macro.lar', wildcard=wcard)
        fname = os.path.join(os.getcwd(), fname)
        if fname is not None:
            if os.path.exists(fname):
                ret = popup(self, "Overwrite Macro File '%s'?" % fname,
                            "Really Overwrite Macro File?",
                            style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION)
                if ret != wx.ID_YES:
                    return
            self.SaveMacroFile(fname)
                
    def SaveMacroFile(self, fname):
        try:
            fh = open(fname, 'w')
            fh.write('%s\n' % self.editor.GetValue())
            fh.close()
        except:
            logging.exception('could not save MacroFile %s' % fname)            

    def onStart(self, event=None):
        print 'Macro Start'
        lines = self.editor.GetValue().split('\n')
        self.scandb.set_info('request_pause',  1)

        for lin in lines:
            lin = lin.strip()
            if lin.startswith('#'): continue
            if '#' in lin:
                lin = lin[:index('#')]
            lin = lin.strip()
            if len(lin) > 0:
                print 'Add Macro line ', lin
                self.scandb.add_command(lin)
        self.scandb.commit()
        self.scandb.set_info('request_abort',  0)
        self.scandb.set_info('request_pause',  0)

    def onPause(self, event=None):
        self.scandb.set_info('request_pause', 1)
        self.scandb.commit()

    def onResume(self, event=None):
        self.scandb.set_info('request_pause', 0)
        self.scandb.commit()

    def onAbort(self, event=None):
        self.scandb.set_info('request_abort', 1)
        self.scandb.commit()

    def onClose(self, event=None):
        self.SaveMacroFile(AUTOSAVE_FILE)
        self.Destroy()
