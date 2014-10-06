#!/usr/bin/env python

import time, sys, os
import threading
import json
import numpy as np

import epics

from ..scandb import ScanDB, ScanDBException, make_datetime

from ..file_utils import fix_varname, nativepath
from ..utils import  strip_quotes


import larch
class ScanServer():
    LARCH_SCANDB = '_scan._scandb'
    def __init__(self, dbname=None, _larch=None,  **kwargs):
        self.scandb = None
        self.abort = False
        self.larch = None
        self.command_in_progress = False
        self.req_shutdown = False
        if dbname is not None:
            self.connect(dbname, **kwargs)

    def connect(self, dbname, **kwargs):
        """connect to Scan Database"""
        self.scandb = ScanDB(dbname=dbname, **kwargs)
        self.set_scan_message('Server Starting')
        self.larch = larch.Interpreter()
        self.larch.symtable.set_symbol(self.LARCH_SCANDB, self.scandb)


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
        print 'shutting down!'


    def do_command(self, req):
        print 'Do Command: ', req.id, req.command, req.arguments
        workdir = self.scandb.get_info('user_folder')
        try:
            os.chdir(nativepath(workdir))
        except:
            pass

        self.command_in_progress = True
        self.scandb.set_info('scan_status', 'starting')
        self.scandb.set_command_status(req.id, 'starting')

        args    = strip_quotes(str(req.arguments))
        notes   = strip_quotes(str(req.notes))
        nrepeat = int(req.nrepeat)
        command = str(req.command)

        filename = req.output_file
        if filename is None:
            filename = ''
        filename = strip_quotes(str(filename))

        if command in ('scan', 'slewscan'):
            scanname = args
            args = "'%s'" % scanname
            if nrepeat > 1 and command != 'slewscan':
                args = "%s, nscans=%i" % (args, nrepeat)
            if len(notes) > 0:
                args = "%s, comments='%s'" % (args, notes)
            if len(filename) > 0:
                args = "%s, filename='%s'" % (args, filename)
                self.scandb.set_info('filename', filename)

            self.scandb.update_where('scandefs', {'name': scanname},
                                     {'last_used_tqime': make_datetime()})

            command = "do_%s" % command
        larch_cmd = "%s(%s)" % (command, args)

        self.scandb.set_info('current_command', larch_cmd)
        self.larch.error = []

        self.scandb.set_info('scan_status', 'running')
        self.scandb.set_command_status(req.id, 'running')

        out = self.larch.eval(larch_cmd)
        time.sleep(0.1)
        if len(self.larch.error) > 0:
            self.scandb.set_info('command_error', repr(self.larch.error[0].msg))

        self.scandb.set_info('command_running', 0)
        self.scandb.set_command_output(req.id, repr(out))
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
        self.req_resume = isset('request_resume')
        self.req_shutdown = isset('request_shutdown')

    def mainloop(self):
        if self.larch is None:
            raise ValueError("Scan server not connected!")

        self.scandb.set_info('scan_status', 'idle')
        msgtime = time.time()
        self.set_scan_message('Server Ready')
        while True:
            self.sleep(0.25)
            self.look_for_interrupt_requests()
            if self.req_shutdown:
                break
            reqs = self.scandb.get_commands('requested')
            if (time.time() - msgtime )> 600:
                print '#Server Alive, %i Pending requests' % len(reqs)
                msgtime = time.time()
            elif len(reqs) > 0:
                self.do_command(reqs.pop(0))
        # mainloop end
        self.finish()
        sys.exit()
