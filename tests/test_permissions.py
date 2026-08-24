import pytest
from app import app
from app.utils.permissions import can_manage_database_actions
from flask import session

def test_permissions_no_admin():
    with app.test_request_context():
        session['user_name'] = 'regular_user'
        app.config['ADMIN_GROUP'] = ['admin']
        assert not can_manage_database_actions()

def test_permissions_admin():
    with app.test_request_context():
        session['user_name'] = 'admin'
        app.config['ADMIN_GROUP'] = ['admin']
        assert can_manage_database_actions()
