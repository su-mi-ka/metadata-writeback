"""marker の柵: 印の形・決まりの文に印が二度入る・欄の名前が揃う。"""
import re

from metadata_writeback import (
    DEFAULT_FIELDS,
    DEFAULT_KEYS,
    end_marker,
    instructions,
    new_marker,
    start_marker,
)


def test_new_marker_is_8_hex_and_changes():
    a, b = new_marker(), new_marker()
    assert re.fullmatch(r"[0-9a-f]{8}", a)
    assert re.fullmatch(r"[0-9a-f]{8}", b)
    assert a != b


def test_marker_lines_shape():
    assert start_marker("ab12cd34") == "<<<METADATA:ab12cd34>>>"
    assert end_marker("ab12cd34") == "<<<END_METADATA:ab12cd34>>>"


def test_instructions_contain_marker_twice_start_and_end():
    m = "ab12cd34"
    for lang in ("ja", "en"):
        text = instructions(m, lang=lang)
        assert text.count(m) == 2
        assert start_marker(m) in text and end_marker(m) in text
        # 開始が終了より前に在る
        assert text.index(start_marker(m)) < text.index(end_marker(m))


def test_instructions_name_every_default_field():
    text = instructions("ab12cd34")
    for f in DEFAULT_FIELDS:
        assert f"- {f.name}:" in text
        assert f'"{f.name}"' in text  # JSON の例にも入っている


def test_instructions_only_prefix_line_is_optional():
    assert "mcp__" not in instructions("ab12cd34")
    assert "mcp__" in instructions("ab12cd34", only_prefix="mcp__")
    assert "mcp__" in instructions("ab12cd34", only_prefix="mcp__", lang="en")


def test_default_keys_are_default_field_names():
    assert DEFAULT_KEYS == frozenset(f.name for f in DEFAULT_FIELDS)
    assert {"thinking", "used_tools", "new_memory", "memory_importance",
            "memory_type", "memory_tags", "memory_links"} == set(DEFAULT_KEYS)
