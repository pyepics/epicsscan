#!/usr/bin/python 
"""
Provides an Epics interface to ScanDB to put status info 
and allow Abort from an Epics PV interface

"""

import epics
import time
import os

class EpicsScanDB(epics.Device):
    """interface for scan server status via larchscan.db"""

    _attrs = ('status', 'message', 'last_error', 'command',
              'filename', 'basedir', 'workdir', 'TSTAMP',
              'cmd_id', 'Shutdown', 'Abort')

    def __init__(self, prefix):
        self._prefix = prefix
        epics.Device.__init__(self, self._prefix, attrs=self._attrs)

    def AbortScan(self):
        self.Abort = 1
        self.status = 4

    def setTime(self, ts=None):
        "Set Time"
        if ts is None:
            ts = time.strftime('%d-%b-%y %H:%M:%S')
        self.TSTAMP =  ts

    def __Fget(self, attr):      return self.get(attr, as_string=True)
    def __Fput(self, attr, val): return self.put(attr, val)

    def pv_property(attr):
        return property(lambda self:     self.__Fget(attr),
                        lambda self, val: self.__Fput(attr, val),
                        None, None)

    status   = pv_property('status')
    message  = pv_property('message')
    last_error = pv_property('last_error')
    command  = pv_property('command')
    filename = pv_property('filename')
    basedir  = pv_property('basedir')
    workdir  = pv_property('workdir')
    cmd_id   = pv_property('cmd_id')


