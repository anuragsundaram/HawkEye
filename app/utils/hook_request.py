from flask import abort, flash, g, redirect, render_template, request, session, url_for

from app import title, view_attr
from app.utils.parse_args import *
from app.utils.permissions import can_manage_database_actions


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
    elif request.view_args['target'] in app.config['USERS'][session['user_name']][1]:
        return None
    else:
        abort(403)


def set_template_context():
    g.title = title
    g.is_admin = can_manage_database_actions()
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
        return render_template('list.html')
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
