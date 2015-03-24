#!/usr/bin/env python

from __future__ import print_function

import time, sys, os
import threading
import json
import numpy as np
import glob
import epics

from ..scandb import ScanDB, ScanDBException, ScanDBAbort, make_datetime

from ..file_utils import fix_varname, nativepath
from ..utils import  strip_quotes

from ..site_config import get_fileroot
from ..larch_interface import LarchScanDBServer, EpicsScanDB

DEBUG_TIMER = False

class ScanServer():
    def __init__(self, dbname=None, fileroot=None, _larch=None,  **kwargs):
        self.epicsdb = EpicsScanDB(prefix='13XRM:SCANDB:')
        time.sleep(0.01)

        self.fileroot = get_fileroot(fileroot)
        self.scandb = None
        self.abort = False
        self.larch = None
        self.larch_modules = {}
        self.command_in_progress = False
        self.req_shutdown = False

        self.epicsdb.Shutdown = 0
        self.epicsdb.Abort = 0
        if dbname is not None:
            self.connect(dbname, **kwargs)


    def connect(self, dbname, **kwargs):
        """connect to Scan Database"""
        self.scandb = ScanDB(dbname=dbname, **kwargs)
        self.set_scan_message('Server initializing ', self.fileroot)
        self.larch = LarchScanDBServer(self.scandb, fileroot=self.fileroot)

        self.scandb.set_hostpid()
        self.scandb.set_info('request_abort',    0)
        self.scandb.set_info('request_pause',    0)
        self.scandb.set_info('request_shutdown', 0)

        self.set_scan_message('Server Loading Larch Plugins...')
        self.larch.load_plugins()
        self.set_scan_message('Server Loading Larch Macros...')
        self.larch.load_modules()
        self.set_scan_message('Server Connected.')

        basedir = self.scandb.get_info('server_fileroot')
        self.epicsdb.basedir = str(basedir)
        workdir = self.scandb.get_info('user_folder')
        self.epicsdb.workdir = str(workdir)


    def set_scan_message(self, msg, verbose=True):
        self.scandb.set_info('scan_message', msg)
        self.epicsdb.message = msg
        print(msg)

    def sleep(self, t=0.05):
        try:
            time.sleep(t)
        except KeyboardInterrupt:
            self.abort = True

    def finish(self):
        print( 'ScanServer: Shutting down')
        self.scandb.set_info('request_pause',    0)
        time.sleep(0.1)
        self.scandb.set_info('request_abort',    1)
        time.sleep(0.1)
        self.scandb.set_info('request_abort',    0)
        time.sleep(0.1)
        self.scandb.set_info('request_shutdown', 0)
        time.sleep(0.1)

    def set_status(self, status):
        self.scandb.set_info('scan_status', status)
        self.epicsdb.status = status.title()

    def set_path(self):
        self.scandb.set_path(fileroot=self.fileroot)

    def do_command(self, req):
        cmd_stat = self.scandb.get_command_status(req.id).lower()
        if not cmd_stat.startswith('request'):
            self.set_scan_message("Warning: skipping command '%s'" % repr(req))
            return

        command = str(req.command)
        if len(command) < 1 or command is 'None':
            return

        all_macros = self.larch.load_modules()
        self.command_in_progress = True
        self.set_status('starting')
        self.scandb.set_command_status(req.id, 'starting')

        args    = strip_quotes(str(req.arguments)).strip()
        notes   = strip_quotes(str(req.notes)).strip()
        nrepeat = int(req.nrepeat)

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
        elif command.lower().startswith('load_plugins'):
            self.set_scan_message('Server Reloading Larch Plugins...')
            self.larch.load_plugins()
            return

        if len(args) == 0:
            larch_cmd = command
        else:
            larch_cmd = "%s(%s)" % (command, args)
        self.scandb.set_info('error_message',   '')
        self.scandb.set_info('current_command', larch_cmd)
        self.scandb.set_info('current_command_id', req.id)
        self.set_status('running')
        self.scandb.set_command_status(req.id, 'running')
        self.epicsdb.cmd_id = req.id
        self.epicsdb.command = larch_cmd

        try:
            print("Larch Run " , larch_cmd)
            out = self.larch.run(larch_cmd)
        except:
            pass
        status, msg = 'finished', 'scan complete'
        err = self.larch.get_error()
        if len(err) > 0:
            err = err[0]
            exc_type, exc_val, exc_tb = err.exc_info
            if 'ScanDBAbort' in repr( exc_type):
                status = 'aborted'
                msg = 'scan aborted'
            else:
                emsg = '\n'.join(err.get_error())
                self.scandb.set_info('error_message', emsg)
                msg = 'scan completed with error'

        time.sleep(0.1)
        self.scandb.set_info('scan_progress', msg)
        self.scandb.set_command_status(req.id, status)
        self.set_status('idle')
        self.command_in_progress = False
        
    def look_for_interrupts(self):
        """set interrupt requests:
        abort / pause / resume
        it is expected that long-running commands
        should do something like this....
        """
        def isset(infostr):
            return self.scandb.get_info(infostr, as_bool=True)
        self.req_shutdown = isset('request_shutdown')
        self.req_pause = isset('request_pause')
        self.req_abort = isset('request_abort')
        return self.req_abort

    def mainloop(self):
        if self.larch is None:
            raise ValueError("Scan server not connected!")

        self.set_status('idle')
        msgtime = time.time()
        self.set_scan_message('Server Ready')
        is_paused = False
        while True:
            epics.poll(0.001, 1.0)
            self.look_for_interrupts()
            if self.epicsdb.Shutdown == 1 or self.req_shutdown:
                break
            if time.time() > msgtime + 1:
                msgtime = time.time()
                self.scandb.set_info('heartbeat', time.ctime())
                self.epicsdb.setTime()
            if self.req_pause:
                continue
            reqs = self.scandb.get_commands(status='requested',
                                            reverse=False)
            if self.epicsdb.Abort == 1 or self.req_abort:
                for req in reqs:
                    self.scandb.set_command_status(req.id, 'aborted')
                    time.sleep(0.1)
                time.sleep(1.0)
            elif len(reqs) > 0:
                self.do_command(reqs[0])
        # mainloop end
        self.finish()
        return None
