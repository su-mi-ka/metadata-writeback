"""receive の柵: 8 例の判定・突き返しの文の形・書く dict の形・tool の出口との合流。"""
from metadata_writeback import (
    Received,
    build_write,
    end_marker,
    instructions,
    receive,
    receive_dict,
    start_marker,
)

M = "ab12cd34"
S, E = start_marker(M), end_marker(M)
JSON_OK = (
    '{"thinking": "挨拶", "used_tools": [], "new_memory": "所有者は朝に挨拶する", '
    '"memory_importance": 300, "memory_type": "episodic", "memory_tags": ["ctx/greeting"], "memory_links": []}'
)


def _first_line(r: Received) -> str:
    assert r.bounce is not None
    return r.bounce.splitlines()[0]


# ---- 8 例 --------------------------------------------------------------------

def test_1_normal_is_accepted_and_written():
    r = receive(f"おはよう。\n{S}\n{JSON_OK}\n{E}", M, executed_tools=[])
    assert r.accepted and r.should_write
    assert r.body == "おはよう。"
    assert r.write == {
        "new_memory": "所有者は朝に挨拶する",
        "memory_importance": 300,
        "memory_type": "episodic",
        "memory_tags": ["#ctx/greeting", "#k/episodic"],
        "memory_links": [],
    }
    assert r.split.tier == 1


def test_2_json_fenced_block_is_accepted():
    r = receive(f"おはよう。\n```json\n{S}\n{JSON_OK}\n{E}\n```", M, executed_tools=[])
    assert r.accepted and r.body == "おはよう。"


def test_3_hallucinated_marker_is_accepted_via_tier2():
    r = receive(f"おはよう。\n<<<METADATA:deadbeef>>>\n{JSON_OK}\n<<<END_METADATA:deadbeef>>>", M, executed_tools=[])
    assert r.accepted and r.split.tier == 2 and r.split.matched_marker == "deadbeef"


def test_4_missing_end_marker_is_accepted_via_tier3():
    r = receive(f"おはよう。\n{S}\n{JSON_OK}", M, executed_tools=[])
    assert r.accepted and r.split.tier == 3


def test_5_no_metadata_is_bounced_with_instructions():
    r = receive("METADATA は <<<METADATA>>> の印で挟んで書きます。", M, executed_tools=[])
    assert not r.accepted and r.write is None
    assert "付いていません" in _first_line(r)
    assert _first_line(r).startswith(f"〔METADATA bounce・marker={M}〕")
    assert "本文はそのままで構いません" in r.bounce
    assert r.bounce.endswith(instructions(M))
    assert r.bounce.count(M) == 3  # 見出しに一度・決まりの文に二度
    assert r.body == "METADATA は <<<METADATA>>> の印で挟んで書きます。"  # 本文の言及は無事


def test_6_empty_object_is_bounced_as_empty():
    r = receive(f"おはよう。\n{S}\n{{}}\n{E}", M, executed_tools=[])
    assert not r.accepted and "空" in _first_line(r)
    assert r.metadata == {}


def test_7_inflated_used_tools_is_bounced():
    reply = f"天気を取得しました。\n{S}\n" + '{"used_tools": ["mcp__weather__today", "Bash"], "new_memory": "晴れ"}' + f"\n{E}"
    r = receive(reply, M, executed_tools=["Bash"], only_prefix="mcp__")
    assert not r.accepted
    assert "mcp__weather__today" in _first_line(r) and "Bash" not in _first_line(r)
    # 同じ返事でも、本当に実行していれば通る
    r2 = receive(reply, M, executed_tools=["Bash", "mcp__weather__today"], only_prefix="mcp__")
    assert r2.accepted


def test_8_body_ending_with_code_block_is_preserved():
    body = "例です。\n```python\nprint(1)\n```"
    r = receive(f"{body}\n{S}\n{JSON_OK}\n{E}", M, executed_tools=[])
    assert r.accepted and r.body == body


# ---- 正直さを罰しない ------------------------------------------------------------

def test_executed_none_does_not_bounce_declared_tools():
    reply = f"本文\n{S}\n" + '{"used_tools": ["mcp__x__y"], "new_memory": "a"}' + f"\n{E}"
    assert receive(reply, M, executed_tools=None).accepted


def test_only_prefix_skips_builtin_tools():
    reply = f"本文\n{S}\n" + '{"used_tools": ["Bash", "Read"], "new_memory": "a"}' + f"\n{E}"
    assert receive(reply, M, executed_tools=[], only_prefix="mcp__").accepted
    assert not receive(reply, M, executed_tools=[]).accepted  # 接頭辞を切らなければ盛り


def test_under_declaration_is_accepted_by_default_and_bounced_when_required():
    reply = f"本文\n{S}\n" + '{"used_tools": [], "new_memory": "a"}' + f"\n{E}"
    assert receive(reply, M, executed_tools=["mcp__x__y"]).accepted
    assert not receive(reply, M, executed_tools=["mcp__x__y"], require_complete=True).accepted


def test_unbacked_claims_are_observed_not_bounced():
    reply = f"ファイルを読んできました。\n{S}\n" + '{"used_tools": [], "new_memory": "a"}' + f"\n{E}"
    r = receive(reply, M, executed_tools=[])
    assert r.accepted
    assert r.unbacked == ["ファイルを読んできました"]


# ---- 突き返しの理由と書く dict ----------------------------------------------------

def test_unreadable_json_has_its_own_reason():
    r = receive(f"本文\n{S}\nこれは JSON ではない\n{E}", M, executed_tools=[])
    assert not r.accepted and "読めませんでした" in _first_line(r)
    assert r.split.tier == 1 and r.split.json_text == "これは JSON ではない"


def test_require_memory_bounces_empty_new_memory():
    reply = f"本文\n{S}\n" + '{"used_tools": [], "new_memory": null, "memory_importance": 0}' + f"\n{E}"
    r = receive(reply, M, executed_tools=[])
    assert r.accepted and not r.should_write and r.write["new_memory"] == ""
    r2 = receive(reply, M, executed_tools=[], require_memory=True)
    assert not r2.accepted and "new_memory" in _first_line(r2)


def test_build_write_defaults_clamps_and_adds_kind_tag():
    w = build_write({"new_memory": "  a  ", "memory_importance": "1500", "memory_tags": ["x"]})
    assert w == {"new_memory": "a", "memory_importance": 1000, "memory_type": "episodic",
                 "memory_tags": ["#x", "#k/episodic"], "memory_links": []}
    w2 = build_write({"new_memory": None, "memory_importance": "abc", "memory_type": "semantic",
                      "memory_tags": ["#k/semantic"], "memory_links": ["[[s]]"]})
    assert w2["new_memory"] == "" and w2["memory_importance"] == 0
    assert w2["memory_tags"] == ["#k/semantic"] and w2["memory_links"] == ["s"]


def test_english_bounce():
    r = receive("no block here", M, executed_tools=[], lang="en")
    assert _first_line(r).startswith(f"[METADATA bounce / marker={M}]")
    assert "No METADATA block" in _first_line(r)
    assert r.bounce.endswith(instructions(M, lang="en"))


def test_receive_dict_is_the_same_contract_for_the_tool_exit():
    # tool（構造化出力）の出口: dict が直に来る。下流は出口の別を知らない
    r = receive_dict("本文", {"used_tools": [], "new_memory": "a", "memory_type": "procedural"}, M, [])
    assert r.accepted and r.write["memory_tags"] == ["#k/procedural"] and r.split is None
    assert not receive_dict("本文", {}, M, []).accepted
    assert "付いていません" in _first_line(receive_dict("本文", None, M, []))
    assert not receive_dict("本文", {"used_tools": ["mcp__x"], "new_memory": "a"}, M, []).accepted
