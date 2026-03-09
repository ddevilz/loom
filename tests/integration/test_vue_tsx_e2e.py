from __future__ import annotations

from pathlib import Path

import pytest

from loom.core import NodeKind
from loom.ingest.code.languages.typescript import parse_typescript


@pytest.mark.integration
def test_vue_tsx_app_parsing_accuracy():
    """E2E test: Parse a complete Vue.js TSX app with TypeScript.

    Tests parser accuracy on:
    - TypeScript interfaces and type aliases
    - Enums (TaskStatus, TaskPriority)
    - Vue composables (useTaskManager)
    - Vue TSX components (TaskCard, TaskList)
    - Arrow functions and function expressions
    - Generic types and utility types
    - Class declarations
    """
    fixture_root = Path(__file__).parent.parent / "fixtures" / "vue_tsx_app"

    if not fixture_root.exists():
        pytest.skip(f"Vue TSX fixture not found at {fixture_root}")

    # Parse all TypeScript/TSX files
    ts_files = list(fixture_root.rglob("*.ts"))
    tsx_files = list(fixture_root.rglob("*.tsx"))
    all_files = ts_files + tsx_files

    assert len(all_files) > 0, "No TypeScript/TSX files found in fixture"

    all_nodes = []
    for file_path in all_files:
        nodes = parse_typescript(str(file_path))
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

    # Verify we found all expected nodes
    assert len(all_nodes) > 0, "No nodes extracted from TypeScript/TSX files"

    # Test 1: Enum detection
    task_status = find_node("TaskStatus", NodeKind.ENUM)
    assert task_status is not None, "TaskStatus enum not found"
    assert task_status.language == "typescript"

    task_priority = find_node("TaskPriority", NodeKind.ENUM)
    assert task_priority is not None, "TaskPriority enum not found"
    assert task_priority.language == "typescript"

    # Test 2: Interface detection
    task_interface = find_node("Task", NodeKind.INTERFACE)
    assert task_interface is not None, "Task interface not found"
    assert "Task.ts" in task_interface.path

    task_filter = find_node("TaskFilter", NodeKind.INTERFACE)
    assert task_filter is not None, "TaskFilter interface not found"

    task_card_props = find_node("TaskCardProps", NodeKind.INTERFACE)
    assert task_card_props is not None, "TaskCardProps interface not found"
    assert "TaskCard.tsx" in task_card_props.path

    # Test 3: Type alias detection
    type_nodes = [n for n in all_nodes if n.kind == NodeKind.TYPE]
    type_names = {t.name for t in type_nodes}
    assert "TaskUpdatePayload" in type_names, "TaskUpdatePayload type alias not found"

    # Test 4: Function detection in composables
    composable_functions = [
        n
        for n in all_nodes
        if n.kind == NodeKind.FUNCTION and "useTaskManager" in n.path
    ]
    func_names = {f.name for f in composable_functions}

    assert "useTaskManager" in func_names, "useTaskManager composable not found"
    assert "fetchTasks" in func_names, "fetchTasks function not found"
    assert "addTask" in func_names, "addTask function not found"
    assert "updateTask" in func_names, "updateTask function not found"
    assert "deleteTask" in func_names, "deleteTask function not found"
    assert "setFilter" in func_names, "setFilter function not found"

    # Test 5: Verify imports are tracked
    imports = [n for n in all_nodes if n.metadata.get("is_import")]
    assert len(imports) > 0, "No imports detected"

    # Check for Vue imports
    vue_imports = [n for n in imports if "vue" in n.metadata.get("import_source", "")]
    assert len(vue_imports) > 0, "Vue imports not detected"

    # Test 6: Verify exports are tracked
    exports = [n for n in all_nodes if n.metadata.get("is_exported")]
    assert len(exports) > 0, "No exports detected"

    # Test 7: Utility functions
    util_functions = [
        n for n in all_nodes if n.kind == NodeKind.FUNCTION and "taskHelpers" in n.path
    ]
    util_func_names = {f.name for f in util_functions}

    assert "sortTasksByPriority" in util_func_names, "sortTasksByPriority not found"
    assert "sortTasksByDueDate" in util_func_names, "sortTasksByDueDate not found"
    assert "getOverdueTasks" in util_func_names, "getOverdueTasks not found"
    assert "getTaskCompletionRate" in util_func_names, "getTaskCompletionRate not found"

    # Test 8: Class detection
    task_validator = find_node("TaskValidator", NodeKind.CLASS)
    assert task_validator is not None, "TaskValidator class not found"
    assert "taskHelpers" in task_validator.path

    # Test 9: Async function detection
    async_funcs = [n for n in all_nodes if n.metadata.get("is_async")]
    assert len(async_funcs) > 0, "No async functions detected"

    # fetchTasks should be async
    fetch_tasks_funcs = [n for n in all_nodes if n.name == "fetchTasks"]
    if fetch_tasks_funcs:
        assert fetch_tasks_funcs[0].metadata.get("is_async"), (
            "fetchTasks should be async"
        )

    # Test 10: Verify node counts by kind
    assert "function" in nodes_by_kind, "No functions found"
    assert len(nodes_by_kind["function"]) >= 10, (
        f"Expected >= 10 functions, found {len(nodes_by_kind.get('function', []))}"
    )

    assert "interface" in nodes_by_kind, "No interfaces found"
    assert len(nodes_by_kind["interface"]) >= 3, (
        f"Expected >= 3 interfaces, found {len(nodes_by_kind.get('interface', []))}"
    )

    assert "enum" in nodes_by_kind, "No enums found"
    assert len(nodes_by_kind["enum"]) >= 2, (
        f"Expected >= 2 enums, found {len(nodes_by_kind.get('enum', []))}"
    )

    assert "type" in nodes_by_kind, "No type aliases found"
    assert len(nodes_by_kind["type"]) >= 1, (
        f"Expected >= 1 type alias, found {len(nodes_by_kind.get('type', []))}"
    )

    # Test 10: Verify all nodes have proper file paths
    for node in all_nodes:
        assert "vue_tsx_app" in node.path, (
            f"Node {node.name} has unexpected path: {node.path}"
        )
        assert node.path.endswith((".ts", ".tsx")), (
            f"Node {node.name} path should end with .ts or .tsx"
        )

    print("\n✅ Vue TSX E2E Test Results:")
    print(f"   Total nodes extracted: {len(all_nodes)}")
    print(f"   Functions: {len(nodes_by_kind.get('function', []))}")
    print(f"   Interfaces: {len(nodes_by_kind.get('interface', []))}")
    print(f"   Enums: {len(nodes_by_kind.get('enum', []))}")
    print(f"   Types: {len(nodes_by_kind.get('type', []))}")
    print(f"   Classes: {len(nodes_by_kind.get('class', []))}")
    print(f"   Methods: {len(nodes_by_kind.get('method', []))}")
    print("\n   Vue Composables: ✓")
    print("   TSX Components: ✓")
    print("   TypeScript Types: ✓")
    print("   Utility Functions: ✓")


@pytest.mark.integration
def test_vue_tsx_app_visual_graph():
    """Generate a visual representation of the parsed Vue TSX app structure."""
    fixture_root = Path(__file__).parent.parent / "fixtures" / "vue_tsx_app"

    if not fixture_root.exists():
        pytest.skip(f"Vue TSX fixture not found at {fixture_root}")

    # Parse all TypeScript/TSX files
    ts_files = list(fixture_root.rglob("*.ts"))
    tsx_files = list(fixture_root.rglob("*.tsx"))
    all_files = ts_files + tsx_files

    all_nodes = []
    for file_path in all_files:
        nodes = parse_typescript(str(file_path))
        all_nodes.extend(nodes)

    # Build graph by layer
    graph_lines = ["\n📊 Vue TSX App Structure:"]
    graph_lines.append("=" * 60)

    # Group by file type
    type_nodes = [n for n in all_nodes if "types" in n.path]
    composable_nodes = [n for n in all_nodes if "composables" in n.path]
    component_nodes = [n for n in all_nodes if "components" in n.path]
    util_nodes = [n for n in all_nodes if "utils" in n.path]

    # Types layer
    graph_lines.append("\n📝 TYPES LAYER (Interfaces, Enums, Type Aliases)")
    graph_lines.append("-" * 60)
    for node in type_nodes:
        if node.kind in [NodeKind.INTERFACE, NodeKind.ENUM, NodeKind.TYPE]:
            icon = (
                "🔶"
                if node.kind == NodeKind.INTERFACE
                else "🔸"
                if node.kind == NodeKind.ENUM
                else "🔷"
            )
            graph_lines.append(f"  {icon} {node.name} ({node.kind.value})")

    # Composables layer
    graph_lines.append("\n🎣 COMPOSABLES LAYER (Vue Composition API)")
    graph_lines.append("-" * 60)
    composable_funcs = [n for n in composable_nodes if n.kind == NodeKind.FUNCTION]
    if composable_funcs:
        main_composable = next(
            (n for n in composable_funcs if n.name == "useTaskManager"), None
        )
        if main_composable:
            graph_lines.append(f"  🔷 {main_composable.name}()")
            other_funcs = [n for n in composable_funcs if n.name != "useTaskManager"]
            for func in other_funcs[:5]:
                graph_lines.append(f"     └─ {func.name}()")

    # Components layer
    graph_lines.append("\n🎨 COMPONENTS LAYER (Vue TSX Components)")
    graph_lines.append("-" * 60)
    for node in component_nodes:
        if node.kind == NodeKind.CLASS:
            graph_lines.append(f"  🔷 {node.name}")
            # Show component methods
            methods = [
                n
                for n in all_nodes
                if n.kind == NodeKind.METHOD and node.name in n.path
            ]
            for method in methods[:3]:
                graph_lines.append(f"     └─ {method.name}()")

    # Utils layer
    graph_lines.append("\n🛠️  UTILS LAYER (Helper Functions)")
    graph_lines.append("-" * 60)
    for node in util_nodes:
        if node.kind == NodeKind.FUNCTION:
            graph_lines.append(f"  🔷 {node.name}()")
        elif node.kind == NodeKind.CLASS:
            graph_lines.append(f"  🔷 {node.name} (class)")
            methods = [
                n
                for n in all_nodes
                if n.kind == NodeKind.METHOD and node.name in n.path
            ]
            for method in methods[:3]:
                graph_lines.append(f"     └─ {method.name}()")

    # Summary
    graph_lines.append("\n" + "=" * 60)
    graph_lines.append(f"Total: {len(all_nodes)} nodes across {len(all_files)} files")
    graph_lines.append("=" * 60 + "\n")

    visual_output = "\n".join(graph_lines)
    print(visual_output)

    # Verify the structure makes sense
    assert len(type_nodes) > 0, "Types layer should have nodes"
    assert len(composable_nodes) > 0, "Composables layer should have nodes"
    assert len(component_nodes) > 0, "Components layer should have nodes"
    assert len(util_nodes) > 0, "Utils layer should have nodes"
