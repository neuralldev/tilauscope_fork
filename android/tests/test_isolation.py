# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Keep the mobile core independently importable without desktop dependencies."""
import ast
from pathlib import Path
import sys
import unittest


class IsolationTests(unittest.TestCase):
    def test_python_core_imports_only_stdlib_and_its_own_package(self):
        root = Path(__file__).resolve().parents[1] / "python"
        allowed = sys.stdlib_module_names | {"tilauscope_mobile", "tilaucore"} # tilaucore: shared with the desktop, stdlib only
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for name in names:
                    self.assertIn(name.split(".")[0], allowed, f"{path}: {name}")


if __name__ == "__main__":
    unittest.main()
