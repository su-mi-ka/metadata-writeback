"""check の柵: 盛りだけ弾く・記録が無ければ突き合わせない・接頭辞で既存の道具を外す・正規化。"""
from metadata_writeback import (
    check_used_tools,
    compare_used_tools,
    parse_links,
    parse_tags,
    parse_used_tools,
    unbacked_action_claims,
)


def test_parse_used_tools():
    assert parse_used_tools(None) is None
    assert parse_used_tools("Bash") is None
    assert parse_used_tools([]) == []
    assert parse_used_tools([" Bash ", "Bash", 3, "", "Read"]) == ["Bash", "Read"]


def test_parse_tags_normalizes_hash_and_whitespace():
    assert parse_tags(["ctx/a", "#ctx/a", " #mode/b ", "two words", "#", "", 5]) == [
        "#ctx/a", "#mode/b", "#two_words",
    ]
    assert parse_tags("not a list") == []


def test_parse_links_unwraps_wikilinks():
    assert parse_links(["[[slug]]", "slug", " gist ", 1, ""]) == ["slug", "gist"]
    assert parse_links(None) == []


def test_executed_none_means_no_comparison():
    assert compare_used_tools(["mcp__x__y"], None) is None
    assert check_used_tools(["mcp__x__y"], None) is None


def test_over_declaration_is_bounced():
    msg = check_used_tools(["mcp__x__y"], [])
    assert msg is not None and "mcp__x__y" in msg


def test_under_declaration_is_not_bounced_by_default():
    assert check_used_tools([], ["mcp__x__y"]) is None
    assert check_used_tools(None, ["mcp__x__y"]) is None
    over, under = compare_used_tools([], ["mcp__x__y"])
    assert over == [] and under == ["mcp__x__y"]  # 観測はできる


def test_under_declaration_is_bounced_with_require_complete():
    msg = check_used_tools([], ["mcp__x__y"], require_complete=True)
    assert msg is not None and "mcp__x__y" in msg
    assert check_used_tools(["mcp__x__y"], ["mcp__x__y"], require_complete=True) is None


def test_only_prefix_excludes_builtin_tools_from_both_sides():
    # 申告した Bash/Read は実行記録に無いが、接頭辞の外なので盛りに数えない
    assert check_used_tools(["Bash", "Read", "mcp__x__y"], ["mcp__x__y"], only_prefix="mcp__") is None
    # 接頭辞の中の盛りは弾く
    msg = check_used_tools(["mcp__x__y", "Bash"], ["Read"], only_prefix="mcp__")
    assert msg is not None and "mcp__x__y" in msg and "Bash" not in msg


def test_canonical_name_mapping_does_not_punish_renames():
    canon = {"old_name": "new_name"}.get
    assert check_used_tools(["old_name"], ["new_name"], canonical=lambda n: canon(n, n)) is None
    assert check_used_tools(["old_name"], ["new_name"]) is not None


def test_check_message_language():
    assert "`used_tools`" in check_used_tools(["mcp__x"], [], lang="en")
    assert "not executed" in check_used_tools(["mcp__x"], [], lang="en")


def test_unbacked_claims_observed_only_when_nothing_was_executed():
    body = "ファイルを読んできました。設定も取得しました。"
    hits = unbacked_action_claims(body, [])
    assert hits == ["ファイルを読んできました", "設定も取得しました"]
    assert unbacked_action_claims(body, ["Read"]) == []   # 何か実行したターンは対象外
    assert unbacked_action_claims(body, None) == []       # 記録が無ければ対象外


def test_unbacked_claims_exclude_negation_future_and_invitation():
    assert unbacked_action_claims("取得していません。", []) == []
    assert unbacked_action_claims("これから実行します。あとで検索します。", []) == []
    assert unbacked_action_claims("何を検索しましょう、ご主人様", []) == []  # 「ましょう」は完了形ではない
    assert unbacked_action_claims("I will read the file.", []) == []
    assert unbacked_action_claims("I have read the file.", []) == ["I have read the file."]


def test_unbacked_claims_limit():
    body = "。".join(["取得しました"] * 10)
    assert len(unbacked_action_claims(body, [])) == 5
