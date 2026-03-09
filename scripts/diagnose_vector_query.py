from __future__ import annotations

import asyncio

from loom.core import LoomGraph


def _vec(n: int) -> list[float]:
    return [0.1] * n


async def main() -> None:
    g = LoomGraph(graph_name="loom_graph")

    print("=== sanity query ===")
    try:
        rows = await g.query("RETURN 1 AS ok")
        print("OK", rows)
    except Exception as e:
        print("sanity query failed:", repr(e), str(e), getattr(e, "args", None))

    print("=== db.idx.list ===")
    try:
        rows = await g.query(
            "CALL db.idx.list() YIELD type, label, properties, options"
        )
        for r in rows:
            print(r)
    except Exception as e:
        print("idx.list failed:", repr(e), str(e), getattr(e, "args", None))

    print("\n=== vector query: vecf32($vec) ===")
    try:
        rows = await g.query(
            "CALL db.idx.vector.queryNodes('Node','embedding',5,vecf32($vec)) YIELD node, score RETURN node.id AS id, score LIMIT 5",
            {"vec": _vec(768)},
        )
        print("OK", rows[:3])
    except Exception as e:
        print("FAIL", repr(e), str(e), getattr(e, "args", None))

    print("\n=== vector query: vecf32([x IN $vec | toFloat(x)]) ===")
    try:
        rows = await g.query(
            "CALL db.idx.vector.queryNodes('Node','embedding',5,vecf32([x IN $vec | toFloat(x)])) YIELD node, score RETURN node.id AS id, score LIMIT 5",
            {"vec": _vec(768)},
        )
        print("OK", rows[:3])
    except Exception as e:
        print("FAIL", repr(e), str(e), getattr(e, "args", None))

    print("\n=== vector query: vecf32([i IN range(0,767) | 0.1]) ===")
    try:
        rows = await g.query(
            "CALL db.idx.vector.queryNodes('Node','embedding',5,vecf32([i IN range(0,767) | 0.1])) YIELD node, score RETURN node.id AS id, score LIMIT 5",
            {},
        )
        print("OK", rows[:3])
    except Exception as e:
        print("FAIL", repr(e), str(e), getattr(e, "args", None))


if __name__ == "__main__":
    asyncio.run(main())
