from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .kicad_parser import KiCadItem


@dataclass(frozen=True)
class SaveResult:
    path: Path
    backup_path: Path
    changed_fields: list[str]


class MetadataSaveError(RuntimeError):
    pass


def save_metadata_changes(item: KiCadItem, changes: dict[str, str]) -> SaveResult:
    clean_changes = {field.strip(): value for field, value in changes.items() if field.strip()}
    if not clean_changes:
        raise MetadataSaveError("No metadata changes were selected.")

    text = item.path.read_text(encoding="utf-8-sig")
    if item.item_type == "Footprint":
        updated_text, changed_fields = _update_footprint(text, clean_changes)
    elif item.item_type == "Symbol":
        updated_text, changed_fields = _update_symbol_library(text, item.name, clean_changes)
    else:
        raise MetadataSaveError(f"Saving is not supported for {item.item_type}.")

    if not changed_fields:
        raise MetadataSaveError("Selected changes did not modify the KiCad file.")

    backup_path = _backup_path(item.path)
    shutil.copy2(item.path, backup_path)
    item.path.write_text(updated_text, encoding="utf-8")
    return SaveResult(item.path, backup_path, changed_fields)


def _update_footprint(text: str, changes: dict[str, str]) -> tuple[str, list[str]]:
    span = _find_first_list_span(text, "footprint") or _find_first_list_span(text, "module")
    if span is None:
        raise MetadataSaveError("Could not find a footprint block to update.")

    start, end = span
    block = text[start:end]
    changed_fields: list[str] = []
    for field, value in changes.items():
        updated_block = _update_footprint_field(block, field, value)
        if updated_block != block:
            block = updated_block
            changed_fields.append(field)

    return text[:start] + block + text[end:], changed_fields


def _update_symbol_library(text: str, symbol_name: str, changes: dict[str, str]) -> tuple[str, list[str]]:
    span = _find_named_list_span(text, "symbol", symbol_name)
    if span is None:
        raise MetadataSaveError(f"Could not find symbol block: {symbol_name}")

    start, end = span
    block = text[start:end]
    next_property_id = _next_symbol_property_id(block)
    changed_fields: list[str] = []
    for field, value in changes.items():
        updated_block, next_property_id = _update_symbol_property(block, field, value, next_property_id)
        if updated_block != block:
            block = updated_block
            changed_fields.append(field)

    return text[:start] + block + text[end:], changed_fields


def _update_footprint_field(block: str, field: str, value: str) -> str:
    field_key = field.casefold()
    if field_key == "value":
        return _replace_first_quoted_value(block, r"(\(fp_text\s+value\s+\")", value)
    if field_key == "reference":
        return _replace_first_quoted_value(block, r"(\(fp_text\s+reference\s+\")", value)
    if field_key == "description":
        updated = _replace_first_quoted_value(block, r"(\(descr\s+\")", value)
        if updated != block:
            return updated
        return _insert_after_first_line(block, f"{_child_indent(block)}(descr {_quote(value)})\n")
    return _update_or_add_footprint_property(block, field, value)


def _update_or_add_footprint_property(block: str, field: str, value: str) -> str:
    updated = _replace_property_value(block, field, value)
    if updated != block:
        return updated

    indent = _child_indent(block)
    nested_indent = indent + "  "
    property_block = (
        f"{indent}(property {_quote(field)} {_quote(value)}\n"
        f"{nested_indent}(at 0 0 0)\n"
        f"{nested_indent}(unlocked yes)\n"
        f"{nested_indent}(layer \"F.Fab\")\n"
        f"{nested_indent}(hide yes)\n"
        f"{nested_indent}(uuid \"{uuid.uuid4()}\")\n"
        f"{nested_indent}(effects (font (size 1 1) (thickness 0.15)))\n"
        f"{indent})\n"
    )
    return _insert_before_block_close(block, property_block)


def _update_symbol_property(
    block: str,
    field: str,
    value: str,
    next_property_id: int,
) -> tuple[str, int]:
    updated = _replace_property_value(block, field, value)
    if updated != block:
        return updated, next_property_id

    indent = _child_indent(block)
    nested_indent = indent + "  "
    property_block = (
        f"{indent}(property {_quote(field)} {_quote(value)} (id {next_property_id}) (at 0 0 0)\n"
        f"{nested_indent}(effects (font (size 1.27 1.27)) hide)\n"
        f"{indent})\n"
    )
    return _insert_before_first_nested_symbol(block, property_block), next_property_id + 1


def _replace_property_value(block: str, field: str, value: str) -> str:
    escaped_field = re.escape(_quote_body(field))
    pattern = re.compile(r'(\(property\s+"' + escaped_field + r'"\s+")((?:\\.|[^"\\])*)(")')
    return pattern.sub(lambda match: match.group(1) + _quote_body(value) + match.group(3), block, count=1)


def _replace_first_quoted_value(block: str, prefix_pattern: str, value: str) -> str:
    pattern = re.compile(prefix_pattern + r'((?:\\.|[^"\\])*)(")')
    return pattern.sub(lambda match: match.group(1) + _quote_body(value) + match.group(3), block, count=1)


def _find_first_list_span(text: str, head: str) -> tuple[int, int] | None:
    match = re.search(r"\(" + re.escape(head) + r"(?:\s|\))", text)
    if match is None:
        return None
    return match.start(), _find_matching_close(text, match.start())


def _find_named_list_span(text: str, head: str, name: str) -> tuple[int, int] | None:
    name_pattern = re.escape(_quote_body(name))
    pattern = re.compile(r'\(' + re.escape(head) + r'\s+"' + name_pattern + r'"(?:\s|\))')
    match = pattern.search(text)
    if match is None:
        return None
    return match.start(), _find_matching_close(text, match.start())


def _find_matching_close(text: str, open_index: int) -> int:
    depth = 0
    in_string = False
    escape_next = False
    for index in range(open_index, len(text)):
        char = text[index]
        if in_string:
            if escape_next:
                escape_next = False
            elif char == "\\":
                escape_next = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise MetadataSaveError("Could not find the end of the KiCad block.")


def _insert_after_first_line(block: str, insertion: str) -> str:
    newline_index = block.find("\n")
    if newline_index < 0:
        return block[:-1] + "\n" + insertion + ")"
    return block[: newline_index + 1] + insertion + block[newline_index + 1 :]


def _insert_before_block_close(block: str, insertion: str) -> str:
    close_index = block.rfind(")")
    if close_index < 0:
        raise MetadataSaveError("Could not find a KiCad block closing parenthesis.")
    return block[:close_index] + insertion + block[close_index:]


def _insert_before_first_nested_symbol(block: str, insertion: str) -> str:
    root_line_end = block.find("\n")
    nested_match = re.search(r'(?m)^\s+\(symbol\s+"', block[root_line_end + 1 :])
    if nested_match is None:
        return _insert_before_block_close(block, insertion)
    insert_index = root_line_end + 1 + nested_match.start()
    return block[:insert_index] + insertion + block[insert_index:]


def _child_indent(block: str) -> str:
    first_line = block.splitlines()[0] if block.splitlines() else ""
    parent_indent = first_line[: len(first_line) - len(first_line.lstrip())]
    return parent_indent + "  "


def _next_symbol_property_id(block: str) -> int:
    ids = [int(match.group(1)) for match in re.finditer(r"\(property\s+\"(?:\\.|[^\"])*\"\s+\"(?:\\.|[^\"])*\"\s+\(id\s+(\d+)\)", block)]
    return max(ids, default=-1) + 1


def _backup_path(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return path.with_name(f"{path.name}.kml_backup_{timestamp}")


def _quote(value: str) -> str:
    return f'"{_quote_body(value)}"'


def _quote_body(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
