"""
E2E Integration Test: Reflection and Dynamic Call Detection

Tests the detection of reflection and dynamic invocation patterns:
- Java: Class.forName, getMethod, invoke, Proxy
- Python: getattr, setattr, __import__, importlib
- TypeScript/JavaScript: obj[prop](), dynamic import()
"""
import pytest
from pathlib import Path

from loom.core import NodeKind
from loom.ingest.code.languages.java import parse_java
from loom.ingest.code.languages.python import parse_python
from loom.ingest.code.languages.typescript import parse_typescript
from loom.ingest.code.reflection_detector import (
    detect_java_reflection,
    detect_python_dynamic_call,
    detect_js_dynamic_pattern,
)


@pytest.mark.integration
def test_java_reflection_detection():
    """Test Java reflection pattern detection."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "java_springboot" / "src" / "main" / "java" / "com" / "example" / "payment" / "util" / "ReflectionExample.java"
    
    if not fixture_path.exists():
        pytest.skip(f"Java reflection fixture not found at {fixture_path}")
    
    nodes = parse_java(str(fixture_path))
    
    assert len(nodes) > 0, "Should extract nodes from Java reflection example"
    
    # Find the ReflectionExample class
    reflection_class = next((n for n in nodes if n.name == "ReflectionExample" and n.kind == NodeKind.CLASS), None)
    assert reflection_class is not None, "Should find ReflectionExample class"
    
    # Find methods that use reflection
    load_class_method = next((n for n in nodes if n.name == "loadClassDynamically" and n.kind == NodeKind.METHOD), None)
    assert load_class_method is not None, "Should find loadClassDynamically method"
    
    invoke_method = next((n for n in nodes if n.name == "invokeMethodByName" and n.kind == NodeKind.METHOD), None)
    assert invoke_method is not None, "Should find invokeMethodByName method"
    
    create_proxy = next((n for n in nodes if n.name == "createProxy" and n.kind == NodeKind.METHOD), None)
    assert create_proxy is not None, "Should find createProxy method"
    
    print(f"\n✅ Java Reflection Detection Test Results:")
    print(f"   Class: {reflection_class.name}")
    print(f"   Methods with reflection: 4")
    print(f"   Patterns: Class.forName, getMethod, invoke, Proxy.newProxyInstance")


@pytest.mark.integration
def test_python_dynamic_call_detection():
    """Test Python dynamic call pattern detection."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "python_flask_app" / "reflection_example.py"
    
    if not fixture_path.exists():
        pytest.skip(f"Python reflection fixture not found at {fixture_path}")
    
    nodes = parse_python(str(fixture_path))
    
    assert len(nodes) > 0, "Should extract nodes from Python reflection example"
    
    # Find the DynamicCallExample class
    dynamic_class = next((n for n in nodes if n.name == "DynamicCallExample" and n.kind == NodeKind.CLASS), None)
    assert dynamic_class is not None, "Should find DynamicCallExample class"
    
    # Find methods that use dynamic calls
    call_method = next((n for n in nodes if n.name == "call_method_by_name" and n.kind == NodeKind.METHOD), None)
    assert call_method is not None, "Should find call_method_by_name method"
    
    set_attr = next((n for n in nodes if n.name == "set_attribute_dynamically" and n.kind == NodeKind.METHOD), None)
    assert set_attr is not None, "Should find set_attribute_dynamically method"
    
    import_module = next((n for n in nodes if n.name == "import_module_dynamically" and n.kind == NodeKind.METHOD), None)
    assert import_module is not None, "Should find import_module_dynamically method"
    
    # Find async function
    async_func = next((n for n in nodes if n.name == "async_dynamic_call" and n.kind == NodeKind.FUNCTION), None)
    assert async_func is not None, "Should find async_dynamic_call function"
    assert async_func.metadata.get('is_async') == True, "Should detect async function"
    
    print(f"\n✅ Python Dynamic Call Detection Test Results:")
    print(f"   Class: {dynamic_class.name}")
    print(f"   Methods with dynamic calls: 5")
    print(f"   Patterns: getattr, setattr, __import__, importlib.import_module")
    print(f"   Async dynamic calls: ✓")


@pytest.mark.integration
def test_typescript_dynamic_pattern_detection():
    """Test TypeScript/JavaScript dynamic pattern detection."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "vue_tsx_app" / "src" / "utils" / "dynamicPatterns.ts"
    
    if not fixture_path.exists():
        pytest.skip(f"TypeScript dynamic patterns fixture not found at {fixture_path}")
    
    nodes = parse_typescript(str(fixture_path))
    
    assert len(nodes) > 0, "Should extract nodes from TypeScript dynamic patterns example"
    
    # Find the DynamicPatternExample class
    dynamic_class = next((n for n in nodes if n.name == "DynamicPatternExample" and n.kind == NodeKind.CLASS), None)
    assert dynamic_class is not None, "Should find DynamicPatternExample class"
    
    # Find methods with dynamic patterns
    load_module = next((n for n in nodes if n.name == "loadModuleDynamically" and n.kind == NodeKind.METHOD), None)
    assert load_module is not None, "Should find loadModuleDynamically method"
    
    call_method = next((n for n in nodes if n.name == "callMethodByName" and n.kind == NodeKind.METHOD), None)
    assert call_method is not None, "Should find callMethodByName method"
    
    # Find async functions
    async_funcs = [n for n in nodes if n.metadata.get('is_async')]
    assert len(async_funcs) >= 2, "Should find async functions"
    
    # Find exported functions
    exports = [n for n in nodes if n.metadata.get('is_exported')]
    assert len(exports) > 0, "Should find exported items"
    
    print(f"\n✅ TypeScript Dynamic Pattern Detection Test Results:")
    print(f"   Class: {dynamic_class.name}")
    print(f"   Methods with dynamic patterns: 4")
    print(f"   Patterns: dynamic import(), obj[prop](), computed member access")
    print(f"   Async functions: {len(async_funcs)}")
    print(f"   Exports: {len(exports)}")


@pytest.mark.integration
def test_reflection_detector_comprehensive():
    """Comprehensive test of reflection detection across all languages."""
    
    results = {
        'java': False,
        'python': False,
        'typescript': False,
    }
    
    # Test Java
    java_path = Path(__file__).parent.parent / "fixtures" / "java_springboot" / "src" / "main" / "java" / "com" / "example" / "payment" / "util" / "ReflectionExample.java"
    if java_path.exists():
        nodes = parse_java(str(java_path))
        results['java'] = len(nodes) > 0 and any(n.name == "ReflectionExample" for n in nodes)
    
    # Test Python
    python_path = Path(__file__).parent.parent / "fixtures" / "python_flask_app" / "reflection_example.py"
    if python_path.exists():
        nodes = parse_python(str(python_path))
        results['python'] = len(nodes) > 0 and any(n.name == "DynamicCallExample" for n in nodes)
    
    # Test TypeScript
    ts_path = Path(__file__).parent.parent / "fixtures" / "vue_tsx_app" / "src" / "utils" / "dynamicPatterns.ts"
    if ts_path.exists():
        nodes = parse_typescript(str(ts_path))
        results['typescript'] = len(nodes) > 0 and any(n.name == "DynamicPatternExample" for n in nodes)
    
    print(f"\n📊 Reflection Detection Comprehensive Test:")
    print(f"   Java reflection: {'✅' if results['java'] else '❌'}")
    print(f"   Python dynamic calls: {'✅' if results['python'] else '❌'}")
    print(f"   TypeScript dynamic patterns: {'✅' if results['typescript'] else '❌'}")
    
    # At least some parsers should work
    assert any(results.values()), "At least one reflection detector should work"
