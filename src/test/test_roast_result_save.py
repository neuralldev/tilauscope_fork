"""Regression tests for post-roast result persistence."""

from __future__ import annotations

import ast
from pathlib import Path


def test_result_dialog_saves_before_accepting() -> None:
    """The post-roast button must write the .alog, not only mutate qmc."""
    source = (Path(__file__).parents[1] / 'tilauscope' / 'roast_properties.py').read_text(
        encoding='utf-8')
    tree = ast.parse(source)
    dialog = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == 'RoastResultDialog')
    on_ok = next(
        node for node in dialog.body
        if isinstance(node, ast.FunctionDef) and node.name == '_on_ok')

    calls = [
        node for node in ast.walk(on_ok)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    file_save = next(node for node in calls if node.func.attr == 'fileSave')
    accept = next(node for node in calls if node.func.attr == 'accept')

    assert file_save.lineno < accept.lineno


def test_result_dialog_keeps_data_open_when_save_fails() -> None:
    """A failed/cancelled file picker must not discard the completed roast."""
    source = (Path(__file__).parents[1] / 'tilauscope' / 'roast_properties.py').read_text(
        encoding='utf-8')
    tree = ast.parse(source)
    dialog = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == 'RoastResultDialog')
    on_ok = next(
        node for node in dialog.body
        if isinstance(node, ast.FunctionDef) and node.name == '_on_ok')

    failed_branch = next(
        node for node in ast.walk(on_ok)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and isinstance(node.test.operand, ast.Name)
        and node.test.operand.id == 'saved')

    assert any(isinstance(node, ast.Return) for node in failed_branch.body)
