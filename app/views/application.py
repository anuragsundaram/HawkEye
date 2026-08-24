from os import path
from platform import platform
from time import sleep

import oracledb
from flask import abort, flash, redirect, render_template, request, send_file, session, url_for

from app import active_connections, app, lock, startup_time, target_pool
from app.utils.decorate_view import *
from app.utils.targets_store import list_targets, add_target, delete_target, get_targets_dict
from app.utils.users_store import set_user_targets, list_users, get_users_dict
from app.utils.oracle import ping


@app.route('/login', methods=['GET', 'POST'])
@title('Login')
def login():
    if not app.config['TARGETS'] or not app.config['USERS']:
        flash('It seems the app is not configured.')
    if request.method == 'GET':
        if 'user_name' in session:
            return redirect(request.args.get('link', url_for('get_welcome_page')))
        else:
            return render_template('login.html')
    if request.method == 'POST':
        if request.form['name'] and request.form['password']:
            uname = request.form['name'].lower()
            pwd = request.form['password']
            # verify using users_store hashed passwords
            from app.utils.users_store import verify_password
            if verify_password(uname, pwd):
                session['user_name'] = uname
                session.permanent = app.config['PERMANENT_USER_SESSION']
                return redirect(request.args.get('link', url_for('get_welcome_page')))
            else:
                flash('Username or Password Invalid')
                return render_template('login.html')
        else:
            return render_template('login.html')


@app.route('/')
def get_welcome_page():
    return render_template('welcome.html')


@app.route('/get_user')
def get_user():
    return render_template('layout.html')


@app.route('/adm')
@title('Administration')
def get_app():
    # Redirect to targets admin page (manage DB targets is the new admin)
    return redirect(url_for('get_targets_admin'))


@app.route('/adm/targets', methods=['GET'])
@title('DB Targets')
def get_targets_admin():
    targets = list_targets()
    # Determine connection status for each target
    statuses = {}
    for t in targets:
        try:
            st = ping(t['name'])
            statuses[t['name']] = 'connected' if st == 0 else 'disconnected'
        except Exception:
            statuses[t['name']] = 'disconnected'
    return render_template('administration_targets.html', targets=targets, statuses=statuses)


@app.route('/adm/targets/add', methods=['POST'])
@title('DB Targets')
def post_targets_add():
    name = request.form.get('name')
    host = request.form.get('host')
    port = int(request.form.get('port') or 1521)
    sid = request.form.get('sid')
    service = request.form.get('service')
    encoding = request.form.get('encoding')
    user = request.form.get('user')
    password = request.form.get('password')
    # Basic validation
    if not name or not host or not user:
        flash('Name, host and user are required', 'error')
        return redirect(url_for('get_targets_admin'))
    if not password:
        flash('Password is required for the target', 'error')
        return redirect(url_for('get_targets_admin'))
    try:
        add_target(name, host, port, sid, service, encoding, user, password)
        # reload app config TARGETS
        with lock:
            app.config['TARGETS'] = get_targets_dict()
        # Auto-grant admin user access to the new target
        admin_users = [u for u in list_users() if u['is_admin']]
        for admin_user in admin_users:
            current_targets = admin_user['targets']
            if name not in current_targets:
                current_targets.append(name)
                set_user_targets(admin_user['username'], current_targets)
        # Reload USERS config for any active admin
        users_dict, admins = get_users_dict()
        with lock:
            app.config['USERS'] = users_dict
            app.config['ADMIN_GROUP'] = admins
        session['show_target_success'] = True
    except Exception as e:
        flash(f'Error adding target: {str(e)}', 'error')
    return redirect(url_for('get_targets_admin'))



@app.route('/adm/targets/edit/<name>', methods=['GET'])
@title('DB Targets')
def get_targets_edit(name):
    targets = list_targets()
    target = next((t for t in targets if t['name'] == name), None)
    if not target:
        flash(f'Target {name} not found', 'error')
        return redirect(url_for('get_targets_admin'))
    return render_template('administration_targets_edit.html', target=target)


@app.route('/adm/targets/update', methods=['POST'])
@title('DB Targets')
def post_targets_update():
    orig_name = request.form.get('orig_name')
    name = request.form.get('name')
    host = request.form.get('host')
    port = int(request.form.get('port') or 1521)
    sid = request.form.get('sid')
    service = request.form.get('service')
    encoding = request.form.get('encoding')
    user = request.form.get('user')
    password = request.form.get('password')
    if not orig_name:
        flash('Original target name missing', 'error')
        return redirect(url_for('get_targets_admin'))
    if not name or not host or not user:
        flash('Name, host and user are required', 'error')
        return redirect(url_for('get_targets_admin'))
    # password may be empty — only update if provided
    try:
        # If name changed, delete old record
        if orig_name != name:
            delete_target(orig_name)
        add_target(name, host, port, sid, service, encoding, user, password or '')

        # Ensure all admin users have access to this target
        admin_users = [u for u in list_users() if u['is_admin']]
        for admin_user in admin_users:
            current_targets = admin_user['targets']
            # Remove old name if renamed
            if orig_name != name and orig_name in current_targets:
                current_targets.remove(orig_name)
            # Add new/current name if not already there
            if name not in current_targets:
                current_targets.append(name)
            set_user_targets(admin_user['username'], current_targets)

        with lock:
            app.config['TARGETS'] = get_targets_dict()
        # Reload USERS config
        users_dict, admins = get_users_dict()
        with lock:
            app.config['USERS'] = users_dict
            app.config['ADMIN_GROUP'] = admins
        flash(f'Target {name} updated', 'success')
    except Exception as e:
        flash(f'Error updating target: {str(e)}', 'error')
    return redirect(url_for('get_targets_admin'))


@app.route('/adm/targets/delete/<name>', methods=['POST'])
@title('DB Targets')
def post_targets_delete(name):
    try:
        delete_target(name)
        for user in list_users():
            user_targets = [target for target in user['targets'] if target != name]
            if user_targets != user['targets']:
                set_user_targets(user['username'], user_targets)
        users_dict, admins = get_users_dict()
        with lock:
            app.config['TARGETS'] = get_targets_dict()
            app.config['USERS'] = users_dict
            app.config['ADMIN_GROUP'] = admins
        flash(f'Target {name} removed', 'success')
    except Exception as e:
        flash(f'Error deleting target: {str(e)}', 'error')
    return redirect(url_for('get_targets_admin'))


@app.route('/cancel_sql')
def cancel_sql():
    try:
        with lock:
            active_connections[request.args['id']][5] = 'Cancelling...'
            active_connections[request.args['id']][0].cancel()
    except KeyError:
        pass
    sleep(1)
    return redirect(url_for('get_app'))


@app.route('/logout')
@title('Log out')
def logout():
    session.pop('user_name', None)
    return redirect(url_for('login'))


@app.route('/change_password', methods=['GET', 'POST'])
@title('Change Password')
def change_password():
    from app.utils.users_store import get_users_dict
    users_dict, admins = get_users_dict()
    
    if 'user_name' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'GET':
        return render_template('change_password.html', get_users_dict=get_users_dict)
    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not new_password or not confirm_password:
            flash('All passwords are required', 'error')
            return redirect(url_for('change_password'))

        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return redirect(url_for('change_password'))

        from app.utils.users_store import verify_password, set_user_password, get_users_dict, validate_password_complexity
        
        is_valid, msg = validate_password_complexity(new_password)
        if not is_valid:
            session['show_password_error'] = msg
            # Redirecting preserves the session flag. But for change_password, it handles template direct return?
            # Flash is still useful if we aren't handling session['show_password_error'] in change_password.html
            # Let's see if change_password route uses redirect here.
            return redirect(url_for('change_password'))

        uname = session['user_name']
        users_dict, admins = get_users_dict()
        
        # Admins don't need to provide old password
        if uname in admins or verify_password(uname, old_password):
            set_user_password(uname, new_password)
            return render_template('change_password.html', show_success=True, get_users_dict=get_users_dict)
        else:
            flash('Current Password Invalid')
            return redirect(url_for('change_password'))


@app.route('/adm/users', methods=['GET'])
@title('Manage Users')
def get_users_admin():
    from app.utils.users_store import list_users
    users = list_users()
    return render_template('administration_users.html', users=users)


@app.route('/adm/users/add', methods=['POST'])
@title('Manage Users')
def post_users_add():
    from app.utils.users_store import add_user, get_users_dict, list_users
    username = request.form.get('username', '').lower().strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'user')

    if not username or not password:
        flash('Username and password are required', 'error')
        return redirect(url_for('get_users_admin'))

    # Check if user already exists
    existing_users = [u['username'] for u in list_users()]
    if username in existing_users:
        flash(f'User {username} already exists', 'error')
        return redirect(url_for('get_users_admin'))
        
    from app.utils.users_store import validate_password_complexity
    is_valid, msg = validate_password_complexity(password)
    if not is_valid:
        session['show_password_error'] = msg
        return redirect(url_for('get_users_admin'))

    try:
        is_admin = role == 'admin'
        add_user(username, password, targets=[], is_admin=is_admin)
        # Reload USERS and ADMIN_GROUP in app config
        users_dict, admins = get_users_dict()
        with lock:
            app.config['USERS'] = users_dict
            app.config['ADMIN_GROUP'] = admins
        flash(f'User {username} added as {role}', 'success')
    except Exception as e:
        flash(f'Error adding user: {str(e)}', 'error')
    return redirect(url_for('get_users_admin'))


@app.route('/adm/users/delete/<username>', methods=['POST'])
@title('Manage Users')
def post_users_delete(username):
    from app.utils.users_store import delete_user, get_users_dict

    # Prevent deleting current user
    if username == session.get('user_name'):
        flash('Cannot delete your own user account', 'error')
        return redirect(url_for('get_users_admin'))

    try:
        delete_user(username)
        # Reload USERS and ADMIN_GROUP in app config
        users_dict, admins = get_users_dict()
        with lock:
            app.config['USERS'] = users_dict
            app.config['ADMIN_GROUP'] = admins
        flash(f'User {username} deleted', 'success')
    except Exception as e:
        flash(f'Error deleting user: {str(e)}', 'error')
    return redirect(url_for('get_users_admin'))


@app.route('/adm/users/password', methods=['POST'])
@title('Manage Users')
def post_users_password():
    from app.utils.users_store import set_user_password, get_users_dict

    # Check if admin
    users_dict, admins = get_users_dict()
    is_admin = session.get('user_name') in admins
    username = request.form.get('username')
    new_password = request.form.get('password')

    # Allow admin to change anyone's password OR allow user to change their own with old password verification
    if not is_admin and username != session.get('user_name'):
        flash('Permission denied', 'error')
        return redirect(url_for('get_users_admin'))

    # If the user is NOT an admin, or if an admin is changing someone else's password, 
    # we might still want to optionally check old password if specified in the form.
    # For now, let's keep the business logic simple:
    # If admin changing own password: simple set.
    # If user changing own password: simple change_password route exists, use that.
    # If admin changing someone else's password: simple set.

    if not username or not new_password:
        flash('Username and password are required', 'error')
        return redirect(url_for('get_users_admin'))
        
    from app.utils.users_store import validate_password_complexity
    is_valid, msg = validate_password_complexity(new_password)
    if not is_valid:
        session['show_password_error'] = msg
        return redirect(url_for('get_users_admin'))

    try:
        set_user_password(username, new_password)
        # Use an admin-specific session flag to trigger modal
        session['show_password_success'] = username
    except Exception as e:
        flash(f'Error updating password: {str(e)}', 'error')
    return redirect(url_for('get_users_admin'))


@app.route('/stop_server')
@title('Shutdown server')
def stop_server():
    with lock:
        app.config['TARGETS'].clear()
        app.config['USERS'].clear()
    with lock:
        for c in active_connections:
            try:
                c.cancel()
            except (DatabaseError, OperationalError):
                pass
    f = request.environ.get('werkzeug.server.shutdown')
    if f:
        f()
        return 'Good bye.'
    elif request.environ.get('uwsgi.version'):
        import uwsgi
        uwsgi.stop()
        return 'Good bye.'
    else:
        return 'Web server does not recognized, kill it manually.'


@app.route('/error_log')
@title('View error log')
def get_error_log():
    file = path.join(path.dirname(path.dirname(path.abspath(__file__))), 'logs', app.config['ERROR_LOG_NAME'])
    if not path.exists(file):
        abort(404)
    return send_file(file, mimetype='text/plain', cache_timeout=0)


@app.route('/access_log')
@title('View access log')
def get_access_log():
    file = path.join(path.dirname(path.dirname(path.abspath(__file__))), 'logs', app.config['ACCESS_LOG_NAME'])
    if not path.exists(file):
        abort(404)
    return send_file(file, mimetype='text/plain', cache_timeout=0)




@app.route('/<target>/search')
@title('Search')
def search(target):
    text = request.args['text'].replace(' ', '')
    if len(text) <= 4 and text.isdigit():
        return redirect(url_for('get_session', target=target, sid=text))
    else:
        return redirect(url_for('get_query', target=target, query=text))
