#!/usr/bin/env python
"""
function:  create_scandb
"""
import time
from datetime import datetime
import logging

from .simpledb import SimpleDB

from sqlalchemy import (MetaData, create_engine, text, Table, Column,
                        ColumnDefault, ForeignKey, Integer, Float, String,
                        Text, DateTime, UniqueConstraint)

from sqlalchemy.orm import Session
from sqlalchemy.dialects import postgresql

from sqlalchemy_utils import database_exists, create_database


## status states for commands
CMD_STATUS = ('unknown', 'requested', 'canceled', 'starting', 'running',
               'aborting', 'stopping', 'aborted', 'finished')

PV_TYPES = (('numeric', 'Numeric Value'),
            ('enum',  'Enumeration Value'),
            ('string',  'String Value'),
            ('motor', 'Motor Value') )

def hasdb(dbname, create=False, server='postgresql',
             user='', password='', host='', port=5432):
    """
    return whether a database existsin the postgresql server,
    optionally creating (but leaving it empty) said database.
    """
    conn_str= f'{server}://{user}:{password}@{host}:{int(port)}/{dbname}'
    engine = create_engine(conn_str)
    if create and not database_exists(engine.url):
        create_database(engine.url)
    return database_exists(engine.url)

def IntCol(name, **kws):
    return Column(name, Integer, **kws)

def ArrayCol(name,  server='postgresql', **kws):
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

def create_scandb(dbname, server='postgresql', create=True,
                  user='', password='',  host='', port=5432, **kws):
    """Create a ScanDB:

    arguments:
    ---------
    dbname    name of database

    options:
    --------
    server    type of database server (postgresql only at the moment)
    host      host serving database
    port      port number for database
    user      user name for database
    password  password for database
    """

    conn = {'user':user, 'password': password,
            'server': server, 'host': host, 'port':port}

    if hasdb(dbname, create=False, **conn):
        return

    if not hasdb(dbname, create=True, **conn):
        raise ValueError(f"could not create database '{dbname}'")

    db = SimpleDB(dbname, **conn)
    engine = db.engine
    metadata = db.metadata

    info = Table('info', metadata,
                 Column('key', Text, primary_key=True, unique=True),
                 StrCol('notes'),
                 StrCol('value'),
                 Column('modify_time', DateTime, default=datetime.now),
                 Column('create_time', DateTime, default=datetime.now),
                 IntCol('display_order')           )

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
    slewpos = NamedTable('slewscanpositioners', metadata, with_use=True,
                         cols=[StrCol('drivepv', size=128),
                               StrCol('readpv',  size=128),
                               StrCol('extrapvs'),
                               PointerCol('config'),
                               ])

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
                            IntCol('run_order', default=1),
                            Column('request_time', DateTime,
                                   default=datetime.now),
                            Column('start_time',    DateTime),
                            Column('modify_time',   DateTime,
                                   default=datetime.now),
                            StrCol('output_value'),
                            StrCol('output_file')])

    pvtype = NamedTable('pvtype', metadata)
    pv     = NamedTable('pv', metadata, cols=[PointerCol('pvtype')])

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

    # instruments
    instrument = NamedTable('instrument', metadata, name_unique=True,
                            cols=[IntCol('show', default=1),
                                  IntCol('display_order', default=0)])

    position  = NamedTable('position', metadata, name_unique=False,
                           cols=[Column('modify_time', DateTime),
                                 StrCol('image'),
                                 PointerCol('instrument'),
                                 UniqueConstraint('name', 'instrument_id', name='pos_inst_name')])


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

    metadata.create_all(bind=engine)
    time.sleep(0.5)

    db = SimpleDB(dbname, **conn)

    # add some initial data:
    for name in CMD_STATUS:
        db.insert('status', name=name)

    for name, notes in PV_TYPES:
        db.insert('pvtype', name=name, notes=notes)

    for key, value in (("version", "3.0"),
                       ("user_name", ""),
                       ("experiment_id",  ""),
                       ("user_folder",    ""),
                       ("request_abort", "0"),
                       ("request_pause", "0"),
                       ("request_resume", "0"),
                       ("request_killall", "0"),
                       ("request_shutdown", "0") ):
        db.set_info(key, value)

    fnow = ColumnDefault(datetime.now)
    for tname in ('info', 'messages', 'commands', 'position','scandefs',
                  'scandata', 'slewscanstatus', 'scandetectorconfig',
                  'commands'):
        db.tables[tname].columns['modify_time'].onupdate =  fnow
        db.tables[tname].columns['modify_time'].default =  fnow

    for tname, cname in (('info', 'create_time'),
                         ('commands', 'request_time'),
                         ('scandefs', 'last_used_time')):
        db.tables[tname].columns[cname].default = fnow
    print(f"Created database for epicsscan: '{dbname}'")
    return
