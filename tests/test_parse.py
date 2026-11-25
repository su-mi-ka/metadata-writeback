"""parse の柵: 三段の救済・本文の掃除が対称であること・寛容パースの梯子と関所。"""
import re

import pytest

from metadata_writeback import (
    extract_outermost_object,
    lenient_json_loads,
    looks_like_metadata,
    remove_metadata_blocks,
    split,
    strip_code_fence,
    strip_json_noise,
    strip_orphan_fence,
    strip_thinking,
    unwrap_single_key,
)

M = "ab12cd34"
S = f"<<<METADATA:{M}>>>"
E = f"<<<END_METADATA:{M}>>>"
JSON_OK = '{"new_memory": "覚える", "memory_importance": 300, "used_tools": []}'


# ---- ブロックの形（Tier-1〜3） -------------------------------------------------

def test_tier1_marker_matched():
    r = split(f"こんにちは。\n{S}\n{JSON_OK}\n{E}", M)
    assert r.tier == 1 and r.matched_marker == M and r.rescue == "strict"
    assert r.metadata["new_memory"] == "覚える"
    assert r.body == "こんにちは。"


def test_wrapped_in_json_fence_is_removed_with_the_fence():
    r = split(f"こんにちは。\n```json\n{S}\n{JSON_OK}\n{E}\n```", M)
    assert r.tier == 1
    assert r.metadata["memory_importance"] == 300
    assert r.body == "こんにちは。"  # 包みのフェンスは残らない


def test_fence_inside_the_block_is_stripped_before_json():
    r = split(f"本文\n{S}\n```json\n{JSON_OK}\n```\n{E}", M)
    assert r.metadata is not None and r.rescue == "fence"
    assert r.body == "本文"


def test_tier2_hallucinated_marker_pair_is_rescued():
    r = split(f"本文\n<<<METADATA:deadbeef>>>\n{JSON_OK}\n<<<END_METADATA:deadbeef>>>", M)
    assert r.tier == 2 and r.matched_marker == "deadbeef"
    assert r.metadata["new_memory"] == "覚える"
    assert r.body == "本文"


def test_tier3_end_marker_missing():
    r = split(f"本文\n{S}\n{JSON_OK}", M)
    assert r.tier == 3 and r.metadata is not None
    assert r.body == "本文"


def test_tier3_with_marker_mismatch():
    r = split(f"本文\n<<<METADATA:0123abcd>>>\n{JSON_OK}", M)
    assert r.tier == 3 and r.matched_marker == "0123abcd" and r.metadata is not None


def test_no_block_returns_none_and_keeps_body():
    r = split("本文だけ。", M)
    assert r.tier is None and r.metadata is None and r.body == "本文だけ。"
    assert "no block" in r.note


def test_body_mention_of_fixed_metadata_string_is_not_a_block():
    text = "本文の末尾に <<<METADATA>>> と <<<END_METADATA>>> で挟んで書きます。"
    r = split(text, M)
    assert r.tier is None and r.metadata is None
    assert r.body == text  # 一字も削られない


def test_empty_object_is_empty_dict_not_none():
    r = split(f"本文\n{S}\n{{}}\n{E}", M)
    assert r.metadata == {} and r.metadata is not None


def test_empty_reply():
    r = split("", M)
    assert r.body == "" and r.metadata is None and r.tier is None


def test_body_ending_with_code_block_keeps_its_closing_fence():
    body = "例です。\n```python\nprint(1)\n```"
    r = split(f"{body}\n{S}\n{JSON_OK}\n{E}", M)
    assert r.body == body
    assert r.metadata is not None


def test_two_blocks_are_both_removed():
    text = f"本文\n{S}\n{JSON_OK}\n{E}\n<<<METADATA:feedface>>>\n{{}}\n<<<END_METADATA:feedface>>>"
    r = split(text, M)
    assert r.body == "本文"
    assert r.metadata["new_memory"] == "覚える"  # 渡した印の方を採る


def test_non_dict_json_is_none():
    r = split(f"本文\n{S}\n[1, 2, 3]\n{E}", M)
    assert r.tier == 1 and r.metadata is None and r.rescue is None
    assert "unreadable" in r.note


# ---- 梯子（中身の書き癖） ------------------------------------------------------

def test_single_quoted_json_is_rescued():
    r = split(f"本文\n{S}\n{{'new_memory': 'a', 'memory_importance': 3}}\n{E}", M)
    assert r.rescue == "single_quotes"
    assert r.metadata == {"new_memory": "a", "memory_importance": 3}


def test_trailing_comma_and_comment_are_rescued_but_url_is_kept():
    broken = '{"new_memory": "https://example.invalid/x", // メモ\n "memory_tags": ["a",],}'
    r = split(f"本文\n{S}\n{broken}\n{E}", M)
    assert r.rescue == "comment_or_trailing_comma"
    assert r.metadata == {"new_memory": "https://example.invalid/x", "memory_tags": ["a"]}


def test_think_block_before_json_is_rescued():
    r = split(f"本文\n{S}\n<think>{{ ここで考えた }}</think>\n{JSON_OK}\n{E}", M)
    assert r.rescue == "thinking"
    assert r.metadata["new_memory"] == "覚える"


def test_prose_around_json_is_rescued_by_outermost_object():
    r = split(f"本文\n{S}\nはい、こちらです: {JSON_OK} 以上です\n{E}", M)
    assert r.rescue == "outermost_object"
    assert r.metadata["new_memory"] == "覚える"


def test_single_key_wrapper_is_unwrapped():
    r = split(f"本文\n{S}\n{{\"metadata\": {JSON_OK}}}\n{E}", M)
    assert r.metadata["new_memory"] == "覚える"
    assert r.rescue == "unwrapped"


def test_tier3_does_not_adopt_a_json_example_from_the_body():
    # 終了の印が欠け、本文に既知のキーを持たない JSON の例が在る → 偽の記憶を焼かない
    r = split(f"説明します。\n{S}\n例えば {{\"foo\": 1}} のように書きます", M)
    assert r.tier == 3 and r.metadata is None


# ---- 部品 --------------------------------------------------------------------

def test_strip_code_fence_only_touches_fenced_text():
    assert strip_code_fence("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert strip_code_fence('{"a": 1}') == '{"a": 1}'


def test_strip_thinking_leaves_unclosed_think_alone():
    assert strip_thinking('<think>x</think>{"a": 1}') == '{"a": 1}'
    assert strip_thinking('<think>{"a": 1}') == '<think>{"a": 1}'
    assert strip_thinking('前置き</think>{"a": 1}') == '{"a": 1}'


def test_extract_outermost_object_ignores_braces_in_strings():
    assert extract_outermost_object('x {"a": "}{", "b": {"c": 1}} y') == '{"a": "}{", "b": {"c": 1}}'
    assert extract_outermost_object("no braces") is None


def test_strip_json_noise_keeps_strings_intact():
    assert strip_json_noise('{"u": "http://a/b", /* c */ "x": [1,],}') == '{"u": "http://a/b",  "x": [1]}'


def test_looks_like_metadata_and_unwrap_gate():
    assert looks_like_metadata({"new_memory": "a"})
    assert not looks_like_metadata({"foo": 1})
    assert unwrap_single_key({"wrap": {"new_memory": "a"}}) == {"new_memory": "a"}
    assert unwrap_single_key({"wrap": {"foo": 1}}) is None
    assert unwrap_single_key({"a": {"new_memory": 1}, "b": 2}) is None


def test_lenient_json_loads_rejects_unknown_dict_found_by_ladder():
    assert lenient_json_loads('{"foo": 1,}') is None  # 梯子で拾ったが既知のキーが無い
    assert lenient_json_loads('{"foo": 1}') == {"foo": 1}  # 素で読める物はそのまま
    assert lenient_json_loads("{}") == {}
    assert lenient_json_loads("not json") is None


def test_remove_metadata_blocks_is_symmetric_about_fences():
    pat = re.compile(r"<<<METADATA:[0-9a-f]{8}>>>.*?<<<END_METADATA:[0-9a-f]{8}>>>", re.DOTALL)
    wrapped = f"本文\n```\n{S}\n{{}}\n{E}\n```"
    assert remove_metadata_blocks(wrapped, pat).strip() == "本文"
    code_end = f"本文\n```py\nx\n```\n{S}\n{{}}\n{E}"
    assert remove_metadata_blocks(code_end, pat).strip() == "本文\n```py\nx\n```"


@pytest.mark.parametrize("text, expected", [
    ("本文\n```", "本文"),                      # 孤児の一本は落とす
    ("本文\n```py\nx\n```", "本文\n```py\nx\n```"),  # 対が取れていれば触らない
    ("末尾が `ls` です", "末尾が `ls` です"),       # インラインコードは対象外
])
def test_strip_orphan_fence(text, expected):
    assert strip_orphan_fence(text) == expected
