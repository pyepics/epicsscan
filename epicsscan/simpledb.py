#!/usr/bin/env python
"""
Simple database interface using SQLAlchemy 2.0
"""

import os
import time
import random
import logging
from datetime import datetime

from sqlalchemy import MetaData, create_engine, text, and_
from sqlalchemy.orm import Session
from sqlalchemy.sql.sqltypes import INTEGER

def get_credentials(credfile=None, envvar='ESCAN_CREDENTIALS', ):
    """look up credentials either from `credfile` (if not None)
    or from a file held in the supplied environment variable

    The file should be "basically yaml", but is parsed by hand.
    It should look like this:
dbname: my_escan_db
host:   host_machine_name_or_ip
server: postgresql
port:  5432
user:  db_user_name
password: db_user_password
    """
    conn = {'dbname': 'escandb', 'server': 'postgresql',
            'host': 'localhost',  'port': 5432,
            'user': '', 'password': '_invalid_password_'}
    if credfile is None:
        credfile = os.environ.get(envvar, None)
    if credfile is not None and os.path.exists(credfile):
        with open(credfile, 'r') as fh:
            lines = fh.readlines()
        for line in lines:
            if ':' in line:
                words = [x.strip() for x in line[:-1].split(':', 1)]
            elif '=' in line:
                words = [x.strip() for x in line[:-1].split('=', 1)]
            else:
                words = [x.strip() for x in line[:-1].split(' ', 1)]
            key, val  = words
            for d in ("'", '"'):
                if val.startswith(d) and val.endswith(d):
                    val = val[1:-1]
            if key in conn:
                conn[key] = val
    return conn

def isotime(dtime=None, sep=' '):
    if dtime is None:
        dtime = datetime.now()
    return datetime.isoformat(dtime, sep=sep)

class SimpleDB(object):
    """simple, common interface to Postgres/SQLite3 databases

    Intended as mixin class, with attributes:

    .dbnname
    .engine
    .metadata
    .tables
    .logfile

    and methods:

    connect(dbname, serve, user, password, port, host)
    close()
    execute()
    set_info()
    get_rows()

    """
    def __init__(self, dbname=None, server='postgresql', user='',
                 password='',  host='', port=5432, dialect=None, logfile=None):
        self.engine = None
        self.metadata = None
        self.logfile = logfile
        if dbname is not None:
            self.connect(dbname, server=server, user=user,
                         password=password, port=port, host=host, dialect=dialect)

    def connect(self, dbname, server='postgresql', user='',
                password='', port=None, host='localhost', dialect=None):
        "connect to an existing database"

        self.dbname = dbname
        if port not in (None, 'None', ''):
            try:
                port = int(port)
            except:
                pass
        connect_args = {}
        if server.startswith('post') or server.startswith('pg'):
            server ='postgresql'
            if port is None:
                port = 5432
            connect_str= f'{user}:{password}@{host}:{port:d}/{dbname}'
        elif server.startswith('my'):
            server = 'mysql'
            if port is None:
                port = 3306
            connect_str= f'{user}:{password}@{host}:{port:d}/{dbname}'
        else:
            server = 'sqlite'
            connect_str = f'/{dbname}'
            connect_args = {'check_same_thread': False}

        if dialect is None:
            connect_str = f'{server}://{connect_str}'
        else:
            connect_str = f'{server}+{dialect}://{connect_str}'

        self.engine = create_engine(connect_str, connect_args=connect_args)
        self.metadata = MetaData()
        try:
            self.metadata.reflect(bind=self.engine)
        except:
            raise ValueError(f'{dbname:s} is not a valid database')

        tables = self.tables = self.metadata.tables

        if self.logfile is None and server.startswith('sqlit'):
            self.logfile = f"{self.dbname:s}.log"
            logging.basicConfig()
            logger = logging.getLogger('sqlalchemy.engine')
            logger.addHandler(logging.FileHandler(self.logfile))

    def get_session(self):
        return Session(self.engine)

    def close(self):
        "close session"
        with Session(self.engine) as session, session.begin():
            session.flush()

    def execute(self, query, set_modify_date=False):
        """
        general execute of query, optionally setting 'modify date'
        and committing
        """
        result = None
        with Session(self.engine) as session, session.begin():
            result = session.execute(query)
            if set_modify_date:
                session.execute(self.set_info('modify_date', isotime(),
                                              do_execute=False))
            session.flush()
        return result

    def set_info(self, key, value, with_modify_time=True, do_execute=True):
        """set key / value in the info table
        do_execute=False to avoid executing, and only return query
        """
        tab = self.tables['info']
        val = self.get_rows('info', where={'key': key}, none_if_empty=True)
        ivals = {'value': value}
        if with_modify_time:
            ivals['modify_time'] = isotime()
        if val is None:
            ivals['key'] = key
            query = tab.insert().values(**ivals)
        else:
            query = tab.update().where(tab.c.key==key).values(**ivals)
        if do_execute:
            self.execute(query, set_modify_date=True)
        return query


    def get_info(self, key=None, default=None, prefix=None, as_int=False,
                 as_bool=False, order_by='modify_time', full_row=False):
        where = {}
        if key is not None:
            where['key'] = key

        allrows = self.get_rows('info', where, order_by=order_by)
        def cast(val, as_int, as_bool):
            if (as_int or as_bool):
                if val is None:
                    val = 0
                try:
                    val = int(float(val))
                    if as_bool:
                        val = bool(val)
                except (ValueError, TypeError):
                    pass
            return val

        if prefix is None:
            thisrow = None if len(allrows)==0 else allrows[0]
            out = None
            if thisrow is None:
                if key is not None: # will add to info
                    self.set_info(key, default)
                out = default
            else:
                out = thisrow
                if not full_row:
                    out = out.value
            out = cast(out, as_int, as_bool)
        else:
            out = []
            for row in allrows:
                if row.key.startswith(prefix):
                    xout = row
                    if not full_row:
                        xout = xout.value
                    out.append(cast(xout, as_int, as_bool))
        return out

    def set_modify_time(self):
        """set modify_date in info table"""
        self.set_info('modify_date', isotime(), do_execute=True)

    def add_row(self, tablename, **kws):
        """add row to a table with keyword/value pairs  == insert()"""
        self.insert(tablename, **kws)

    def insert(self, tablename, **kws):
        """insert to a table with keyword/value pairs"""
        tab = self.tables[tablename]
        self.execute(tab.insert().values(**kws), set_modify_date=True)

    def table_error(self, message, tablename, funcname):
        raise ValueError(f"{message} for table '{tablename}' in {funcname}()")

    def handle_where(self, tablename, where=None, funcname=None, **kws):
        if funcname is None:
            funcname = 'handle_where'
        tab = self.tables.get(tablename, None)
        if tab is None:
            self.table_error(f"no table found", tablename, funcname)

        filters = []
        if where is None or isinstance(where, bool) and where:
            where = {}
            if len(kws) == 0:
                filters.append(True)

        if isinstance(where, int):
            if 'id' in tab.c:
                filters.append(tab.c.id==where)
                print(" .(id).  ", where)
            else:
                for colname, coldat in tab.columns.items():
                    if coldat.primary_key and isinstance(coldat.type, INTEGER):
                        filters.append(getattr(tab.c, colname)==where)
            if len(filters) == 0:
                self.table_error(f"could not interpret integer `where` value",
                                      tablename, funcname)
        elif isinstance(where, dict):
            where.update(kws)
            for keyname, val in where.items():
                key = getattr(tab.c, keyname, None)
                if key is None:
                    key = getattr(tab.c, "%s_id" % keyname, None)
                if key is None:
                    self.table_error(f"no column '{keyname}'", tablename, funcname)
                filters.append(key==val)

        return and_(*filters)

    def get_rows(self, tablename, where=None, order_by=None, limit_one=False,
                none_if_empty=False, **kws):
        """general-purpose select of row data:

        Arguments
        ----------
        tablename    name of table
        where        dict of key/value pairs for where clause [None]
        order_by     name of column to order by [None]
        limit_one    whether to limit result to 1 row [False[
        none_if_empty whether to return None for an empty row [False]
        kwargs        other keyword/value pairs are included in the `where` dictionary
        Returns
        -------
        rows matching `where` (all if `where=None`) optionally ordered by order_by

        Examples
        --------
        >>> db.get_rows('element', where{'z': 30})
        """
        tab = self.tables.get(tablename, None)
        if tab is None:
            self.table_error(f"no table found", tablename, 'get_rows')

        where = self.handle_where(tablename, where=where, funcname='get_rows', **kws)
        query = tab.select().where(where)

        order_key = None
        if order_by is None:
            order_key = getattr(tab.c, "id", None)
        else:
            order_key = getattr(tab.c, order_by, None)
            if order_key is None:
                order_key = getattr(tab.c, f"{order_by}_id", None)
            if order_key is None:
                self.table_error(f"no column '{order_by}'", tablename, 'get_rows')
        if order_key is not None:
            query = query.order_by(order_key)

        result = self.execute(query)
        if limit_one:
            result = result.fetchone()
        else:
            result = result.fetchall()

        if result is not None and len(result) == 0 and none_if_empty:
            result = None
        return result

    def lookup(self, tablename, **kws):
        """
        simple select of table with any equality filter on columns by name

        a simple wrapper for
           self.get_rows(tablename, limit_one=False, none_if_empty=False, **kws)

        """
        return self.get_rows(tablename, limit_one=False, none_if_empty=False, **kws)

    def update(self, tablename, where=None, **kws):
        """update a row (with where in a table
        using keyword args

        Arguments
        ----------
        tablename   name of table
        where       select row to update, either int for id or dict for key/val

        kws          values to update


        """
        tab = self.tables.get(tablename, None)
        if tab is None:
            self.table_error(f"no table found", tablename, 'update')

        where = self.handle_where(tablename, where=where, funcname='update')
        self.execute(tab.update().where(where).values(**kws), set_modify_date=True)


    def delete_rows(self, tablename, where):
        """delete rows from table

        Arguments
        ----------
        tablename   name of table
        where       rows to delete, either int for id or dict for key/val
        """

        tab = self.tables.get(tablename, None)
        if tab is None:
            self.table_error(f"no table found", tablename, 'delete')

        where = self.handle_where(tablename, where=where, funcname='delete')
        self.execute(tab.delete().where(where), set_modify_date=True)