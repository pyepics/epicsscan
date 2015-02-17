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

from ..site_config import get_fileroot
from ..larch_interface import LarchScanDBServer

class ScanServer():
    def __init__(self, dbname=None, fileroot=None, _larch=None,  **kwargs):

        self.fileroot = get_fileroot(fileroot)
        self.scandb = None
        self.abort = False
        self.larch = None
        self.larch_modules = {}
        self.command_in_progress = False
        self.req_shutdown = False
        if dbname is not None:
            self.connect(dbname, **kwargs)

    def connect(self, dbname, **kwargs):
        """connect to Scan Database"""
        self.scandb = ScanDB(dbname=dbname, **kwargs)
        self.set_scan_message('Server initializing ', self.fileroot)
        self.larch = LarchScanDBServer(self.scandb, fileroot=self.fileroot)

        self.scandb.set_info('request_abort',    0)
        self.scandb.set_info('request_pause',    0)
        self.scandb.set_info('request_shutdown', 0)

        self.set_scan_message('Server Loading Larch Plugins...')
        self.larch.load_plugins()
        self.set_scan_message('Server Loading Larch Macros...')
        self.larch.load_modules()
        self.set_scan_message('Server Connected.')

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
        time.sleep(0.1)
        self.scandb.set_info('request_abort',    1)
        time.sleep(0.1)
        self.scandb.set_info('request_abort',    0)
        time.sleep(0.1)
        self.scandb.set_info('request_shutdown', 0)
        time.sleep(0.1)

    def set_path(self):
        self.scandb.set_path(fileroot=self.fileroot)

    def do_command(self, req):
        print 'Do Command: ', req.id, req.command, req.arguments
        all_macros = self.larch.load_modules()

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
        elif command.lower() == 'reload':
            self.set_scan_message('Server Reloading Larch Plugins...')
            self.larch.load_plugins()

        if len(args) == 0:
            larch_cmd = command
        else:
            larch_cmd = "%s(%s)" % (command, args)
        print '>>> Larch: ', larch_cmd
        self.scandb.set_info('current_command', larch_cmd)

        self.scandb.set_info('scan_status', 'running')
        self.scandb.set_command_status(req.id, 'running')

        out = self.larch.run(larch_cmd)
        time.sleep(0.1)
        if len(self.larch.get_error()) > 0:
            err = self.larch.get_error()[0]
            self.scandb.set_info('command_error', repr(err.msg))


        if hasattr(out, 'dtimer'):
            try:
                out.dtimer.save("_debugscantime.dat")
            except:
                print('Could not save _debugscantime.dat')

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

        self.req_shutdown = isset('request_shutdown')
        self.req_pause = isset('request_pause')
        self.req_abort = isset('request_abort')
        return self.req_abort

    def mainloop(self):
        if self.larch is None:
            raise ValueError("Scan server not connected!")

        self.scandb.set_info('scan_status', 'idle')
        msgtime = time.time()
        self.set_scan_message('Server Ready')

        is_paused = False
        while True:
            self.look_for_interrupt_requests()
            if self.req_shutdown:
                break
            if time.time() > (msgtime + 120):
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

        # mainloop end
        self.finish()
        sys.exit()
