#!/usr/bin/env python3
"""Audit GH41 decorator auth declarations against capability evidence.

The audit uses capability JSONs only as development inputs. Runtime code must
read auth metadata from ``@yandex_api_method`` declarations, not from these
generated files.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
METHODS_PATH = ROOT / "capabilities" / "methods.json"
SCOPE_MAP_PATH = ROOT / "capabilities" / "method-scope-map.json"
MATRIX_PATH = ROOT / "capabilities" / "matrix.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_runtime_current_used(row: dict[str, Any]) -> bool:
    if row.get("classification") != "current_used":
        return False
    sources = [str(item) for item in row.get("local_sources") or []]
    if not sources:
        return False
    return not all(source.endswith(".md") for source in sources)


def expected_methods() -> dict[str, dict[str, Any]]:
    methods = _load_json(METHODS_PATH)["methods"]
    scope_map = _load_json(SCOPE_MAP_PATH)["methods"]
    expected: dict[str, dict[str, Any]] = {}
    for row in methods:
        if not _is_runtime_current_used(row):
            continue
        method_id = row["id"]
        if method_id not in scope_map:
            raise RuntimeError(f"Missing method-scope-map entry for {method_id}")
        expected[method_id] = scope_map[method_id]
    return expected


def _decorator_call(node: ast.AST) -> ast.Call | None:
    call = node if isinstance(node, ast.Call) else None
    if call is None:
        return None
    target = call.func
    if isinstance(target, ast.Name) and target.id == "yandex_api_method":
        return call
    if isinstance(target, ast.Attribute) and target.attr == "yandex_api_method":
        return call
    return None


def _literal_list(value: ast.AST) -> list[str]:
    raw = ast.literal_eval(value)
    if not isinstance(raw, (list, tuple)):
        raise ValueError("auth scope shape must be a list/tuple literal")
    return [str(item) for item in raw]


def _shape_from_call(call: ast.Call) -> tuple[str, dict[str, Any]]:
    if not call.args:
        raise ValueError("yandex_api_method requires method id")
    method_id = ast.literal_eval(call.args[0])
    if not isinstance(method_id, str):
        raise ValueError("method id must be a string literal")

    shape: dict[str, Any] = {}
    for keyword in call.keywords:
        if keyword.arg == "public":
            shape["public"] = bool(ast.literal_eval(keyword.value))
        elif keyword.arg == "one_of":
            shape["one_of"] = _literal_list(keyword.value)
        elif keyword.arg == "all_of":
            shape["all_of"] = _literal_list(keyword.value)
    return method_id, shape


def decorated_methods() -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {}
    script_path = Path(__file__).resolve()
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if "tests" in rel.parts or path.resolve() == script_path:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                call = _decorator_call(decorator)
                if call is None:
                    continue
                method_id, shape = _shape_from_call(call)
                found.setdefault(method_id, []).append(
                    {
                        "path": str(rel),
                        "name": node.name,
                        "shape": shape,
                    }
                )
    return found


def _assert_matrix_policy_source() -> None:
    """Ensure the matrix still contains the expected ForbiddenError evidence."""

    matrix = _load_json(MATRIX_PATH)
    cells = matrix.get("cells", [])
    has_forbidden = any(
        cell.get("status") == "does_not_work"
        and cell.get("http_status") == 403
        and cell.get("error") == "ForbiddenError"
        for cell in cells
    )
    if not has_forbidden:
        raise RuntimeError("matrix.json no longer contains 403 ForbiddenError denial evidence")


def main() -> int:
    expected = expected_methods()
    decorated = decorated_methods()
    errors: list[str] = []

    for method_id, expected_shape in sorted(expected.items()):
        declarations = decorated.get(method_id, [])
        if len(declarations) != 1:
            errors.append(
                f"{method_id}: expected exactly one decorator, found {len(declarations)}"
            )
            continue
        actual_shape = declarations[0]["shape"]
        if actual_shape != expected_shape:
            errors.append(
                f"{method_id}: shape mismatch expected={expected_shape} actual={actual_shape}"
            )

    for method_id in sorted(set(decorated) - set(expected)):
        errors.append(f"{method_id}: decorated but not expected runtime current_used")

    try:
        _assert_matrix_policy_source()
    except RuntimeError as exc:
        errors.append(str(exc))

    if errors:
        print("method auth audit failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"method auth audit ok: {len(expected)} declarations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
