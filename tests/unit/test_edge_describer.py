from loom.indexer.edge_describer import describe_call_edge, extract_verb


def test_extract_verb_get():
    assert extract_verb("get_user") == "user retrieval"


def test_extract_verb_validate():
    assert extract_verb("validate_token") == "token validation"


def test_extract_verb_handle_password():
    assert extract_verb("handle") is None  # bare generic verb → None


def test_extract_verb_generic_returns_none():
    assert extract_verb("run") is None
    assert extract_verb("process") is None


def test_describe_call_edge_cross_module():
    desc = describe_call_edge(
        caller_name="handle_login",
        callee_name="hash_password",
        callee_module="auth",
        caller_module="api",
    )
    assert desc is None or "password" in desc


def test_describe_call_edge_well_named():
    desc = describe_call_edge(
        caller_name="create_order",
        callee_name="validate_payment",
        callee_module="billing",
        caller_module="orders",
    )
    assert desc is not None
    assert "validation" in desc or "validate" in desc
