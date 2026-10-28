from datetime import datetime, timedelta
from urllib.parse import quote

from flask import abort, flash, g, redirect, render_template, request, session, url_for

from app import title, view_attr
from app.utils.parse_args import *
from app.utils.permissions import can_manage_database_actions
from app.utils.targets_store import group_targets_by_database


ADVISOR_DATE_ENDPOINTS = ('get_advisor_tasks', 'get_advisor_findings')


def validate_request():
    app.logger.info(f"{session.get('user_name', 'unknown')} {' '.join(request.access_route)} {request.full_path}")
    if 'favicon.ico' in request.url or 'apple-touch-icon' in request.url:
        return 'not today', 404
    elif not request.endpoint:
        abort(404)
    elif request.endpoint in ('login', 'static'):
        return None
    elif 'user_name' not in session:
        if request.url != request.url_root:
            return redirect(url_for('login', link=request.url))
        else:
            return redirect(url_for('login'))
    elif request.endpoint in app.config['ADMIN_ONLY_VIEWS'] and session['user_name'] not in app.config['ADMIN_GROUP']:
        abort(403)
    elif not request.view_args.get('target'):
        return None
    else:
        user_config = app.config['USERS'].get(session['user_name'], ('', []))
        allowed_targets = user_config[1]
        if allowed_targets and request.view_args['target'] not in allowed_targets:
            abort(403)
        target = app.config['TARGETS'].get(request.view_args['target'], {})
        if target.get('database_type', 'oracle') == 'postgresql' \
                and request.endpoint not in (
                    'get_target',
                    'get_top_activity',
                    'get_sql_monitor',
                    'get_sql_monitor_data',
                    'get_session_monitor',
                    'get_postgresql_top_activity_metrics',
                    'terminate_postgresql_session',
                ):
            abort(501)
        return None


def set_template_context():
    g.title = title
    g.is_admin = can_manage_database_actions()
    g.admin_entry_url = (
        f"{url_for('get_app')}?return_to={quote(request.full_path, safe='')}"
    )
    target = app.config['TARGETS'].get(request.view_args.get('target'), {})
    g.database_type = target.get('database_type', 'oracle')
    all_targets = app.config['TARGETS']
    user_config = app.config['USERS'].get(session.get('user_name', ''), ('', []))
    allowed_targets = user_config[1] or all_targets.keys()
    visible_targets = {
        name: all_targets[name]
        for name in allowed_targets
        if name in all_targets
    }
    g.target_groups = group_targets_by_database(visible_targets)
    for k, v in view_attr[request.endpoint].items():
        setattr(g, k, v)


def render_form():
    if getattr(app.view_functions[request.endpoint], 'template', '') == 'list':
        return render_list()
    else:
        return None


def render_list():
    f = app.view_functions[request.endpoint]
    if 'do' not in request.args and hasattr(f, 'auto'):
        p = {}
        p.update(request.view_args)
        if hasattr(f, 'default_filters') and len(f.default_filters) > 0:
            p['filter'] = f.default_filters[0]
        if hasattr(f, 'default_sort'):
            p['sort'] = f.default_sort
        p['do'] = ''
        return redirect(url_for(request.endpoint, **p))

    if 'do' not in request.args:
        if request.endpoint in ADVISOR_DATE_ENDPOINTS:
            g.execution_start_date = datetime.now().date().isoformat()
        return render_template('list.html')

    if request.endpoint in ADVISOR_DATE_ENDPOINTS:
        date_text = request.args.get('execution_start_date', datetime.now().date().isoformat())
        g.execution_start_date = date_text
        try:
            start_time = datetime.strptime(date_text, '%Y-%m-%d')
        except ValueError:
            flash('Incorrect execution start date')
            return render_template('list.html')

        end_time = start_time + timedelta(days=1)
        g.filter_expr = 'execution_start >= :1 and execution_start < :2'
        g.filter_values = [start_time, end_time]
        g.sort_expr = 'execution_start desc'
        return None

    rf = rs = 0
    rr = ''
    if request.args.get('filter'):
        rf, g.filter_expr, g.filter_values = parse_filter_expr(request.args['filter'], f.columns)
        if rf:
            flash(f'Incorrect filter expression at char: {rf}')
    if request.args.get('sort'):
        rs, g.sort_expr = parse_sort(request.args['sort'], f.columns)
        if rs:
            flash(f'Incorrect sort expression at char: {rs}')
    if g.parameters:
        rr, g.required_values = parse_parameters(request.args, g.parameters)
        if rr:
            flash(f'Incorrect value for required parameter: {rr}')
    if rf or rs or rr:
        return render_template('list.html')
    else:
        return None
