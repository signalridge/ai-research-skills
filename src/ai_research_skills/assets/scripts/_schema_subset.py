"""JSON-Schema subset used when jsonschema is unavailable.

This is deliberately scoped to the schemas shipped by ai-research-skills. It implements
only the Draft 2020-12 keywords those schemas use and raises an explicit error for a
keyword outside that profile instead of claiming a document was validated.
"""

from __future__ import annotations

import datetime
import re
from typing import Any


class SchemaSubsetError(ValueError):
    pass


_SUPPORTED = {
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "title",
    "description",
    "type",
    "required",
    "additionalProperties",
    "properties",
    "items",
    "minItems",
    "minLength",
    "minimum",
    "maximum",
    "pattern",
    "format",
    "enum",
    "const",
    "if",
    "then",
    "allOf",
}


def _check_schema_keywords(schema: Any, where: str = "#") -> None:
    """Walk every schema node, including unused $defs, before validating an instance."""
    if not isinstance(schema, dict):
        raise SchemaSubsetError(f"schema node at {where} is not an object")
    unknown = set(schema) - _SUPPORTED
    if unknown:
        raise SchemaSubsetError(
            f"unsupported JSON Schema keyword(s) at {where}: " + ", ".join(sorted(unknown))
        )
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise SchemaSubsetError(f"schema properties at {where} must be an object")
        for name, child in properties.items():
            _check_schema_keywords(child, f"{where}/properties/{name}")
    defs = schema.get("$defs")
    if defs is not None:
        if not isinstance(defs, dict):
            raise SchemaSubsetError(f"schema $defs at {where} must be an object")
        for name, child in defs.items():
            _check_schema_keywords(child, f"{where}/$defs/{name}")
    for key in ("items", "additionalProperties", "if", "then"):
        child = schema.get(key)
        if isinstance(child, dict):
            _check_schema_keywords(child, f"{where}/{key}")
    all_of = schema.get("allOf")
    if all_of is not None:
        if not isinstance(all_of, list):
            raise SchemaSubsetError(f"schema allOf at {where} must be an array")
        for index, child in enumerate(all_of):
            _check_schema_keywords(child, f"{where}/allOf/{index}")


def _type_matches(value: Any, wanted: str) -> bool:
    if wanted == "object":
        return isinstance(value, dict)
    if wanted == "array":
        return isinstance(value, list)
    if wanted == "string":
        return isinstance(value, str)
    if wanted == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if wanted == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if wanted == "boolean":
        return isinstance(value, bool)
    if wanted == "null":
        return value is None
    raise SchemaSubsetError(f"unsupported JSON Schema type: {wanted}")


def iter_errors(
    instance: Any,
    schema: dict[str, Any],
    root: dict[str, Any] | None = None,
    path: tuple[Any, ...] = (),
) -> list[tuple[tuple[Any, ...], str]]:
    if root is None:
        root = schema
        _check_schema_keywords(schema)
    unknown = set(schema) - _SUPPORTED
    if unknown:
        raise SchemaSubsetError(
            "unsupported JSON Schema keyword(s): " + ", ".join(sorted(unknown))
        )
    errors: list[tuple[tuple[Any, ...], str]] = []
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            raise SchemaSubsetError(f"unsupported schema ref: {ref!r}")
        defs = root.get("$defs", {})
        target = defs.get(ref.removeprefix("#/$defs/"))
        if not isinstance(target, dict):
            raise SchemaSubsetError(f"missing schema definition: {ref}")
        return iter_errors(instance, target, root, path)

    wanted = schema.get("type")
    if wanted is not None:
        types = wanted if isinstance(wanted, list) else [wanted]
        if not all(isinstance(value, str) for value in types):
            raise SchemaSubsetError("schema type must be a string or string array")
        if not any(_type_matches(instance, value) for value in types):
            return [(path, f"is not of type {types!r}")]

    if "const" in schema and instance != schema["const"]:
        errors.append((path, f"is not {schema['const']!r}"))
    if "enum" in schema and instance not in schema["enum"]:
        errors.append((path, f"is not one of {schema['enum']!r}"))

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(((*path, key), "is a required property"))
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise SchemaSubsetError("schema properties must be an object")
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in properties:
                errors.extend(iter_errors(value, properties[key], root, (*path, key)))
            elif additional is False:
                errors.append(((*path, key), "is an additional property"))
            elif isinstance(additional, dict):
                errors.extend(iter_errors(value, additional, root, (*path, key)))
    elif isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(
                (path, f"has too few items ({len(instance)} < {schema['minItems']})")
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, value in enumerate(instance):
                errors.extend(iter_errors(value, item_schema, root, (*path, index)))
    elif isinstance(instance, str):
        if "format" in schema:
            if schema["format"] != "date":
                raise SchemaSubsetError(f"unsupported string format: {schema['format']!r}")
            try:
                datetime.date.fromisoformat(instance)
            except ValueError:
                errors.append((path, "is not a real ISO calendar date"))
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append((path, f"is too short ({len(instance)} < {schema['minLength']})"))
        if "pattern" in schema:
            try:
                matched = re.search(schema["pattern"], instance)
            except re.error as exc:
                raise SchemaSubsetError(f"invalid schema pattern: {exc}") from exc
            if not matched:
                errors.append((path, f"does not match {schema['pattern']!r}"))
    elif isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append((path, f"is less than minimum {schema['minimum']}"))
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append((path, f"is greater than maximum {schema['maximum']}"))

    for sub in schema.get("allOf", []):
        errors.extend(iter_errors(instance, sub, root, path))
    condition = schema.get("if")
    if isinstance(condition, dict) and not iter_errors(instance, condition, root, path):
        then = schema.get("then")
        if isinstance(then, dict):
            errors.extend(iter_errors(instance, then, root, path))
    return errors
