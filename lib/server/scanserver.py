#!/usr/bin/env python

from __future__ import print_function

import time, sys, os
import json
import numpy as np
import glob
import epics

from ..scandb import ScanDB, make_datetime
from ..file_utils import fix_varname, nativepath
from ..utils import (strip_quotes, plain_ascii, tstamp,
                     ScanDBException, ScanDBAbort)

from ..larch_interface import LarchScanDBServer, HAS_LARCH

def command_complete(s, *args, **kws):
    return True

if HAS_LARCH:
    from larch.inputText import is_complete as command_complete

from .epics_scandb import EpicsScanDB
from .abort_slewscan import abort_slewscan

DEBUG_TIMER = False

class ScanServer():
    def __init__(self, dbname=None, _larch=None,  **kws):
        self.epicsdb = None
        self.scandb = None
        self.abort = False
        self.larch = None
        self.larch_modules = {}
        self.command_in_progress = False
        self.req_shutdown = False
        self.connect(dbname, **kws)

    def connect(self, dbname, **kws):
        """connect to Scan Database"""
        self.scandb = ScanDB(dbname=dbname, **kws)

        self.set_scan_message('Server Initializing')
        self.scandb.set_hostpid()
        self.scandb.set_info('request_abort',    0)
        self.scandb.set_info('request_pause',    0)
        self.scandb.set_info('request_shutdown', 0)
        self.set_path()

        if HAS_LARCH:
            self.larch = LarchScanDBServer(self.scandb)
            self.set_scan_message('Server Loading Larch Macros')
            time.sleep(0.05)
            current_macros = self.larch.load_macros()
            self.set_scan_message('Server Connected.')
            if 'startup' in current_macros:
                self.scandb.add_command("startup()")

        eprefix = self.scandb.get_info('epics_status_prefix')
        basedir = self.scandb.get_info('server_fileroot')
        workdir = self.scandb.get_info('user_folder')

        if eprefix is not None:
            self.epicsdb = EpicsScanDB(prefix=eprefix)
            time.sleep(0.1)
            self.epicsdb.Shutdown = 0
            self.epicsdb.Abort = 0
            self.epicsdb.basedir = plain_ascii(basedir)
            self.epicsdb.workdir = plain_ascii(workdir)

    def set_scan_message(self, msg, verbose=True):
        self.scandb.set_info('scan_message', msg)
        if self.epicsdb is not None:
            self.epicsdb.message = msg
        print(msg)

    def sleep(self, t=0.05):
        try:
            time.sleep(t)
        except KeyboardInterrupt:
            self.abort = True

    def finish(self):
        self.set_scan_message('Server Shutting Down')
        self.scandb.set_info('request_pause',    0)
        self.scandb.set_info('request_abort',    1)
        self.scandb.set_info('request_abort',    0)
        self.scandb.set_info('request_shutdown', 0)
        time.sleep(0.025)

    def set_status(self, status):
        self.scandb.set_info('scan_status', status)
        if self.epicsdb is not None:
            self.epicsdb.status = status.title()

    def set_path(self):
        self.scandb.set_path()
        self.fileroot = self.scandb.get_info('server_fileroot')

    def do_command(self, req):
        self.set_path()
        cmd_stat = self.scandb.get_command_status(req.id).lower()
        if str(cmd_stat) not in ('requested', 'starting', 'running', 'aborting'):
            msg = "Warning: skipping command <%s> status=%s"
            self.set_scan_message(msg % repr(req.command), cmd_stat )
            self.scandb.set_command_status('canceled', cmdid=req.id)
            return

        if req.command in (None, 'None', ''):
            self.scandb.set_command_status('canceled', cmdid=req.id)

        workdir = self.scandb.get_info('user_folder')
        if self.epicsdb is not None:
            self.epicsdb.workdir = plain_ascii(workdir)

        command = plain_ascii(req.command)
        if len(command) < 1 or command == 'None':
            return

        if not command_complete(command):
            self.set_scan_message("Error:  command <%s> is incomplete (missing paren or quote?)." % repr(command))
            self.scandb.set_command_status('canceled', cmdid=req.id)
            return

        self.command_in_progress = True
        self.set_status('starting')
        self.scandb.set_command_status('starting', cmdid=req.id)
        self.set_scan_message("Executing:  %s" % repr(req.command))

        args    = strip_quotes(plain_ascii(req.arguments)).strip()
        notes   = strip_quotes(plain_ascii(req.notes)).strip()
        nrepeat = int(req.nrepeat)

        filename = req.output_file
        if filename is None:
            filename = ''
        filename = strip_quotes(plain_ascii(filename))

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
                self.scandb.set_filename(filename)

            self.scandb.update('scandefs', where={'name': scanname},
                               last_used_time= make_datetime())
            command = "do_%s" % command
            args = ', '.join(words)
        elif command.lower().startswith('restart_scanserver'):
            self.scandb.set_info('error_message',   '')
            self.scandb.set_info('request_shutdown', 1)
        elif command.lower().startswith('load_macro'):
            self.scandb.set_info('error_message',   '')
            self.scandb.set_command_status('running', cmdid=req.id)
            self.set_scan_message('Server reloading macros..')
            if HAS_LARCH:
                self.larch.load_macros()
            else:
                self.scandb.set_info('error_message',  'Macro system not available')
            self.scandb.set_command_status('finished', cmdid=req.id)
        else:
            if len(args) == 0:
                larch_cmd = command
            else:
                larch_cmd = "%s(%s)" % (command, args)
            self.scandb.set_info('scan_progress', 'running')
            self.scandb.set_info('error_message',   '')
            self.scandb.set_info('current_command', larch_cmd)
            self.scandb.set_info('current_command_id', req.id)
            self.set_status('running')
            self.scandb.set_command_status('running', cmdid=req.id)
            if self.epicsdb is not None:
                self.epicsdb.cmd_id = req.id
                self.epicsdb.command = larch_cmd

            msg = 'done'
            if HAS_LARCH:
                try:
                    print("<%s>%s" % (tstamp(), larch_cmd))
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
            self.scandb.set_command_status(status, cmdid=req.id)
        self.set_status('idle')
        self.command_in_progress = False

    def look_for_interrupts(self):
        """look for aborts"""
        get_info = self.scandb.get_info
        self.req_abort = get_info('request_abort', as_bool=True)
        self.req_pause = get_info('request_pause', as_bool=True)
        self.req_shutdown = get_info('request_shutdown', as_bool=True)
        return self.req_abort

    def clear_interrupts(self):
        """re-set interrupt requests:
        abort / pause / resume
        if scandb is being used, these are looked up from database.
        otherwise local larch variables are used.
        """
        self.req_abort = self.req_pause = False
        self.scandb.set_info('request_abort', 0)
        self.scandb.set_info('request_pause', 0)

    def mainloop(self):
        if self.larch is None:
            raise ValueError("Scan server not connected!")

        self.set_status('idle')
        msgtime = time.time()
        self.set_scan_message('Server Ready')
        is_paused = False

        # we're going to be doing a lot of reading of the 'commands'
        # table in scandb, so we pre-compile the query to get the
        # requested commands, in order.
        session = self.scandb.get_session()
        request_id = self.scandb.status_codes['requested']
        tab = self.scandb.tables['commands']
        cmd_query = tab.select().where(tab.c.status_id==request_id
                                       ).order_by(tab.c.run_order)

        # Note: this loop is really just looking for new commands
        # or interrupts, so does not need to go super fast.
        while True:
            epics.poll(0.025, 1.0)
            time.sleep(0.25)
            now = time.time()
            self.look_for_interrupts()

            # shutdown?
            if (self.req_shutdown or (self.epicsdb is not None
                                     and  self.epicsdb.Shutdown == 1)):
                break

            # update server heartbeat / message
            if now > msgtime + 0.75:
                msgtime = now
                self.scandb.set_info('heartbeat', tstamp())
                if self.epicsdb is not None:
                    self.epicsdb.setTime()
            # if pauses, continue loop
            if self.req_pause:
                time.sleep(1.0)
                continue

            # get ordered list of requested commands
            reqs = session.execute(cmd_query).fetchall()

            # abort command?
            if (self.req_abort or (self.epicsdb is not None
                                   and  self.epicsdb.Abort == 1)):
                if len(reqs) > 0:
                    req = reqs[0]
                    self.scandb.set_command_status('aborted', cmdid=req.id)
                    abort_slewscan()
                    reqs = []
                if self.epicsdb is not None:
                    self.epicsdb.Abort = 0
                self.clear_interrupts()
                time.sleep(0.5)

            # do next command
            if len(reqs) > 0:
                self.do_command(reqs[0])
            else:
                time.sleep(0.5)
        # mainloop end
        self.finish()
        return None
