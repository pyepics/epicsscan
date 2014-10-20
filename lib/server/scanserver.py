#!/usr/bin/env python

import time, sys, os
import threading
import json
import numpy as np
import glob
import epics

from ..scandb import ScanDB, ScanDBException, make_datetime

from ..file_utils import fix_varname, nativepath
from ..utils import  strip_quotes


import larch
from larch.larchlib import Procedure
DARWIN_ROOT  = '/Volumes/Data/xas_user'
WINDOWS_ROOT = 'T:/xas_user'
LINUX_ROOT   = '/cars5/Data/user'
MACRO_FOLDER  = 'scan_config/13ide'

class ScanServer():
    LARCH_SCANDB = '_scan._scandb'
    def __init__(self, dbname=None, fileroot=None, _larch=None,  **kwargs):
        self.scandb = None
        self.fileroot = fileroot
        self.abort = False
        self.set_basepath(fileroot)
        self.larch = None
        self.larch_modules_dir = '.'
        self.larch_modules = {}
        self.command_in_progress = False
        self.req_shutdown = False
        if dbname is not None:
            self.connect(dbname, **kwargs)

    def set_basepath(self, fileroot):
        if fileroot is None:
            if sys.platform == 'darwin':
                fileroot = DARWIN_ROOT
            elif os.name == 'nt':
                fileroot = WINDOWS_ROOT
            else:
                fileroot = LINUX_ROOT
        self.fileroot = fileroot

    def connect(self, dbname, **kwargs):
        """connect to Scan Database"""
        self.scandb = ScanDB(dbname=dbname, **kwargs)
        self.set_scan_message('Server initializing')
        self.larch = larch.Interpreter()
        self.scandb.set_info('request_abort',    0)
        self.scandb.set_info('request_pause',    0)
        self.scandb.set_info('request_shutdown', 0)


        symtab = self.larch.symtable
        symtab.set_symbol(self.LARCH_SCANDB, self.scandb)
        macro_folder = self.scandb.get_info('macro_folder')
        if macro_folder is None:
            macro_folder = 'scan_config/13ide'
        self.set_scan_message('Server Loading Plugins...')
        plugindir = os.path.join(self.fileroot, macro_folder, 'plugins')
        symtab._sys.config.plugin_paths.insert(0, plugindir)
        self.larch.run("add_plugin('basic_macros')")

        moddir = os.path.join(self.fileroot, macro_folder, 'macros')
        symtab._sys.path.insert(0, moddir)
        self.larch_modules_dir = moddir
        self.load_larch_modules()
        self.set_scan_message('Server Connected.')

    def load_larch_modules(self, verbose=False):
        """read latest larch modules"""
        os.chdir(self.larch_modules_dir)
        for name in glob.glob('*.lar'):
            modname = name[:-4]
            this_mtime = os.stat(name).st_mtime
            if modname in self.larch_modules:
                last_mtime = self.larch_modules[modname]
                if this_mtime <= last_mtime:
                    if verbose: print 'Not rereading ', modname
                    continue

            self.larch.error = []
            if verbose: print 'importing ', modname
            if modname in  self.larch_modules:
                self.larch.run('reload(%s)' % modname)
            else:
                self.larch.run('import %s' % modname)
            if len( self.larch.error) > 0:
                for err in self.larch.error:
                    print 'Error import %s' % modname
                    print err.msg
            else:
                self.larch_modules[modname] = this_mtime
                omod = getattr(self.larch.symtable, modname)
                for s in dir(omod):
                    thing = getattr(omod, s)
                    if isinstance(thing, Procedure):
                        setattr(self.larch.symtable, s, thing)

        self.set_path()

    def set_scan_message(self, msg, verbose=True):
        self.scandb.set_info('scan_message', msg)
        if verbose:
            print 'ScanServer: ', msg

    def sleep(self, t=0.05):
        try:
            time.sleep(t)
        except KeyboardInterrupt:
            self.abort = True

    def finish(self):
        print 'ScanServer: Shutting down'
        self.scandb.set_info('request_pause',    0)
        time.sleep(0.25)
        self.scandb.set_info('request_abort',    1)
        time.sleep(0.25)
        self.scandb.set_info('request_abort',    0)
        time.sleep(0.25)
        self.scandb.set_info('request_shutdown', 0)
        time.sleep(0.25)

    def set_path(self):
        workdir = nativepath(self.scandb.get_info('user_folder'))
        for root in (WINDOWS_ROOT, LINUX_ROOT, DARWIN_ROOT):
            proot = nativepath(root)
            if workdir.startswith(proot):
                workdir = workdir[len(proot):]
        try:
            os.chdir(os.path.join(self.fileroot, workdir))
        except:
            pass

    def do_command(self, req):
        print 'Do Command: ', req.id, req.command, req.arguments
        self.load_larch_modules()

        self.command_in_progress = True
        self.scandb.set_info('scan_status', 'starting')
        self.scandb.set_command_status(req.id, 'starting')

        args    = strip_quotes(str(req.arguments)).strip()
        notes   = strip_quotes(str(req.notes)).strip()
        nrepeat = int(req.nrepeat)
        command = str(req.command)

        filename = req.output_file
        if filename is None:
            filename = ''
        filename = strip_quotes(str(filename))

        if command.lower() in ('scan', 'slewscan'):
            scanname = args
            words = ["'%s'" % scanname]
            if nrepeat > 1 and command != 'slewscan':
                words.append("nscans=%i" % nrepeat)
                self.scandb.set_info('nscans', nrepeat)
            if len(notes) > 0:
                words.append("comments='%s'" % notes)
            if len(filename) > 0:
                words.append("filename='%s'" % filename)
                self.scandb.set_info('filename', filename)

            self.scandb.update_where('scandefs', {'name': scanname},
                                     {'last_used_time': make_datetime()})
            command = "do_%s" % command
            args = ', '.join(words)

        if len(args) == 0:
            larch_cmd = command
        else:
            larch_cmd = "%s(%s)" % (command, args)

        self.scandb.set_info('current_command', larch_cmd)
        self.larch.error = []

        self.scandb.set_info('scan_status', 'running')
        self.scandb.set_command_status(req.id, 'running')

        print 'RUN LARCH COMMAND ', larch_cmd
        out = self.larch.run(larch_cmd)
        time.sleep(0.1)
        if len(self.larch.error) > 0:
            self.scandb.set_info('command_error', repr(self.larch.error[0].msg))


        print "Larch OUT ", out, out.dtimer
        try:
            out.dtimer.save("scan_debugtimer.dat")
        except:
            pass

        self.scandb.set_command_status(req.id, 'finished')
        self.scandb.set_info('scan_status', 'idle')
        self.scandb.commit()
        self.command_in_progress = False

    def look_for_interrupt_requests(self):
        """set interrupt requests:
        abort / pause / resume
        it is expected that long-running commands
        should do something like this....
        """
        def isset(infostr):
            return self.scandb.get_info(infostr, as_bool=True)
        self.req_abort = isset('request_abort')
        self.req_pause = isset('request_pause')
        self.req_shutdown = isset('request_shutdown')

        return self.req_abort

    def mainloop(self):
        if self.larch is None:
            raise ValueError("Scan server not connected!")

        self.scandb.set_info('scan_status', 'idle')
        msgtime = time.time()
        self.set_scan_message('Server Ready')
        is_paused = False
        while True:
            try:
                self.sleep(0.25)
                self.look_for_interrupt_requests()
                if self.req_shutdown:
                    break
                if time.time() > (msgtime + 30):
                    print '#Server Alive, paused=%s' % (repr(self.req_pause))
                    msgtime = time.time()

                if self.req_pause:
                    continue
                reqs = self.scandb.get_commands('requested')
                if self.req_abort:
                    for req in reqs:
                        self.scandb.set_command_status(req.id, 'aborted')
                elif len(reqs) > 0:
                    self.do_command(reqs[0])

            except KeyboardInterrupt:
                print 'KB Interrupt!'
                self.scandb.set_info('request_shutdown', 1)


        # mainloop end
        self.finish()
        sys.exit()
