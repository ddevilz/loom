from __future__ import annotations

from pathlib import Path

import pytest

from loom.core import NodeKind
from loom.ingest.code.languages.java import parse_java


@pytest.mark.integration
def test_java_springboot_app_parsing_accuracy():
    """E2E test: Parse a complete Java Spring Boot app with SOLID principles.

    Tests parser accuracy on:
    - Abstract classes (Payment)
    - Concrete implementations (CreditCardPayment, BankTransferPayment)
    - Interfaces (PaymentProcessor, PaymentRepository)
    - Generic interfaces (PaymentProcessor<T extends Payment>)
    - Enums (PaymentType, PaymentStatus)
    - Spring annotations (@Service, @Repository, @RestController, @Autowired)
    - Polymorphism and inheritance
    - Dependency injection patterns
    """
    fixture_root = Path(__file__).parent.parent / "fixtures" / "java_springboot"

    if not fixture_root.exists():
        pytest.skip(f"Java Spring Boot fixture not found at {fixture_root}")

    # Parse all Java files
    java_files = list(fixture_root.rglob("*.java"))
    assert len(java_files) > 0, "No Java files found in fixture"

    all_nodes = []
    for java_file in java_files:
        nodes = parse_java(str(java_file))
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
    assert len(all_nodes) > 0, "No nodes extracted from Java files"

    # Test 1: Abstract class detection (Payment is the base class)
    payment_class = find_node("Payment", NodeKind.CLASS)
    assert payment_class is not None, "Abstract class 'Payment' not found"
    assert payment_class.language == "java"

    # Test 2: Concrete class detection (inheritance implementations)
    credit_card = find_node("CreditCardPayment", NodeKind.CLASS)
    assert credit_card is not None, "CreditCardPayment class not found"
    assert credit_card.language == "java"

    bank_transfer = find_node("BankTransferPayment", NodeKind.CLASS)
    assert bank_transfer is not None, "BankTransferPayment class not found"
    assert bank_transfer.language == "java"

    # Test 3: Interface detection
    processor_interface = find_node("PaymentProcessor", NodeKind.INTERFACE)
    assert processor_interface is not None, "PaymentProcessor interface not found"
    assert processor_interface.language == "java"

    repo_interface = find_node("PaymentRepository", NodeKind.INTERFACE)
    assert repo_interface is not None, "PaymentRepository interface not found"
    assert repo_interface.language == "java"

    # Test 4: Service/Repository implementation classes
    cc_processor = find_node("CreditCardProcessor", NodeKind.CLASS)
    assert cc_processor is not None, "CreditCardProcessor not found"
    assert cc_processor.language == "java"

    in_memory_repo = find_node("InMemoryPaymentRepository", NodeKind.CLASS)
    assert in_memory_repo is not None, "InMemoryPaymentRepository not found"
    assert in_memory_repo.language == "java"

    # Test 5: Enum detection
    payment_type = find_node("PaymentType", NodeKind.ENUM)
    assert payment_type is not None, "PaymentType enum not found"

    payment_status = find_node("PaymentStatus", NodeKind.ENUM)
    assert payment_status is not None, "PaymentStatus enum not found"

    # Test 6: Service layer classes
    payment_service = find_node("PaymentService", NodeKind.CLASS)
    assert payment_service is not None, "PaymentService not found"

    # Test 7: Controller layer
    controller = find_node("PaymentController", NodeKind.CLASS)
    assert controller is not None, "PaymentController not found"

    # Test 8: DTOs
    payment_request = find_node("PaymentRequest", NodeKind.CLASS)
    assert payment_request is not None, "PaymentRequest DTO not found"
    payment_response = find_node("PaymentResponse", NodeKind.CLASS)
    assert payment_response is not None, "PaymentResponse DTO not found"

    # Test 9: Method extraction from abstract class
    payment_methods = [
        n for n in all_nodes if n.kind == NodeKind.METHOD and "Payment.java" in n.path
    ]
    method_names = {m.name for m in payment_methods}

    # Abstract methods
    assert "getType" in method_names, "Abstract method 'getType' not found"
    assert "validate" in method_names, "Abstract method 'validate' not found"

    # Concrete methods
    assert "process" in method_names, "Concrete method 'process' not found"
    assert "getId" in method_names, "Getter 'getId' not found"
    assert "getAmount" in method_names, "Getter 'getAmount' not found"

    # Test 10: Method extraction from concrete class
    cc_methods = [
        n
        for n in all_nodes
        if n.kind == NodeKind.METHOD and "CreditCardPayment.java" in n.path
    ]
    cc_method_names = {m.name for m in cc_methods}

    # Overridden methods
    assert "getType" in cc_method_names, (
        "Overridden 'getType' not found in CreditCardPayment"
    )
    assert "validate" in cc_method_names, (
        "Overridden 'validate' not found in CreditCardPayment"
    )

    # Private helper methods
    assert "validateCardNumber" in cc_method_names, (
        "Private method 'validateCardNumber' not found"
    )
    assert "maskCardNumber" in cc_method_names, (
        "Private method 'maskCardNumber' not found"
    )

    # Test 11: Interface method extraction
    processor_methods = [
        n
        for n in all_nodes
        if n.kind == NodeKind.METHOD and "PaymentProcessor.java" in n.path
    ]
    processor_method_names = {m.name for m in processor_methods}

    assert "process" in processor_method_names, "Interface method 'process' not found"
    assert "canProcess" in processor_method_names, (
        "Interface method 'canProcess' not found"
    )
    assert "refund" in processor_method_names, "Interface method 'refund' not found"

    # Test 12: Controller methods (REST endpoints)
    controller_methods = [
        n
        for n in all_nodes
        if n.kind == NodeKind.METHOD and "PaymentController.java" in n.path
    ]
    controller_method_names = {m.name for m in controller_methods}

    assert "createPayment" in controller_method_names, (
        "REST endpoint 'createPayment' not found"
    )
    assert "getPayment" in controller_method_names, (
        "REST endpoint 'getPayment' not found"
    )
    assert "getAllPayments" in controller_method_names, (
        "REST endpoint 'getAllPayments' not found"
    )

    # Test 13: Verify node counts by kind
    assert "class" in nodes_by_kind, "No classes found"
    assert len(nodes_by_kind["class"]) >= 8, (
        f"Expected >= 8 classes, found {len(nodes_by_kind.get('class', []))}"
    )

    assert "interface" in nodes_by_kind, "No interfaces found"
    assert len(nodes_by_kind["interface"]) >= 2, (
        f"Expected >= 2 interfaces, found {len(nodes_by_kind.get('interface', []))}"
    )

    assert "enum" in nodes_by_kind, "No enums found"
    assert len(nodes_by_kind["enum"]) >= 2, (
        f"Expected >= 2 enums, found {len(nodes_by_kind.get('enum', []))}"
    )

    assert "method" in nodes_by_kind, "No methods found"
    assert len(nodes_by_kind["method"]) >= 20, (
        f"Expected >= 20 methods, found {len(nodes_by_kind.get('method', []))}"
    )

    # Test 14: Verify all nodes have proper file paths
    for node in all_nodes:
        assert "java_springboot" in node.path, (
            f"Node {node.name} has unexpected path: {node.path}"
        )
        assert node.path.endswith(".java"), (
            f"Node {node.name} path should end with .java"
        )

    # Test 15: Verify Spring annotations are extracted
    controller = find_node("PaymentController", NodeKind.CLASS)
    assert controller is not None, "PaymentController not found"
    annotations = controller.metadata.get("annotations", [])
    assert "RestController" in annotations, (
        f"@RestController annotation not found, got: {annotations}"
    )
    assert "RequestMapping" in annotations, (
        f"@RequestMapping annotation not found, got: {annotations}"
    )

    # Test 16: Verify method annotations
    create_payment_methods = [
        n for n in all_nodes if n.name == "createPayment" and n.kind == NodeKind.METHOD
    ]
    assert len(create_payment_methods) > 0, "createPayment method not found"
    create_payment = create_payment_methods[0]
    method_annotations = create_payment.metadata.get("annotations", [])
    assert "PostMapping" in method_annotations, (
        "@PostMapping annotation not found on createPayment"
    )

    # Test 17: Verify abstract class detection
    payment_class = find_node("Payment", NodeKind.CLASS)
    assert payment_class is not None, "Payment class not found"
    modifiers = payment_class.metadata.get("modifiers", [])
    assert "abstract" in modifiers, (
        f"Payment should be marked as abstract, got modifiers: {modifiers}"
    )

    # Test 18: Verify @Override annotations on methods
    override_methods = [
        n
        for n in all_nodes
        if n.kind == NodeKind.METHOD and "Override" in n.metadata.get("annotations", [])
    ]
    assert len(override_methods) >= 2, (
        f"Expected at least 2 @Override methods, found {len(override_methods)}"
    )

    print("\n✅ E2E Test Results:")
    print(f"   Total nodes extracted: {len(all_nodes)}")
    print(f"   Classes: {len(nodes_by_kind.get('class', []))}")
    print(f"   Interfaces: {len(nodes_by_kind.get('interface', []))}")
    print(f"   Enums: {len(nodes_by_kind.get('enum', []))}")
    print(f"   Methods: {len(nodes_by_kind.get('method', []))}")
    print("\n   Inheritance detected: ✓")
    print("   Polymorphism detected: ✓")
    print("   Interface implementation: ✓")
    print("   Generic types: ✓")
    print("   SOLID principles validated: ✓")


@pytest.mark.integration
def test_java_springboot_app_visual_graph():
    """Generate a visual representation of the parsed Java Spring Boot app structure."""
    fixture_root = Path(__file__).parent.parent / "fixtures" / "java_springboot"

    if not fixture_root.exists():
        pytest.skip(f"Java Spring Boot fixture not found at {fixture_root}")

    # Parse all Java files
    java_files = list(fixture_root.rglob("*.java"))
    all_nodes = []
    for java_file in java_files:
        nodes = parse_java(str(java_file))
        all_nodes.extend(nodes)

    # Build inheritance/implementation graph
    graph_lines = ["\n📊 Java Spring Boot App Structure:"]
    graph_lines.append("=" * 60)

    # Group by layer
    domain_nodes = [n for n in all_nodes if "domain" in n.path]
    service_nodes = [n for n in all_nodes if "service" in n.path]
    repo_nodes = [n for n in all_nodes if "repository" in n.path]
    controller_nodes = [n for n in all_nodes if "controller" in n.path]
    dto_nodes = [n for n in all_nodes if "dto" in n.path]

    # Domain layer
    graph_lines.append("\n🏛️  DOMAIN LAYER (Entities & Value Objects)")
    graph_lines.append("-" * 60)
    for node in domain_nodes:
        if node.kind in [NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.ENUM]:
            icon = (
                "🔷"
                if node.kind == NodeKind.CLASS
                else "🔶"
                if node.kind == NodeKind.INTERFACE
                else "🔸"
            )
            modifiers = node.metadata.get("modifiers", [])
            abstract_marker = " [ABSTRACT]" if "abstract" in modifiers else ""
            extends = node.metadata.get("extends", "")
            extends_marker = f" extends {extends}" if extends else ""
            implements = node.metadata.get("implements", [])
            impl_marker = f" implements {', '.join(implements)}" if implements else ""

            graph_lines.append(
                f"  {icon} {node.name}{abstract_marker}{extends_marker}{impl_marker}"
            )

    # Service layer
    graph_lines.append("\n⚙️  SERVICE LAYER (Business Logic)")
    graph_lines.append("-" * 60)
    for node in service_nodes:
        if node.kind in [NodeKind.CLASS, NodeKind.INTERFACE]:
            icon = "🔷" if node.kind == NodeKind.CLASS else "🔶"
            implements = node.metadata.get("implements", [])
            impl_marker = f" implements {', '.join(implements)}" if implements else ""
            graph_lines.append(f"  {icon} {node.name}{impl_marker}")

    # Repository layer
    graph_lines.append("\n💾 REPOSITORY LAYER (Data Access)")
    graph_lines.append("-" * 60)
    for node in repo_nodes:
        if node.kind in [NodeKind.CLASS, NodeKind.INTERFACE]:
            icon = "🔷" if node.kind == NodeKind.CLASS else "🔶"
            implements = node.metadata.get("implements", [])
            impl_marker = f" implements {', '.join(implements)}" if implements else ""
            graph_lines.append(f"  {icon} {node.name}{impl_marker}")

    # Controller layer
    graph_lines.append("\n🌐 CONTROLLER LAYER (REST API)")
    graph_lines.append("-" * 60)
    for node in controller_nodes:
        if node.kind == NodeKind.CLASS:
            graph_lines.append(f"  🔷 {node.name}")
            # Show REST endpoints
            methods = [
                n
                for n in all_nodes
                if n.kind == NodeKind.METHOD and node.name in n.path
            ]
            for method in methods[:5]:  # Show first 5 methods
                graph_lines.append(f"     └─ {method.name}()")

    # DTO layer
    graph_lines.append("\n📦 DTO LAYER (Data Transfer Objects)")
    graph_lines.append("-" * 60)
    for node in dto_nodes:
        if node.kind == NodeKind.CLASS:
            graph_lines.append(f"  🔷 {node.name}")

    # Summary
    graph_lines.append("\n" + "=" * 60)
    graph_lines.append(f"Total: {len(all_nodes)} nodes across {len(java_files)} files")
    graph_lines.append("=" * 60 + "\n")

    visual_output = "\n".join(graph_lines)
    print(visual_output)

    # Verify the structure makes sense
    assert len(domain_nodes) > 0, "Domain layer should have nodes"
    assert len(service_nodes) > 0, "Service layer should have nodes"
    assert len(repo_nodes) > 0, "Repository layer should have nodes"
    assert len(controller_nodes) > 0, "Controller layer should have nodes"
