import pytest
from app import app
from app.utils.oracle import ping
from unittest.mock import patch

def test_ping_failure():
    # Test ping with a non-existent target
    with app.test_request_context():
        app.config['TARGETS'] = {'dummy': {'host': 'localhost', 'user': 'test', 'password': 'pwd', 'sid': 'xe'}}
        # Expect failures with thin client and fake host
        assert ping('dummy') != 0
