import os
import sys
import time
import logging
from datetime import datetime, timedelta
import wx
import wx.lib.scrolledpanel as scrolled
from wx.lib.editor import Editor

from ..ordereddict import OrderedDict
from .gui_utils import (GUIColors, set_font_with_children, YesNo,
                        add_menu, add_button, pack, SimpleText,
                        FileOpen, FileSave, popup,
                        FRAMESTYLE, Font)

import larch
from larch.wxlib.readlinetextctrl import ReadlineTextCtrl
LEFT = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL|wx.ALL
CEN  = wx.ALIGN_CENTER|wx.ALIGN_CENTER_VERTICAL|wx.ALL

AUTOSAVE_FILE = 'macros_autosave.lar'
MACRO_HISTORY = 'scan_macro_history.lar'
LONG_AGO = datetime.now()-timedelta(2000)

class MacroFrame(wx.Frame) :
    """Edit/Manage Macros (Larch Code)"""
    output_colors = {'error_message':'#BB0000',
                     'scan_message':'#0000BB'}
    output_fields = ('error_message', 'scan_message')

    info_mapping = {'File Name': 'filename',
                    'Current Command': 'current_command',
                    'Status': 'scan_status',
                    'Timestamp': 'heartbeat'}

    def __init__(self, parent, pos=(-1, -1), _larch=None):

        self.parent = parent
        self.scandb = parent.scandb
        self.winfo = OrderedDict()
        self.output_stats = {}
        for key in self.output_fields:
            self.output_stats[key] = LONG_AGO

        wx.Frame.__init__(self, None, -1,  title='Epics Scanning: Macro',
                          style=FRAMESTYLE)

        self.SetFont(Font(10))
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.createMenus()

        self.colors = GUIColors()
        self.SetBackgroundColour(self.colors.bg)

        self.editor = wx.TextCtrl(self, -1, size=(550, 250),
                                  style=wx.TE_MULTILINE|wx.TE_RICH2)
        self.editor.SetBackgroundColour('#FFFFFF')

        text = """## Edit Macro text here\n#\n"""
        self.editor.SetValue(text)
        self.editor.SetInsertionPoint(len(text)-2)
        self.ReadMacroFile(AUTOSAVE_FILE)

        sfont = wx.Font(11,  wx.SWISS, wx.NORMAL, wx.BOLD, False)
        self.output = wx.TextCtrl(self, -1,  '## Output Buffer\n', size=(550, 250),
                                  style=wx.TE_MULTILINE|wx.TE_RICH|wx.TE_READONLY)
        self.output.CanCopy()
        self.output.SetInsertionPointEnd()
        self.output.SetDefaultStyle(wx.TextAttr('black', 'white', sfont))

        sizer.Add(self.make_info(),    0, wx.ALIGN_LEFT, 3)
        sizer.Add(self.make_buttons(), 0, wx.ALIGN_LEFT, 3)
        sizer.Add(self.editor, 1, CEN|wx.GROW|wx.ALL, 3)

        sizer.Add(self.output, 1, CEN|wx.GROW|wx.ALL, 3)
        sizer.Add(self.InputPanel(),  0, border=2,
                  flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL|wx.EXPAND)

        self._stimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_info, self._stimer)
        self._stimer.Start(500)

        wx.EVT_CLOSE(self, self.onClose)
        self.SetMinSize((600, 450))
        pack(self, sizer)
        self.Show()
        self.Raise()

    def update_info(self, evt=None):
        for key, attr in self.info_mapping.items():
            val = str(self.scandb.get_info(attr, '--'))
            if key in self.winfo:
                self.winfo[key].SetLabel(val)
            if key == 'Status':
                if val.lower().startswith('idle'):
                    self.start_btn.Enable()
                else:
                    self.start_btn.Disable()


        for key in self.output_fields:
            row = self.scandb.get_info(key, full_row=True)
            mtime = self.output_stats.get(key, LONG_AGO)
            if row.modify_time > mtime:
                self.output_stats[key] = row.modify_time
                if len(row.value) > 0:
                    self.writeOutput(row.value,
                                     color=self.output_colors.get(key, None))

    def make_info(self):
        panel = wx.Panel(self)
        sizer = wx.GridBagSizer(8, 4)

        self.winfo = OrderedDict()
        opts1 = {'label':' '*99, 'colour': '#000088', 'size': (425, -1),
                 'minsize': (375, -1), 'style': wx.ALIGN_LEFT}
        opts2 = {'label':' '*50, 'colour': '#000088', 'size': (275, -1),
                 'minsize': (200, -1), 'style': wx.ALIGN_LEFT}
        self.winfo['File Name']       = SimpleText(panel, **opts1)
        self.winfo['Current Command'] = SimpleText(panel, **opts1)
        self.winfo['Status']     = SimpleText(panel, **opts2)
        self.winfo['Timestamp']  = SimpleText(panel, **opts2)

        irow = 0
        for attr in ('Current Command', 'File Name'):
            lab  = SimpleText(panel, "%s:" % attr, size=(120, -1))
            sizer.Add(lab,               (irow, 0), (1, 1), LEFT, 1)
            sizer.Add(self.winfo[attr],  (irow, 1), (1, 3), LEFT, 1)
            irow += 1

        icol = 0
        for attr in ('Status', 'Timestamp'):
            lab  = SimpleText(panel, "%s:" % attr, size=(120, -1))
            sizer.Add(lab,               (irow, icol),   (1, 1), LEFT, 1)
            sizer.Add(self.winfo[attr],  (irow, icol+1), (1, 1), LEFT, 1)
            icol +=2

        pack(panel, sizer)
        return panel

    def make_buttons(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.start_btn = add_button(panel, label='Start',  action=self.onStart)
        sizer.Add(self.start_btn, 0, wx.ALIGN_LEFT, 2)
        sizer.Add(add_button(panel, label='Pause',  action=self.onPause),
                  0, wx.ALIGN_LEFT, 2)
        sizer.Add(add_button(panel, label='Resume',  action=self.onResume),
                  0, wx.ALIGN_LEFT, 2)
        sizer.Add(add_button(panel, label='Abort',  action=self.onAbort),
                  0, wx.ALIGN_LEFT, 2)
        sizer.Add(add_button(panel, label='Cancel All', action=self.onCancelAll),
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

    def InputPanel(self):
        panel = wx.Panel(self, -1)
        self.prompt = wx.StaticText(panel, -1, ' >>>', size = (30,-1),
                                    style=wx.ALIGN_CENTER|wx.ALIGN_RIGHT)
        self.histfile = os.path.join(larch.site_config.usr_larchdir, MACRO_HISTORY)
        self.input = ReadlineTextCtrl(panel, -1,  '', size=(525,-1),
                                      historyfile=self.histfile, mode='emacs',
                                      style=wx.ALIGN_LEFT|wx.TE_PROCESS_ENTER)

        self.input.Bind(wx.EVT_TEXT_ENTER, self.onText)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        sizer.Add(self.prompt,  0, wx.BOTTOM|wx.CENTER)
        sizer.Add(self.input,   1, wx.ALIGN_LEFT|wx.ALIGN_CENTER|wx.EXPAND)
        panel.SetSizer(sizer)
        sizer.Fit(panel)
        return panel

    def onText(self, event=None):
        text = event.GetString().strip()
        if len(text) < 1:
            return
        self.input.Clear()
        self.input.AddToHistory(text)
        out = self.scandb.add_command(text)
        self.scandb.commit()
        time.sleep(0.01)
        self.writeOutput(text)

    def writeOutput(self, text, color=None):
        pos0 = self.output.GetLastPosition()
        if not text.endswith('\n'):
            text = '%s\n' % text
        self.output.WriteText(text)
        if color is not None:
            style = self.output.GetDefaultStyle()
            bgcol = style.GetBackgroundColour()
            sfont = style.GetFont()
            pos1  = self.output.GetLastPosition()
            self.output.SetStyle(pos0, pos1, wx.TextAttr(color, bgcol, sfont))
        self.output.SetInsertionPoint(self.output.GetLastPosition())
        self.output.Refresh()


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
        time.sleep(1.0)
        self.scandb.set_info('request_abort', 0)
        self.scandb.commit()

    def onCancelAll(self, event=None):
        self.scandb.cancel_remaining_commands()
        self.onAbort()

    def onClose(self, event=None):
        self.SaveMacroFile(AUTOSAVE_FILE)
        print self.histfile
        self.input.SaveHistory(self.histfile)
        self.Destroy()
