#!/usr/bin/env python

from __future__ import print_function

import time, sys, os
import json
import numpy as np
import glob
import epics

from .scandb import ScanDB, make_datetime
from .file_utils import fix_varname, nativepath
from .utils import (strip_quotes, plain_ascii, tstamp,
                    is_complete, ScanDBException, ScanDBAbort)

from .macro_kernel import MacroKernel

from .epics_scandb import EpicsScanDB
# from .abort_slewscan import abort_slewscan

DEBUG_TIMER = False

class ScanServer():
    def __init__(self, dbname=None,  **kws):
        self.epicsdb = None
        self.scandb = None
        self.abort = False
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
        self.set_workdir()

        self.mkernel = MacroKernel(self.scandb, load_macros=True)
        time.sleep(0.05)
        self.set_scan_message('Server Connected.')
        if 'startup' in self.mkernel.get_macros():
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

    def set_workdir(self):
        self.scandb.set_workdir()
        self.fileroot = self.scandb.get_info('server_fileroot')

    def do_command(self, cmd_row):
        """execute a single command: a row from the commands table"""
        self.set_workdir()
        cmdid = cmd_row.id
        command = plain_ascii(cmd_row.command)

        cmd_stat = self.scandb.get_command_status(cmdid).lower()
        if str(cmd_stat) not in ('requested', 'starting', 'running', 'aborting'):
            msg = f"Warning: skipping command <{command}s> status={cmd_stat}"
            self.set_scan_message(msg)
            self.scandb.set_command_status('canceled', cmdid=cmdid)
            return

        if len(command) < 1 or command in (None, 'None', ''):
            self.scandb.set_command_status('canceled', cmdid=cmdid)
            return

        workdir = plain_ascii(self.scandb.get_info('user_folder'))
        if self.epicsdb is not None:
            self.epicsdb.workdir = workdir

        if not is_complete(command):
            self.set_scan_message(f"Error: command <command> is incomplete")
            self.scandb.set_command_status('canceled', cmdid=cmdid)
            return

        self.command_in_progress = True
        self.set_status('starting')
        self.scandb.set_command_status('starting', cmdid=cmdid)
        self.set_scan_message(f"Executing: <{command}>")

        args    = strip_quotes(plain_ascii(cmd_row.arguments)).strip()
        notes   = strip_quotes(plain_ascii(cmd_row.notes)).strip()
        nrepeat = int(cmd_row.nrepeat)

        filename = cmd_row.output_file
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
            self.scandb.set_command_status('running', cmdid=cmdid)
            self.set_scan_message('Server reloading macros..')
            self.mkernel.load_macros()
            self.scandb.set_command_status('finished', cmdid=cmdid)
        else:
            if len(args) == 0:
                cmd = command
            else:
                cmd = "%s(%s)" % (command, args)
            self.scandb.set_info('scan_progress', 'running')
            self.scandb.set_info('error_message',   '')
            self.scandb.set_info('current_command', cmd)
            self.scandb.set_info('current_command_id', cmdid)
            self.set_status('running')
            self.scandb.set_command_status('running', cmdid=cmdid)
            if self.epicsdb is not None:
                self.epicsdb.cmd_id = cmdid
                self.epicsdb.command = cmd

            msg = 'done'
            try:
                # print(f"[{tstamp()}] <{cmd}>")
                out = self.mkernel.run(cmd)
            except:
                pass
            status, msg = 'finished', 'scan complete'
            err = self.mkernel.get_error()
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
            self.scandb.set_command_status(status, cmdid=cmdid)
        self.set_status('idle')
        self.command_in_progress = False

    def look_for_interrupts(self):
        """look for aborts"""
        get_info = self.scandb.get_info
        self.req_abort = get_info('request_abort', as_bool=True)
        self.req_pause = get_info('request_pause', as_bool=True)
        self.req_shutdown = get_info('request_shutdown', as_bool=True)
        if self.epicsdb is not None:
            if self.epicsdb.Abort == 1:
                self.req_abort = 1
            if self.epicsdb.Shutdown == 1:
                self.req_shutdown = 1
        return self.req_abort

    def clear_interrupts(self):
        """re-set interrupt requests:
        abort / pause / resume
        if scandb is being used, these are looked up from database.
        otherwise local Macro variables are used.
        """
        self.req_abort = self.req_pause = False
        self.scandb.set_info('request_abort', 0)
        self.scandb.set_info('request_pause', 0)
        if self.epicsdb is not None:
            self.epicsdb.Abort = 0
            self.epicsdb.Shutdown = 0

    def set_heartbeat(self):
        tmsg = tstamp()
        self.scandb.set_info('heartbeat', tmsg)
        if self.epicsdb is not None:
            self.epicsdb.TSTAMP = tmsg

    def mainloop(self):
        self.set_status('idle')
        msgtime = t0 = time.time()
        self.set_scan_message('Server Ready')
        is_paused = False
        request_id = self.scandb.status_codes['requested']

        # Note: this loop is really just looking for new commands
        # or interrupts, so does not need to go super fast.
        while True:
            epics.poll(0.025, 1.0)
            time.sleep(0.25)
            now = time.time()

            # update server heartbeat / message
            if now > msgtime + 0.75:
                msgtime = now
                self.set_heartbeat()

            self.look_for_interrupts()

            # shutdown?
            if self.req_shutdown:
                break

            # pause: sleep, continue loop until un-paused
            if self.req_pause:
                time.sleep(1.0)
                continue

            # get ordered list of requested commands
            cmds = self.scandb.get_rows('commands',
                                        status=request_id,
                                        order_by='run_order')
            # abort current command?
            if self.req_abort:
                if len(cmds) > 0:
                    cmd = cmds[0]
                    self.scandb.set_command_status('aborted', cmdid=cmd.id)
                    cmds = []
                self.clear_interrupts()
                time.sleep(1.0)

            # do next command
            if len(cmds) > 0:
                self.do_command(cmds[0])
            else:
                time.sleep(0.25)
        # mainloop end
        self.finish()
        return None
