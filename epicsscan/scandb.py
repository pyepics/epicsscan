#!/usr/bin/env python
"""
SQLAlchemy wrapping of scan database

Main Class for full Database:  ScanDB
"""
from __future__ import print_function
import os
import sys
import json
import time
import logging
import numpy as np
from socket import gethostname
from datetime import datetime
import yaml
from charset_normalizer import from_bytes
# from utils import backup_versions, save_backup
import epics

from .scandb_schema import create_scandb
from .simpledb import SimpleDB, isotime

from .utils import (normalize_pvname, asciikeys, pv_fullname,
                    ScanDBException, ScanDBAbort)
from .create_scan import create_scan

def get_credentials(envvar='ESCAN_CREDENTIALS'):
    """look up credentials file from environment variable"""
    conn = {}
    credfile = os.environ.get(envvar, None)
    if credfile is not None and os.path.exists(credfile):
        with open(credfile, 'rb') as fh:
            text = str(from_bytes(fh.read()).best())
            conn = yaml.load(text, Loader=yaml.Loader)
    return conn

def json_encode(val):
    "simple wrapper around json.dumps"
    if val is None or isinstance(val, (str, unicode)):
        return val
    return  json.dumps(val)

def isotime2datetime(xisotime):
    "convert isotime string to datetime object"
    sdate, stime = xisotime.replace('T', ' ').split(' ')
    syear, smon, sday = [int(x) for x in sdate.split('-')]
    sfrac = '0'
    if '.' in stime:
        stime, sfrac = stime.split('.')
    shour, smin, ssec  = [int(x) for x in stime.split(':')]
    susec = int(1e6*float('.%s' % sfrac))
    return datetime(syear, smon, sday, shour, smin, ssec, susec)

def make_datetime(t=None, iso=False):
    """unix timestamp to datetime iso format
    if t is None, current time is used"""
    if t is None:
        dt = datetime.now()
    else:
        dt = datetime.utcfromtimestamp(t)
    if iso:
        return datetime.isoformat(dt)
    return dt


class ScanDB(SimpleDB):
    """
    Main Interface to Scans Database
    """
    def __init__(self, dbname=None, server='postgresql', create=False, **kws):
        if dbname is None:
            conndict = get_credentials(envvar='ESCAN_CREDENTIALS')
            if 'dbname' in conndict:
                dbname = conndict.pop('dbname')
            if 'server' in conndict:
                server = conndict.pop('server')
            kws.update(conndict)

        self.dbname = dbname
        self.server = server
        self.tables = None
        self.engine = None
        self.session = None
        self.pvs = {}
        self.scandata = []
        self.restoring_pvs = []
        if create:
            create_scandb(dbname, server=self.server, create=True, **kws)

        SimpleDB.__init__(self, dbname=self.dbname, server=self.server, **kws)

        self.status_codes = {}
        self.status_names = {}
        for row in self.get_rows('status'):
            self.status_codes[row.name] = row.id
            self.status_names[row.id] = row.name

    def create_newdb(self, dbname, connect=False, **kws):
        "create a new, empty database"
        create_scandb(dbname,  **kws)
        if connect:
            time.sleep(0.5)
            self.connect(dbname, **kws)

    def set_path(self, fileroot=None):
        workdir = self.get_info('user_folder')
        workdir = workdir.replace('\\', '/').replace('//', '/')
        if workdir.startswith('/'):
            workdir = workdir[1:]
        if fileroot is None:
            fileroot = self.get_info('server_fileroot')
            if os.name == 'nt':
                fileroot = self.get_info('windows_fileroot')
                if not fileroot.endswith('/'):
                    fileroot += '/'
            fileroot = fileroot.replace('\\', '/').replace('//', '/')
        if workdir.startswith(fileroot):
            workdir = workdir[len(fileroot):]

        fullpath = os.path.join(fileroot, workdir)
        fullpath = fullpath.replace('\\', '/').replace('//', '/')
        try:
            os.chdir(fullpath)
        except:
            logging.exception("ScanDB: Could not set working directory to %s " % fullpath)
        finally:
            # self.set_info('server_fileroot',  fileroot)
            self.set_info('user_folder',      workdir)
        time.sleep(0.1)

    def isScanDB(self, dbname, server='sqlite',
                 user='', password='', host='', port=None):
        """test if a file is a valid scan database:
        must be a sqlite db file, with tables named
        'postioners', 'detectors', and 'scans'
        """
        return True

    def getrow(self, table, name):
        """return named row from a table"""
        return self.get_rows(table, where={'name': name},
                             none_if_empty=True, limit_one=True)


    def commit(self):
        pass

    def set_config(self, name, text):
        """add configuration, general purpose table"""
        row = self.getrow('config', name=name)

        if row is None:
            self.insert('config', name=name, notes=text)
        else:
            self.update('config', where={'name': name}, notes=text)

    def get_config(self, name):
        """get configuration, general purpose table"""
        return self.getrow('config', name)

    def get_config_id(self, idnum):
        """get configuration by ID"""
        return self.get_rows('config', where={'id': idnum}, limit_one=True)

    def add_slewscanstatus(self, text):
        """add message to slewscanstatus table"""
        self.insert('slewscanstatus', text=text)

    def clear_slewscanstatus(self, **kws):
        self.delete_rows('slewscanstatus', where=True)

    def get_slewscanstatus(self):
        return self.get_rows('slewscanstatus')

    def read_slewscan_status(self):
        text = []
        for row in self.get_rows('slewscanstatus'):
            text.append(str(row.text))
        return "\n".join(text)

    def last_slewscan_status(self):
        lastrow = self.rows('slewscanstatus')[-1]
        return lastrow.modify_time.isoformat()

    def set_message(self, text):
        """add message to messages table"""
        self.add_row('messages', text=text)

    def set_hostpid(self, clear=False):
        """set hostname and process ID, as on intial set up"""
        name, pid = '', '0'
        if not clear:
            name, pid = gethostname(), str(os.getpid())
        self.set_info('host_name', name)
        self.set_info('process_id', pid)

    def check_hostpid(self):
        """check whether hostname and process ID match current config"""
        if not self.server.startswith('sqlite'):
            return True
        db_host_name = self.get_info('host_name', default='')
        db_process_id  = self.get_info('process_id', default='0')
        return ((db_host_name == '' and db_process_id == '0') or
                (db_host_name == gethostname() and
                 db_process_id == str(os.getpid())))

    def add_row_attr(self, tablename, **kws):
        """add generic row"""
        if 'attributes' in kws:
            kws['attributes'] = json_encode(val)
        self.add_row(tablename, **kws)
        where = {}
        if 'name' in kws:
            where['name'] = kws['name']
        elif 'id' in kws:
            where['id'] = kws['id']
        return self.get_rows(tablename, where=where, limit_one=True)

    # Scan Definitions
    def get_scandef(self, name):
        """return scandef by name"""
        return self.getrow('scandefs', name)

    def rename_scandef(self, scanid, name):
        self.update('scandefs', where={'id': scanid}, name=name)

    def del_scandef(self, name=None, scanid=None):
        """delete scan defn by name"""
        where = {}
        if name is not None:
            where['name'] = name
        elif scanid is not None:
            where['id'] = scanid
        self.delete_rows('scandefs', where=where)

    def add_scandef(self, name, text='', notes='', type='', **kws):
        """add scan"""
        name = name.strip()
        now = make_datetime()
        kws.update({'notes': notes, 'text': text,
                    'type': type, 'name': name,
                    'modify_time': now, 'last_used_time': now})
        self.add_row_attr('scandefs', **kws)

    def get_scandict(self, scanname):
        """return dictionary of scan configuration for a named scan"""
        sobj = self.get_scandef(scanname)
        if sobj is None:
            raise ScanDBException('get_scandict needs valid scan name')
        return json.loads(sobj.text, object_hook=asciikeys)

    def make_scan(self, scanname, filename='scan.001',
                  data_callback=None, larch=None):
        """
        create a StepScan object from a saved scan definition

        Arguments
        ---------
        scanname (string): name of scan
        filename (string): name for datafile

        Returns
        -------
        scan object
        """
        try:
            sdict = self.get_scandict(scanname)
        except ScanDBException:
            raise ScanDBException("make.scan(): '%s' not a valid scan name" % scanname)

        if 'rois' not in sdict:
            sdict['rois'] = json.loads(self.get_info('rois'), object_hook=asciikeys)
        sdict['filename'] = filename
        sdict['scandb'] = self
        sdict['larch'] = larch
        sdict['data_callback'] = data_callback
        sdict['extra_pvs'] = []
        for det in sdict['detectors']:
            if det.get('label', None) ==  'xspress3' and det.get('nrois', None) is not None:
                det['nrois'] = 48

        for row  in self.get_rows('extrapvs'):
            if row.use:
                sdict['extra_pvs'].append((row.name, row.pvname))
        return create_scan(**sdict)

    # macros
    def get_macro(self, name):
        """return macro by name"""
        return self.getrow('macros', name)

    def add_macro(self, name, text, arguments='',
                  output='', notes='', **kws):
        """add macro"""
        name = name.strip()
        kws.update({'notes': notes, 'text': text,
                    'arguments': arguments, 'name': name})
        return self.add_row_attr('macros', **kws)

    ## scan data
    ## note that this is supported differently for Postgres and Sqlite:
    ##    With Postgres, data arrays are held internally,
    ##    With Sqlite, data is held as json-ified arrays
    def get_scandata(self):
        return self.get_rows('scandata')

    def add_scandata(self, name, value, notes='', pvname='', **kws):
        name = name.strip()
        kws.update({'notes': notes, 'pvname': pvname, 'name': name})
        if self.server.startswith('sqli'):
            value = json_encode(value)
        kws['data'] = value

        return self.add_row_attr('scandata', **kws)

    def set_scandata(self, name, data, **kws):
        tab = self.tables['scandata']
        if isinstance(data, np.ndarray):
            data = data.tolist()
        elif isinstance(data, tuple):
            data = list(data)
        if isinstance(data, (int, float)):
            data = [data]
        where = "name='%s'" % name
        self.update('scandata', where={'name': name}, data=data)

    def append_scandata(self, name, val):
        tab = self.tables['scandata']
        row = self.get_rows('scandata', name=name, limit_one=True)
        n = len(row.data)
        where = self.handle_where('scandata', where={'name': name})
        self.execute(tab.update(where=where).values(tab.c.data[n]==val),
                     set_modify_date=True)


    def clear_scandata(self, **kws):
        a = self.get_scandata()
        if len(a) > 0:
            self.delete_rows('scandata', where=True)

    ### positioners
    def get_positioners(self):
        return self.get_rows('scanpositioners')

    def get_slewpositioners(self, **kws):
        return self.get_rows('slewscanpositioners')

    def get_positioner(self, name):
        """return positioner by name"""
        return self.getrow('scanpositioners', name)

    def del_slewpositioner(self, name):
        """delete slewscan positioner by name"""
        self.delete_rows('slewscanpositioners', {'name': name})

    def del_positioner(self, name):
        """delete positioner by name"""
        self.delete_rows('scanpositioners', {'name': name})

    def add_positioner(self, name, drivepv, readpv=None, notes='',
                       extrapvs=None, **kws):
        """add positioner"""
        name = name.strip()
        drivepv = pv_fullname(drivepv)
        if readpv is not None:
            readpv = pv_fullname(readpv)
        epvlist = []
        if extrapvs is not None:
            epvlist = [pv_fullname(p) for p in extrapvs]

        self.add_pv(drivepv, notes=name)
        if readpv is not None:
            self.add_pv(readpv, notes="%s readback" % name)
        for epv in epvlist:
            self.add_pv(epv)

        kws.update({'notes': notes, 'drivepv': drivepv,
                    'readpv': readpv, 'extrapvs':json.dumps(epvlist),
                    'name': name})
        return self.add_row_attr('scanpositioners', **kws)

    def get_slewpositioner(self, name):
        """return slewscan positioner by name"""
        return self.getrow('slewscanpositioners', name)

    def add_slewpositioner(self, name, drivepv, readpv=None, notes='',
                           extrapvs=None, **kws):
        """add slewscan positioner"""
        name = name.strip()
        drivepv = pv_fullname(drivepv)
        if readpv is not None:
            readpv = pv_fullname(readpv)
        epvlist = []
        if extrapvs is not None:
            epvlist = [pv_fullname(p) for p in extrapvs]

        self.add_pv(drivepv, notes=name)
        if readpv is not None:
            self.add_pv(readpv, notes="%s readback" % name)
        for epv in epvlist:
            self.add_pv(epv)

        kws.update({'name': name, 'notes': notes, 'drivepv': drivepv,
                    'readpv': readpv, 'extrapvs':json.dumps(evpvlist) })
        return self.add_row_attr('slewscanpositioners', **kws)


    ### detectors
    def get_detectors(self):
        return self.get_rows('scandetectors')

    def get_detector(self, name=None, pvname=None):
        """return detector by name or prefix"""
        out = None
        if name is not None:
            out = self.getrow('scandetectors', name)
        if out is None and pvname is not None:
            out = self.get_rows('scandetectors', where={'pvname': pvname},
                             none_if_empty=True, limit_one=True)
        return out

    def use_detector(self, detname, use=True):
        useval = 1 if use else 0
        self.update('scandetectors', where={'name':detname}, use=useval)

    def del_detector(self, name):
        """delete detector by name"""
        self.delete_rows('scandetectors', {'name': name})

    def add_detector(self, name, pvname, kind='', options='', **kws):
        """add detector"""
        name = name.strip()
        pvname = pv_fullname(pvname)
        kws.update({'pvname': pvname, 'name': name,
                    'kind': kind, 'options': options})
        return self.add_row_attr('scandetectors', **kws)


    ### detector configurations
    def get_detectorconfigs(self):
        return self.get_rows('scandetectorconfig')

    def get_detectorconfig(self, name):
        return self.getrow('scandetectorconfig', name)

    def set_detectorconfig(self, name, text, notes=None):
        """set detector configuration"""
        row = self.get_detectorconfig(name)
        kws = {'text': text, 'name': name}
        if notes is not None:
            kws['notes'] = notes

        if row is None:
            self.insert('scandetectorconfig', **kws)
        else:
            where = {'name': kws.pop('name')}
            self.update('scandetectorconfig', where=where, **kws)

    ### counters -- simple, non-triggered PVs to add to detectors
    def get_counters(self):
        return self.get_rows('scancounters')

    def get_counter(self, name):
        """return counter by name"""
        return self.getrow('scancounters', name)

    def del_counter(self, name):
        """delete counter by name"""
        self.delete_rows('scancounters', where={'name': name})

    def add_counter(self, name, pvname, **kws):
        """add counter (non-triggered detector)"""
        pvname = pv_fullname(pvname)
        self.add_pv(pvname, notes=name)

        name = name.strip()
        kws.update({'pvname': pvname, 'name': name})
        return self.add_row_attr('scancounters',**kws)

    ### extra pvs: pvs recorded at breakpoints of scans
    def get_extrapvs(self):
        return self.get_rows('extrapvs')

    def get_extrapv(self, name):
        """return extrapv by name"""
        return self.getrow('extrapvs', name)

    def del_extrapv(self, name):
        """delete extrapv by name"""
        self.delete_rows('extrapvs', {'name': name})

    def add_extrapv(self, name, pvname, use=True, **kws):
        """add extra pv (recorded at breakpoints in scans"""
        name = name.strip()
        pvname = pv_fullname(pvname)
        self.add_pv(pvname, notes=name)

        kws.update({'pvname': pvname, 'use': int(use), 'name': name})
        return self.add_row_attr('extrapvs', **kws)

    def get_common_commands(self):
        return self.get_rows('common_commands', order_by='display_order')

    def add_common_commands(self, name, args='', show=True, display_order=1000):
        """add extra pv (recorded at breakpoints in scans"""
        kws = {'name': name.strip(), 'args': args.strip(), 'show': int(show),
               'display_order': int(display_order)}
        return self.add_row_attr('common_commands', **kws)


    # add PV to list of PVs
    def add_pv(self, name, notes=''):
        """add pv to PV table if not already there """
        if len(name) < 2:
            return
        name = pv_fullname(name)
        self.connect_pvs(names=[name])
        vals  = self.get_rows('pv', where={'name': name})
        if len(vals) < 1:
            self.insert('pv', name=name, notes=notes)
        elif notes != '':
            self.update('pv', where={'name': name}, notes=notes)

        pvrow = self.get_rows('pv', where={'name': name}, limit_one=true)
        return pvrow

    def get_pvrow(self, name):
        """return db row for a PV"""
        if len(name) > 2:
            return self.getrow('pv', name)


    def get_pv(self, name):
        """return pv object from known PVs"""
        if len(name) > 2:
            name = pv_fullname(name)
            if name in self.pvs:
                return self.pvs[name]

    def connect_pvs(self, names=None):
        "connect all PVs in pvs table"
        if names is None:
            names = [row.name for row in self.get_rows('pv')]

        _connect = []
        for name in names:
            name = pv_fullname(name)
            if len(name) < 2:
                continue
            if name not in self.pvs:
                self.pvs[name] = epics.get_pv(name)
                _connect.append(name)

        for name in _connect:
            connected, count = False, 0
            while not connected:
                time.sleep(0.003)
                count += 1
                connected = self.pvs[name].connected or count > 100


    ### commands -- a more complex interface
    def get_commands(self, status=None, reverse=False, order_by='run_order',
                     requested_since=None, **kws):
        """return command by status"""
        table = self.tables['commands']
        order = table.c.id
        if order_by.lower().startswith('run'):
            order = table.c.run_order
        # rows = self.get_rows('commands', order_by=order_by)

        if reverse:
            order = order.desc()

        q = table.select().order_by(order)
        if status in self.status_codes:
            q = q.where(table.c.status_id == self.status_codes[status])
        if requested_since is not None:
            q = q.where(table.c.request_time >= requested_since)
        return self.execute(q).fetchall()

    # commands -- a more complex interface
    def get_mostrecent_command(self):
        """return last command entered"""
        return self.get_rows('commands', order_by='request_time')[-1]

    def add_command(self, command, arguments='',output_value='',
                    output_file='', notes='', nrepeat=1, **kws):
        """add command"""
        kws.update({'command': command,
                    'arguments': arguments,
                    'output_file': output_file,
                    'output_value': output_value,
                    'notes': notes,
                    'nrepeat': nrepeat,
                    'request_time': isotime(),
                    'status_id': self.status_codes.get('requested', 1)})
        return self.insert('commands', **kws)


    def get_current_command_id(self):
        """return id of current command"""
        cmdid  = self.get_info('current_command_id', default=0)
        if cmdid == 0:
            cmdid = self.get_mostrecent_command().id
        return int(cmdid)

    def get_current_command(self):
        """return command by status"""
        cmdid  = self.get_current_command_id()
        return self.get_rows('commands', where={'id': cmdid}, limit_one=True)

    def get_command_status(self, cmdid=None):
        "get status for a command by id"
        if cmdid is None:
            cmdid = self.get_current_command_id()
        row = self.get_rows('commands', where={'id': cmdid}, limit_one=True)
        return self.status_names[row.status_id]

    def set_command_status(self, status, cmdid=None):
        """set the status of a command (by id)"""
        if cmdid is None:
            cmdid = self.get_current_command_id()

        status = status.lower()
        if status not in self.status_codes:
            status = 'unknown'

        statid = self.status_codes[status]
        kws = {'status_id': statid}
        if status.startswith('start'):
            kws['start_time'] = datetime.now()
        self.update('commands', where={'id': cmdid}, **kws)


    def set_command_run_order(self, run_order, cmdid):
        """set the run_order of a command (by id)"""
        self.update('commands', where={'id': cmdid}, run_order=run_order)

    def set_filename(self, filename):
        """set filename for info and command"""
        self.set_info('filename', filename)
        ufolder = self.get_info('user_folder', default='')
        self.set_command_filename(os.path.join(ufolder, filename))

    def set_command_filename(self, filename, cmdid=None):
        """set filename for command"""
        if cmdid is None:
            cmdid  = self.get_current_command_id()
        self.update('commands', where={'id': cmdid}, output_file=filename)

    def set_command_output(self, value=None, cmdid=None):
        """set the status of a command (by id)"""
        if cmdid is None:
            cmdid  = self.get_current_command_id()
        self.update('commands', where={'id': cmdid}, output_value=repr(value))

    def replace_command(self, cmdid, new_command):
        """replace requested  command"""
        where = {'id': cmdid}
        row = self.get_rows('commands', where=where, limit_one=True)
        if self.status_names[row.status_id].lower() == 'requested':
            self.update('commands', where=where, command=new_command)

    def cancel_command(self, cmdid):
        """cancel command"""
        self.set_command_status('canceled', cmdid)
        self.update('commands', where={'id': cmdid},
                    status_id=self.status_codes['canceled'])

    def cancel_remaining_commands(self):
        """cancel all commmands to date"""
        requested = self.status_codes['requested']
        canceled  = self.status_codes['canceled']
        for row in self.get_rows('commands', where={'status_id': requested},
                               order_by='run_order'):
            self.update('commands', where={'id': row.id}, status_id=canceled)

    def test_abort(self, msg='scan abort'):
        """look for abort, raise ScanDBAbort if set"""
        return self.get_info('request_abort', as_bool=True)

    def wait_for_pause(self, timeout=86400.0):
        """if request_pause is set, wait until it is unset"""
        paused = self.get_info('request_pause', as_bool=True)
        if not paused:
            return

        t0 = time.time()
        while paused:
            time.sleep(0.25)
            paused = (self.get_info('request_pause', as_bool=True) and
                      (time.time() - t0) < timeout)

class InstrumentDB(object):
    """Instrument / Position class using a scandb instance"""

    def __init__(self, scandb):
        self.scandb = scandb
        self.make_pvmap()

    def make_pvmap(self):
        """generate pv {id:name} dict"""
        self.pvmap = dict([(r.id, r.name) for r in self.scandb.get_rows('pv')])

    ### Instrument Functions
    def add_instrument(self, name, pvs=None, notes=None, attributes=None, **kws):
        """add instrument
        notes and attributes optional
        returns Instruments instance
        """
        print("would add instrument!! ", name, pvs)
        name = name.strip()
        kws['name'] = notes
        kws['notes'] = notes
        kws['attributes'] = attributes
        inst = self.get_instrument(name)
        if inst is None:
            out = self.scandb.add_row_attr(**kws)
            inst = self.get_instrument(name)

        if pvs is not None:
            pvlist = []
            for pvname in pvs:
                thispv = self.scandb.get_pvrow(pvname)
                if thispv is None:
                    thispv = self.scandb.add_pv(pvname)
                pvlist.append(thispv)
            for dorder, pv in enumerate(pvlist):
                data = {'display_order': dorder, 'pv_id': pv.id,
                        'instrument_id': inst.id}
                self.scandb.insert('instrument_pv', **data)

    def get_all_instruments(self):
        """return instrument list
        """
        return self.scandb.get_rows('instrument', order_by='display_order')

    def get_instrument(self, name):
        """return instrument by name
        """
        return self.scandb.getrow('instrument', name)

    def remove_position(self, instname, posname):
        inst = self.get_instrument(instname)
        if inst is None:
            raise ScanDBException('remove_position needs valid instrument')

        posname = posname.strip()
        pos  = self.get_position(instname, posname)
        if pos is None:
            raise ScanDBException("Postion '%s' not found for '%s'" %
                                        (posname, inst.name))

        self.scandb.delete_rows('position_pv', {'position_id': pos.id})
        self.scandb.delete_rows('position_pv', {'position_id': None})
        self.scandb.delete_rows('position', {'id': pos.id})

    def remove_all_positions(self, instname):
        for posname in self.get_positionlist(instname):
            self.remove_position(instname, posname)

    def remove_instrument(self, inst):
        inst = self.get_instrument(inst)
        if inst is None:
            raise ScanDBException('Save Postion needs valid instrument')

        self.scandb.delete_rows('inststrument', {'id': inst.id})

        for tablename in ('position', 'instrument_pv', 'instrument_precommand',
                          'instrument_postcommand'):
            self.scandb.delete_rows(tablename, {'instrument_id': inst.id})

    def save_position(self, instname, posname, values, image=None, notes=None, **kw):
        """save position for instrument
        """
        inst = self.get_instrument(instname)
        if inst is None:
            raise ScanDBException('Save Postion needs valid instrument')

        posname = posname.strip()
        pos  = self.get_position(instname, posname)

        if pos is None:
            kws = dict(name=posname, instrument_id=inst.id,
                       modify_time=datetime.now())
            if image is not None:
                kws['image'] = image
            if notes is not None:
                kws['notes'] = notes

            self.scandb.insert('position', **kws)

            pos  = self.get_position(instname, posname)

        pvnames = []
        for row in self.scandb.get_rows('instrument_pv', where={'instrument_id': inst.id}):
            name = self.scandb.get_rows('pv', where={'id': row.pv_id}, limit_one=True).name
            pvnames.append(str(name))

        ## print("@ Save Position: ", posname, pvnames, values)
        # check for missing pvs in values
        missing_pvs = []
        for pv in pvnames:
            if pv not in values:
                missing_pvs.append(pv)

        if len(missing_pvs) > 0:
            raise ScanDBException('save_position: missing pvs:\n %s' %
                                        missing_pvs)

        self.scandb.delete_rows('position_pv', {'position_id': pos.id})
        self.scandb.delete_rows('position_pv', {'position_id': None})

        for name in pvnames:
            thispv = self.scandb.get_pvrow(name)
            val = values[name]
            if val is not None:
                try:
                    val = float(val)
                except:
                    pass
                self.scandb.insert('position_pv', pv_id=thispv.id,
                                   value=val,  position_id=pos.id,
                                   notes="'%s' / '%s'" % (inst.name, posname))


    def save_current_position(self, instname, posname, image=None, notes=None):
        """save current values for an instrument to posname
        """
        inst = self.get_instrument(instname)
        if inst is None:
            raise ScanDBException('Save Postion needs valid instrument')
        vals = {}
        for pv in inst.pvs:
            vals[pv.name] = epics.caget(pv.name)
        self.save_position(instname, posname,  vals, image=image, notes=notes)

    def restore_complete(self):
        "return whether last restore_position has completed"
        if len(self.restoring_pvs) > 0:
            return all([p.put_complete for p in self.restoring_pvs])
        return True

    def rename_position(self, inst, oldname, newname):
        """rename a position"""
        pos = self.get_position(inst, oldname)
        if pos is not None:
            self.scandb.update('position', where={'id': pos.id} , name=newname)

    def get_position(self, instname, posname):
        """return position from namea and instrument
        """
        inst = self.get_instrument(instname)
        return self.scandb.get_rows('position', where={'name': posname, 'instrument_id': inst.id},
                                    limit_one=True, none_if_empty=True)

    def get_position_vals(self, instname, posname):
        """return position with dictionary of PVName:Value pairs"""
        pos = self.get_position(instname, posname)
        out = {}
        for row in self.scandb.get_rows('position_pv', where={'position_id':  pos.id}):
            if row.pv_id not in self.pvmap:
                self.make_pvmap()
            out[self.pvmap[row.pv_id]]= float(row.value)
        return out

    def get_positionlist(self, instname, reverse=False):
        """return list of position names for an instrument
        """
        inst = self.get_instrument(instname)
        rows = self.scandb.get_rows('position', where={'instrument_id': inst.id},
                                   order_by='modify_time')

        out = [row.name for row in rows]
        if reverse:
            out.reverse()
        return out

    def restore_position(self, instname, posname, wait=False, timeout=5.0,
                         exclude_pvs=None):
        """
        restore named position for instrument
        """
        inst = self.get_instrument(instname)
        if inst is None:
            raise ScanDBException('restore_postion needs valid instrument')

        posname = posname.strip()
        pos  = self.get_position(instname, posname)
        if pos is None:
            raise ScanDBException(
                "restore_postion  position '%s' not found" % posname)

        if exclude_pvs is None:
            exclude_pvs = []

        pv_vals = []
        for row in self.scandb.get_rows('position_pv', where={'position_id': pos.id}):
            if row.pv_id not in self.pvmap:
                self.make_pvmap()
            pvname = self.pvmap[row.pv_id]
            if pvname not in exclude_pvs:
                val = row.value
                try:
                    val = float(val)
                except ValueError:
                    pass
                pv_vals.append((epics.get_pv(pvname), val))

        time.sleep(0.01)
        # put values without waiting
        for thispv, val in pv_vals:
            if not thispv.connected:
                thispv.wait_for_connection(timeout=timeout)
            try:
                thispv.put(val)
            except:
                pass

        if wait:
            for thispv, val in pv_vals:
                try:
                    thispv.put(val, wait=True)
                except:
                    pass
