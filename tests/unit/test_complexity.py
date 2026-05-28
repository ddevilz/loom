"""Tests for complexity classification."""


def test_simple_function():
    """Short function with no branches → SIMPLE."""
    import tree_sitter_python as ts_py
    from tree_sitter import Language, Parser

    from loom.graph.models.enums import Complexity
    from loom.indexer.complexity import classify_complexity

    src = b"def foo(x):\n    return x + 1\n"
    lang = Language(ts_py.language())
    parser = Parser(lang)
    tree = parser.parse(src)
    fn_node = tree.root_node.children[0]  # function_definition
    result = classify_complexity(fn_node, "python")
    assert result == Complexity.SIMPLE


def test_complex_function_by_lines():
    """Function > 60 lines → COMPLEX."""
    import tree_sitter_python as ts_py
    from tree_sitter import Language, Parser

    from loom.graph.models.enums import Complexity
    from loom.indexer.complexity import classify_complexity

    # Build a function with 65 lines (many pass statements)
    body = "    pass\n" * 63
    src = f"def big():\n{body}".encode()
    lang = Language(ts_py.language())
    parser = Parser(lang)
    tree = parser.parse(src)
    fn_node = tree.root_node.children[0]
    result = classify_complexity(fn_node, "python")
    assert result == Complexity.COMPLEX


def test_complex_function_by_branches():
    """Function with >= 8 branches → COMPLEX."""
    import tree_sitter_python as ts_py
    from tree_sitter import Language, Parser

    from loom.graph.models.enums import Complexity
    from loom.indexer.complexity import classify_complexity

    ifs = "    if x:\n        pass\n" * 8
    src = f"def branchy(x):\n{ifs}".encode()
    lang = Language(ts_py.language())
    parser = Parser(lang)
    tree = parser.parse(src)
    fn_node = tree.root_node.children[0]
    result = classify_complexity(fn_node, "python")
    assert result == Complexity.COMPLEX


def test_moderate_function():
    """Function that's neither simple nor complex → MODERATE."""
    import tree_sitter_python as ts_py
    from tree_sitter import Language, Parser

    from loom.graph.models.enums import Complexity
    from loom.indexer.complexity import classify_complexity

    ifs = (
        "    if x:\n        pass\n" * 5
    )  # 5 branches — above SIMPLE_BRANCHES (3), below COMPLEX_BRANCHES (8)
    src = f"def moderate(x):\n{ifs}".encode()
    lang = Language(ts_py.language())
    parser = Parser(lang)
    tree = parser.parse(src)
    fn_node = tree.root_node.children[0]
    result = classify_complexity(fn_node, "python")
    assert result == Complexity.MODERATE


def test_unknown_language_defaults_to_no_branches():
    """Unknown language has empty BRANCH_NODES — no branches counted."""
    import tree_sitter_python as ts_py
    from tree_sitter import Language, Parser

    from loom.indexer.complexity import count_branch_nodes

    src = b"def foo(x):\n    if x:\n        return x\n"
    lang = Language(ts_py.language())
    parser = Parser(lang)
    tree = parser.parse(src)
    fn_node = tree.root_node.children[0]
    # For unknown language, no branch nodes are counted
    count = count_branch_nodes(fn_node, "cobol")
    assert count == 0
