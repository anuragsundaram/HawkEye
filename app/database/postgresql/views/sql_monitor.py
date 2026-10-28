import psycopg
from flask import jsonify, render_template

from app.database.postgresql.adapter import execute
from app.utils.permissions import can_manage_database_actions


def get_postgresql_sql_monitor(target):
    return render_template(
        'postgresql/sql_monitor.html',
        target=target,
        can_manage_database=can_manage_database_actions(),
    )


def get_postgresql_sql_monitor_data(target):
    try:
        rows = execute(
            target,
            "select pid, md5(query) query_hash, left(query, 4000) query_text, "
            "usename, application_name, state, "
            "extract(epoch from clock_timestamp() - query_start)::bigint elapsed_seconds, "
            "coalesce(wait_event_type || ': ' || wait_event, 'CPU') wait_event, "
            "client_addr::text "
            "from pg_stat_activity "
            "where backend_type = 'client backend' and state = 'active' "
            "and pid <> pg_backend_pid() and query_start is not null "
            "order by query_start asc limit 200",
        )
    except psycopg.Error as error:
        return jsonify({'error': str(error)}), 500
    return jsonify([
        {
            'pid': row[0],
            'query_hash': row[1],
            'query_text': row[2],
            'username': row[3],
            'application': row[4],
            'state': row[5],
            'elapsed_seconds': row[6],
            'wait_event': row[7],
            'client_addr': row[8],
        }
        for row in rows
    ])
