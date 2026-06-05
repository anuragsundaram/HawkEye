from datetime import datetime
from uuid import uuid4

import oracledb
from flask import abort, session

from app import active_connections, app, lock, target_pool


def set_ora_pool(target):
    """Create a connection pool using oracledb thin client (no Oracle client library required)"""
    target_description = app.config['TARGETS'][target]
    
    # Build connection string in the format: host:port/service_name or host:port:sid
    # Prefer service_name if provided and non-empty, otherwise use SID
    host = target_description['host']
    port = target_description.get('port', 1521)
    service = target_description.get('service', '').strip()
    sid = target_description.get('sid', '').strip()
    
    pool_kwargs = {
        'user': target_description['user'],
        'password': target_description['password'],
        'host': host,
        'port': port,
        'min': 1,
        'max': app.config['ORA_MAX_POOL_SIZE'],
        'increment': 1
    }
    
    # Validate credentials presence to avoid ambiguous DPY-4001 errors from driver
    if not pool_kwargs.get('user') or not pool_kwargs.get('password'):
        raise RuntimeError(f"Missing credentials for target {target}: user and password are required")
    
    # Use service_name if provided and non-empty, otherwise use SID
    if service:
        pool_kwargs['service_name'] = service
    elif sid:
        pool_kwargs['sid'] = sid
    else:
        raise RuntimeError(f"Target {target} must have either service or sid configured")

    target_pool[target] = oracledb.create_pool(**pool_kwargs)


def execute(target, statement, parameters=None, fetch_mode='many', user_context=True):
    with lock:
        if user_context:
            if tuple(v[2] for v in active_connections.values()) \
                    .count(session['user_name']) == app.config['MAX_DB_SESSIONS_PER_USER']:
                abort(429)
        if not target_pool.get(target):
            set_ora_pool(target)

    connection = None
    try:
        connection = target_pool[target].acquire()
        connection.ping()
    except oracledb.Error:
        if connection:
            target_pool[target].drop(connection)
        connection = target_pool[target].acquire()

    cursor = None
    result = None
    uuid = None
    try:
        uuid = uuid4().hex
        active_connections[uuid] = [connection
                                    , datetime.now()
                                    , session['user_name'] if user_context else 'system'
                                    , target
                                    , statement
                                    , '']
        cursor = connection.cursor()
        # Execute statement first. Some oracledb versions return None from
        # cursor.execute(), so use cursor.fetchone()/fetchmany() on the cursor
        # object instead of chaining calls.
        if fetch_mode == 'func':
            result = cursor.callfunc(statement, oracledb.CLOB, [], parameters or {}).read()
        else:
            cursor.execute(statement, parameters or {})
            if fetch_mode == 'one':
                result = cursor.fetchone()
            elif fetch_mode == 'clob':
                row = cursor.fetchone()
                if row and row[0]:
                    result = row[0].read()
            elif fetch_mode == 'none':
                connection.commit()
            elif fetch_mode == 'many':
                result = cursor.fetchmany(app.config['ORA_NUM_ROWS'])
        cursor.close()
    except oracledb.Error as e:
        error_code = e.args[0].code if hasattr(e.args[0], 'code') else None
        if error_code not in (1013, 604):  # cancel, recursive
            app.logger.error(f'failed statement: {statement}')
        raise
    except oracledb.DatabaseError:
        if cursor:
            cursor.close()
        raise
    finally:
        if uuid:
            del active_connections[uuid]
        if connection:
            try:
                target_pool[target].release(connection)
            except oracledb.DatabaseError:
                pass
    return result


def get_tab_columns(target, owner, table_name):
    return {item[0]: item[1] for item in execute(target
                                                 , 'select column_name, data_type'
                                                   ' from dba_tab_columns'
                                                   ' where owner = :owner'
                                                   ' and table_name = :table_name'
                                                 , {'owner': owner, 'table_name': table_name}
                                                 , 'many'
                                                 , False)}


def ping(target):
    try:
        with lock:
            if not target_pool.get(target):
                set_ora_pool(target)
        connection = target_pool[target].acquire()
        connection.ping()
        target_pool[target].release(connection)
        return 0
    except oracledb.Error:
        return -1
