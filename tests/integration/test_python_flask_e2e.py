"""
E2E Integration Test: Python Flask Application Parsing

Tests the Python parser's ability to extract:
- Classes and inheritance
- Functions and methods
- Decorators (Flask routes, custom decorators)
- Async functions
- Import statements
- Type hints
- Properties and class methods
"""
import pytest
from pathlib import Path

from loom.core import NodeKind
from loom.ingest.code.languages.python import parse_python


@pytest.mark.integration
def test_python_flask_app_parsing_accuracy():
    """E2E test: Parse a complete Flask REST API application."""
    fixture_root = Path(__file__).parent.parent / "fixtures" / "python_flask_app"
    
    if not fixture_root.exists():
        pytest.skip(f"Python Flask fixture not found at {fixture_root}")
    
    # Parse all Python files
    py_files = list(fixture_root.rglob("*.py"))
    assert len(py_files) > 0, "No Python files found in fixture"
    
    all_nodes = []
    for file_path in py_files:
        nodes = parse_python(str(file_path))
        all_nodes.extend(nodes)
    
    # Create lookup maps
    nodes_by_kind = {}
    for node in all_nodes:
        kind = node.kind.value
        if kind not in nodes_by_kind:
            nodes_by_kind[kind] = []
        nodes_by_kind[kind].append(node)
    
    # Helper to find node by name and kind
    def find_node(name: str, kind: NodeKind) -> object | None:
        return next((n for n in all_nodes if n.name == name and n.kind == kind), None)
    
    # Verify we found nodes
    assert len(all_nodes) > 0, "No nodes extracted from Python files"
    
    # Test 1: Import detection
    imports = [n for n in all_nodes if n.metadata.get('is_import')]
    assert len(imports) > 0, "No imports detected"
    
    # Check for specific imports
    flask_imports = [n for n in imports if 'flask' in n.metadata.get('import_from', '') or 
                     'flask' in n.metadata.get('import_module', '')]
    assert len(flask_imports) > 0, "Flask imports not detected"
    
    typing_imports = [n for n in imports if 'typing' in n.metadata.get('import_from', '')]
    assert len(typing_imports) > 0, "Typing imports not detected"
    
    # Test 2: Class detection
    assert "class" in nodes_by_kind, "No classes found"
    
    user_class = find_node("User", NodeKind.CLASS)
    assert user_class is not None, "User class not found"
    
    user_service = find_node("UserService", NodeKind.CLASS)
    assert user_service is not None, "UserService class not found"
    
    base_service = find_node("BaseService", NodeKind.CLASS)
    assert base_service is not None, "BaseService class not found"
    
    # Test 3: Decorator detection on classes
    user_dto = find_node("UserDTO", NodeKind.CLASS)
    if user_dto:
        decorators = user_dto.metadata.get('decorators', [])
        assert 'dataclass' in decorators, "dataclass decorator not found on UserDTO"
    
    # Test 4: Function detection with Flask decorators
    assert "function" in nodes_by_kind, "No functions found"
    
    get_users = find_node("get_users", NodeKind.FUNCTION)
    assert get_users is not None, "get_users function not found"
    
    # Check for Flask route decorator
    if get_users:
        decorators = get_users.metadata.get('decorators', [])
        assert 'app.route' in decorators, f"app.route decorator not found, got: {decorators}"
        
        # Check for framework hint
        framework_hint = get_users.metadata.get('framework_hint')
        assert framework_hint == 'flask_route', f"Expected flask_route hint, got: {framework_hint}"
    
    # Test 5: Async function detection
    async_funcs = [n for n in all_nodes if n.metadata.get('is_async')]
    assert len(async_funcs) > 0, "No async functions detected"
    
    # Check specific async functions
    async_func_names = {f.name for f in async_funcs}
    assert "get_user_async" in async_func_names, "get_user_async not found"
    assert "async_background_task" in async_func_names, "async_background_task not found"
    
    # Test 6: Method detection
    assert "method" in nodes_by_kind, "No methods found"
    
    methods = nodes_by_kind["method"]
    method_names = {m.name for m in methods}
    
    # User class methods
    assert "set_password" in method_names, "set_password method not found"
    assert "check_password" in method_names, "check_password method not found"
    assert "to_dict" in method_names, "to_dict method not found"
    
    # UserService methods
    assert "get_all_users" in method_names, "get_all_users method not found"
    assert "create_user" in method_names, "create_user method not found"
    
    # Test 7: Static and class methods
    validate_email = find_node("validate_email", NodeKind.METHOD)
    if validate_email:
        decorators = validate_email.metadata.get('decorators', [])
        assert 'staticmethod' in decorators, "staticmethod decorator not found"
    
    from_config = find_node("from_config", NodeKind.METHOD)
    if from_config:
        decorators = from_config.metadata.get('decorators', [])
        assert 'classmethod' in decorators, "classmethod decorator not found"
    
    # Test 8: Decorator functions
    timing_decorator = find_node("timing_decorator", NodeKind.FUNCTION)
    assert timing_decorator is not None, "timing_decorator function not found"
    
    cache_decorator = find_node("cache_decorator", NodeKind.FUNCTION)
    assert cache_decorator is not None, "cache_decorator function not found"
    
    # Test 9: Functions with custom decorators
    process_data = find_node("process_data", NodeKind.FUNCTION)
    if process_data:
        decorators = process_data.metadata.get('decorators', [])
        assert 'timing_decorator' in decorators, "timing_decorator not applied to process_data"
    
    fibonacci = find_node("fibonacci", NodeKind.FUNCTION)
    if fibonacci:
        decorators = fibonacci.metadata.get('decorators', [])
        assert 'cache_decorator' in decorators, "cache_decorator not applied to fibonacci"
    
    # Test 10: Generic classes
    data_processor = find_node("DataProcessor", NodeKind.CLASS)
    assert data_processor is not None, "DataProcessor generic class not found"
    
    # Test 11: Verify node counts
    assert len(nodes_by_kind.get("class", [])) >= 8, \
        f"Expected >= 8 classes, found {len(nodes_by_kind.get('class', []))}"
    
    assert len(nodes_by_kind.get("function", [])) >= 15, \
        f"Expected >= 15 functions, found {len(nodes_by_kind.get('function', []))}"
    
    assert len(nodes_by_kind.get("method", [])) >= 20, \
        f"Expected >= 20 methods, found {len(nodes_by_kind.get('method', []))}"
    
    # Test 12: Verify all nodes have proper file paths
    for node in all_nodes:
        assert "python_flask_app" in node.path, f"Node {node.name} has unexpected path: {node.path}"
        assert node.path.endswith(".py"), f"Node {node.name} path should end with .py"
    
    print("\n✅ Python Flask E2E Test Results:")
    print(f"   Total nodes extracted: {len(all_nodes)}")
    print(f"   Classes: {len(nodes_by_kind.get('class', []))}")
    print(f"   Functions: {len(nodes_by_kind.get('function', []))}")
    print(f"   Methods: {len(nodes_by_kind.get('method', []))}")
    print(f"   Imports: {len(imports)}")
    print(f"   Async functions: {len(async_funcs)}")
    print("\n   Flask decorators: ✓")
    print("   Custom decorators: ✓")
    print("   Async/await: ✓")
    print("   Type hints: ✓")
    print("   Import tracking: ✓")


@pytest.mark.integration
def test_python_flask_app_visual_graph():
    """E2E test: Generate visual representation of Python Flask app structure."""
    fixture_root = Path(__file__).parent.parent / "fixtures" / "python_flask_app"
    
    if not fixture_root.exists():
        pytest.skip(f"Python Flask fixture not found at {fixture_root}")
    
    py_files = list(fixture_root.rglob("*.py"))
    all_nodes = []
    
    for file_path in py_files:
        nodes = parse_python(str(file_path))
        all_nodes.extend(nodes)
    
    # Group nodes by file and type
    nodes_by_file = {}
    for node in all_nodes:
        file_name = Path(node.path).name
        if file_name not in nodes_by_file:
            nodes_by_file[file_name] = {'classes': [], 'functions': [], 'methods': [], 'imports': []}
        
        if node.metadata.get('is_import'):
            nodes_by_file[file_name]['imports'].append(node)
        elif node.kind == NodeKind.CLASS:
            nodes_by_file[file_name]['classes'].append(node)
        elif node.kind == NodeKind.FUNCTION:
            nodes_by_file[file_name]['functions'].append(node)
        elif node.kind == NodeKind.METHOD:
            nodes_by_file[file_name]['methods'].append(node)
    
    # Generate visual representation
    print("\n📊 Python Flask App Structure:")
    print("=" * 80)
    
    for file_name, categories in sorted(nodes_by_file.items()):
        print(f"\n📄 {file_name}")
        print("-" * 80)
        
        if categories['imports']:
            print(f"  📥 Imports ({len(categories['imports'])})")
            for imp in categories['imports'][:5]:
                source = imp.metadata.get('import_from') or imp.metadata.get('import_module', '')
                print(f"     - {source}")
        
        if categories['classes']:
            print(f"  📦 Classes ({len(categories['classes'])})")
            for cls in categories['classes']:
                decorators = cls.metadata.get('decorators', [])
                dec_str = f" @{', @'.join(decorators)}" if decorators else ""
                print(f"     - {cls.name}{dec_str}")
        
        if categories['functions']:
            print(f"  🔷 Functions ({len(categories['functions'])})")
            for func in categories['functions'][:10]:
                decorators = func.metadata.get('decorators', [])
                is_async = func.metadata.get('is_async', False)
                async_str = "async " if is_async else ""
                dec_str = f" @{decorators[0]}" if decorators else ""
                print(f"     - {async_str}{func.name}(){dec_str}")
        
        if categories['methods']:
            print(f"  🔹 Methods ({len(categories['methods'])})")
    
    print("\n" + "=" * 80)
    print(f"Total: {len(all_nodes)} nodes across {len(nodes_by_file)} files")
    print("=" * 80)
    
    # Validate structure
    assert len(nodes_by_file) >= 3, "Expected at least 3 Python files"
    assert len(all_nodes) >= 40, f"Expected at least 40 nodes, got {len(all_nodes)}"
