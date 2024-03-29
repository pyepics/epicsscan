#!/usr/bin/env python
"""
SQLAlchemy wrapping of scan database

Main Class for full Database:  ScanDB
"""
import os
import time
from datetime import datetime
import logging

# from utils import backup_versions, save_backup


from sqlalchemy import (MetaData, and_, create_engine, text, func,
                        Table, Column, ColumnDefault, ForeignKey,
                        Integer, Float, String, Text, DateTime,
                        UniqueConstraint)

from sqlalchemy.orm import sessionmaker, mapper, relationship
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.pool import SingletonThreadPool

# needed for py2exe?
from sqlalchemy.dialects import sqlite, mysql, postgresql

## status states for commands
CMD_STATUS = ('unknown', 'requested', 'canceled', 'starting', 'running',
               'aborting', 'stopping', 'aborted', 'finished')

PV_TYPES = (('numeric', 'Numeric Value'),
            ('enum',  'Enumeration Value'),
            ('string',  'String Value'),
            ('motor', 'Motor Value') )

def hasdb_pg(dbname, create=False,
             user='', password='', host='', port=5432):
    """
    return whether a database is known to the postgresql server,
    optionally creating (but leaving it empty) said database.
    """

    dbname = dbname.lower()
    conn_str= 'postgresql://%s:%s@%s:%i/%s'
    query = "select datname from pg_database"
    port = int(port)
    engine = create_engine(conn_str % (user, password,
                                       host, port, 'postgres'))
    conn = engine.connect()
    conn.execution_options(autocommit=True)
    conn.execute("commit")
    dbs = [i[0] for i in conn.execute(query).fetchall()]
    if create and dbname not in dbs:
        conn.execute("create database %s" % dbname)
        conn.execute("commit")
    dbs = [i[0] for i in conn.execute(query).fetchall()]
    conn.close()
    return dbname in dbs

def get_dbengine(dbname, server='sqlite', create=False,
                user='', password='',  host='', port=None):
    """create databse engine"""
    if server == 'sqlite':
        return create_engine('sqlite:///%s' % (dbname),
                             poolclass=SingletonThreadPool)
    elif server == 'mysql':
        conn_str= 'mysql+mysqldb://%s:%s@%s:%i/%s'
        if port is None:
            port = 3306
        port = int(port)
        return create_engine(conn_str % (user, password, host, port, dbname))

    elif server.startswith('p'):
        conn_str= 'postgresql://%s:%s@%s:%i/%s'
        if port is None:
            port = 5432
        port = int(port)
        hasdb = hasdb_pg(dbname, create=create, user=user, password=password,
                         host=host, port=port)
        return create_engine(conn_str % (user, password, host, port, dbname))

def IntCol(name, **kws):
    return Column(name, Integer, **kws)

def ArrayCol(name,  server='sqlite', **kws):
    ArrayType = Text
    if server.startswith('post'):
        ArrayType = postgresql.ARRAY(Float)
    return Column(name, ArrayType, **kws)

def StrCol(name, size=None, **kws):
    val = Text
    if size is not None:
        val = String(size)
    return Column(name, val, **kws)

def PointerCol(name, other=None, keyid='id', **kws):
    if other is None:
        other = name
    return Column("%s_%s" % (name, keyid), None,
                  ForeignKey('%s.%s' % (other, keyid)), **kws)

def NamedTable(tablename, metadata, keyid='id', nameid='name', name_unique=True,
               name=True, notes=True, with_pv=False, with_use=False, cols=None):
    args  = [Column(keyid, Integer, primary_key=True)]
    if name:
        args.append(StrCol(nameid, size=512, nullable=False, unique=name_unique))
    if notes:
        args.append(StrCol('notes'))
    if with_pv:
        args.append(StrCol('pvname', size=128))
    if with_use:
        args.append(IntCol('use', default=1))
    if cols is not None:
        args.extend(cols)
    return Table(tablename, metadata, *args)

class _BaseTable(object):
    "generic class to encapsulate SQLAlchemy table"
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%s' % getattr(self, 'name', 'UNNAMED'),
                  'id=%s' % repr(getattr(self, 'id', 'NOID'))]
        return "<%s(%s)>" % (name, ', '.join(fields))

class Info(_BaseTable):
    "general information table (versions, etc)"
    key, value, notes, modify_time = [None]*4

    def __repr__(self):
        name = self.__class__.__name__
        return "<%s(%s='%s')>" % (name, self.key, str(self.value))

class Messages(_BaseTable):
    "messages table"
    text = None

class Config(_BaseTable):
    "Miscelleneous Configuration table"
    name, notes = None, None

class Status(_BaseTable):
    "status table"
    name, notes = None, None

class ScanPositioners(_BaseTable):
    "positioners table"
    name, notes, drivepv, readpv, extrapvs, use = [None]*6

class SlewScanPositioners(_BaseTable):
    "positioners table for slew scans"
    name, notes, drivepv, readpv, extrapvs, use = [None]*6

class ScanCounters(_BaseTable):
    "counters table"
    name, notes, pvname, use = [None]*4

class ScanDetectors(_BaseTable):
    "detectors table"
    name, notes, pvname, kind, options, use = [None]*6

class ScanDetectorConfig(_BaseTable):
    "detector calibration, masks, and other config table"
    name, notes, kind, text, modify_time =  [None]*5

class ExtraPVs(_BaseTable):
    "extra pvs in scan table"
    name, notes, pvname, use = [None]*4

class ScanDefs(_BaseTable):
    "scandefs table"
    name, notes, text, type, modify_time, last_used_time = [None]*6

class PV(_BaseTable):
    "pv table"
    name, notes, is_monitor = None, None, None

class PVType(_BaseTable):
    "pvtype table"
    name, notes = None, None

class MonitorValues(_BaseTable):
    "monitor PV Values table"
    id, modify_time, value = None, None, None

class Macros(_BaseTable):
    "table of pre-defined macros"
    name, notes, arguments, text, output = None, None, None, None, None

class Commands(_BaseTable):
    "commands-to-be-executed table"
    command, notes, arguments = None, None, None
    status, status_name, run_order = None, None, None
    request_time, start_time, modify_time = None, None, None
    output_value, output_file, nrepeat = None, None, None
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%s' % getattr(self, 'command', 'Unknown'),
                  'id=%s' % getattr(self, 'id', 'NOID')]
        return "<%s(%s)>" % (name, ', '.join(fields))

class ScanData(_BaseTable):
    notes, pvname, data, units, breakpoints, modify_time = [None]*6

class SlewScanStatus(_BaseTable):
    text, modify_time = None, None

class Instrument(_BaseTable):
    "instrument table"
    name, notes = None, None

class Common_Commands(_BaseTable):
    "common table"
    name, notes, args, display_order, show = None, None, None, None, None

class Position(_BaseTable):
    "position table"
    pv, date, name, notes, image = None, None, None, None, None
    instrument, instrument_id = None, None

class Position_PV(_BaseTable):
    "position-pv join table"
    name, notes, pv, value = None, None, None, None
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%s=%s' % (getattr(self, 'pv_id', '?'),
                             getattr(self, 'value', '?'))]
        return "<%s(%s)>" % (name, ', '.join(fields))

class Instrument_PV(_BaseTable):
    "intruemnt-pv join table"
    name, id, instrument, pv, display_order = None, None, None, None, None
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%s/%s' % (getattr(getattr(self, 'instrument', '?'),'name','?'),
                             getattr(getattr(self, 'pv', '?'), 'name', '?'))]
        return "<%s(%s)>" % (name, ', '.join(fields))

class Instrument_Precommands(_BaseTable):
    "instrument precommand table"
    name, notes = None, None

class Instrument_Postcommands(_BaseTable):
    "instrument postcommand table"
    name, notes = None, None

def create_scandb(dbname, server='sqlite', create=True, **kws):
    """Create a ScanDB:

    arguments:
    ---------
    dbname    name of database (filename for sqlite server)

    options:
    --------
    server    type of database server ([sqlite], mysql, postgresql)
    host      host serving database   (mysql,postgresql only)
    port      port number for database (mysql,postgresql only)
    user      user name for database (mysql,postgresql only)
    password  password for database (mysql,postgresql only)
    """

    engine  = get_dbengine(dbname, server=server, create=create, **kws)
    metadata =  MetaData(engine)
    info = Table('info', metadata,
                 Column('key', Text, primary_key=True, unique=True),
                 StrCol('notes'),
                 StrCol('value'),
                 Column('modify_time', DateTime, default=datetime.now),
                 Column('create_time', DateTime, default=datetime.now))

    messages = Table('messages', metadata,
                 Column('id', Integer, primary_key=True),
                 StrCol('text'),
                 Column('modify_time', DateTime, default=datetime.now))

    common_commands = NamedTable('common_commands', metadata,
                                 cols=[StrCol('args'),
                                       IntCol('show', default=1),
                                       IntCol('display_order', default=1)])

    config = NamedTable('config', metadata)
    status = NamedTable('status', metadata)
    slewpos    = NamedTable('slewscanpositioners', metadata, with_use=True,
                            cols=[StrCol('drivepv', size=128),
                                  StrCol('readpv',  size=128),
                                  StrCol('extrapvs') ])

    pos    = NamedTable('scanpositioners', metadata, with_use=True,
                        cols=[StrCol('drivepv', size=128),
                              StrCol('readpv',  size=128),
                              StrCol('extrapvs') ])

    cnts   = NamedTable('scancounters', metadata, with_pv=True, with_use=True)
    det    = NamedTable('scandetectors', metadata, with_pv=True, with_use=True,
                        cols=[StrCol('kind',   size=128),
                              StrCol('options')])

    detconf = NamedTable('scandetectorconfig', metadata,
                         cols=[StrCol('kind', size=128),
                               StrCol('text'),
                               PointerCol('scandetectors'),
                               Column('modify_time', DateTime, default=datetime.now),
                         ])

    scans = NamedTable('scandefs', metadata,
                       cols=[StrCol('text'),
                             StrCol('type'),
                             Column('modify_time', DateTime),
                             Column('last_used_time', DateTime)])

    extrapvs = NamedTable('extrapvs', metadata, with_pv=True, with_use=True)

    macros = NamedTable('macros', metadata,
                        cols=[StrCol('arguments'),
                              StrCol('text'),
                              StrCol('output')])

    cmds = NamedTable('commands', metadata, name=False,
                      cols=[StrCol('command'),
                            StrCol('arguments'),
                            PointerCol('status', default=1),
                            IntCol('nrepeat',  default=1),
                            IntCol('runy_order', default=1),
                            Column('request_time', DateTime,
                                   default=datetime.now),
                            Column('start_time',    DateTime),
                            Column('modify_time',   DateTime,
                                   default=datetime.now),
                            StrCol('output_value'),
                            StrCol('output_file')])

    pvtype = NamedTable('pvtype', metadata)
    pv     = NamedTable('pv', metadata,
                        cols=[PointerCol('pvtype'),
                              IntCol('is_monitor', default=0)])

    monvals = Table('monitorvalues', metadata,
                    IntCol('id', primary_key=True),
                    PointerCol('pv'),
                    StrCol('value'),
                    Column('modify_time', DateTime))

    scandata = NamedTable('scandata', metadata, with_pv=True,
                         cols = [PointerCol('commands'),
                                 ArrayCol('data', server=server),
                                 StrCol('units', default=''),
                                 StrCol('breakpoints', default=''),
                                 Column('modify_time', DateTime)])

    slewscanstatus = Table('slewscanstatus', metadata,
                           Column('id', Integer, primary_key=True),
                           StrCol('text'),
                           Column('modify_time', DateTime, default=datetime.now))


    instrument = NamedTable('instrument', metadata, name_unique=True,
                            cols=[IntCol('show', default=1),
                                  IntCol('display_order', default=0)])

    position  = NamedTable('position', metadata, name_unique=False,
                           cols=[Column('modify_time', DateTime),
                                 StrCol('image'),
                                 PointerCol('instrument'),
                                 UniqueConstraint('name', 'instrument_id', name='pos_inst_name')])


    instrument_precommand = NamedTable('instrument_precommands', metadata,
                                       cols=[IntCol('exec_order'),
                                             PointerCol('commands'),
                                             PointerCol('instrument')])

    instrument_postcommand = NamedTable('instrument_postcommands', metadata,
                                        cols=[IntCol('exec_order'),
                                              PointerCol('commands'),
                                              PointerCol('instrument')])

    instrument_pv = Table('instrument_pv', metadata,
                          IntCol('id', primary_key=True),
                          PointerCol('instrument'),
                          PointerCol('pv'),
                          IntCol('display_order', default=0))


    position_pv = Table('position_pv', metadata,
                        IntCol('id', primary_key=True),
                        StrCol('notes'),
                        PointerCol('position'),
                        PointerCol('pv'),
                        StrCol('value'))

    metadata.create_all()
    session = sessionmaker(bind=engine)()

    # add some initial data:
    scans.insert().execute(name='NULL', text='')

    for name in CMD_STATUS:
        status.insert().execute(name=name)

    for name, notes in PV_TYPES:
        pvtype.insert().execute(name=name, notes=notes)

    for key, value in (("version", "2.0"),
                       ("user_name", ""),
                       ("experiment_id",  ""),
                       ("user_folder",    ""),
                       ("request_abort", "0"),
                       ("request_pause", "0"),
                       ("request_resume", "0"),
                       ("request_killall", "0"),
                       ("request_shutdown", "0") ):
        info.insert().execute(key=key, value=value)
    session.commit()
    return engine, metadata

def map_scandb(metadata):
    """set up mapping of SQL metadata and classes
    returns two dictionaries, tables and classes
    each with entries
    tables:    {tablename: table instance}
    classes:   {tablename: table class}

    """
    tables = metadata.tables
    classes = {}
    map_props = {}
    keyattrs = {}
    for cls in (Info, Messages, Config, Status, PV, PVType, MonitorValues,
                Macros, ExtraPVs, Commands, ScanData, ScanPositioners,
                ScanCounters, ScanDetectors, ScanDetectorConfig, ScanDefs,
                SlewScanPositioners, SlewScanStatus, Common_Commands,
                Position, Position_PV, Instrument, Instrument_PV,
                Instrument_Precommands, Instrument_Postcommands):

        name = cls.__name__.lower()
        props = {}
        if name == 'commands':
            props = {'status': relationship(Status)}
        elif name == 'scandata':
            props = {'commands': relationship(Commands)}
        elif name == 'monitorvalues':
            props = {'pv': relationship(PV)}
        elif name == 'pvtype':
            props = {'pv': relationship(PV, backref='pvtype')}
        elif name == 'instrument':
            props = {'pv': relationship(PV,
                                         backref='instrument',
                                         secondary=tables['instrument_pv'])}
        elif name == 'position':
            props = {'instrument': relationship(Instrument,
                                                backref='position'),
                     'pv': relationship(Position_PV)}
        elif name == 'instrument_pv':
            props = {'pv': relationship(PV),
                     'instrument': relationship(Instrument)}
        elif name == 'position_pv':
            props = {'pv': relationship(PV)}
        elif name == 'instrument_precommands':
            props = {'instrument': relationship(Instrument,
                                                backref='precommands'),
                     'command': relationship(Commands)}
        elif name == 'instrument_postcommands':
            props = {'instrument': relationship(Instrument,
                                                backref='postcommands'),
                     'command': relationship(Commands)}
        mapper(cls, tables[name], properties=props)
        classes[name] = cls
        map_props[name] = props
        keyattrs[name] = 'name'

    keyattrs['info'] = 'key'
    keyattrs['commands'] = 'command'
    keyattrs['position_pv'] = 'id'
    keyattrs['instrument_pv'] = 'id'
    keyattrs['monitovalues'] = 'id'
    keyattrs['messages'] = 'id'
    keyattrs['slewscanstatus'] = 'id'

    # set onupdate and default constraints for several datetime columns
    # note use of ColumnDefault to wrap onpudate/default func
    fnow = ColumnDefault(datetime.now)

    for tname in ('info', 'messages', 'commands', 'position','scandefs',
                  'scandata', 'slewscanstatus', 'scandetectorconfig',
                  'monitorvalues', 'commands'):
        tables[tname].columns['modify_time'].onupdate =  fnow
        tables[tname].columns['modify_time'].default =  fnow

    for tname, cname in (('info', 'create_time'),
                         ('commands', 'request_time'),
                         ('scandefs', 'last_used_time')):
        tables[tname].columns[cname].default = fnow

    return tables, classes, map_props, keyattrs
