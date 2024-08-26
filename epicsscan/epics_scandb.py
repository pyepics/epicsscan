#!/usr/bin/python
"""
Provides an Epics interface to ScanDB to put status info
and allow Abort from an Epics PV interface
"""
import epics
import time
import os

class EpicsScanDB(epics.Device):
    """interface for scan server status via epics_scan.db"""

    _attrs = ('status', 'message', 'last_error', 'command',
              'filename', 'basedir', 'workdir', 'timestamp',
              'cmd_id', 'shutdown', 'abort', 'scan_abort')

    def __init__(self, prefix):
        self._prefix = prefix
        epics.Device.__init__(self, self._prefix, attrs=self._attrs)

    def setTime(self, ts=None):
        "Set Time"
        if ts is None:
            ts = time.strftime('%d-%b-%y %H:%M:%S')
        self.time_stamp =  ts

    def __Fget(self, attr):
        self.setTime()
        return self.get(attr, as_string=True)

    def __Fput(self, attr, val):
        self.setTime()
        return self.put(attr, val)

    def pv_property(attr):
        return property(lambda self:     self.__Fget(attr),
                        lambda self, val: self.__Fput(attr, val),
                        None, attr)

    status   = pv_property('status')
    message  = pv_property('message')
    last_error = pv_property('last_error')
    command  = pv_property('command')
    filename = pv_property('filename')
    basedir  = pv_property('basedir')
    workdir  = pv_property('workdir')
    cmd_id   = pv_property('cmd_id')
    abort    = pv_property('abort')
    shutdown = pv_property('shutdown')
    abort_scan = pv_property('abort_scan')
