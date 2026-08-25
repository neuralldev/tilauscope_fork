"""Regression tests for post-roast result persistence."""

from __future__ import annotations

import ast
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any


ROAST_PROPERTIES = Path(__file__).parents[1] / 'tilauscope' / 'roast_properties.py'
DISPLAY_SCOPE = Path(__file__).parents[1] / 'tilauscope' / 'displayscope.py'


def _class_method(path: Path, class_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name)
    return next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name)


def _compile_method(
    path: Path,
    class_name: str,
    method_name: str,
    globals_: dict[str, Any] | None = None,
) -> Any:
    node = _class_method(path, class_name, method_name)
    node.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = {} if globals_ is None else dict(globals_)
    exec(compile(module, path, 'exec'), namespace)  # noqa: S102
    return namespace[method_name]


def test_result_dialog_saves_before_accepting() -> None:
    """The post-roast button must write the .alog, not only mutate qmc."""
    source = ROAST_PROPERTIES.read_text(encoding='utf-8')
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
    source = ROAST_PROPERTIES.read_text(encoding='utf-8')
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


def test_review_passes_its_frozen_profile_to_result_form() -> None:
    """The review identity must travel with the weight-edit request."""
    enter_weights = _compile_method(
        DISPLAY_SCOPE, 'TilauScope', '_enter_roast_weights',
        {'_log': SimpleNamespace(warning=lambda *_args: None)},
    )
    profile = {'beans': 'Coffee A\nuuid: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}
    opened: list[dict] = []
    scope = SimpleNamespace(
        # The panel hands out its snapshot as a copy — see reviewed_profile().
        roast_review=SimpleNamespace(reviewed_profile=lambda: dict(profile)),
        _review_shown=False,
        _open_roast_result_dialog=opened.append,
    )

    enter_weights(scope)

    assert opened == [profile]
    assert opened[0] is not profile  # caller receives an immutable-by-convention copy


def test_a_review_showing_no_roast_opens_no_result_form() -> None:
    """With no snapshot there is no roast to attribute the weight to.

    Opening the form anyway would let it fall back to the live session, which is
    exactly the wrong-coffee bug the snapshot exists to prevent.
    """
    enter_weights = _compile_method(
        DISPLAY_SCOPE, 'TilauScope', '_enter_roast_weights',
        {'_log': SimpleNamespace(warning=lambda *_args: None)},
    )
    opened: list[dict] = []
    scope = SimpleNamespace(
        roast_review=SimpleNamespace(reviewed_profile=lambda: None),
        _review_shown=False,
        _open_roast_result_dialog=opened.append,
    )

    enter_weights(scope)

    assert opened == []


def test_review_bean_resolution_uses_roast_uuid_not_current_selection() -> None:
    """A BeanCave selection made after the roast must not replace its UUID."""
    class Bean:
        def __init__(self, name: str = '', uuid: str = '', **fields: Any) -> None:
            self.name = name
            self.uuid = uuid
            for key, value in fields.items():
                setattr(self, key, value)

    roast_uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    selected_uuid = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
    roasted_bean = Bean('Coffee A', roast_uuid)
    selected_bean = Bean('Coffee B', selected_uuid)
    resolve = _compile_method(
        ROAST_PROPERTIES, 'RoastResultDialog', '_resolve_bean',
        {
            're': re,
            'GreenBean': Bean,
            '_log': SimpleNamespace(warning=lambda *_args: None),
        },
    )
    dialog = SimpleNamespace(
        _bean_description=f'Coffee A\nuuid: {roast_uuid}',
        _aw=SimpleNamespace(
            qmc=SimpleNamespace(beans=f'Coffee B\nuuid: {selected_uuid}'),
            beancaveWindow=SimpleNamespace(
                uuidmap={roast_uuid: roasted_bean, selected_uuid: selected_bean},
                current_bean_name='Coffee B',
            ),
        ),
    )

    assert resolve(dialog) is roasted_bean


def test_result_form_does_not_read_beancave_selection() -> None:
    """The display-scope bridge must feed the reviewed beans description."""
    open_form = _class_method(
        DISPLAY_SCOPE, 'TilauScope', '_open_roast_result_dialog')
    attributes = {
        node.attr for node in ast.walk(open_form) if isinstance(node, ast.Attribute)
    }
    dialog_call = next(
        node for node in ast.walk(open_form)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'RoastResultDialog'
    )

    assert 'currentRow' not in attributes
    assert 'current_bean_name' not in attributes
    assert isinstance(dialog_call.args[0], ast.Constant)
    assert dialog_call.args[0].value is None
    assert any(keyword.arg == 'bean_description' for keyword in dialog_call.keywords)


def test_review_identity_is_written_only_when_result_is_saved() -> None:
    """Saving weights must persist the reviewed UUID before writing the .alog."""
    on_ok = _class_method(ROAST_PROPERTIES, 'RoastResultDialog', '_on_ok')
    identity_write = next(
        node for node in ast.walk(on_ok)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == 'qmc'
            and target.attr == 'beans'
            for target in node.targets
        )
    )
    file_save = next(
        node for node in ast.walk(on_ok)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'fileSave'
    )

    assert isinstance(identity_write.value, ast.Attribute)
    assert identity_write.value.attr == '_bean_description'
    assert identity_write.lineno < file_save.lineno
