import pytest
from app.utils.users_store import validate_password_complexity

def test_password_complexity():
    # Test valid password
    is_valid, msg = validate_password_complexity("Valid1!pass")
    assert is_valid
    
    # Test length less than 8
    is_valid, msg = validate_password_complexity("Val1!p")
    assert not is_valid
    assert "8 characters" in msg
    
    # Test no uppercase
    is_valid, msg = validate_password_complexity("valid1!pass")
    assert not is_valid
    assert "uppercase" in msg
    
    # Test no lowercase
    is_valid, msg = validate_password_complexity("VALID1!PASS")
    assert not is_valid
    assert "lowercase" in msg
    
    # Test no number
    is_valid, msg = validate_password_complexity("Valid!pass")
    assert not is_valid
    assert "number" in msg
    
    # Test no special character
    is_valid, msg = validate_password_complexity("Valid1pass")
    assert not is_valid
    assert "special character" in msg
    
    # Test 3 sequential characters (abc)
    is_valid, msg = validate_password_complexity("Valabc1!pass")
    assert not is_valid
    assert "3 sequential" in msg
    
    # Test 3 sequential numbers (123)
    is_valid, msg = validate_password_complexity("Val123!pass")
    assert not is_valid
    assert "3 sequential" in msg

