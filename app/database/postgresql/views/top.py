from datetime import datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from flask import jsonify, render_template, request, url_for

from app import app
from app.database.postgresql.adapter import execute

ACTIVITY_SERIES = (
    ('total_sessions', 'Total', '#004AE7', 1, 1),
    ('active_sessions', 'Active', '#00CC00', 1, 1),
    ('idle_sessions', 'Idle', '#9F9371', 1, 1),
    ('transactions_per_second', 'Transactions', '#5C440B', 1, 4),
    ('commits_per_second', 'Commits', '#E46800', 1, 4),
    ('rollbacks_per_second', 'Rollbacks', '#8B1A00', 1, 4),
    ('inserts_per_second', 'Inserts', '#717354', 2, 1),
    ('updates_per_second', 'Updates', '#C02800', 2, 1),
    ('deletes_per_second', 'Deletes', '#C2B79B', 2, 1),
    ('fetched_per_second', 'Fetched', '#004AE7', 2, 3),
    ('returned_per_second', 'Returned', '#F06EAA', 2, 3),
    ('reads_per_second', 'Reads', '#0094E7', 2, 5),
    ('hits_per_second', 'Hits', '#00CC00', 2, 5),
)


def _activity_chart(initial_sample=None):
    chart = make_subplots(
        rows=2,
        cols=6,
        subplot_titles=(
            'Database sessions',
            'Transactions per second',
            'Tuples in per second',
            'Tuples out per second',
            'Block I/O per second',
        ),
        specs=[
            [{'colspan': 3}, None, None, {'colspan': 3}, None, None],
            [{'colspan': 2}, None, {'colspan': 2}, None, {'colspan': 2}, None],
        ],
        vertical_spacing=0.16,
        horizontal_spacing=0.025,
    )
    initial_time = (
        datetime.fromtimestamp(initial_sample['timestamp'])
        if initial_sample else None
    )
    for key, label, color, row, column in ACTIVITY_SERIES:
        initial_value = initial_sample.get(key) if initial_sample else None
        chart.add_trace(
            go.Scatter(
                x=[initial_time] if initial_sample else [],
                y=[initial_value] if initial_sample else [],
                mode='lines',
                name=label,
                legendgroup=f'{row}-{column}',
                line={'color': color, 'width': 1.5},
                hovertemplate=f'{label}: %{{y:.2f}}<extra></extra>',
            ),
            row=row,
            col=column,
        )
    chart.update_layout(
        height=620,
        margin={'l': 58, 'r': 18, 't': 88, 'b': 55},
        paper_bgcolor='white',
        plot_bgcolor='white',
        font={'family': 'Arial', 'size': 12, 'color': '#374151'},
        title={
            'text': (
                f"sessions(max): {initial_sample['total_sessions']}, "
                f"sessions(limit): {initial_sample['session_limit']};"
                if initial_sample else 'PostgreSQL activity'
            ),
            'font': {'size': 14, 'color': '#111827'},
            'x': 0,
            'xanchor': 'left',
        },
        legend={
            'orientation': 'h',
            'yanchor': 'bottom',
            'y': 1.02,
            'xanchor': 'center',
            'x': 0.5,
            'font': {'size': 9, 'color': '#374151'},
            'entrywidth': 78,
            'entrywidthmode': 'pixels',
            'tracegroupgap': 2,
        },
        showlegend=True,
        hovermode='closest',
        uirevision='postgres-top-activity',
    )
    chart.update_xaxes(
        showgrid=True,
        gridcolor='#e5e7eb',
        zeroline=False,
        tickfont={'color': '#374151', 'size': 9},
        tickformat='%H:%M\n%d.%m',
    )
    chart.update_yaxes(
        showgrid=True,
        gridcolor='#e5e7eb',
        zeroline=False,
        tickfont={'color': '#374151', 'size': 9},
    )
    return chart


def get_top_activity(target):
    user_name = request.args.get('user_name', '').strip()
    query_text = request.args.get('query_text', '').strip()
    waits = execute(
        target,
        "select coalesce(wait_event_type || ': ' || wait_event, 'CPU') event, count(*) samples "
        "from pg_stat_activity where backend_type = 'client backend' "
        "and state = 'active' and pid <> pg_backend_pid() "
        "and (:user_name = '' or usename ilike '%%' || :user_name || '%%') "
        "and (:query_text = '' or query ilike '%%' || :query_text || '%%') "
        "group by wait_event_type, wait_event order by samples desc, event limit 10",
        {'user_name': user_name, 'query_text': query_text},
    )
    top_sql = execute(
        target,
        "select md5(query) sql_hash, count(*) samples "
        "from pg_stat_activity where backend_type = 'client backend' "
        "and state = 'active' and pid <> pg_backend_pid() "
        "and (:user_name = '' or usename ilike '%%' || :user_name || '%%') "
        "and (:query_text = '' or query ilike '%%' || :query_text || '%%') "
        "group by md5(query) order by samples desc, sql_hash limit 10",
        {'user_name': user_name, 'query_text': query_text},
    )
    active_sessions = execute(
        target,
        "select pid, datname, usename, application_name, client_addr::text, state, "
        "wait_event_type, wait_event, "
        "extract(epoch from clock_timestamp() - query_start)::bigint runtime_seconds, "
        "left(query, 4000) query_text "
        "from pg_stat_activity "
        "where backend_type = 'client backend' and state = 'active' and pid <> pg_backend_pid() "
        "and (:user_name = '' or usename ilike '%%' || :user_name || '%%') "
        "and (:query_text = '' or query ilike '%%' || :query_text || '%%') "
        "order by query_start asc nulls last limit 100",
        {'user_name': user_name, 'query_text': query_text},
    )
    initial_sample = _get_activity_sample(target, user_name, query_text)

    return render_template(
        'postgresql/top_activity.html',
        waits=waits,
        top_sql=top_sql,
        active_sessions=active_sessions,
        activity_chart=_activity_chart(initial_sample).to_html(
            full_html=False,
            include_plotlyjs=True,
            div_id='postgres-top-activity-chart',
            config={
                'displaylogo': False,
                'responsive': True,
                'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
            },
        ),
        selected_user_name=user_name,
        selected_query_text=query_text,
        metrics_url=url_for(
            'get_postgresql_top_activity_metrics',
            target=target,
            user_name=user_name,
            query_text=query_text,
        ),
        initial_sample=initial_sample,
        activity_series=[series[0] for series in ACTIVITY_SERIES],
    )


@app.route('/<target>/top/activity_data')
def get_postgresql_top_activity_metrics(target):
    if app.config['TARGETS'].get(target, {}).get('database_type') != 'postgresql':
        return jsonify({'error': 'Not found'}), 404
    return get_top_activity_metrics(target)


def get_top_activity_metrics(target):
    return jsonify(_get_activity_sample(
        target,
        request.args.get('user_name', '').strip(),
        request.args.get('query_text', '').strip(),
    ))


def _get_activity_sample(target, user_name='', query_text=''):
    row = execute(
        target,
        "with matching_sessions as ("
        " select state from pg_stat_activity"
        " where backend_type = 'client backend' and pid <> pg_backend_pid()"
        " and (:user_name = '' or usename ilike '%%' || :user_name || '%%')"
        " and (:query_text = '' or query ilike '%%' || :query_text || '%%')"
        "), session_counts as ("
        " select count(*) total_sessions,"
        " count(*) filter (where state = 'active') active_sessions,"
        " count(*) filter (where state = 'idle') idle_sessions"
        " from matching_sessions"
        ")"
        " select s.total_sessions, s.active_sessions, s.idle_sessions,"
        " current_setting('max_connections')::integer session_limit,"
        " d.xact_commit, d.xact_rollback, d.tup_inserted, d.tup_updated,"
        " d.tup_deleted, d.tup_fetched, d.tup_returned, d.blks_read, d.blks_hit,"
        " extract(epoch from coalesce(d.stats_reset, pg_postmaster_start_time())) stats_reset"
        " from session_counts s"
        " join pg_stat_database d on d.datname = current_database()",
        {'user_name': user_name, 'query_text': query_text},
        fetch_mode='one',
    )
    metrics = {
        'total_sessions': row[0],
        'active_sessions': row[1],
        'idle_sessions': row[2],
        'session_limit': row[3],
        'commits': row[4],
        'rollbacks': row[5],
        'inserts': row[6],
        'updates': row[7],
        'deletes': row[8],
        'fetched': row[9],
        'returned': row[10],
        'reads': row[11],
        'hits': row[12],
        'stats_reset': float(row[13].timestamp() if hasattr(row[13], 'timestamp') else row[13]),
    }
    metrics['timestamp'] = datetime.now().timestamp()
    metrics.update(_activity_rates(metrics, None))
    return metrics


def _activity_rates(sample, previous):
    elapsed = (
        max(sample['timestamp'] - previous['timestamp'], 0.001)
        if previous else
        max(sample['timestamp'] - sample['stats_reset'], 0.001)
    )

    def rate(key):
        current = sample[key]
        before = previous[key] if previous else 0
        delta = current - before if current >= before else current
        return delta / elapsed

    commits_per_second = rate('commits')
    rollbacks_per_second = rate('rollbacks')
    return {
        'transactions_per_second': commits_per_second + rollbacks_per_second,
        'commits_per_second': commits_per_second,
        'rollbacks_per_second': rollbacks_per_second,
        'inserts_per_second': rate('inserts'),
        'updates_per_second': rate('updates'),
        'deletes_per_second': rate('deletes'),
        'fetched_per_second': rate('fetched'),
        'returned_per_second': rate('returned'),
        'reads_per_second': rate('reads'),
        'hits_per_second': rate('hits'),
    }
