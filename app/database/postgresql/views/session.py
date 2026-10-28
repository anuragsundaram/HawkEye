from flask import flash, redirect, render_template, request, url_for

from app import app
from app.database.postgresql.adapter import execute
from app.utils.permissions import can_manage_database_actions


def get_postgresql_session_monitor(target):
    status = request.args.get('status', 'ACTIVE').upper()
    if status not in (
        'ACTIVE',
        'IDLE',
        'IDLE IN TRANSACTION',
        'IDLE IN TRANSACTION (ABORTED)',
        'ALL',
    ):
        status = 'ACTIVE'

    rows = execute(
        target,
        "select pid, md5(query) query_hash, datname, usename, state, "
        "client_addr::text, application_name, backend_start, state_change, "
        "wait_event_type, wait_event, "
        "extract(epoch from clock_timestamp() - query_start)::bigint runtime_seconds, "
        "left(query, 2000) query_text "
        "from pg_stat_activity "
        "where backend_type = 'client backend' and pid <> pg_backend_pid() "
        "and (:status = 'ALL' or state = :status) "
        "order by backend_start desc nulls last, pid",
        {'status': status.lower() if status != 'ALL' else status},
    )
    return render_template(
        'postgresql/session_monitor.html',
        rows=rows,
        selected_status=status,
        can_manage_database=can_manage_database_actions(),
    )


@app.route('/<target>/postgresql/terminate_session', methods=['POST'])
def terminate_postgresql_session(target):
    return_endpoint = (
        'get_sql_monitor'
        if request.form.get('return_to') == 'sql_monitor'
        else 'get_session_monitor'
    )
    return_url = url_for(return_endpoint, target=target)
    if not can_manage_database_actions():
        flash('Only administrators can terminate database sessions.', 'error')
        return redirect(return_url)

    pid_value = request.form.get('pid', '')
    if not pid_value.isdecimal() or int(pid_value) <= 0:
        flash('A valid session PID is required.', 'error')
        return redirect(return_url)

    try:
        result = execute(
            target,
            "select pg_terminate_backend(pid) "
            "from pg_stat_activity "
            "where pid = :pid and backend_type = 'client backend' "
            "and pid <> pg_backend_pid()",
            {'pid': int(pid_value)},
            fetch_mode='one',
        )
        if result and result[0]:
            flash(f'Session {pid_value} termination requested.', 'success')
        else:
            flash(f'Session {pid_value} was not found or could not be terminated.', 'error')
    except Exception as error:
        flash(f'Unable to terminate session {pid_value}: {error}', 'error')

    return redirect(return_url)
