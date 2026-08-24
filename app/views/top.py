from html import escape
from uuid import uuid4

from flask import flash, redirect, render_template, request, session, url_for
import plotly.graph_objects as go
from datetime import datetime, timedelta

from app import app
from app.utils.decorate_view import *
from app.utils.oracle import execute
from app.utils.parse_args import parse_parameters
from app.utils.permissions import can_manage_database_actions


TUNING_TERMINAL_STATUSES = ("COMPLETED", "ERROR", "FATAL ERROR", "INTERRUPTED", "CANCELLED")
TOP_ACTIVITY_CACHE = {}


def convert_iso_datetime(iso_string):
    """Convert ISO datetime format (2026-05-27T15:00) to expected format (27.05.2026 15:00:00)"""
    if not iso_string or not isinstance(iso_string, str):
        return iso_string
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.strftime('%d.%m.%Y %H:%M:%S')
    except (ValueError, AttributeError):
        return iso_string


def to_iso_datetime(value):
    if not value:
        return value
    if isinstance(value, datetime):
        return value.isoformat(timespec='minutes')
    try:
        return datetime.fromisoformat(value).isoformat(timespec='minutes')
    except (TypeError, ValueError):
        pass
    try:
        return datetime.strptime(value, app.config['DATETIME_FORMAT']).isoformat(timespec='minutes')
    except (TypeError, ValueError):
        return value


def initial_top_activity_state():
    end_datetime = datetime.now().replace(second=0, microsecond=0)
    start_datetime = end_datetime - timedelta(minutes=30)
    return {
        'start_date': start_datetime.isoformat(timespec='minutes'),
        'end_date': end_datetime.isoformat(timespec='minutes'),
        'user_name': '',
        'sql_id': ''
    }


def top_activity_state_key(target):
    return f'top_activity:{target}'


def get_top_activity_state(target):
    key = top_activity_state_key(target)
    state = session.get(key)
    refresh_requested = 'refresh' in request.args
    if not state or refresh_requested:
        state = initial_top_activity_state()
    if 'do' in request.args and not refresh_requested:
        state = {
            'start_date': to_iso_datetime(request.args.get('start_date', state['start_date'])),
            'end_date': to_iso_datetime(request.args.get('end_date', state['end_date'])),
            'user_name': request.args.get('user_name', ''),
            'sql_id': request.args.get('sql_id', '')
        }
    elif 'do' in request.args and refresh_requested:
        state['user_name'] = request.args.get('user_name', '')
        state['sql_id'] = request.args.get('sql_id', '')
    session[key] = state
    session.modified = True
    return state


def top_activity_cache_key(target):
    return session.get('user_name', ''), target, can_manage_database_actions()


def top_activity_context(top_state, optional_values, rendered_activity, top_sql, top_wait_events, top_objects, slow_sql):
    return {
        'default_start_date_iso': top_state['start_date'],
        'default_end_date_iso': top_state['end_date'],
        'selected_user_name': top_state.get('user_name', ''),
        'selected_sql_id': top_state.get('sql_id', ''),
        'top_activity': rendered_activity,
        'top_sql': top_sql if 'sql_id' not in optional_values.keys() else None,
        'top_wait_events': top_wait_events,
        'top_objects': top_objects,
        'slow_sql': slow_sql,
        'can_manage_database': can_manage_database_actions()
    }


def render_top_activity_page(context):
    return render_template('top_activity.html', **context)


def render_plotly_chart(fig, width, height, include_plotlyjs=False, clickable=False, hide_x_axis=False, full_width=False):
    layout = dict(
        margin=dict(l=58, r=18, t=44, b=38),
        paper_bgcolor='white',
        plot_bgcolor='white',
        font=dict(family='Arial', size=12, color='#374151'),
        title=dict(font=dict(size=14, color='#111827')),
        legend=dict(orientation='h', yanchor='top', y=-0.18, xanchor='left', x=0),
        hovermode='closest'
    )
    if full_width:
        layout['autosize'] = True
        layout['height'] = height
    else:
        layout['width'] = width
        layout['height'] = height
    fig.update_layout(**layout)
    fig.update_xaxes(showgrid=True, gridcolor='#e5e7eb', zeroline=False, automargin=True)
    fig.update_yaxes(showgrid=False, zeroline=False, automargin=True)
    if hide_x_axis:
        fig.update_xaxes(showticklabels=False, ticks='', title_text=None)
    post_script = None
    if clickable:
        post_script = """
        document.getElementById('{plot_id}').on('plotly_click', function(data) {
            var url = data.points[0].customdata;
            if (url) window.open(url, '_blank');
        });
        """
    return fig.to_html(full_html=False,
                       include_plotlyjs=include_plotlyjs,
                       post_script=post_script,
                       default_width='100%' if full_width else width,
                       default_height=height,
                       config={
        'displaylogo': False,
        'responsive': full_width,
        'modeBarButtonsToRemove': ['lasso2d', 'select2d']
    })


def top_activity_ash_table(start_date):
    try:
        start_dt = datetime.strptime(start_date, '%d.%m.%Y %H:%M:%S')
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if start_dt.date() < today.date():
            return "dba_hist_active_sess_history"
    except (TypeError, ValueError):
        pass
    return "v$active_session_history"


def table_from_items(title, headers, rows):
    table_class = 'top-objects-table' if title == 'Top Objects' else 'top-wait-events-table' if title == 'Top Wait Events' else ''
    class_attr = f' {table_class}' if table_class else ''
    html = [f'<div class="section-title">{escape(title)}</div>',
            f'<div class="top-activity-list"><table class="rman-table{class_attr}"><thead><tr>']
    html.extend(f'<th>{escape(header)}</th>' for header in headers)
    html.append('</tr></thead><tbody>')
    for row in rows:
        html.append('<tr>')
        for cell in row:
            value, link, css_class = cell
            class_attr = f' class="{escape(css_class)}"' if css_class else ''
            if link:
                html.append(f'<td{class_attr}><a href="{escape(link, quote=True)}" target="_blank">{escape(str(value))}</a></td>')
            else:
                html.append(f'<td{class_attr}>{escape(str(value))}</td>')
        html.append('</tr>')
    html.append('</tbody></table></div>')
    return '\n'.join(html)


def current_top_activity_args(extra=None):
    state = session.get(top_activity_state_key(request.view_args['target']), {})
    args = {
        'start_date': state.get('start_date', request.args.get('start_date', '')),
        'end_date': state.get('end_date', request.args.get('end_date', ''))
    }
    user_name = state.get('user_name', request.args.get('user_name', ''))
    sql_id = state.get('sql_id', request.args.get('sql_id', ''))
    if user_name:
        args['user_name'] = user_name
    if sql_id:
        args['sql_id'] = sql_id
    if extra:
        args.update(extra)
    return args


def parse_activity_time(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return value


def sql_tuning_task_prefix(sql_id):
    return f"OMST_{sql_id[:13]}_".upper()


def terminal_status_sql():
    return "'" + "', '".join(TUNING_TERMINAL_STATUSES) + "'"


def active_tuning_sql_ids(target, sql_ids):
    if not sql_ids:
        return set()
    rows = execute(target,
                   ("select lower(substr(task_name, 6, 13)) sql_id"
                    " from dba_advisor_tasks"
                    " where advisor_name = 'SQL Tuning Advisor'"
                    " and task_name like 'OMST\\_%' escape '\\'"
                    " and upper(status) not in (" + terminal_status_sql() + ")"))
    active = {row[0] for row in rows}
    return {sql_id for sql_id in sql_ids if sql_id.lower() in active}


def has_active_tuning_task(target, sql_id):
    task_prefix = sql_tuning_task_prefix(sql_id)
    row = execute(target,
                  ("select count(1)"
                   " from dba_advisor_tasks"
                   " where advisor_name = 'SQL Tuning Advisor'"
                   " and substr(task_name, 1, :task_prefix_len) = :task_prefix"
                   " and upper(status) not in (" + terminal_status_sql() + ")"),
                  {'task_prefix': task_prefix, 'task_prefix_len': len(task_prefix)},
                  fetch_mode='one')
    return row and row[0] > 0


def tuning_task_is_successful(target, owner, task_name):
    row = execute(target,
                  ("select count(1)"
                   " from dba_advisor_tasks"
                   " where owner = :owner"
                   " and task_name = :task_name"
                   " and advisor_name = 'SQL Tuning Advisor'"
                   " and upper(status) = 'COMPLETED'"),
                  {'owner': owner, 'task_name': task_name},
                  fetch_mode='one')
    return row and row[0] == 1


def render_top_sql_table(target, labels, rows, active_sql_ids, can_run_tuning):
    html = ['<div class="section-title">Top SQL</div>',
            '<div class="top-activity-list"><table class="rman-table top-sql-table"><thead><tr>',
            '<th>SQL id</th><th>Samples</th>']
    if can_run_tuning:
        html.append('<th>Action</th>')
    html.append('</tr></thead><tbody>')
    for label in labels:
        samples = sum(tuple(item[4] for item in rows if item[0] == 2 and item[1] == label))
        query_link = url_for('get_query', target=target, query=label)
        tune_link = url_for('run_sql_tuning_advisor', target=target)
        html.append('<tr>')
        html.append(f'<td><a href="{escape(query_link, quote=True)}" target="_blank">{escape(str(label))}</a></td>')
        html.append(f'<td class="sample-cell">{escape(str(samples))}</td>')
        if can_run_tuning:
            html.append('<td>')
            if label in active_sql_ids:
                html.append('<span class="disabled-action-button" title="A tuning task is already running or pending for this SQL ID">Tune</span>')
            else:
                # Add confirm-tune class so JS shows confirmation before submitting.
                html.append(f'<form class="inline-action-form confirm-tune" method="post" action="{escape(tune_link, quote=True)}" data-sqlid="{escape(str(label), quote=True)}">')
                html.append(f'<input type="hidden" name="sql_id" value="{escape(str(label), quote=True)}">')
                html.append(f'<input type="hidden" name="return_to" value="{escape(request.full_path, quote=True)}">')
                html.append('<input type="submit" value="Tune">')
                html.append('</form>')
            html.append('</td>')
        html.append('</tr>')
    html.append('</tbody></table></div>')
    return '\n'.join(html)


@app.route('/<target>/tuning_advisor/run', methods=['POST'])
@title('Run SQL tuning advisor')
def run_sql_tuning_advisor(target):
    sql_id = request.form.get('sql_id', '').strip()
    return_to = request.form.get('return_to') or url_for('get_top_activity', target=target)
    if not can_manage_database_actions():
        flash('Only administrators can run SQL tuning advisor.', 'error')
        return redirect(return_to)

    if not sql_id:
        flash('SQL id is required')
        return redirect(return_to)
    if has_active_tuning_task(target, sql_id):
        flash(f'A tuning advisor task is already running or pending for SQL ID {sql_id}')
        return redirect(return_to)

    task_name = f"OMST_{sql_id[:13]}_{uuid4().hex[:8]}".upper()
    job_name = f"OMJ_{sql_id[:13]}_{uuid4().hex[:8]}".upper()
    try:
        execute(target,
                ("declare "
                 "  l_task_name varchar2(128); "
                 "begin "
                 "  l_task_name := dbms_sqltune.create_tuning_task("
                 "      sql_id => :sql_id,"
                 "      time_limit => 300,"
                 "      task_name => :task_name,"
                 "      description => 'Oracle Monitoring SQL tuning advisor task for SQL ID ' || :sql_id); "
                 "  dbms_scheduler.create_job("
                 "      job_name => :job_name,"
                 "      job_type => 'PLSQL_BLOCK',"
                 "      job_action => 'begin dbms_sqltune.execute_tuning_task(task_name => ''' ||"
                 "                    replace(l_task_name, '''', '''''') || '''); end;',"
                 "      enabled => true,"
                 "      auto_drop => true); "
                 "end;"),
                {'sql_id': sql_id, 'task_name': task_name, 'job_name': job_name},
                fetch_mode='none')
        flash(f'Tuning advisor task {task_name} started for SQL ID {sql_id}')
    except Exception as e:
        flash(str(e))
    return redirect(url_for('get_tuning_advisor', target=target))


@app.route('/<target>/tuning_advisor')
@title('Tuning Advisor')
def get_tuning_advisor(target):
    from_date = request.args.get('from_date', datetime.now().strftime('%Y-%m-%d'))
    till_date = request.args.get('till_date', datetime.now().strftime('%Y-%m-%d'))
    try:
        datetime.strptime(from_date, '%Y-%m-%d')
        datetime.strptime(till_date, '%Y-%m-%d')
    except ValueError:
        flash('Incorrect date format')
        from_date = datetime.now().strftime('%Y-%m-%d')
        till_date = datetime.now().strftime('%Y-%m-%d')
    tasks = execute(target,
                    ("select owner, task_name, created, execution_start, execution_end, status,"
                     " case"
                     "   when upper(status) = 'EXECUTING' then 'Running'"
                     "   when upper(status) = 'COMPLETED' then 'Successful'"
                     "   when upper(status) in ('ERROR', 'FATAL ERROR', 'INTERRUPTED', 'CANCELLED') then 'Failed'"
                     "   else initcap(status)"
                     " end display_status,"
                     " description, status_message"
                     " from dba_advisor_tasks"
                     " where advisor_name = 'SQL Tuning Advisor'"
                     " and created >= to_date(:from_date, 'yyyy-mm-dd')"
                     " and created < to_date(:till_date, 'yyyy-mm-dd') + 1"
                     " order by created desc"),
                    {'from_date': from_date, 'till_date': till_date})
    return render_template('tuning_advisor.html', from_date=from_date, till_date=till_date, tasks=tasks)


@app.route('/<target>/tuning_advisor/report')
@title('Tuning Advisor Report')
def get_tuning_advisor_report(target):
    owner = request.args.get('owner', '')
    task_name = request.args.get('task_name', '')
    if not owner or not task_name:
        flash('Task owner and name are required')
        return render_template('tuning_advisor_report.html', task_name=task_name, report=None)
    if not tuning_task_is_successful(target, owner, task_name):
        flash('Report is available only after the tuning task is successful')
        return render_template('tuning_advisor_report.html', task_name=task_name, report=None)
    try:
        report = execute(target,
                         "dbms_sqltune.report_tuning_task",
                         {'task_name': task_name,
                          'type': 'TEXT',
                          'level': 'ALL',
                          'owner_name': owner},
                         fetch_mode='func')
    except Exception as e:
        flash(str(e))
        report = None
    return render_template('tuning_advisor_report.html', task_name=task_name, report=report)


@app.route('/<target>/object')
@title('Object')
def get_object_detail(target):
    owner = request.args.get('owner', '')
    object_type = request.args.get('object_type', '')
    object_name = request.args.get('object_name', '')
    if not owner or not object_type or not object_name:
        flash('Object owner, type and name are required')
        return render_template('object_detail.html', rows=None, object_links=[])

    rows = execute(target,
                   "select owner, object_name, subobject_name, object_type, status,"
                   " created, last_ddl_time, temporary, generated"
                   " from all_objects"
                   " where owner = :owner and object_type = :object_type and object_name = :object_name"
                   " order by subobject_name",
                   {'owner': owner, 'object_type': object_type, 'object_name': object_name})
    object_links = []
    if object_type == 'TABLE':
        object_links.append(('Table details', url_for('get_table', target=target, owner=owner, table=object_name)))
        object_links.append(('Columns', url_for('get_table_columns', target=target, owner=owner, table=object_name)))
        object_links.append(('Indexes', url_for('get_table_indexes', target=target, owner=owner, table=object_name)))
    elif object_type == 'VIEW':
        object_links.append(('View details', url_for('get_view', target=target, owner=owner, view=object_name)))
        object_links.append(('Columns', url_for('get_view_columns', target=target, owner=owner, view=object_name)))
        object_links.append(('Text', url_for('get_view_text', target=target, owner=owner, view=object_name)))
    return render_template('object_detail.html', rows=rows, object_links=object_links)


@app.route('/<target>/top/wait_event')
@title('Wait event SQL')
def get_top_wait_event_sql(target):
    required_source = {'start_date': convert_iso_datetime(request.args.get('start_date', ''))
                       , 'end_date': convert_iso_datetime(request.args.get('end_date', ''))}
    required = {'start_date': 'datetime'
                , 'end_date': 'datetime'}
    error, required_values = parse_parameters(required_source, required)
    if error:
        flash(f'Incorrect value: {error}')
        return render_template('top_wait_event_sql.html', event=request.args.get('event', ''), rows=None)

    optional_source = {'event': request.args.get('event', '')
                       , 'user_name': request.args.get('user_name', '')
                       , 'sql_id': request.args.get('sql_id', '')}
    optional = {'event': 'str'
                , 'user_name': 'str'
                , 'sql_id': 'str'}
    error, values = parse_parameters(optional_source, optional, True)
    if error or not values.get('event'):
        flash(f'Incorrect value: {error}' if error else 'Event is required')
        return render_template('top_wait_event_sql.html', event=request.args.get('event', ''), rows=None)
    values = {k: v for k, v in values.items() if v}
    ash_table = top_activity_ash_table(required_values['start_date'])
    rows = execute(target,
                   ("with h as ("
                    " select sql_id, count(1) samples from {} ash"
                    " where sample_time >= trunc(:start_date, 'mi') and sample_time < trunc(:end_date, 'mi')"
                    " and nvl(event, 'CPU') = :event"
                    "{}{}"
                    " and sql_id is not null"
                    " group by sql_id)"
                    " select h.sql_id,"
                    " nvl(substr(max(sa.sql_text), 1, 1000),"
                    "     nvl(max(dbms_lob.substr(ht.sql_text, 1000, 1)), 'SQL text not found')) sql_text,"
                    " h.samples"
                    " from h"
                    " left join v$sqlarea sa on sa.sql_id = h.sql_id"
                    " left join dba_hist_sqltext ht on ht.sql_id = h.sql_id"
                    " group by h.sql_id, h.samples"
                    " order by h.samples desc, h.sql_id").format(
                       ash_table,
                       " and sql_id = :sql_id" if values.get('sql_id', '') else "",
                       " and user_id in (select user_id from dba_users where username like :user_name)"
                       if values.get('user_name', '') else ""),
                   {**required_values, **values})
    return render_template('top_wait_event_sql.html', event=values['event'], rows=rows)


@app.route('/<target>/top')
@title('Top activity')
def get_top_activity(target):
    top_state = get_top_activity_state(target)
    default_start_date_iso = top_state['start_date']
    default_end_date_iso = top_state['end_date']
    required_source = {'start_date': convert_iso_datetime(top_state['start_date'])
                       , 'end_date': convert_iso_datetime(top_state['end_date'])}
    required = {'start_date': 'datetime'
                , 'end_date': 'datetime'}
    error, required_values = parse_parameters(required_source, required)
    if error:
        flash(f'Incorrect value: {error}')
        return render_template('top_activity.html'
                               , default_start_date_iso=default_start_date_iso
                               , default_end_date_iso=default_end_date_iso
                               , can_manage_database=can_manage_database_actions())
    optional_source = {'user_name': top_state.get('user_name', '')
                       , 'sql_id': top_state.get('sql_id', '')}
    _optional = {'user_name': 'str'
                 , 'sql_id': 'str'}
    error, optional_values = parse_parameters(optional_source, _optional, True)
    if error:
        flash(f'Incorrect value: {error}')
        return render_template('top_activity.html', can_manage_database=can_manage_database_actions())
    optional_values = {k: v for k, v in optional_values.items() if v}

    cache_key = top_activity_cache_key(target)
    force_reload = 'do' in request.args or 'refresh' in request.args
    cached = TOP_ACTIVITY_CACHE.get(cache_key)
    if cached and not force_reload and cached.get('state') == top_state:
        # ensure slow running SQL list is fresh even when other parts are cached
        try:
            fresh_slow_sql = execute(target,
                "select * from ("
                "  select sql_id, nvl(sql_text,'SQL text not found') sql_text,"
                "    floor(elapsed_secs/60) || 'm ' || mod(elapsed_secs,60) || 's' runtime,"
                "    sessions"
                "  from ("
                "    select sql_id, sql_text, elapsed_secs, cnt sessions,"
                "      row_number() over (partition by sql_id order by elapsed_secs desc) rn"
                "    from ("
                "      select s.sql_id, coalesce(dbms_lob.substr(q.sql_fulltext,4000,1), substr(q.sql_text,1,4000), '-') sql_text,"
                "        case when s.sql_exec_start is not null then round((sysdate - s.sql_exec_start) * 86400) else s.last_call_et end elapsed_secs,"
                "        count(*) over (partition by s.sql_id) cnt"
                "      from v$session s"
                "      left join v$sql q on q.sql_id = s.sql_id and q.child_number = s.sql_child_number"
                "      where s.status = 'ACTIVE' and s.type = 'USER' and s.sql_id is not null"
                "    )"
                "  ) where rn = 1"
                "  order by elapsed_secs desc"
                ") where rownum <= 5",
                )
            cached['context']['slow_sql'] = fresh_slow_sql
        except Exception:
            pass
        return render_top_activity_page(cached['context'])
    
    ash_table = top_activity_ash_table(required_values['start_date'])
    
    sql_query = ("with h as (select sample_id, sample_time,"
                  " sql_id, o.owner, o.object_name, o.object_type, event, event_id, user_id, session_id,"
                  " to_char(session_id) || ':' || to_char(session_serial#) sess"
                  ", nvl(wait_class, 'CPU') wait_class"
                  ", nvl(wait_class_id, -1) wait_class_id"
                  ", wait_time, time_waited from {} ash"
                  " left join dba_objects o on o.object_id = ash.current_obj#"
                  " where sample_time >= trunc(:start_date, 'mi') and sample_time < trunc(:end_date, 'mi')"
                  "{}{})"
                  " select 1 t, to_char(trunc(sample_time, 'mi'), 'yyyy-mm-dd hh24:mi:ss') s,"
                  " wait_class v1, wait_class_id v2, count(1) c"
                  " from h group by trunc(sample_time, 'mi'), wait_class, wait_class_id union all"
                  " select 2 t, sql_id s, wait_class v1, wait_class_id v2, count(1) c from h"
                  " where sql_id is not null and sql_id in (select sql_id"
                  " from (select sql_id, row_number() over (order by tc desc) rn"
                  " from (select sql_id, count(1) tc from h"
                  " where sql_id is not null group by sql_id)) where rn <= 10)"
                  " group by sql_id, wait_class, wait_class_id union all"
                  " select 6 t, to_char(h.session_id) || ':' || nvl(u.username, '') s,"
                  " wait_class v1, wait_class_id v2, count(1) c from h"
                  " left join dba_users u on u.user_id = h.user_id"
                  " where sess in (select sess"
                  " from (select sess, row_number() over (order by tc desc) rn"
                  " from (select sess, count(1) tc from h"
                  " group by sess)) where rn <= 10)"
                  " group by to_char(h.session_id) || ':' || nvl(u.username, ''), wait_class, wait_class_id union all"
                  " select 3 t, owner || '|' || object_type || '|' || object_name s,"
                  " wait_class v1, wait_class_id v2, count(1) c from h"
                  " where object_name is not null and owner || '|' || object_type || '|' || object_name in ("
                  " select object_key from (select object_key, row_number() over (order by tc desc) rn"
                  " from (select owner || '|' || object_type || '|' || object_name object_key, count(1) tc from h"
                  " where object_name is not null group by owner, object_type, object_name))"
                  " where rn <= 10) group by owner, object_type, object_name, wait_class, wait_class_id union all"
                  " select 4 t, null s, wait_class v1, wait_class_id v2, count(1) c"
                  " from h group by wait_class, wait_class_id union all"
                  " select 5 t, null s, nvl(event, 'CPU') v1, nvl(wait_class_id, -1) v2, count(1) c"
                  " from h group by nvl(event, 'CPU'), nvl(wait_class_id, -1) union all"
                  " select 7 t, to_char(sample_time, 'hh24:mi:ss') s, null v1, null v2, count(distinct session_id) c"
                  " from h group by to_char(sample_time, 'hh24:mi:ss') union all"
                  " select 8 t, null s, null v1, null v2, to_number(value) c"
                  " from v$parameter where name = 'cpu_count' union all"
                  " select 9 t, null s, null v1, null v2, to_number(value) c"
                  " from v$parameter where name = 'sessions' order by 1, 4, 2"
                  ).format(ash_table
                  , " and sql_id = :sql_id" if optional_values.get('sql_id', '') else ""
                  , " and user_id in (select user_id from dba_users where username like :user_name)" if optional_values.get('user_name', '') else ""
                  )
    
    r = execute(target, sql_query, {**required_values, **optional_values})
    colors = {'Other': '#F06EAA'
              , 'Application': '#C02800'
              , 'Configuration': '#5C440B'
              , 'Administrative': '#717354'
              , 'Concurrency': '#8B1A00'
              , 'Commit': '#E46800'
              , 'Idle': '#FFFFFF'
              , 'Network': '#9F9371'
              , 'User I/O': '#004AE7'
              , 'System I/O': '#0094E7'
              , 'Scheduler': '#CCFFCC'
              , 'Queueing': '#C2B79B'
              , 'CPU': '#00CC00'}

    series = {k[1]: [] for k in sorted(set((item[3], item[2]) for item in r if item[0] == 1), key=lambda x: x[0])}
    session_count = max(tuple(item[4] for item in r if item[0] == 7) or (0,))
    session_limit = max(tuple(item[4] for item in r if item[0] == 9) or (0,))
    cpu_count = max(tuple(item[4] for item in r if item[0] == 8) or (0,))
    top_activity = go.Figure()
    activity_labels = sorted(set(item[1] for item in r if item[0] == 1), key=parse_activity_time)
    activity_times = [parse_activity_time(label) for label in activity_labels]
    for label in activity_labels:
        for serie in series.keys():
            v = tuple(item[4] for item in r if item[0] == 1 and item[1] == label and item[2] == serie)
            series[serie].append(v[0] if len(v) > 0 else 0)
    for serie in series.keys():
        top_activity.add_trace(go.Scatter(
            x=activity_times,
            y=series[serie],
            mode='lines',
            name=serie,
            stackgroup='activity',
            line=dict(width=1.4, color=colors[serie], shape='spline'),
            hovertemplate='%{x|%d.%m %H:%M}<br>%{y} sessions<extra>' + serie + '</extra>'
        ))
    top_activity.update_layout(title=f'sessions(max): {session_count}, '
                                     f'sessions(limit): {session_limit}, '
                                     f'cpu cores: {cpu_count};')
    top_activity.update_xaxes(type='date', tickformat='%H:%M\n%d.%m')

    top_sql_labels = sorted(set(item[1] for item in r if item[0] == 2),
                            key=lambda x: (-sum(tuple(item[4] for item in r if item[0] == 2 and item[1] == x)), x))
    can_manage_database = can_manage_database_actions()
    top_sql = render_top_sql_table(
        target,
        top_sql_labels,
        r,
        active_tuning_sql_ids(target, top_sql_labels) if can_manage_database else set(),
        can_manage_database)

    top_object_labels = sorted(set(item[1] for item in r if item[0] == 3)
                               , key=lambda x: (-sum(tuple(item[4] for item in r if item[0] == 3 and item[1] == x)), x))
    top_object_rows = []
    for label in top_object_labels:
        owner, object_type, object_name = label.split('|', 2)
        total_samples = sum(tuple(item[4] for item in r if item[0] == 3 and item[1] == label))
        link = url_for('get_object_detail', target=target, owner=owner, object_type=object_type, object_name=object_name)
        top_object_rows.append(((f'{owner}.{object_name}', link, ''),
                                (object_type, None, ''),
                                (total_samples, None, 'number-cell')))
    top_objects = table_from_items('Top Objects', ('Object', 'Type', 'Samples'), top_object_rows)

    wait_event_totals = {}
    for item in r:
        if item[0] == 5:
            wait_event_totals[item[2]] = wait_event_totals.get(item[2], 0) + item[4]
    top_wait_event_labels = sorted(wait_event_totals.keys(), key=lambda x: (-wait_event_totals[x], x))[:10]
    top_wait_events = table_from_items(
        'Top Wait Events',
        ('Event', 'Samples'),
        [((label, url_for('get_top_wait_event_sql', target=target,
                          **current_top_activity_args({'event': label})), ''),
          (wait_event_totals[label], None, 'number-cell'))
         for label in top_wait_event_labels])

    # Top 5 slow running SQL (ordered by runtime_seconds desc)
    slow_sql = execute(target,
        "select * from ("
        "  select sql_id, nvl(sql_text,'SQL text not found') sql_text,"
        "    floor(elapsed_secs/60) || 'm ' || mod(elapsed_secs,60) || 's' runtime,"
        "    sessions"
        "  from ("
        "    select sql_id, sql_text, elapsed_secs, cnt sessions,"
        "      row_number() over (partition by sql_id order by elapsed_secs desc) rn"
        "    from ("
        "      select s.sql_id, coalesce(dbms_lob.substr(q.sql_fulltext,4000,1), substr(q.sql_text,1,4000), '-') sql_text,"
        "        case when s.sql_exec_start is not null then round((sysdate - s.sql_exec_start) * 86400) else s.last_call_et end elapsed_secs,"
        "        count(*) over (partition by s.sql_id) cnt"
        "      from v$session s"
        "      left join v$sql q on q.sql_id = s.sql_id and q.child_number = s.sql_child_number"
        "      where s.status = 'ACTIVE' and s.type = 'USER' and s.sql_id is not null"
        "    )"
        "  ) where rn = 1"
        "  order by elapsed_secs desc"
        ") where rownum <= 5",
        )

    context = top_activity_context(
        top_state,
        optional_values,
        render_plotly_chart(top_activity, 1180, 340, True, full_width=True),
        top_sql,
        top_wait_events,
        top_objects,
        slow_sql)
    TOP_ACTIVITY_CACHE[cache_key] = {'state': dict(top_state), 'context': context}
    return render_top_activity_page(context)
