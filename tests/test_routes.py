import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_application_routes(client):
    routes = ['/', '/login', '/adm']
    for route in routes:
        response = client.get(route)
        assert response.status_code in [200, 302]
