from flask import session

from app import app


def can_manage_database_actions():
    return session.get('user_name') in app.config.get('ADMIN_GROUP', [])
