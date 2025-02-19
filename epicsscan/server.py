#!/usr/bin/env python
"""
scan server
"""
import traceback
from time import time, sleep

from collections import deque
from datetime import datetime
import epics
from pyshortcuts import isotime

from .scandb import ScanDB
from .utils import strip_quotes, plain_ascii, is_complete

from .macro_kernel import MacroKernel

from .epics_scandb import EpicsScanDB
# from .abort_slewscan import abort_slewscan

DEBUG_TIMER = False

class ScanServer():
    """Scan Server"""
    def __init__(self, dbname=None,  **kws):
        self.epicsdb = None
        self.scandb = None
        self.abort = False
        self.command_in_progress = False
        self.req_shutdown = False
        self.req_abort = False
        self.req_pause = False
        self.req_shutdown = False
        self.fileroot = None
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
        sleep(0.05)
        self.set_scan_message('Server Connected.')
        if 'startup' in self.mkernel.get_macros():
            self.scandb.add_command("startup()")

        eprefix = self.scandb.get_info('epics_status_prefix')
        basedir = self.scandb.get_info('server_fileroot')
        workdir = self.scandb.get_info('user_folder')

        if eprefix is not None:
            self.epicsdb = EpicsScanDB(prefix=eprefix)
            sleep(0.1)
            self.epicsdb.Shutdown = 0
            self.epicsdb.Abort = 0
            self.epicsdb.basedir = plain_ascii(basedir)
            self.epicsdb.workdir = plain_ascii(workdir)

    def set_scan_message(self, msg):
        self.scandb.set_info('scan_message', msg)
        if self.epicsdb is not None:
            self.epicsdb.message = msg
        print(msg)

    def sleep(self, t=0.05):
        try:
            sleep(t)
        except KeyboardInterrupt:
            self.abort = True

    def finish(self):
        "shut down scan server"
        self.set_scan_message('Server Shutting Down')
        self.scandb.set_info('request_pause',    0)
        self.scandb.set_info('request_abort',    1)
        self.scandb.set_info('request_abort',    0)
        self.scandb.set_info('request_shutdown', 0)
        sleep(0.025)

    def set_status(self, status):
        "set status"
        self.scandb.set_info('scan_status', status)
        if self.epicsdb is not None:
            self.epicsdb.status = status.title()

    def set_workdir(self, verbose=False):
        "ser working folder"
        self.scandb.set_workdir(verbose=verbose)
        self.fileroot = self.scandb.get_info('server_fileroot')

    def do_command(self, cmd_row):
        """execute a single command: a row from the commands table"""
        self.set_workdir(verbose=False)
        cmdid = cmd_row.id
        command = plain_ascii(cmd_row.command)
        # print(f"#Server.do_command: <{command}>")
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
            self.set_scan_message("Error: command <command> is incomplete")
            self.scandb.set_command_status('canceled', cmdid=cmdid)
            return

        self.command_in_progress = True
        self.set_status('starting')
        self.set_scan_message(f"Executing: <{command}>")
        self.scandb.set_command_status('starting', cmdid=cmdid)

        args    = strip_quotes(plain_ascii(cmd_row.arguments)).strip()
        notes   = strip_quotes(plain_ascii(cmd_row.notes)).strip()
        nrepeat = int(cmd_row.nrepeat)

        filename = cmd_row.output_file
        if filename is None:
            filename = ''
        filename = strip_quotes(plain_ascii(filename))

        if command.lower() in ('scan', 'slewscan'):
            scanname = args
            words = [f"'{scanname}'"]
            if nrepeat > 1 and command != 'slewscan':
                words.append(f"nscans={nrepeat:d}")
                self.scandb.set_info('nscans', nrepeat)
            if len(notes) > 0:
                words.append(f"comments='{notes}'")
            if len(filename) > 0:
                words.append(f"filename='{filename}'")
                self.scandb.set_filename(filename)

            self.scandb.update('scandefs', where={'name': scanname},
                               last_used_time=datetime.now())
            command = f"do_{command}"
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
                cmd = f"{command}({args})"
            self.scandb.set_info('scan_progress', 'running')
            self.scandb.set_info('error_message',   '')
            self.scandb.set_info('current_command', cmd)
            self.scandb.set_info('current_command_id', cmdid)
            self.set_status('running')
            self.scandb.set_command_status('running', cmdid=cmdid)
            if self.epicsdb is not None:
                self.epicsdb.cmd_id = cmdid
                self.epicsdb.command = cmd

            try:
                # print(f"#Server.do_command  run <{cmd}> {isotime()}")
                self.mkernel.run(cmd)
            except:
                pass
            status, msg = 'finished', 'scan complete'
            errors = self.mkernel.get_error()
            # print(f"#Server.do_command  errors? {len(errors)}")
            if len(errors) > 0:
                ebuff = []
                for err in errors:
                    exc_type, exc_val, exc_tb = err.exc_info
                    ebuff.append(f'#> Exception {exc_type}: {exc_val}')
                    ebuff.extend(err.get_error())
                    print(f'#>Exception {exc_type}: {exc_val}')
                    print(traceback.print_tb(exc_tb))
                emsg = '\n'.join(ebuff)
                self.scandb.set_info('error_message', emsg)
                msg = 'scan completed with error'
                print('## Error ', emsg)
            sleep(0.1)
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

        if not self.scandb.check_hostpid():
            print("No Longer Host, exiting")
            sleep(5)
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
        "set scan infor heart beat"
        tmsg = isotime()
        self.scandb.set_info('heartbeat', tmsg)
        if self.epicsdb is not None:
            self.epicsdb.TSTAMP = tmsg

    def mainloop(self):
        """ main serve loop"""
        self.set_status('idle')
        msgtime = time()
        self.set_scan_message('Server Ready')
        request_id = self.scandb.status_codes['requested']

        # Note: this loop is really just looking for new commands
        # or interrupts, so does not need to go super fast.
        next_logtime = 0.0
        cmds = deque([])
        while True:
            epics.poll(0.05, 1.0)

            now = time()
            if now > next_logtime:
                print(f"scan server:  {isotime()} {len(cmds)} in queue")
                next_logtime = now + 120.0

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
                sleep(1.0)
                continue

            # abort current command?
            if self.req_abort:
                if len(cmds) > 0:
                    cmd = cmds.popleft()
                    self.scandb.set_command_status('aborted', cmdid=cmd.id)
                self.clear_interrupts()
                sleep(1.0)

            # we are not paused or aborting:
            # if there are more commands in the queue, do the next one
            if len(cmds) > 0:
                self.do_command(cmds.popleft())

            # otherwise get ordered list of requested commands
            else:
                cmds = deque(self.scandb.get_rows('commands',
                                             status=request_id,
                                             order_by='run_order'))

        # mainloop end
        self.finish()
