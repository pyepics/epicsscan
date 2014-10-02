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
        self.command_in_progress = False
        self.larch = larch.Interpreter()
        if dbname is not None:
            self.connect(dbname, **kwargs)

    def connect(self, dbname, **kwargs):
        """connect to Scan Database"""
        self.scandb = ScanDB(dbname=dbname, **kwargs)
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

    def execute_command(self, req):
        print 'Execute: ', req.id, req.command, req.arguments, req.output_file

        workdir = self.scandb.get_info('user_folder')
        os.chdir(nativepath(workdir))

#         print 'req.id      = ', req.id
#         print 'req.arguments = ', req.arguments
#         print 'req.status_id, req.status = ', req.status_id
#         print 'req.request_time = ', req.request_time
#         print 'req.start_time = ', req.start_time
#         print 'req.modify_time = ', req.modify_time
#         print 'req.output_value = ', req.output_value
#         print 'req.output_file = ', req.output_file
#
        self.scandb.set_info('command_running', 1)
        self.scandb.set_info('command_status', '')


        self.scandb.set_info('scan_status', 'starting')
        self.scandb.set_command_status(req.id, 'starting')

        self.do_command(req)

        self.scandb.set_command_status(req.id, 'finished')
        self.scandb.set_info('scan_status', 'idle')
        self.scandb.commit()
        self.command_in_progress = False

    def do_command(self, req=None, **kws):
        self.command_in_progress = True
        self.scandb.set_info('scan_status', 'running')
        self.scandb.set_command_status(req.id, 'running')
        args = str(req.arguments)
        filename = req.output_file
        if filename is None: 
            filename = ''          
        filename = str(filename)
        if len(filename) > 0:
            args = "%s, filename='%s'" % (args, filename)
            self.scandb.set_info('filename', filename)

        if req.command == 'doscan':
            larch_cmd = "do_scan(%s)" % args
            words = args.split(',')
            scanname = strip_quotes(words[0].strip())
            self.scandb.update_where('scandefs', {'name': scanname},
                                     {'last_used_time': make_datetime()})
        elif req.command == 'do_slewscan':
            larch_cmd = "do_slewscan(%s)" % (args)
            words = args.split(',')
            scanname = strip_quotes(words[0].strip())
            self.scandb.update_where('scandefs', {'name': scanname},
                                     {'last_used_time': make_datetime()})
        else:
            larch_cmd = "%s(%s)" % (req.command, args)
        self.scandb.set_info('current_command', larch_cmd)
        self.larch.error = []
        out = self.larch.eval(larch_cmd)
        time.sleep(0.1)
        if len(self.larch.error) > 0:
            self.scandb.set_info('command_error', self.larch.error[0].msg)
            # print 'Set Larch Error!! ', self.larch.error[0].msg
        self.scandb.set_info('command_running', 0)
        self.scandb.set_command_output(req.id, out)
        self.scandb.set_command_status(req.id, 'stopping')

    def look_for_interrupt_requests(self):
        """set interrupt requests:
        abort / pause / resume
        it is expected that long-running commands
        should do something like this....
        """
        def isset(infostr):
            return self.db.get_info(infostr, as_bool=True)
        self.abort_request = isset('request_abort')
        self.pause_request = isset('request_pause')
        self.resume_request = isset('request_resume')

    def mainloop(self):
        self.set_scan_message('Server Starting')
        self.scandb.set_info('scan_status', 'idle')
        msgtime = time.time()
        self.set_scan_message('Server Ready')
        while True:
            self.sleep(0.25)
            if self.abort:
                break
            reqs = self.scandb.get_commands('requested')
            if (time.time() - msgtime )> 300:
                print '#Server Alive, nrequests = ', len(reqs)
                msgtime = time.time()
            if self.command_in_progress:
                self.look_for_interrupt_requests()
                if self.abort_request:
                    print '#Abort request'
                elif self.pause_request:
                    print '#Pause Request'
                elif self.resume_request:
                    print '#Resume Request'
            elif len(reqs) > 0: # and not self.command_in_progress:
                print '#Execute Next Command: '
                self.execute_command(reqs.pop(0))

        # mainloop end
        self.finish()
        sys.exit()




if __name__  == '__main__':
    s = ScanServer(dbname='A.sdb')
    s.mainloop()
