# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2016 Symantec.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import eventlet
import os
import time
import sqlalchemy.orm
from sqlalchemy import exc as sqla_exc
from sqlalchemy.pool import NullPool, StaticPool

from dao.common import config as cfg
from dao.common import exceptions as exception
from dao.common import log


sql_opts = [
    cfg.StrOpt('db', 'sql_connection',
               default='sqlite:///' +
                       os.path.abspath(os.path.join(os.path.dirname(__file__),
                       '../', '$sqlite_db')),
               help='The SQLAlchemy connection string used to connect to the '
                    'database'),
    cfg.StrOpt('db', 'sqlite_db',
               default='dao.sqlite',
               help='the filename to use with sqlite'),
    cfg.IntOpt('db', 'sql_idle_timeout',
               default=3600,
               help='timeout before idle sql connections are reaped'),
    cfg.BoolOpt('db', 'sqlite_synchronous',
                default=True,
                help='If passed, use synchronous mode for sqlite'),
    cfg.IntOpt('db', 'sql_min_pool_size',
               default=1,
               help='Minimum number of SQL connections to keep open in a '
                    'pool'),
    cfg.IntOpt('db', 'sql_max_pool_size',
               default=5,
               help='Maximum number of SQL connections to keep open in a '
                    'pool'),
    cfg.IntOpt('db', 'sql_max_retries',
               default=10,
               help='maximum db connection retries during startup. '
                    '(setting -1 implies an infinite retry count)'),
    cfg.IntOpt('db', 'sql_retry_interval',
               default=10,
               help='interval between retries of opening a sql connection'),
    cfg.IntOpt('db', 'sql_max_overflow',
               default=None,
               help='If set, use this value for max_overflow with sqlalchemy'),
    cfg.IntOpt('db', 'sql_connection_debug',
               default=0,
               help='Verbosity of SQL debugging information. 0=None, '
                    '100=Everything'),
    cfg.BoolOpt('db', 'sql_connection_trace',
                default=False,
                help='Add python stack traces to SQL as comment strings'),
]

cfg.register(sql_opts)
CONF = cfg.get_config()
LOG = log.getLogger(__name__)
_ENGINE = None
_MAKER = None


def greenthread_yield(dbapi_con, con_record):
    """
    Ensure other greenthreads get a chance to execute by forcing a context
    switch. With common database backends (eg MySQLdb and sqlite), there is
    no implicit yield caused by network I/O since they are implemented by
    C libraries that eventlet cannot monkey patch.
    """
    eventlet.sleep(0)


def ping_listener(dbapi_conn, connection_rec, connection_proxy):
    """
    Ensures that MySQL connections checked out of the
    pool are alive.

    Borrowed from:
    http://groups.google.com/group/sqlalchemy/msg/a4ce563d802c929f
    """
    try:
        dbapi_conn.cursor().execute('select 1')
    except dbapi_conn.OperationalError, ex:
        if ex.args[0] in (2006, 2013, 2014, 2045, 2055):
            LOG.warn('Got mysql server has gone away: %s', ex)
            raise sqla_exc.DisconnectionError("Database server went away")
        else:
            raise


def is_db_connection_error(args):
    """Return True if error in connecting to db."""
    # NOTE(adam_g): This is currently MySQL specific and needs to be extended
    #               to support Postgres and others.
    conn_err_codes = ('2002', '2003', '2006')
    for err_code in conn_err_codes:
        if args.find(err_code) != -1:
            return True
    return False


def synchronous_switch_listener(dbapi_conn, connection_rec):
    """Switch sqlite connections to non-synchronous mode."""
    dbapi_conn.execute("PRAGMA synchronous = OFF")


def create_engine(sql_connection):
    """Return a new SQLAlchemy engine."""
    connection_dict = sqlalchemy.engine.url.make_url(sql_connection)

    engine_args = {
        "pool_recycle": CONF.db.sql_idle_timeout,
        "echo": False,
        'convert_unicode': True,
    }

    # Map our SQL debug level to SQLAlchemy's options
    if CONF.db.sql_connection_debug >= 100:
        engine_args['echo'] = 'debug'
    elif CONF.db.sql_connection_debug >= 50:
        engine_args['echo'] = True

    if "sqlite" in connection_dict.drivername:
        engine_args["poolclass"] = NullPool

        if CONF.db.sql_connection == "sqlite://":
            engine_args["poolclass"] = StaticPool
            engine_args["connect_args"] = {'check_same_thread': False}
    else:
        engine_args['pool_size'] = CONF.db.sql_max_pool_size
        if CONF.db.sql_max_overflow is not None:
            engine_args['max_overflow'] = CONF.db.sql_max_overflow

    engine = sqlalchemy.create_engine(sql_connection, **engine_args)

    sqlalchemy.event.listen(engine, 'checkin', greenthread_yield)

    if 'mysql' in connection_dict.drivername:
        sqlalchemy.event.listen(engine, 'checkout', ping_listener)
    elif 'sqlite' in connection_dict.drivername:
        if not CONF.db.sqlite_synchronous:
            sqlalchemy.event.listen(engine, 'connect',
                                    synchronous_switch_listener)

    try:
        engine.connect()
    except sqla_exc.OperationalError, e:
        if not is_db_connection_error(e.args[0]):
            raise

        remaining = CONF.db.sql_max_retries
        if remaining == -1:
            remaining = 'infinite'
        while True:
            msg = 'SQL connection failed. %s attempts left.'
            LOG.warn(msg % remaining)
            if remaining != 'infinite':
                remaining -= 1
            time.sleep(CONF.db.sql_retry_interval)
            try:
                engine.connect()
                break
            except sqla_exc.OperationalError, e:
                if (remaining != 'infinite' and remaining == 0) or \
                        not is_db_connection_error(e.args[0]):
                    raise
    return engine


def wrap_db_error(f):
    def _wrap(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except UnicodeEncodeError:
            raise exception.DBInvalidUnicodeParameter()
        except Exception, e:
            LOG.exception('DB exception wrapped.')
            raise exception.DBError(e)
    _wrap.func_name = f.func_name
    return _wrap


class Session(sqlalchemy.orm.session.Session):
    """Custom Session class to avoid SqlAlchemy Session monkey patching."""
    @wrap_db_error
    def query(self, *args, **kwargs):
        return super(Session, self).query(*args, **kwargs)

    @wrap_db_error
    def flush(self, *args, **kwargs):
        return super(Session, self).flush(*args, **kwargs)

    @wrap_db_error
    def execute(self, *args, **kwargs):
        return super(Session, self).execute(*args, **kwargs)


def get_engine():
    """Return a SQLAlchemy engine."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(CONF.db.sql_connection)
    return _ENGINE


def get_maker(engine, autocommit=True, expire_on_commit=False):
    """Return a SQLAlchemy sessionmaker using the given engine."""
    return sqlalchemy.orm.sessionmaker(bind=engine,
                                       class_=Session,
                                       autocommit=autocommit,
                                       expire_on_commit=expire_on_commit,
                                       query_cls=sqlalchemy.orm.query.Query)


def get_session(autocommit=True, expire_on_commit=False):
    """Return a SQLAlchemy session."""
    global _MAKER

    if _MAKER is None:
        engine = get_engine()
        _MAKER = get_maker(engine, autocommit, expire_on_commit)

    session = _MAKER()
    return session

