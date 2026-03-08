from __future__ import annotations

import unittest

class TestImports(unittest.TestCase):
    def test_imports(self) -> None:
        pass


    def test_hello(self) -> None:
        import loom

        self.assertIsInstance(loom.hello(), str)


if __name__ == "__main__":
    unittest.main()
