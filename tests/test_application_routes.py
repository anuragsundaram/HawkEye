import pytest
from app import app
from flask import session

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test'
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_name'] = 'admin'
        yield client

def test_routes_admin(client):
    # Test admin pages
    response = client.get('/adm/users')
    assert response.status_code == 200
    
    response = client.get('/adm/targets')
    assert response.status_code == 200

def test_login_logout(client):
    response = client.get('/logout')
    assert response.status_code == 302
    
    response = client.get('/login')
    assert response.status_code == 200

def test_change_password_get(client):
    response = client.get('/change_password')
    assert response.status_code == 200
