from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def _type_matches(expected: str, value: Any) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int | float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _validate(schema: dict[str, Any], value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []

    if "oneOf" in schema:
        matches = [not _validate(option, value, path) for option in schema["oneOf"]]
        if sum(matches) != 1:
            errors.append(f"{path}: expected exactly one oneOf schema to match")
        return errors

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _type_matches(expected_type, value):
        return [f"{path}: expected {expected_type}, got {type(value).__name__}"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}")
    if "pattern" in schema and isinstance(value, str) and not re.match(schema["pattern"], value):
        errors.append(f"{path}: does not match {schema['pattern']}")
    if "minLength" in schema and isinstance(value, str) and len(value) < schema["minLength"]:
        errors.append(f"{path}: shorter than minLength")
    if "minimum" in schema and isinstance(value, int | float) and value < schema["minimum"]:
        errors.append(f"{path}: below minimum")
    if "maximum" in schema and isinstance(value, int | float) and value > schema["maximum"]:
        errors.append(f"{path}: above maximum")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        pattern_properties = schema.get("patternProperties", {})
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{path}.{required}: missing required property")
        for key, item in value.items():
            matched = False
            if key in properties:
                matched = True
                errors.extend(_validate(properties[key], item, f"{path}.{key}"))
            for pattern, subschema in pattern_properties.items():
                if re.match(pattern, key):
                    matched = True
                    errors.extend(_validate(subschema, item, f"{path}.{key}"))
            if not matched:
                additional = schema.get("additionalProperties", True)
                if additional is False:
                    errors.append(f"{path}.{key}: unexpected property")
                elif isinstance(additional, dict):
                    errors.extend(_validate(additional, item, f"{path}.{key}"))

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate(item_schema, item, f"{path}[{index}]"))
        if schema.get("uniqueItems") and len(value) != len(set(json.dumps(item, sort_keys=True) for item in value)):
            errors.append(f"{path}: duplicate array items")

    return errors


def _assert_descriptions(schema: dict[str, Any], path: str = "$") -> None:
    assert schema.get("description"), f"{path}: missing description"
    for name, subschema in schema.get("properties", {}).items():
        _assert_descriptions(subschema, f"{path}.{name}")
    for pattern, subschema in schema.get("patternProperties", {}).items():
        _assert_descriptions(subschema, f"{path}.{pattern}")
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        _assert_descriptions(additional, f"{path}.*")
    items = schema.get("items")
    if isinstance(items, dict):
        _assert_descriptions(items, f"{path}[]")
    for index, option in enumerate(schema.get("oneOf", [])):
        _assert_descriptions(option, f"{path}.oneOf[{index}]")


def test_agent_config_schema_is_complete_for_current_sections() -> None:
    schema = json.loads((ROOT / "config.agent.schema.json").read_text(encoding="utf-8"))
    properties = schema["properties"]

    assert set(properties) == {"mail", "calendar", "contacts", "directory", "forms", "oauth_apps"}
    assert "accounts" not in properties
    assert "accounts" not in schema
    assert {"timezone", "utc_offset"} <= set(properties["calendar"]["properties"])
    assert "same UTC offset" in properties["calendar"]["description"]
    assert "config.skill.json" in properties["calendar"]["properties"]["timezone"]["description"]
    assert "CLI --timezone overrides" in properties["calendar"]["properties"]["timezone"]["description"]
    assert "CLI --utc-offset overrides" in properties["calendar"]["properties"]["utc_offset"]["description"]


def test_agent_config_schema_describes_all_defined_properties() -> None:
    schema = json.loads((ROOT / "config.agent.schema.json").read_text(encoding="utf-8"))
    _assert_descriptions(schema)


def test_agent_config_example_validates_against_schema() -> None:
    schema = json.loads((ROOT / "config.agent.schema.json").read_text(encoding="utf-8"))
    example = json.loads((ROOT / "config.agent.example.json").read_text(encoding="utf-8"))

    assert _validate(schema, example) == []
