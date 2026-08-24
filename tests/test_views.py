import pytest
from app import app as flask_app

@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        yield client

def test_login_page(client):
    response = client.get('/login')
    assert response.status_code == 200

def test_welcome_page(client):
    # This might redirect to login if no session
    response = client.get('/')
    # If it redirects, status 302
    assert response.status_code in [200, 302]
