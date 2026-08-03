from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SExpr = str | list["SExpr"]


@dataclass
class KiCadItem:
    item_type: str
    name: str
    path: Path
    properties: dict[str, str] = field(default_factory=dict)
    summary: dict[str, str] = field(default_factory=dict)


def parse_sexpr(text: str) -> list[SExpr]:
    tokens = _tokenize(text)
    index = 0

    def parse_node() -> SExpr:
        nonlocal index
        if index >= len(tokens):
            raise ValueError("Unexpected end of file.")

        token = tokens[index]
        index += 1

        if token == "(":
            node: list[SExpr] = []
            while index < len(tokens) and tokens[index] != ")":
                node.append(parse_node())
            if index >= len(tokens):
                raise ValueError("Missing closing parenthesis.")
            index += 1
            return node

        if token == ")":
            raise ValueError("Unexpected closing parenthesis.")

        return token

    roots: list[SExpr] = []
    while index < len(tokens):
        roots.append(parse_node())
    return roots


def load_footprint(path: Path) -> KiCadItem:
    text = path.read_text(encoding="utf-8-sig")
    root = _first_list(parse_sexpr(text))
    if not root or _atom(root, 0) not in {"footprint", "module"}:
        raise ValueError("The selected file is not a KiCad footprint.")

    properties = _direct_properties(root)
    name = _atom(root, 1) or path.stem
    value = _fp_text_value(root, "value")
    reference = _fp_text_value(root, "reference")
    description = _single_child_value(root, "descr")
    model_paths = [
        _atom(child, 1)
        for child in _direct_children(root, "model")
        if _atom(child, 1)
    ]
    pad_count = sum(1 for child in root if _list_starts_with(child, "pad"))

    summary = {
        "Name": name,
        "Reference": reference,
        "Value": value,
        "Description": description,
        "Model": model_paths[0] if model_paths else "",
        "Pad count": str(pad_count) if pad_count else "",
    }

    combined = {key: value for key, value in summary.items() if value}
    combined.update(properties)
    return KiCadItem("Footprint", name, path, combined, summary)


def load_symbol_names(path: Path) -> list[str]:
    root = _load_symbol_library_root(path)
    names = [_atom(child, 1) for child in _direct_children(root, "symbol")]
    return sorted(name for name in names if name)


def load_symbol(path: Path, symbol_name: str) -> KiCadItem:
    root = _load_symbol_library_root(path)
    for child in _direct_children(root, "symbol"):
        if _atom(child, 1) == symbol_name:
            properties = _direct_properties(child)
            summary = {
                "Name": symbol_name,
                "Reference": properties.get("Reference", ""),
                "Value": properties.get("Value", ""),
                "Footprint": properties.get("Footprint", ""),
                "Description": properties.get("Description", ""),
                "Datasheet": properties.get("Datasheet", ""),
            }
            combined = {key: value for key, value in summary.items() if value}
            combined.update(properties)
            return KiCadItem("Symbol", symbol_name, path, combined, summary)

    raise ValueError(f"Symbol not found: {symbol_name}")


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char == ";":
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char in "()":
            tokens.append(char)
            index += 1
            continue
        if char == '"':
            index += 1
            value = []
            while index < len(text):
                char = text[index]
                if char == "\\" and index + 1 < len(text):
                    value.append(text[index + 1])
                    index += 2
                    continue
                if char == '"':
                    index += 1
                    break
                value.append(char)
                index += 1
            tokens.append("".join(value))
            continue

        start = index
        while index < len(text) and not text[index].isspace() and text[index] not in "()":
            index += 1
        tokens.append(text[start:index])
    return tokens


def _load_symbol_library_root(path: Path) -> list[SExpr]:
    text = path.read_text(encoding="utf-8-sig")
    root = _first_list(parse_sexpr(text))
    if not root or _atom(root, 0) != "kicad_symbol_lib":
        raise ValueError("The selected file is not a KiCad symbol library.")
    return root


def _first_list(values: list[SExpr]) -> list[SExpr]:
    for value in values:
        if isinstance(value, list):
            return value
    return []


def _atom(values: list[SExpr], index: int) -> str:
    if index >= len(values):
        return ""
    value = values[index]
    return value if isinstance(value, str) else ""


def _list_starts_with(value: SExpr, head: str) -> bool:
    return isinstance(value, list) and bool(value) and value[0] == head


def _direct_children(values: list[SExpr], head: str) -> list[list[SExpr]]:
    return [value for value in values if _list_starts_with(value, head)]


def _single_child_value(values: list[SExpr], head: str) -> str:
    for child in _direct_children(values, head):
        value = _atom(child, 1)
        if value:
            return value
    return ""


def _direct_properties(values: list[SExpr]) -> dict[str, str]:
    properties: dict[str, str] = {}
    for child in _direct_children(values, "property"):
        name = _atom(child, 1)
        value = _atom(child, 2)
        if name:
            properties[name] = value
    return properties


def _fp_text_value(values: list[SExpr], text_type: str) -> str:
    for child in _direct_children(values, "fp_text"):
        if _atom(child, 1) == text_type:
            return _atom(child, 2)
    return ""
