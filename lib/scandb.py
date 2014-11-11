#!/usr/bin/env python
"""
SQLAlchemy wrapping of scan database

Main Class for full Database:  ScanDB
"""
import os
import sys
import json
import time
import atexit
from socket import gethostname
from datetime import datetime

# from utils import backup_versions, save_backup
from sqlalchemy import MetaData, Table, select, and_, create_engine
from sqlalchemy.orm import sessionmaker, mapper

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import  NoResultFound

# needed for py2exe?
from sqlalchemy.dialects import sqlite, mysql, postgresql

from scandb_schema import get_dbengine, create_scandb, map_scandb

from scandb_schema import (Info, Status, PVs, MonitorValues, ExtraPVs,
                           Macros, Commands, ScanData, ScanPositioners,
                           ScanCounters, ScanDetectors, ScanDefs,
                           SlewScanPositioners, Positions, Position_PV,
                           Instruments, Instrument_PV,
                           Instrument_Precommands, Instrument_Postcommands)

from .utils import strip_quotes, normalize_pvname, asciikeys

class ScanDBException(Exception):
    """Scan Exception: General Errors"""
    def __init__(self, *args):
        Exception.__init__(self, *args)
        sys.excepthook(*sys.exc_info())


def json_encode(val):
    "simple wrapper around json.dumps"
    if val is None or isinstance(val, (str, unicode)):
        return val
    return  json.dumps(val)

def isotime2datetime(isotime):
    "convert isotime string to datetime object"
    sdate, stime = isotime.replace('T', ' ').split(' ')
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

def None_or_one(val, msg='Expected 1 or None result'):
    """expect result (as from query.all() to return
    either None or exactly one result
    """
    if len(val) == 1:
        return val[0]
    elif len(val) == 0:
        return None
    else:
        raise ScanDBException(msg)

class ScanDB(object):
    """
    Main Interface to Scans Database
    """
    def __init__(self, dbname=None, server='sqlite', create=False, **kws):
        self.dbname = dbname
        self.server = server
        self.tables = None
        self.engine = None
        self.session = None
        self.conn    = None
        self.metadata = None
        self.pvs = {}
        self.restoring_pvs = []
        if dbname is not None:
            self.connect(dbname, server=server, create=create, **kws)

    def create_newdb(self, dbname, connect=False, **kws):
        "create a new, empty database"
        create_scandb(dbname,  **kws)
        if connect:
            time.sleep(0.5)
            self.connect(dbname, backup=False, **kws)

    def set_path(self, fileroot=None):
        workdir = self.get_info('user_folder')
        workdir = workdir.replace('\\', '/').replace('//', '/')
        if workdir.startswith('/'): workdir = workdir[1:]
        if fileroot is None:
            fileroot = self.get_info('server_fileroot')
            fileroot = fileroot.replace('\\', '/').replace('//', '/')
        if workdir.startswith(fileroot):
            workdir = workdir[len(fileroot):]

        fullpath = os.path.join(fileroot, workdir)
        fullpath = fullpath.replace('\\', '/').replace('//', '/')
        try:
            os.chdir(fullpath)
            print("ScanDB: Working directory %s " % fullpath)
        except:
            pass
        finally:
            self.set_info('server_fileroot',  fileroot)
            self.set_info('user_folder',  workdir)
        time.sleep(0.1)

    def isScanDB(self, dbname, server='sqlite',
                 user='', password='', host='', port=None):
        """test if a file is a valid scan database:
        must be a sqlite db file, with tables named
        'postioners', 'detectors', and 'scans'
        """
        if server == 'sqlite':
            if not os.path.exists(dbname):
                return False
        else:
            if port is None:
                if server.startswith('my'): port = 3306
                if server.startswith('p'):  port = 5432
            #conn = "%s://%s:%s@%s:%i/%s"
            #try:
            #    _db = create_engine(conn % (server, user, password,
            #                                host, port, dbname))
            #except:
            #   return False

        _tables = ('info', 'status', 'commands', 'pvs', 'scandefs')
        engine = get_dbengine(dbname, server=server, create=False,
                              user=user, password=password,
                              host=host, port=port)
        try:
            meta = MetaData(engine)
            meta.reflect()
        except:
            engine, meta = None, None
            return False

        allfound = False
        if all([t in meta.tables for t in _tables]):
            keys = [row.keyname for row in
                    meta.tables['info'].select().execute().fetchall()]
            allfound = 'version' in keys and 'experiment_id' in keys
        if allfound:
            self.engine = engine
            self.dbname = dbname
            self.metadata = meta
        return allfound

    def connect(self, dbname, server='sqlite', create=False,
                user='', password='', host='', port=None, **kws):
        "connect to an existing database"
        creds = dict(user=user, password=password, host=host,
                     port=port, server=server)

        self.dbname = dbname
        if not self.isScanDB(dbname,  **creds) and create:
            engine, meta = create_scandb(dbname, create=True, **creds)
            self.engine = engine
            self.metadata = meta
            self.metadata.reflect()

        if self.engine is None:
            raise ValueError("Cannot use '%s' as a Scan Database!" % dbname)

        self.conn   = self.engine.connect()
        self.session = sessionmaker(bind=self.engine, autocommit=True)()

        tabs, classes, mapprops, mapkeys = map_scandb(self.metadata)
        self.tables, self.classes = tabs, classes
        self.mapprops, self.mapkeys = mapprops, mapkeys

        self.status_codes = {}
        for row in self.getall('status'):
            self.status_codes[row.name] = row.id
        atexit.register(self.close)

    def read_station_config(self, config):
        """convert station config to db entries
        DEPRECATED - kept for compatibility only"""

        for key, val in config.setup.items():
            self.set_info(key, val)

        for key, val in config.xafs.items():
            self.set_info(key, val)

        for key, val in config.slewscan.items():
            self.set_info('slew_%s' % key, val)

        for name, pvname in config.extrapvs.items():
            pvname = normalize_pvname(pvname)
            this = self.get_extrapv(name)
            if this is None:
                self.add_extrapv(name, pvname)
            else:
                self.update_where('extrapvs', {'name': name},
                                  {'pvname': pvname})

        for name, data in config.detectors.items():
            thisdet  = self.get_detector(name)
            pvname, opts = data
            pvname = normalize_pvname(pvname)
            dkind = strip_quotes(opts.pop('kind'))
            opts = json_encode(opts)
            if thisdet is None:
                self.add_detector(name, pvname, kind=dkind, options=opts)
            else:
                self.update_where('scandetectors', {'name': name},
                                  {'pvname': pvname, 'kind': dkind,
                                   'options': opts})

        for name, data in config.positioners.items():
            thispos  = self.get_positioner(name)
            drivepv = normalize_pvname(data[0])
            readpv = normalize_pvname(data[1])
            if thispos is None:
                self.add_positioner(name, drivepv, readpv=readpv)
            else:
                self.update_where('scanpositioners', {'name': name},
                                  {'drivepv': drivepv, 'readpv': readpv})

        for name, data in config.slewscan_positioners.items():
            thispos  = self.get_slewpositioner(name)
            drivepv = normalize_pvname(data[0])
            readpv = normalize_pvname(data[1])
            if thispos is None:
                self.add_slewpositioner(name, drivepv, readpv=readpv)
            else:
                self.update_where('slewscanpositioners', {'name': name},
                                  {'drivepv': drivepv, 'readpv': readpv})

        for name, pvname in config.counters.items():
            pvname = normalize_pvname(pvname)
            this  = self.get_counter(name)
            if this is None:
                self.add_counter(name, pvname)
            else:
                self.update_where('scancounters', {'name': name},
                                  {'pvname': pvname})

    def commit(self):
        "commit session state"
        try:
            return self.session.commit()
        except:
            pass

    def close(self):
        "close session"
        try:
            self.set_hostpid(clear=True)
            self.session.flush()
            self.session.close()
            self.conn.close()
        except:
            pass

    def query(self, *args, **kws):
        "generic query"
        try:
            # self.session.autoflush = False
            return self.session.query(*args, **kws)
        except sqlalchemy.StatementError():
            time.sleep(0.01)
            self.session.rollback()
            time.sleep(0.01)
            try:
                return self.session.query(*args, **kws)
            except:
                self.session.rollback()
                return None
        # self.session.autoflush = True

    def _get_table(self, tablename):
        return self.get_table(tablename)

    def get_table(self, tablename):
        "return (self.tables, self.classes) for a table name"
        cls   = self.classes[tablename]
        table = self.tables[tablename]
        attr  = self.mapkeys[tablename]
        props = self.mapprops[tablename]
        if not hasattr(cls , attr):
            mapper(cls, table, props)
        return cls, table

    def getall(self, tablename, orderby=None):
        """return objects for all rows from a named table
         orderby   to order results
        """
        cls, table = self.get_table(tablename)
        columns = table.c.keys()
        q = self.query(cls)
        if orderby is not None and hasattr(cls, orderby):
            q = q.order_by(getattr(cls, orderby))
        return q.all()

    def select(self, tablename, orderby=None, **kws):
        """return data for all rows from a named table,
         orderby   to order results
         key=val   to get entries matching a column (where clause)
        """
        cls, table = self.get_table(tablename)
        columns = table.c.keys()
        q = table.select()
        for key, val in kws.items():
            if key in columns:
                q = q.where(getattr(table.c, key)==val)
        if orderby is not None and hasattr(cls, orderby):
            q = q.order_by(getattr(cls, orderby))
        return q.execute().fetchall()

    def get_info(self, key=None, default=None,
                 as_int=False, as_bool=False, with_notes=False):
        """get a value for an entry in the info table,
        if this key doesn't exist, it will be added with the default
        value and the default value will be returned.

        use as_int, as_bool and with_notes to alter the output.
        """
        errmsg = "get_info expected 1 or None value for name='%s'"
        cls, table = self.get_table('info')
        if key is None:
            return self.query(table).all()

        vals = self.query(cls).filter(cls.keyname==key).all()
        thisrow = None_or_one(vals, errmsg % key)
        if thisrow is None:
            out = default
            data = {'keyname': key, 'value': default}
            table.insert().execute(**data)
        else:
            out = thisrow.value

        if as_int:
            if out is None: out = 0
            out = int(float(out))
        if as_bool:
            if out is None: out = 0
            out = bool(int(out))
        if with_notes:
            notes = ''
            if thisrow is not None: notes = thisrow.notes
            out = out, notes
        return out

    def set_info(self, key, value, notes=None):
        """set key / value in the info table"""
        cls, table = self.get_table('info')
        vals  = self.query(table).filter(cls.keyname==key).all()
        data = {'keyname': key, 'value': value}
        if notes is not None:
            data['notes'] = notes
        if len(vals) < 1:
            table = table.insert()
        else:
            table = table.update(whereclause="keyname='%s'" % key)
        table.execute(**data)

    def clobber_all_info(self):
        """dangerous!!!! clear all info --
        can leave a DB completely broken and unusable
        useful when going to repopulate db anyway"""
        cls, table = self.get_table('info')
        self.session.execute(table.delete().where(table.c.keyname!=''))

    def set_hostpid(self, clear=False):
        """set hostname and process ID, as on intial set up"""
        name, pid = '', '0'
        if not clear:
            name, pid = gethostname(), str(os.getpid())
        self.set_info('host_name', name)
        self.set_info('process_id', pid)

    def check_hostpid(self):
        """check whether hostname and process ID match current config"""
        if self.server != 'sqlite':
            return True
        db_host_name = self.get_info('host_name', default='')
        db_process_id  = self.get_info('process_id', default='0')
        return ((db_host_name == '' and db_process_id == '0') or
                (db_host_name == gethostname() and
                 db_process_id == str(os.getpid())))

    def __addRow(self, table, argnames, argvals, **kws):
        """add generic row"""
        table = table()
        for name, val in zip(argnames, argvals):
            setattr(table, name, val)
        for key, val in kws.items():
            if key == 'attributes':
                val = json_encode(val)
            setattr(table, key, val)
        try:
            self.session.add(table)
            # self.session.commit()
        except IntegrityError, msg:
            self.session.rollback()
            raise Warning('Could not add data to table %s\n%s' % (table, msg))

        return table

    def _get_foreign_keyid(self, table, value, name='name',
                           keyid='id', default=None):
        """generalized lookup for foreign key
        arguments
        ---------
           table: a valid table class, as mapped by mapper.
           value: can be one of the following table instance:
              keyid is returned string
        'name' attribute (or set which attribute with 'name' arg)
        a valid id
        """
        if isinstance(value, table):
            return getattr(table, keyid)
        else:
            if isinstance(value, (str, unicode)):
                xfilter = getattr(table, name)
            elif isinstance(value, int):
                xfilter = getattr(table, keyid)
            else:
                return default
            try:
                query = self.query(table).filter(
                    xfilter==value)
                return getattr(query.one(), keyid)
            except (IntegrityError, NoResultFound):
                return default

        return default

    def update_where(self, table, where, vals):
        """update a named table with dicts for 'where' and 'vals'"""
        if table in self.tables:
            table = self.tables[table]
        constraints = ["%s=%s" % (str(k), repr(v)) for k, v in where.items()]
        whereclause = ' AND '.join(constraints)
        table.update(whereclause=whereclause).execute(**vals)
        self.commit()


    def getrow(self, table, name, one_or_none=False):
        """return named row from a table"""
        cls, table = self.get_table(table)
        if table is None: return None
        if isinstance(name, Table):
            return name
        out = self.query(table).filter(cls.name==name).all()
        if one_or_none:
            return None_or_one(out, 'expected 1 or None from table %s' % table)
        return out


    # Scan Definitions
    def get_scandef(self, name):
        """return scandef by name"""
        return self.getrow('scandefs', name, one_or_none=True)

    def rename_scandef(self, scanid, name):
        cls, table = self.get_table('scandefs')
        table.update(whereclause="id='%d'" % scanid).execute(name=name)

        # self.update_where('scandefs', {'id': scanid},  {'name': name})


    def del_scandef(self, name=None, scanid=None):
        """delete scan defn by name"""
        cls, table = self.get_table('scandefs')
        if name is not None:
            self.session.execute(table.delete().where(table.c.name==name))
        elif scanid is not None:
            self.session.execute(table.delete().where(table.c.id==scanid))

    def add_scandef(self, name, text='', notes='', type='', **kws):
        """add scan"""
        cls, table = self.get_table('scandefs')
        kws.update({'notes': notes, 'text': text, 'type': type})

        name = name.strip()
        row = self.__addRow(cls, ('name',), (name,), **kws)
        self.session.add(row)
        return row

    def get_scandict(self, scan):
        """return dictionary of scan configuration for a named scan"""
        sobj = self.get_scandef(scan)
        if sobj is None:
            raise ScanDBException('get_scandict needs valid scan name')
        return json.loads(sobj.text, object_hook=asciikeys)

    # macros
    def get_macro(self, name):
        """return macro by name"""
        return self.getrow('macros', name, one_or_none=True)


    def add_macro(self, name, text, arguments='',
                  output='', notes='', **kws):
        """add macro"""
        cls, table = self.get_table('macros')
        name = name.strip()
        kws.update({'notes': notes, 'text': text,
                    'arguments': arguments})
        row = self.__addRow(cls, ('name',), (name,), **kws)
        self.session.add(row)
        return row

    # scan data
    def get_scandata(self, **kws):
        return self.getall('scandata', orderby='id', **kws)

    def add_scandata(self, name, value, notes='', pvname='', **kws):
        cls, table = self.get_table('scandata')
        kws.update({'notes': notes, 'pvname': pvname})
        name = name.strip()
        row = self.__addRow(cls, ('name', 'data'), (name, value), **kws)
        self.session.add(row)
        return row

    def set_scandata(self, name, value,  **kws):
        cls, tab = self.get_table('scandata')
        where = "name='%s'" % name
        tab.update().where(whereclause=where
                           ).values({tab.c.data: value}).execute()

    def append_scandata(self, name, val):
        cls, tab = self.get_table('scandata')
        where = "name='%s'" % name
        n = len(tab.select(whereclause=where
                           ).execute().fetchone().data)
        tab.update().where(whereclause=where
                           ).values({tab.c.data[n]: val}).execute()

    def clear_scandata(self, **kws):
        cls, table = self.get_table('scandata')
        a = self.get_scandata()
        if len(a) < 0:
            return
        self.session.execute(table.delete().where(table.c.id != 0))

    # positioners
    def get_positioners(self, **kws):
        return self.getall('scanpositioners', orderby='id', **kws)

    def get_slewpositioners(self, **kws):
        return self.getall('slewscanpositioners', orderby='id', **kws)

    def get_detectors(self, **kws):
        return self.getall('scandetectors', orderby='id', **kws)

    def get_positioner(self, name):
        """return positioner by name"""
        return self.getrow('scanpositioners', name, one_or_none=True)

    def del_slewpositioner(self, name):
        """delete slewscan positioner by name"""
        cls, table = self.get_table('slewscanpositioners')
        self.session.execute(table.delete().where(table.c.name==name))

    def del_positioner(self, name):
        """delete positioner by name"""
        cls, table = self.get_table('scanpositioners')

        self.session.execute(table.delete().where(table.c.name==name))

    def add_positioner(self, name, drivepv, readpv=None, notes='',
                       extrapvs=None, **kws):
        """add positioner"""
        cls, table = self.get_table('scanpositioners')
        name = name.strip()
        drivepv = normalize_pvname(drivepv)
        if readpv is not None:
            readpv = normalize_pvname(readpv)
        epvlist = []
        if extrapvs is not None:
            epvlist = [normalize_pvname(p) for p in extrapvs]
        kws.update({'notes': notes, 'drivepv': drivepv,
                    'readpv': readpv, 'extrapvs':json.dumps(epvlist)})

        row = self.__addRow(cls, ('name',), (name,), **kws)
        self.session.add(row)
        self.add_pv(drivepv, notes=name)
        if readpv is not None:
            self.add_pv(readpv, notes="%s readback" % name)
        for epv in epvlist:
            self.add_pv(epv)
        return row

    def get_slewpositioner(self, name):
        """return slewscan positioner by name"""
        return self.getrow('slewscanpositioners', name, one_or_none=True)

    def add_slewpositioner(self, name, drivepv, readpv=None, notes='',
                           extrapvs=None, **kws):
        """add slewscan positioner"""
        cls, table = self.get_table('slewscanpositioners')
        name = name.strip()
        drivepv = normalize_pvname(drivepv)
        if readpv is not None:
            readpv = normalize_pvname(readpv)
        epvlist = []
        if extrapvs is not None:
            epvlist = [normalize_pvname(p) for p in extrapvs]
        kws.update({'notes': notes, 'drivepv': drivepv,
                    'readpv': readpv, 'extrapvs':json.dumps(evpvlist)})

        row = self.__addRow(cls, ('name',), (name,), **kws)
        self.session.add(row)
        self.add_pv(drivepv, notes=name)
        if readpv is not None:
            self.add_pv(readpv, notes="%s readback" % name)
        for epv in epvlist:
            self.add_pv(epv)
        return row

    # detectors
    def get_detector(self, name):
        """return detector by name"""
        return self.getrow('scandetectors', name, one_or_none=True)

    def del_detector(self, name):
        """delete detector by name"""
        cls, table = self.get_table('scandetectors')
        self.session.execute(table.delete().where(table.c.name==name))

    def add_detector(self, name, pvname, kind='', options='', **kws):
        """add detector"""
        cls, table = self.get_table('scandetectors')
        name = name.strip()
        pvname = normalize_pvname(pvname)
        kws.update({'pvname': pvname,
                    'kind': kind, 'options': options})
        row = self.__addRow(cls, ('name',), (name,), **kws)
        self.session.add(row)
        return row

    # counters -- simple, non-triggered PVs to add to detectors
    def get_counters(self, **kws):
        return self.getall('scancounters', orderby='id', **kws)

    def get_counter(self, name):
        """return counter by name"""
        return self.getrow('scancounters', name, one_or_none=True)

    def del_counter(self, name):
        """delete counter by name"""
        cls, table = self.get_table('scancounters')
        self.session.execute(table.delete().where(table.c.name==name))

    def add_counter(self, name, pvname, **kws):
        """add counter (non-triggered detector)"""
        cls, table = self.get_table('scancounters')
        pvname = normalize_pvname(pvname)
        name = name.strip()
        kws.update({'pvname': pvname})
        row = self.__addRow(cls, ('name',), (name,), **kws)
        self.session.add(row)
        self.add_pv(pvname, notes=name)
        return row

    # extra pvs: pvs recorded at breakpoints of scans
    def get_extrapvs(self, **kws):
        return self.getall('extrapvs', orderby='id', **kws)

    def get_extrapv(self, name):
        """return extrapv by name"""
        return self.getrow('extrapvs', name, one_or_none=True)

    def del_extrapv(self, name):
        """delete extrapv by name"""
        cls, table = self.get_table('extrapvs')
        self.session.execute(table.delete().where(table.c.name==name))

    def add_extrapv(self, name, pvname, use=True, **kws):
        """add extra pv (recorded at breakpoints in scans"""
        cls, table = self.get_table('extrapvs')
        name = name.strip()
        pvname = normalize_pvname(pvname)
        kws.update({'pvname': pvname, 'use': int(use)})
        row = self.__addRow(cls, ('name',), (name,), **kws)
        self.session.add(row)
        self.add_pv(pvname, notes=name)
        return row

    # add PV to list of PVs
    def add_pv(self, name, notes='', monitor=False):
        """add pv to PV table if not already there """
        if len(name) < 2:
            return
        name = normalize_pvname(name)
        cls, table = self.get_table('pvs')
        vals  = self.query(table).filter(cls.name == name).all()
        ismon = {False:0, True:1}[monitor]
        if len(vals) < 1:
            table.insert().execute(name=name, notes=notes, is_monitor=ismon)
        elif notes is not '':
            where = "name='%s'" % name
            table.update(whereclause=where).execute(notes=notes,
                                                    is_monitor=ismon)
        thispv = self.query(table).filter(cls.name == name).one()
        if name not in self.pvs:
            self.pvs[name] = thispv.id
        return thispv

    def record_monitorpv(self, pvname, value, commit=False):
        """save value for monitor pvs"""
        pvname = normalize_pvname(pvname)
        if pvname not in self.pvs:
            pv = self.add_pv(pvname, monitor=True)
            self.pvs[pvname] = pv.id

        cls, table = self.get_table('monitorvalues')
        mval = cls()
        mval.pv_id = self.pvs[pvname]
        mval.value = value
        self.session.add(mval)

    def get_monitorvalues(self, pvname, start_date=None, end_date=None):
        """get (value, time) pairs for a monitorpvs given a time range
        """
        pvname = normalize_pvname(pvname)
        if pvname not in self.pvs:
            pv = self.add_monitorpv(pvname)
            self.pvs[pvname] = pv.id

        cls, valtab = self.get_table('monitorvalues')

        query = select([valtab.c.value, valtab.c.time],
                       valtab.c.monitorpvs_id==self.pvs[pvname])
        if start_date is not None:
            query = query.where(valtab.c.time >= start_date)
        if end_date is not None:
            query = query.where(valtab.c.time <= end_date)

        return query.execute().fetchall()

    # commands -- a more complex interface
    def get_commands(self, status=None, **kws):
        """return command by status"""
        cls, table = self.get_table('commands')
        q = self.query(cls).order_by(cls.id)
        if status not in self.status_codes:
            return q.all()
        return q.filter(cls.status_id==self.status_codes[status]).all()

    # commands -- a more complex interface
    def get_mostrecent_command(self):
        """return command by status"""
        cls, table = self.get_table('commands')
        q = self.query(cls).order_by(cls.request_time)
        return q.all()[-1]

    def add_command(self, command, arguments='',output_value='',
                    output_file='', notes='', nrepeat=1, **kws):
        """add command"""
        cls, table = self.get_table('commands')
        statid = self.status_codes.get('requested', 1)

        kws.update({'arguments': arguments,
                    'output_file': output_file,
                    'output_value': output_value,
                    'notes': notes,
                    'nrepeat': nrepeat,
                    'status_id': statid})

        row = self.__addRow(cls, ('command',), (command,), **kws)
        self.session.add(row)
        return row

    def set_command_status(self, cmdid, status):
        """set the status of a command (by id)"""
        cls, table = self.get_table('commands')
        if status not in self.status_codes:
            status = 'unknown'
        statid = self.status_codes[status]
        table.update(whereclause="id='%i'" % cmdid).execute(status_id=statid)
        # print 'Commands Table update status to ' , statid, cmdid
        self.commit()
        # print 'After status update:'
        # print self.get_commands('requested')


    def set_command_output(self, cmdid, value=None):
        """set the status of a command (by id)"""
        cls, table = self.get_table('commands')
        table.update(whereclause="id='%i'" % cmdid).execute(output_value=repr(value))
        self.commit()

    def cancel_command(self, id):
        """cancel command"""
        self.set_command_status(id, 'canceled')


if __name__ == '__main__':
    dbname = 'Test.sdb'
    create_scandb(dbname)
    print '''%s  created and initialized.''' % dbname
