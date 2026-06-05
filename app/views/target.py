from app import app
from app.utils.decorate_view import *
from app.utils.render_page import render_page
from app.utils.oracle import execute
from app.utils.permissions import can_manage_database_actions
from flask import request, render_template, flash, redirect, url_for, jsonify


@app.route('/<target>')
@title('Activity')
@template('single')
@select("v$instance")
@columns({"instance_name": 'str'
          , "version": 'str'
          , "host_name": 'str'
          , "startup_time": 'datetime'
          , "user connected_as": 'str'})
def get_target(target):
    return render_page()


@app.route('/<target>/sql_monitor')
@title('SQL Monitor')
def get_sql_monitor(target):
    return render_template('sql_monitor.html', target=target)


@app.route('/<target>/sql_monitor/data')
def get_sql_monitor_data(target):
    """Return currently executing SQLs as JSON for AJAX refresh."""
    sql = ("SELECT m.sid, m.session_serial#, m.sql_id, "
           "COALESCE(DBMS_LOB.SUBSTR(a.sql_fulltext, 4000, 1), SUBSTR(m.sql_text,1,4000), '-') sql_text, "
           "m.status, m.username, m.module, ROUND(m.elapsed_time / 1000000) elapsed_secs, "
           "m.buffer_gets, m.disk_reads, m.sql_exec_start "
           "FROM v$sql_monitor m "
           "LEFT JOIN v$sqlarea a ON a.sql_id = m.sql_id "
           "WHERE UPPER(m.status) = 'EXECUTING' "
           "ORDER BY m.sql_exec_start DESC")
    active_sql = ("SELECT s.sid, s.serial#, s.sql_id, "
                  "COALESCE(DBMS_LOB.SUBSTR(q.sql_fulltext, 4000, 1), SUBSTR(q.sql_text,1,4000), '-') sql_text, "
                  "s.status, s.username, s.module, "
                  "CASE WHEN s.sql_exec_start IS NOT NULL "
                  "     THEN ROUND((SYSDATE - s.sql_exec_start) * 86400) "
                  "     ELSE s.last_call_et END elapsed_secs, "
                  "q.buffer_gets, q.disk_reads, s.sql_exec_start "
                  "FROM v$session s "
                  "LEFT JOIN v$sql q ON q.sql_id = s.sql_id AND q.child_number = s.sql_child_number "
                  "WHERE s.status = 'ACTIVE' "
                  "AND s.type = 'USER' "
                  "AND s.sql_id IS NOT NULL "
                  "ORDER BY elapsed_secs DESC")
    try:
        rows = execute(target, sql, fetch_mode='many')
        if not rows:
            rows = execute(target, active_sql, fetch_mode='many')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    result = []
    for r in rows:
        result.append({
            'sid': r[0],
            'serial': r[1],
            'sql_id': r[2],
            'sql_text': r[3],
            'status': r[4],
            'username': r[5],
            'module': r[6],
            'elapsed_secs': r[7],
            'buffer_gets': r[8],
            'disk_reads': r[9],
            'sql_exec_start': r[10].strftime('%Y-%m-%d %H:%M:%S') if r[10] else None
        })
    return jsonify(result)


@app.route('/<target>/sql_monitor/sql_text/<sql_id>')
def get_sql_monitor_sql_text(target, sql_id):
    """Return full SQL text for the SQL Monitor modal."""
    try:
        sql_text = execute(target,
                           "select sql_fulltext from v$sqlarea where sql_id = :sql_id",
                           {'sql_id': sql_id},
                           fetch_mode='clob')
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'sql_text': sql_text or ''})


@app.route('/<target>/session_monitor')
@title('Session Monitor')
def get_session_monitor(target):
    """Session monitor with status filter dropdown, defaulting to ACTIVE, sorted by logon_time desc."""
    # status param: ACTIVE, INACTIVE, or ALL
    status = request.args.get('status', 'ACTIVE').upper()
    if status not in ('ACTIVE', 'INACTIVE', 'ALL'):
        status = 'ACTIVE'

    where_clause = "s.type = 'USER'"
    if status in ('ACTIVE', 'INACTIVE'):
        where_clause += f" and s.status = '{status}'"

    sql = ("select s.sid, s.serial#, s.sql_id, a.name command, s.username, s.status, s.osuser, s.machine, s.program,"
           " s.logon_time, (sysdate - s.last_call_et/86400) last_call, s.wait_class, s.event"
           " from v$session s left join audit_actions a on a.action = s.command"
           f" where {where_clause}"
           " order by s.logon_time desc")
    try:
        rows = execute(target, sql, fetch_mode='many')
    except Exception as e:
        flash(str(e), 'error')
        rows = []
    return render_template('session_monitor.html', target=target, rows=rows, selected_status=status)






@app.route('/<target>/users')
@title('Users')
@template('list')
@columns({"user_id": 'int'
         , "username": 'str'
         , "account_status": 'str'
         , "lock_date": 'datetime'
         , "expiry_date": 'datetime'
         , "default_tablespace": 'str'
         , "temporary_tablespace": 'str'})
@select("dba_users")
@default_filters("account_status = 'OPEN'")
@default_sort("expiry_date desc")
def get_users(target):
    return render_page()


@app.route('/<target>/table_stats')
@title('Table Stats')
@template('list')
@snail()
@columns({"s.owner": 'str'
         , "object_type": 'str'
         , "s.table_name": 'str'
         , "s.partition_name": 'str'
         , "s.subpartition_name": 'str'
         , "s.num_rows": 'int'
         , "round((s.blocks * p.value) / 1024 / 1024) size_mb": 'int'
         , "round((((s.blocks * p.value) - (num_rows * avg_row_len))"
           " / nullif((s.blocks * p.value), 0)) * 100) pct_wasted": 'int'
         , "s.last_analyzed": 'datetime'
         , "s.stale_stats": 'str'})
@select("all_tab_statistics s join v$parameter p on p.name  = 'db_block_size'")
@default_filters("owner not like 'SYS%' and stale_stats = 'YES'", "object_type = 'TABLE'")
@default_sort("last_analyzed")
def get_table_stats(target):
    """Pct wasted is a very approximate parameter, based on average row length."""
    return render_page()


@app.route('/<target>/segments')
@title('Segments')
@template('list')
@snail()
@columns({"tablespace_name": 'str'
         , "owner": 'str'
         , "segment_name": 'str'
         , "segment_type": 'str'
         , "round(nvl(sum(bytes) / 1024 / 1024, 0)) size_mb": 'int'})
@select("dba_segments group by tablespace_name, owner, segment_name, segment_type")
@default_filters("size_mb > 0", "tablespace_name like '%%'")
@default_sort("size_mb desc")
def get_segments(target):
    return render_page()


@app.route('/<target>/tablespace_usage')
@title('Tablespace Usage')
@template('list')
@snail()
@columns({"t.tablespace_name": 'str'
         , "files.datafiles": 'int'
         , "t.segment_space_management": 'str'
         , "round(((files.max_files_size - (files.free_files_space + free.free_space))"
           " / files.max_files_size) * 100) pct_used": 'int'
         , "round(files.max_files_size / 1024 / 1024 / 1024) allocated_gb": 'int'
         , "round((files.max_files_size - (files.free_files_space + free.free_space))"
           " / 1024 / 1024 / 1024) used_gb": 'int'
         , "round((files.free_files_space + free.free_space) / 1024 / 1024 / 1024) free_gb": 'int'})
@select("dba_tablespaces t"
        " left join (select tablespace_name, sum(nvl(bytes,0)) free_space"
        " from dba_free_space group by tablespace_name) free"
        " on t.tablespace_name = free.tablespace_name"
        " left join (select tablespace_name, count(1) datafiles,"
        " sum(decode(maxbytes, 0, bytes, maxbytes)) - sum(bytes) free_files_space,"
        " sum(decode(maxbytes, 0, bytes, maxbytes)) max_files_size"
        " from dba_data_files group by tablespace_name) files"
        " on t.tablespace_name = files.tablespace_name")
@default_sort("pct_used desc")
def get_tablespace_usage(target):
    return render_page()


@app.route('/<target>/temp_usage')
@title('Temp usage')
@template('list')
@auto()
@columns({"tablespace": 'str'
         , "total_mb": 'int'
         , "total_used_mb": 'int'
         , "total_free_mb": 'int'
         , "username": 'str'
         , "sid": 'int'
         , "sql_id": 'str'
         , "pct_sql_used": 'int'
         , "sql_used_mb": 'int'
         , "segtype": 'str'})
@select("(select u.tablespace, u.segtype, s.username, s.sid, s.sql_id"
        " , round(((min(t.total_blocks) * min(p.value)) / 1024 / 1024)) total_mb"
        " , round(((min(t.used_blocks) * min(p.value)) / 1024 / 1024)) total_used_mb"
        " , round(((min(t.free_blocks) * min(p.value)) / 1024 / 1024)) total_free_mb"
        " , round(((sum(u.blocks) / min(t.total_blocks)) * 100)) pct_sql_used"
        " , round(((sum(u.blocks) * min(p.value)) / 1024 / 1024)) sql_used_mb"
        " from v$sort_usage u"
        " join v$parameter p on p.name  = 'db_block_size'"
        " join v$sort_segment t on t.tablespace_name = u.tablespace"
        " join v$session s on s.saddr = u.session_addr"
        " group by u.tablespace, u.segtype, s.username, s.sid, s.sql_id)")
@default_sort("tablespace, sql_used_mb desc")
def get_temp_usage(target):
    return render_page()





@app.route('/<target>/index_stats')
@title('Index stats')
@template('list')
@snail()
@columns({"owner": 'str'
         , "object_type": 'str'
         , "index_name": 'str'
         , "table_name": 'str'
         , "partition_name": 'str'
         , "subpartition_name": 'str'
         , "leaf_blocks": 'int'
         , "distinct_keys": 'int'
         , "avg_leaf_blocks_per_key": 'int'
         , "avg_data_blocks_per_key": 'int'
         , "clustering_factor": 'int'
         , "num_rows": 'int'
         , "last_analyzed": 'datetime'
         , "stale_stats": 'str'})
@select("all_ind_statistics")
@default_sort("last_analyzed")
def get_index_stats(target):
    return render_page()


@app.route('/<target>/privileges')
@title('Privileges')
@template('list')
@columns({"grantee": 'str'
          , "owner": 'str'
          , "table_name": 'str'
          , "grantor": 'str'
          , "privilege": 'str'
          , "grantable": 'str'
          , "hierarchy": 'str'})
@select("dba_tab_privs")
@default_sort("table_name")
def get_privileges(target):
    return render_page()


@app.route('/<target>/rman')
@title('Rman Status')
def get_rman_status(target):
    """Display RMAN backup status with date and type filter."""
    from datetime import datetime, timedelta
    
    # Get date range parameters (defaults to today) and optional type filter (empty = all)
    today = datetime.now().strftime('%Y-%m-%d')
    backup_start = request.args.get('start_date', today)
    backup_end = request.args.get('end_date', today)
    backup_type = request.args.get('type', '')

    # SQL mapping for different backup types. Use UPPER() to be robust.
    # Broaden matching across multiple columns to handle varied RMAN text
    backup_types_sql = {
        'ARCHIVE_LOG': (
            "(UPPER(operation) LIKE '%ARCHIV%' OR UPPER(row_type) LIKE '%ARCHIV%' "
            "OR UPPER(object_type) LIKE '%ARCHIV%' OR UPPER(operation) LIKE '%ARCHIVELOG%')"
        ),
        'INCREMENTAL_BACKUP': (
            "(UPPER(operation) LIKE '%INCREMENT%' OR UPPER(operation) LIKE '% INCR%' "
            "OR UPPER(row_type) LIKE '%INCR%' OR UPPER(row_type) LIKE '%DIFFERENTIAL%' "
            "OR UPPER(object_type) LIKE '%INCR%')"
        )
    }

    # If no type selected, do not filter by type
    if backup_type and backup_type in backup_types_sql:
        type_filter = 'AND ' + backup_types_sql[backup_type]
    else:
        type_filter = ''

    # Compute total time in minutes (rounded). Use NVL(end_time, SYSTIMESTAMP) for running backups.
    sql = ("SELECT recid, row_type, operation, status, start_time, end_time, object_type, "
           "ROUND((NVL(end_time, SYSTIMESTAMP) - start_time) * 24 * 60) total_minutes "
           "FROM v$rman_status "
           "WHERE TRUNC(NVL(start_time, end_time)) BETWEEN TO_DATE(:start_date, 'YYYY-MM-DD') AND TO_DATE(:end_date, 'YYYY-MM-DD') "
           f"{type_filter} "
           "ORDER BY end_time DESC")

    try:
        rows = execute(target, sql, parameters={'start_date': backup_start, 'end_date': backup_end}, fetch_mode='many')
    except Exception as e:
        rows = []
        flash(f'Error fetching RMAN status: {str(e)}', 'error')
    
    return render_template('rman_status.html', 
                         target=target,
                         rows=rows,
                         backup_type=backup_type,
                         backup_start=backup_start,
                         backup_end=backup_end)


@app.route('/<target>/dml_locks')
@title('DML Locks')
@template('dml_locks')
def get_dml_locks(target):
    return render_template('dml_locks.html', target=target)


@app.route('/<target>/dml_locks/data')
def get_dml_locks_data(target):
    """Return current DML blocking locks as JSON for dynamic reloads."""
    sql = ("SELECT DISTINCT s.sid, s.serial# , s.sql_id, "
           "COALESCE(SUBSTR(q.sql_text,1,2000), '-') sql_text, "
           "s.event operation, ROUND(s.last_call_et/60) running_minutes, "
           "(SELECT COUNT(1) FROM v$session ss WHERE ss.blocking_session = s.sid) blocked_count, "
           "s.username, s.machine "
           "FROM v$lock l "
           "JOIN v$session s ON s.sid = l.sid "
           "LEFT JOIN v$sqlarea q ON q.sql_id = s.sql_id "
           "WHERE l.block = 1 "
           "ORDER BY blocked_count DESC NULLS LAST, running_minutes DESC")
    try:
        rows = execute(target, sql, fetch_mode='many')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    locks = []
    for r in rows:
        locks.append({
            'sid': r[0],
            'serial': r[1],
            'sql_id': r[2],
            'sql_text': r[3],
            'operation': r[4],
            'running_minutes': r[5],
            'blocked_count': r[6],
            'username': r[7],
            'machine': r[8]
        })
    return jsonify(locks)


@app.route('/<target>/kill_session', methods=['POST'])
def kill_session(target):
    """Kill a session by sid and serial#."""
    sid = request.form.get('sid')
    serial = request.form.get('serial')
    return_to = request.form.get('return_to') or url_for('get_dml_locks', target=target)

    if not can_manage_database_actions():
        flash('Only administrators can kill database sessions.', 'error')
        return redirect(return_to)

    if not sid or not serial:
        flash('Missing sid or serial', 'error')
        return redirect(return_to)

    try:
        kill_sql = f"ALTER SYSTEM KILL SESSION '{sid},{serial}' IMMEDIATE"
        # ALTER SYSTEM KILL SESSION does not return rows — use 'none'
        execute(target, kill_sql, fetch_mode='none', user_context=True)
        flash(f'Session {sid},{serial} marked for kill', 'success')
    except Exception as e:
        flash(f'Error killing session: {str(e)}', 'error')

    return redirect(return_to)


@app.route('/<target>/kill_sql', methods=['POST'])
def kill_sql(target):
    """Kill all active sessions running given SQL id."""
    sql_id = request.form.get('sql_id', '').strip()
    return_to = request.form.get('return_to') or url_for('get_dml_locks', target=target)
    if not can_manage_database_actions():
        flash('Only administrators can kill database sessions.', 'error')
        return redirect(return_to)

    if not sql_id:
        flash('SQL id is required', 'error')
        return redirect(return_to)
    try:
        rows = execute(target,
                       "select sid, serial# from v$session where sql_id = :sql_id and status = 'ACTIVE'",
                       {'sql_id': sql_id}, fetch_mode='many')
        if not rows:
            flash(f'No active sessions found for SQL ID {sql_id}', 'info')
            return redirect(return_to)
        killed = 0
        errors = []
        for sid, serial in rows:
            try:
                # Use fetch_mode='none' for statements that don't return rows
                execute(target, f"ALTER SYSTEM KILL SESSION '{sid},{serial}' IMMEDIATE", fetch_mode='none', user_context=True)
                killed += 1
            except Exception as e:
                errors.append(f"{sid},{serial}: {str(e)}")
        if killed:
            flash(f'{killed} Sessions for sqlid({sql_id}) marked for kill', 'success')
        if errors:
            flash('Errors: ' + '; '.join(errors), 'error')
    except Exception as e:
        flash(f'Error finding sessions: {str(e)}', 'error')
    return redirect(return_to)


@app.route('/<target>/tab_partitions')
@title('Tab partitions count')
@template('list')
@snail()
@columns({"table_owner": 'str'
          , "table_name": 'str'
          , "count(partition_name) part_count": 'int'
          , "sum(subpartition_count) subpart_count": 'int'})
@select("all_tab_partitions group by table_owner, table_name")
@default_sort("part_count desc")
@default_filters("part_count > 1000 or subpart_count > 1000")
def get_tab_partitions_count(target):
    return render_page()


@app.route('/<target>/ind_partitions')
@title('Ind partitions count')
@template('list')
@snail()
@columns({"index_owner": 'str'
          , "index_name": 'str'
          , "count(partition_name) part_count": 'int'
          , "sum(subpartition_count) subpart_count": 'int'})
@select("all_ind_partitions group by index_owner, index_name")
@default_sort("part_count desc")
@default_filters("part_count > 1000 or subpart_count > 1000")
def get_ind_partitions_count(target):
    return render_page()


@app.route('/<target>/modifications')
@title('Modifications')
@template('list')
@columns({"table_owner": 'str'
         , "table_name": 'str'
         , "partition_name": 'str'
         , "subpartition_name": 'str'
         , "inserts": 'int'
         , "updates": 'int'
         , "deletes": 'int'
         , "timestamp": 'datetime'
         , "truncated": 'str'
         , "drop_segments": 'int'})
@select("all_tab_modifications")
@default_sort("timestamp desc")
@default_filters("timestamp > -1d")
def get_modifications(target):
    return render_page()


@app.route('/<target>/ts_fragmentation')
@title('Tabspace fragmentation')
@template('list')
@snail()
@columns({"t.tablespace_name": 'str'
         , "f.fc free_blocks_count": 'int'
         , "u.uc used_blocks_count": 'int'
         , "round((f.fc / (f.fc + u.uc)) * 100) pct_fragmented": 'int'})
@select("dba_tablespaces t"
        " inner join (select tablespace_name, sum(blocks) fc from dba_free_space group by tablespace_name) f"
        " on f.tablespace_name = t.tablespace_name"
        " inner join (select tablespace_name, sum(blocks) uc from dba_segments group by tablespace_name) u"
        " on u.tablespace_name = t.tablespace_name"
        " where t.contents = 'PERMANENT'")
@default_sort("pct_fragmented desc")
@default_filters("used_blocks_count >= 1000 and pct_fragmented > 30")
def get_ts_fragmentation(target):
    return render_page()


@app.route('/<target>/synonyms')
@title('Synonyms')
@template('list')
@select("dba_synonyms")
@columns({"owner": 'str'
         , "synonym_name": 'str'
         , "table_owner": 'str'
         , "table_name": 'str'
         , "db_link": 'str'})
@default_filters("table_owner not like '%SYS%'")
def get_synonyms(target):
    return render_page()


@app.route('/<target>/segment_usage')
@title('Segment usage')
@template('list')
@select("v$segment_statistics")
@columns({"owner": 'str'
         , "object_name": 'str'
         , "subobject_name": 'str'
         , "tablespace_name": 'str'
         , "object_type": 'str'
         , "statistic_name": 'str'
         , "value": 'int'})
@default_filters(""
                 , "statistic_name = 'segment scans'"
                 , "statistic_name = 'row lock waits'"
                 , "statistic_name like '%read%'"
                 , "statistic_name like '%write%'")
def get_segment_usage(target):
    return render_page()


@app.route('/<target>/index_usage')
@title('Index usage')
@template('list')
@select("dba_index_usage iu left join all_indexes i on i.index_name = iu.name and i.owner = iu.owner")
@columns({"i.table_name": 'str'
          , "iu.owner": 'str'
          , "iu.name": 'str'
          , "i.num_rows": 'int'
          , "iu.total_access_count": 'int'
          , "iu.total_exec_count": 'int'
          , "iu.total_rows_returned": 'int'
          , "iu.last_used": 'datetime'})
@default_filters(""
                 , "table_name like '%FCT%'")
@default_sort("last_used")
def get_index_usage(target):
    return render_page()
