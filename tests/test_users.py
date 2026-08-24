import pytest
from app.utils.users_store import add_user, delete_user, list_users, init_db
import os

def test_user_management():
    # Ensure fresh DB or temporary file for tests?
    # Since init_db uses a constant, might be better to mock or use test-specific path
    # Let's see if we can at least test adding a user
    
    # We should probably refactor users_store to accept DB path for testing.
    # But user requested "dont change any code apart from test cases".
    # This is tricky without refactoring.
    
    # Assuming standard run environment is okay if we cleanup
    init_db()
    add_user('testuser', 'testpass')
    users = list_users()
    assert any(u['username'] == 'testuser' for u in users)
    delete_user('testuser')
    users = list_users()
    assert not any(u['username'] == 'testuser' for u in users)
