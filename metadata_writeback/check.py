"""check — 申告（used_tools・tags・links）を読み、申告した道具を実行の記録と突き合わせる。

原則は「正直さを罰しない」。
  - 実行していない道具を申告した（盛り）だけを弾く。
  - 実行したのに申告していない（過少申告）は既定では観測だけ。
    フィオ本体は 2026-06 に「空にしておけば突合に引っかからない」をモデルが戦略として
    学習したため対称（過少申告も突き返す）へ戻した。その形は require_complete=True で選べる。
  - 実行の記録を渡せない経路（executed=None）では突き合わせない。未知を「一つも使っていない」
    と読むと、正直な申告が丸ごと盛りになって突き返しが空回りする。
  - 本文の「〜しました」に道具の裏付けが無い物（unbacked_action_claims）は列挙するだけで罰しない。
    意味内容の機械判定には誤検知が必ず混ざる。
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable

__all__ = [
    "parse_used_tools",
    "parse_tags",
    "parse_links",
    "compare_used_tools",
    "check_used_tools",
    "DEFAULT_CLAIM_RE",
    "DEFAULT_EXCLUDE_RE",
    "unbacked_action_claims",
]


def parse_used_tools(value: object) -> list[str] | None:
    """`used_tools` の申告を読む。

    list 以外（欠落の None・文字列・dict 等）は None（申告欠損）。list なら文字列の要素だけを
    採り、順序を保って重複を除く。空 list は有効な「使っていない」の申告。
    """
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for v in value:
        if not isinstance(v, str):
            continue
        name = v.strip()
        if name and name not in out:
            out.append(name)
    return out


_WS_RE = re.compile(r"\s+")


def parse_tags(value: object) -> list[str]:
    """`memory_tags` の申告をタグ列へ正規化する。

    文字列の要素だけを採る。`#` の有無はどちらでも受け、必ず `#` 一つを頭に付けた形へ寄せる
    （`ctx/a` と `#ctx/a` は同じタグ）。中の空白は `_` に畳む。順序を保って重複を除く。
    list 以外・空は []。
    """
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for v in value:
        if not isinstance(v, str):
            continue
        t = v.strip().lstrip("#").strip()
        if not t:
            continue
        t = "#" + _WS_RE.sub("_", t)
        if t not in out:
            out.append(t)
    return out


def parse_links(value: object) -> list[str]:
    """`memory_links` の申告を読む。`[[slug]]` の包みは外す。list 以外・空は []。

    捏造されたリンクの実害は小さい（解決しないリンクは下流で無視される）ので、ここでは弾かない。
    """
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for v in value:
        if not isinstance(v, str):
            continue
        link = v.strip()
        if link.startswith("[[") and link.endswith("]]"):
            link = link[2:-2].strip()
        if link and link not in out:
            out.append(link)
    return out


def _identity(name: str) -> str:
    return name


def compare_used_tools(
    declared: object,
    executed: Iterable[str] | None,
    only_prefix: str | None = None,
    canonical: Callable[[str], str] | None = None,
) -> tuple[list[str], list[str]] | None:
    """申告と実行の記録を突き合わせ、(盛り, 過少申告) を返す。突き合わせられない時は None。

    declared     METADATA の `used_tools` の生の値（list 以外は「申告無し」として空扱い）
    executed     このターンに実際に実行した道具の名前。None＝記録を渡せない経路（突き合わせない）
    only_prefix  指定すると、この接頭辞で始まる名前だけを両側で見る（器に元から付いている道具を外す）
    canonical    名前を現行名へ寄せる関数（改名・別名の巻き添えで正直さを罰しないため）
    """
    if executed is None:
        return None
    canon = canonical or _identity
    declared_list = parse_used_tools(declared) or []
    executed_list = [str(n).strip() for n in executed if str(n).strip()]
    if only_prefix:
        declared_list = [n for n in declared_list if n.startswith(only_prefix)]
        executed_list = [n for n in executed_list if n.startswith(only_prefix)]
    executed_canon = {canon(n) for n in executed_list}
    declared_canon = {canon(n) for n in declared_list}
    over = [n for n in declared_list if canon(n) not in executed_canon]
    under: list[str] = []
    for n in executed_list:
        if canon(n) not in declared_canon and n not in under:
            under.append(n)
    return over, under


def check_used_tools(
    declared: object,
    executed: Iterable[str] | None,
    only_prefix: str | None = None,
    require_complete: bool = False,
    canonical: Callable[[str], str] | None = None,
    lang: str = "ja",
) -> str | None:
    """`used_tools` の申告を実行の記録と突き合わせ、突き返す理由の文を返す。問題が無ければ None。

    既定で弾くのは盛り（実行していない道具の申告）だけ。require_complete=True なら
    過少申告（実行したのに申告していない・申告欄そのものが無い）も突き返す。
    executed が None（記録を渡せない経路）なら何も言わない。
    """
    cmp = compare_used_tools(declared, executed, only_prefix, canonical)
    if cmp is None:
        return None
    over, under = cmp
    issues: list[str] = []
    if over:
        issues.append(
            f"tools listed but not executed: {over}" if lang == "en"
            else f"実際には実行していない道具が含まれています: {over}"
        )
    if require_complete and under:
        issues.append(
            f"executed tools missing from the list: {under} (leaving them out is the same as claiming you did not use them)"
            if lang == "en"
            else f"実行した道具の記載漏れがあります: {under}（空のままにする・一部を省くのは、使っていないと申告するのと同じです）"
        )
    if not issues:
        return None
    if lang == "en":
        return "`used_tools` does not match the execution log — " + "; ".join(issues) + "."
    return "`used_tools` の申告が実行の記録と一致しません — " + "、".join(issues) + "。"


# ---------------------------------------------------------------------------
# 本文の実行主張（観測のみ）
# ---------------------------------------------------------------------------

_SENT_SPLIT = re.compile(r"[。\n！!？?]|(?<=[.])\s+")

#: 完了形の実行報告（日本語＋英語）。`まし` は後ろが `た`/`て` の時だけ完了形——
#: 「何を検索しましょう」（意志・勧誘）まで拾って台帳に刻んだ実測があった。
DEFAULT_CLAIM_RE = re.compile(
    r"(読んでき(?:た|まし(?=[たて]))|見てき(?:た|まし(?=[たて]))|取れた|取れまし(?=[たて])|"
    r"取得し(?:た|まし(?=[たて]))|実行し(?:た|まし(?=[たて]))|呼びまし(?=[たて])|"
    r"検索し(?:た|まし(?=[たて]))|調べてき(?:た|まし(?=[たて]))|投げまし(?=[たて])|起動して(?:い)?ま"
    r"|\bI(?:'ve| have)? (?:read|ran|run|executed|searched|fetched|checked|opened|looked up)\b)",
    re.IGNORECASE,
)

#: 否定・失敗・未来・意図・過去ターン参照。これを含む文は数えない（正直さを罰しない）。
DEFAULT_EXCLUDE_RE = re.compile(
    r"(ない|ません|なかった|失敗|未実行|エラー|架空|捏造|これから|予定|つもり|"
    r"しよう|したい|してみ|あとで|さっき|前のターン|昨日|今朝"
    r"|\b(?:not|n't|never|failed|cannot|can't|will|going to|plan to|earlier|yesterday|last turn)\b)",
    re.IGNORECASE,
)


def unbacked_action_claims(
    body: str,
    executed: Iterable[str] | None,
    claim_re: re.Pattern[str] = DEFAULT_CLAIM_RE,
    exclude_re: re.Pattern[str] = DEFAULT_EXCLUDE_RE,
    limit: int = 5,
) -> list[str]:
    """道具を一つも実行していないターンで、本文に完了形の実行報告が無いかを走査する。

    「used_tools は正直に空、嘘は本文に置く」という抜け道を可視化する。否定・失敗報告・
    未来・意図・過去ターン参照を含む文は除く。実行の記録が不明（None）か、何か実行した
    ターンは対象外。返すのは当たった文の先頭 40 字まで（最大 limit 件）——観測のためだけで、
    突き返しには使わない。
    """
    if executed is None:
        return []
    if any(str(n).strip() for n in executed):
        return []
    hits: list[str] = []
    for sent in _SENT_SPLIT.split(body or ""):
        sent = (sent or "").strip()
        if not sent:
            continue
        if claim_re.search(sent) and not exclude_re.search(sent):
            hits.append(sent[:40])
            if len(hits) >= limit:
                break
    return hits
