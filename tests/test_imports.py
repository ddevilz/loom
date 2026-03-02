from __future__ import annotations

import unittest

class TestImports(unittest.TestCase):
    def test_imports(self) -> None:
        import loom

        import loom.core
        import loom.ingest
        import loom.analysis
        import loom.embed
        import loom.linker
        import loom.search
        import loom.watch
        import loom.drift
        import loom.llm
        import loom.mcp

    def test_hello(self) -> None:
        import loom

        self.assertIsInstance(loom.hello(), str)


if __name__ == "__main__":
    unittest.main()
