"""
Reflection and Dynamic Call Detection

Detects reflection patterns and dynamic invocations across languages:
- Java: Class.forName, getMethod, invoke, Proxy
- Python: getattr, setattr, __import__, importlib
- TypeScript/JavaScript: obj[prop](), dynamic import()
"""
from __future__ import annotations

from typing import Any

from loom.ingest.code.languages.constants import (
    JAVA_REFLECTION_METHODS,
    PYTHON_DYNAMIC_METHODS,
    META_REFLECTION_PATTERN,
    META_DYNAMIC_TARGET,
    META_RAW_EXPRESSION,
    META_CALL_CONFIDENCE,
)


def detect_java_reflection(node: Any) -> dict[str, Any] | None:
    """
    Detect Java reflection patterns in method invocation.
    
    Returns metadata dict if reflection detected, None otherwise.
    """
    # Check if this is a method invocation
    if node.type != "method_invocation":
        return None
    
    # Get method name
    method_name_node = node.child_by_field_name("name")
    if not method_name_node:
        return None
    
    method_name = method_name_node.text.decode("utf-8") if method_name_node.text else None
    
    # Check if it's a reflection method
    if method_name not in JAVA_REFLECTION_METHODS:
        return None
    
    metadata = {
        META_REFLECTION_PATTERN: method_name,
        META_CALL_CONFIDENCE: "low",
    }
    
    # Try to extract string literal target (e.g., getMethod("foo"))
    arguments = node.child_by_field_name("arguments")
    if arguments:
        for child in arguments.children:
            if child.type == "string_literal":
                # Extract the string value (remove quotes)
                target = child.text.decode("utf-8").strip('"\'')
                metadata[META_DYNAMIC_TARGET] = target
                metadata[META_CALL_CONFIDENCE] = "medium"
                break
    
    # Capture raw expression for traceability
    if node.text:
        metadata[META_RAW_EXPRESSION] = node.text.decode("utf-8")[:200]  # Limit length
    
    return metadata


def detect_python_dynamic_call(node: Any) -> dict[str, Any] | None:
    """
    Detect Python dynamic call patterns (getattr, setattr, __import__, etc.).
    
    Returns metadata dict if dynamic pattern detected, None otherwise.
    """
    # Check if this is a function call
    if node.type != "call":
        return None
    
    # Get function name
    function_node = node.child_by_field_name("function")
    if not function_node:
        return None
    
    function_name = function_node.text.decode("utf-8") if function_node.text else None
    
    # Check if it's a dynamic method
    if function_name not in PYTHON_DYNAMIC_METHODS:
        return None
    
    metadata = {
        META_REFLECTION_PATTERN: function_name,
        META_CALL_CONFIDENCE: "low",
    }
    
    # Try to extract string literal target
    # For getattr(obj, "method_name"), we want the second argument
    arguments = node.child_by_field_name("arguments")
    if arguments:
        arg_list = [c for c in arguments.children if c.type == "string"]
        if arg_list:
            # Take the last string literal (usually the attribute/module name)
            target = arg_list[-1].text.decode("utf-8").strip('"\'')
            metadata[META_DYNAMIC_TARGET] = target
            metadata[META_CALL_CONFIDENCE] = "medium"
    
    # Capture raw expression
    if node.text:
        metadata[META_RAW_EXPRESSION] = node.text.decode("utf-8")[:200]
    
    return metadata


def detect_js_dynamic_pattern(node: Any) -> dict[str, Any] | None:
    """
    Detect JavaScript/TypeScript dynamic patterns:
    - obj[prop]() - computed member access with call
    - import() - dynamic import
    
    Returns metadata dict if dynamic pattern detected, None otherwise.
    """
    metadata = None
    
    # Check for dynamic import: import("module")
    if node.type == "call_expression":
        function_node = node.child_by_field_name("function")
        if function_node and function_node.type == "import":
            metadata = {
                META_REFLECTION_PATTERN: "dynamic_import",
                META_CALL_CONFIDENCE: "low",
            }
            
            # Try to extract module specifier
            arguments = node.child_by_field_name("arguments")
            if arguments:
                for child in arguments.children:
                    if child.type == "string":
                        target = child.text.decode("utf-8").strip('"\'')
                        metadata[META_DYNAMIC_TARGET] = target
                        metadata[META_CALL_CONFIDENCE] = "high"
                        break
    
    # Check for computed member access: obj[prop]()
    elif node.type == "call_expression":
        function_node = node.child_by_field_name("function")
        if function_node and function_node.type == "subscript_expression":
            metadata = {
                META_REFLECTION_PATTERN: "computed_member_call",
                META_CALL_CONFIDENCE: "low",
            }
            
            # Try to extract property if it's a string literal
            index_node = function_node.child_by_field_name("index")
            if index_node and index_node.type == "string":
                target = index_node.text.decode("utf-8").strip('"\'')
                metadata[META_DYNAMIC_TARGET] = target
                metadata[META_CALL_CONFIDENCE] = "medium"
    
    # Capture raw expression
    if metadata and node.text:
        metadata[META_RAW_EXPRESSION] = node.text.decode("utf-8")[:200]
    
    return metadata
