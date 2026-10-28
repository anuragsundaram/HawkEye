from datetime import datetime
from uuid import uuid4

import psycopg
from psycopg_pool import ConnectionPool
from flask import abort, session

from app import active_connections, app, lock

error_types = (psycopg.Error,)
database_type = 'postgresql'


def _get_pool(target):
    from app import target_pool

    if not target_pool.get(target):
        description = app.config['TARGETS'][target]
        pool = ConnectionPool(
            conninfo='',
            kwargs={
                'host': description['host'],
                'port': description.get('port') or 5432,
                'dbname': description['database_name'],
                'user': description['user'],
                'password': description['password'],
                'connect_timeout': 5,
            },
            min_size=1,
            max_size=app.config.get('PG_MAX_POOL_SIZE', app.config['ORA_MAX_POOL_SIZE']),
            open=False,
        )
        pool.open()
        target_pool[target] = pool
    return target_pool[target]


def _convert_parameters(statement, parameters):
    """Translate named binds without changing colons inside SQL strings or comments."""
    ordered_values = []
    converted = []
    index = 0
    state = 'normal'
    block_depth = 0
    dollar_delimiter = None

    while index < len(statement):
        char = statement[index]
        next_char = statement[index + 1] if index + 1 < len(statement) else ''

        if state == 'single':
            converted.append(char)
            if char == "'" and next_char == "'":
                converted.append(next_char)
                index += 2
                continue
            if char == "'":
                state = 'normal'
            elif char == '\\' and index + 1 < len(statement):
                converted.append(next_char)
                index += 2
                continue
        elif state == 'double':
            converted.append(char)
            if char == '"' and next_char == '"':
                converted.append(next_char)
                index += 2
                continue
            if char == '"':
                state = 'normal'
        elif state == 'line_comment':
            converted.append(char)
            if char == '\n':
                state = 'normal'
        elif state == 'block_comment':
            converted.append(char)
            if char == '/' and next_char == '*':
                converted.append(next_char)
                block_depth += 1
                index += 2
                continue
            if char == '*' and next_char == '/':
                converted.append(next_char)
                block_depth -= 1
                index += 2
                if block_depth == 0:
                    state = 'normal'
                continue
        elif state == 'dollar':
            if statement.startswith(dollar_delimiter, index):
                converted.append(dollar_delimiter)
                index += len(dollar_delimiter)
                state = 'normal'
                continue
            converted.append(char)
        elif char == "'":
            converted.append(char)
            state = 'single'
        elif char == '"':
            converted.append(char)
            state = 'double'
        elif char == '-' and next_char == '-':
            converted.extend((char, next_char))
            index += 2
            state = 'line_comment'
            continue
        elif char == '/' and next_char == '*':
            converted.extend((char, next_char))
            index += 2
            state = 'block_comment'
            block_depth = 1
            continue
        elif char == '$':
            delimiter_end = statement.find('$', index + 1)
            if delimiter_end != -1:
                candidate = statement[index:delimiter_end + 1]
                tag = candidate[1:-1]
                if not tag or (tag[0].isalpha() or tag[0] == '_') \
                        and all(character.isalnum() or character == '_' for character in tag):
                    converted.append(candidate)
                    index = delimiter_end + 1
                    state = 'dollar'
                    dollar_delimiter = candidate
                    continue
            converted.append(char)
        elif char == ':' and next_char != ':' and (index == 0 or statement[index - 1] != ':'):
            end = index + 1
            while end < len(statement) and (statement[end].isalnum() or statement[end] == '_'):
                end += 1
            name = statement[index + 1:end]
            if name and (name[0].isalpha() or name[0] == '_' or name.isdigit()):
                key = int(name) if name.isdigit() and name not in parameters else name
                ordered_values.append(parameters[key])
                converted.append('%s')
                index = end
                continue
            converted.append(char)
        else:
            converted.append(char)
        index += 1

    converted_statement = ''.join(converted)
    if not ordered_values:
        return converted_statement, parameters or None
    return converted_statement, tuple(ordered_values)


def execute(target, statement, parameters=None, fetch_mode='many', user_context=True):
    if fetch_mode == 'func':
        raise ValueError('PostgreSQL does not support Oracle-style stored function execution.')

    parameters = parameters or {}
    statement, parameters = _convert_parameters(statement, parameters)
    with lock:
        if user_context and tuple(connection[2] for connection in active_connections.values()) \
                .count(session['user_name']) == app.config['MAX_DB_SESSIONS_PER_USER']:
            abort(429)
        pool = _get_pool(target)

    request_id = uuid4().hex
    with pool.connection() as connection:
        active_connections[request_id] = [
            connection,
            datetime.now(),
            session['user_name'] if user_context else 'system',
            target,
            statement,
            '',
        ]
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement, parameters)
                if fetch_mode == 'one':
                    result = cursor.fetchone()
                elif fetch_mode == 'clob':
                    row = cursor.fetchone()
                    result = row[0] if row and row[0] is not None else None
                elif fetch_mode == 'none':
                    connection.commit()
                    result = None
                elif fetch_mode == 'many':
                    result = cursor.fetchmany(app.config['ORA_NUM_ROWS'])
                else:
                    raise ValueError(f'Unsupported fetch mode: {fetch_mode}')
            return result
        except psycopg.Error:
            app.logger.error('failed PostgreSQL statement: %s', statement)
            raise
        finally:
            active_connections.pop(request_id, None)


def get_tab_columns(target, owner, table_name):
    return {
        item[0]: item[1]
        for item in execute(
            target,
            'select column_name, data_type from information_schema.columns '
            'where table_schema = %(owner)s and table_name = %(table_name)s',
            {'owner': owner, 'table_name': table_name},
        )
    }


def get_database_info(target):
    row = execute(
        target,
        'select current_database(), version(), inet_server_addr()::text, '
        'pg_postmaster_start_time(), current_user',
        fetch_mode='one',
    )
    return {
        'database_name': row[0],
        'version': row[1],
        'host_name': row[2] or app.config['TARGETS'][target]['host'],
        'startup_time': row[3],
        'connected_as': row[4],
    }


def ping(target):
    try:
        with _get_pool(target).connection() as connection:
            connection.execute('select 1')
        return 0
    except psycopg.Error:
        return -1


def cancel_active(request_id):
    with lock:
        connection = active_connections.get(request_id)
        if connection is None:
            return False
        connection[5] = 'Cancelling...'
        connection[0].cancel()
        return True


def close_pool(target):
    from app import target_pool

    pool = target_pool.pop(target, None)
    if pool is not None:
        pool.close()
