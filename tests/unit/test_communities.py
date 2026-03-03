from __future__ import annotations

from loom.analysis.code.communities import _generate_community_name


def test_generate_community_name_from_common_prefix():
    """Test that community name is generated from most common word."""
    names = ["auth_login", "auth_logout", "auth_validate", "auth_refresh"]
    result = _generate_community_name(names)
    assert result == "auth"


def test_generate_community_name_mixed_words():
    """Test community naming with mixed function names."""
    names = ["validate_user", "validate_token", "check_auth", "validate_session"]
    result = _generate_community_name(names)
    assert result == "validate"


def test_generate_community_name_single_word_functions():
    """Test community naming with single-word function names."""
    names = ["login", "logout", "authenticate"]
    result = _generate_community_name(names)
    # Should pick the most common single word
    assert result in ["login", "logout", "authenticate"]


def test_generate_community_name_empty_list():
    """Test community naming with empty list."""
    result = _generate_community_name([])
    assert result == "unnamed"


def test_generate_community_name_no_underscores():
    """Test community naming when no underscores in names."""
    names = ["login", "logout", "refresh"]
    result = _generate_community_name(names)
    # Should pick one of the names
    assert result in ["login", "logout", "refresh"]


def test_generate_community_name_tie_breaking():
    """Test that tie-breaking works (Counter.most_common picks first)."""
    names = ["data_fetch", "auth_login"]
    result = _generate_community_name(names)
    # Should be either "data" or "auth" (both appear once)
    assert result in ["data", "auth", "fetch", "login"]


def test_generate_community_name_complex_names():
    """Test with complex multi-part function names."""
    names = [
        "user_auth_validate_token",
        "user_auth_refresh_session",
        "user_profile_update",
    ]
    result = _generate_community_name(names)
    # "user" and "auth" appear most frequently
    assert result in ["user", "auth"]
