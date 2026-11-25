"""parse — 返事を本文と METADATA（dict）に分け、壊れた JSON を寛容に読む。

層は二つある。
  ブロックの形の救済（split の Tier-1〜3）
    1) 印が一致する開始・終了で挟まれたブロック
    2) 印が違っても、開始と終了が同じ hex で揃っているブロック（印の幻覚）
    3) 終了の印が欠けている（開始…末尾）
  中身の書き癖の救済（lenient_json_loads の梯子）
    <think> 除去 → コードフェンス剥がし → 最外の {…} 抽出 → コメント・末尾カンマ除去 → 単引用符

どちらも**救済であって防止ではない**。素の JSON が通る限り、梯子は一段も動かない。
救った段は SplitResult.rescue / note に残す——救済が常態化しているなら、それは
パーサで隠し続ける物ではなく、指示文かモデルの側を直す物だ。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .marker import DEFAULT_KEYS, MARKER_HEX_RE, end_marker, start_marker

__all__ = [
    "SplitResult",
    "strip_code_fence",
    "strip_thinking",
    "extract_outermost_object",
    "strip_json_noise",
    "single_to_double_quotes",
    "looks_like_metadata",
    "unwrap_single_key",
    "lenient_json_loads",
    "remove_metadata_blocks",
    "strip_orphan_fence",
    "split",
]

logger = logging.getLogger(__name__)

# コードフェンス。開き側は言語タグを伴いうる（```json）。閉じ側は裸。
_FENCE_OPEN_LINE = r"[ \t]*`{3,}[A-Za-z0-9_+.-]*[ \t]*"
_FENCE_LINE_RE = re.compile(rf"^{_FENCE_OPEN_LINE}$", re.MULTILINE)

# ブロックを包む開き側フェンス（直前の行）と、その閉じ側（直後の行）。
# 閉じ側は `Pattern.match(text, pos)` で途中から当てる。先頭に `\A` を書くと pos>0 では
# 決して当たらない（`\A` は文字列の本当の先頭にしか一致しない）ので付けない。
_LEADING_FENCE_RE = re.compile(rf"(?:\A|\n)({_FENCE_OPEN_LINE})\r?\n?\Z")
_TRAILING_FENCE_RE = re.compile(r"\r?\n?[ \t]*`{3,}[ \t]*(?=\r?\n|\Z)")

# `<think>` / `<reasoning>` の対。
_THINK_PAIR_RE = re.compile(r"<(think|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)
_THINK_HEAD_RE = re.compile(r"\A.*?</(?:think|reasoning)>", re.DOTALL | re.IGNORECASE)


# ---------------------------------------------------------------------------
# 中身の書き癖の救済
# ---------------------------------------------------------------------------

def strip_code_fence(text: str) -> str:
    """JSON 候補を包んでいるコードフェンスを剥がす。

    モデルは JSON を出せと言われると ```json で包む癖がある。ブロックの**内側**が
    包まれていると、剥がさない限り json.loads が必ず落ちて metadata=None になる
    ＝記憶が黙って死ぬ。本文側の掃除（remove_metadata_blocks）とは別口で、
    こちらは「JSON として読む直前」に効かせる。
    """
    if not text:
        return text
    t = text.strip()
    if not t.startswith("`"):
        return t
    t = re.sub(rf"\A{_FENCE_OPEN_LINE}\r?\n?", "", t)
    t = re.sub(r"\r?\n?[ \t]*`{3,}[ \t]*\Z", "", t)
    return t.strip()


def strip_thinking(text: str) -> str:
    """JSON 候補に混じった思考ブロック（<think>…</think>）を落とす。

    思考の中に `{` が一つでもあると extract_outermost_object がそちらから数え始めて、
    後ろにある本物の JSON に届かない。閉じないまま終わった <think> は触らない
    （開きタグの後ろに JSON が続く形は最外抽出が救えるので、以降を捨てると JSON まで消える）。
    判断が付かない時は残す——剥がしすぎより剥がし損ねの方が復旧できる。
    """
    if not text or "<" not in text:
        return text
    out = _THINK_PAIR_RE.sub("", text)
    # 開きタグをテンプレートが前置した形（閉じタグだけが孤立して先頭側に来る）。
    out = _THINK_HEAD_RE.sub("", out, count=1)
    return text if out == text else out.strip()


def extract_outermost_object(text: str) -> str | None:
    """最初の `{` から対応する `}` までを取り出す（文字列リテラル内の括弧は数えない）。

    ブロックの中にモデルが前置き・後書きの散文を混ぜた時の救済。
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def strip_json_noise(text: str) -> str:
    """JSON5 風の混入（// と /* */ のコメント・末尾カンマ）を落とす。**文字列の中は触らない**。

    素朴な正規表現でやると "https://example.com" の // を消して URL を壊す。
    記憶の本文には URL が入りうるので、文字列の内外を持って一度の走査で済ませる。
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_str = False
    esc = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def single_to_double_quotes(text: str) -> str:
    """全体が単引用符で書かれた擬似 JSON を二重引用符へ寄せる（梯子の最終段）。

    本文のアポストロフィと干渉するので、二重引用符が一つも無く単引用符が偶数個の時だけ試みる。
    判断が付かない物は素通しして失敗させる——「黙って別物になる」より「黙って落ちる」方が
    下流で気づける。
    """
    if '"' in text or text.count("'") % 2 != 0:
        return text
    return text.replace("'", '"')


def looks_like_metadata(parsed: dict, keys: frozenset[str] | set[str] = DEFAULT_KEYS) -> bool:
    """寛容パースが拾った dict を METADATA として採用してよいか（偽の記憶を焼かないための関所）。

    本文の中で METADATA の仕組みを説明したターンでは、本文に JSON の例が現に出る。
    終了の印が欠けた Tier-3 が本文を丸ごと候補にすると、最外の {…} 抽出が
    **本文に書かれた例**を拾ってしまう。既知のキーを一つも持たない dict は METADATA ではない、と見る。
    素の json.loads が通る正規のブロックはこの関所を通らないので、意図的な空 dict `{}` の意味は保たれる。
    """
    return bool(set(keys) & set(parsed))


def unwrap_single_key(parsed: dict, keys: frozenset[str] | set[str] = DEFAULT_KEYS) -> dict | None:
    """`{"metadata": {...}}` のようにキー一つで包まれた METADATA を開く。

    開くのはキーがちょうど一つで、中身が既知のキーを持つ時だけ。
    """
    if len(parsed) != 1:
        return None
    (inner,) = parsed.values()
    if isinstance(inner, dict) and looks_like_metadata(inner, keys):
        return inner
    return None


def _loads_with_ladder(json_text: str, keys: frozenset[str] | set[str]) -> tuple[dict | None, str | None]:
    """素の json.loads → 梯子。返すのは (dict|None, 救った段の名前|None)。

    梯子は「壊れ方の軽い順」で、途中で通ったらそこで止める。素の JSON が通る限り
    一段も介入しない（既定の挙動は不変）。
    """
    try:
        parsed = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        # 素で読めた dict はそのまま採る（空 dict `{}` も「空と申告した」として返す）。
        # 例外は「既知のキーを一つも持たないキー一つの包み」で、中身が METADATA なら開く
        # ——包みごと棄却すると中身は正しいのに記憶が落ちる。
        if parsed and not looks_like_metadata(parsed, keys):
            inner_d = unwrap_single_key(parsed, keys)
            if inner_d is not None:
                logger.warning("[METADATA] single-key wrapper -> using its content (wrapper=%r)", sorted(parsed)[0])
                return inner_d, "unwrapped"
        return parsed, "strict"
    if parsed is not None:
        # dict 以外（配列・数値…）が素で読めた。METADATA ではないので梯子にも掛けない。
        return None, None

    ladder: list[tuple[str, str]] = []
    base = json_text
    no_think = strip_thinking(base)
    if no_think != base:
        ladder.append(("thinking", no_think))
        base = no_think
    fenced = strip_code_fence(base)
    if fenced != base:
        ladder.append(("fence", fenced))
        base = fenced
    inner = extract_outermost_object(base)
    if inner is not None and inner != base:
        ladder.append(("outermost_object", inner))
        base = inner
    noise = strip_json_noise(base)
    if noise != base:
        ladder.append(("comment_or_trailing_comma", noise))
        base = noise
    quoted = single_to_double_quotes(base)
    if quoted != base:
        ladder.append(("single_quotes", quoted))

    for label, candidate in ladder:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        if not looks_like_metadata(parsed, keys):
            inner_d = unwrap_single_key(parsed, keys)
            if inner_d is None:
                logger.warning(
                    "[METADATA] lenient parse found a JSON object without any known key "
                    "-> treated as an example in the body and rejected (step=%s keys=%s)",
                    label, sorted(parsed)[:5],
                )
                continue
            logger.warning(
                "[METADATA] lenient parse found a single-key wrapper -> using its content (step=%s wrapper=%r)",
                label, sorted(parsed)[0],
            )
            parsed = inner_d
        logger.warning("[METADATA] rescued by lenient parse (step=%s)", label)
        return parsed, label
    return None, None


def lenient_json_loads(json_text: str, keys: frozenset[str] | set[str] = DEFAULT_KEYS) -> dict | None:
    """METADATA 候補の文字列を dict に読む。素の JSON が通ればそのまま、落ちたら梯子で救う。

    梯子: <think> 除去 → コードフェンス剥がし → 最外の {…} 抽出 → コメント・末尾カンマ除去
    → 単引用符。梯子で拾った dict は既知のキー（keys）を一つも持たなければ棄却し、
    キー一つの包みなら中身を開く。読めなければ None。
    """
    parsed, _label = _loads_with_ladder(json_text, keys)
    return parsed


# ---------------------------------------------------------------------------
# 本文の掃除
# ---------------------------------------------------------------------------

def remove_metadata_blocks(text: str, pattern: "re.Pattern[str] | str") -> str:
    """pattern に当たる METADATA ブロックを本文から取り除く。**ブロックを包んでいるフェンスも一緒に**。

    包みを落とさないと、本文の末尾に開き側のフェンスだけが取り残されて人の目に見える。
    ただし単純に「直前のフェンス行を食う」とすると、**本文自身がコードブロックで終わる
    ターンでその閉じフェンスを食ってしまう**。見分け方は「その行より前にあるフェンス行の数」で、
    偶数なら開き役（＝包み）、奇数なら本文のコードブロックの閉じ役。閉じ側を食うのは
    開き側を食った時だけ＝対称にしか手を出さない。
    """
    if isinstance(pattern, str):
        pattern = re.compile(pattern, re.DOTALL)
    out: list[str] = []
    pos = 0
    for m in pattern.finditer(text):
        head = text[pos:m.start()]
        lead = _LEADING_FENCE_RE.search(head)
        ate_lead = False
        if lead and len(_FENCE_LINE_RE.findall(head[:lead.start(1)])) % 2 == 0:
            head = head[:lead.start(1)]
            ate_lead = True
        out.append(head)
        pos = m.end()
        if ate_lead:
            trailing = _TRAILING_FENCE_RE.match(text, pos)
            if trailing:
                pos = trailing.end()
    out.append(text[pos:])
    return "".join(out)


def strip_orphan_fence(text: str) -> str:
    """対を失ったコードフェンス行が末尾に残っていたら、それだけを落とす。

    「末尾のバッククォートを全部食う」と、本文がコードブロックやインラインコードで終わる
    ターンまで壊れる。フェンスの本数が偶数（対応が取れている）なら手を出さず、奇数の時だけ
    末尾の一本を落とす。3 連未満（インラインコード）は対象外。
    """
    if not text:
        return text
    stripped = text.rstrip()
    tail = re.search(r"(?:\A|\n)[ \t]*`{3,}[ \t]*\Z", stripped)
    if not tail:
        return text
    if len(_FENCE_LINE_RE.findall(stripped)) % 2 == 0:
        return text
    return stripped[:tail.start()]


# ---------------------------------------------------------------------------
# 分ける
# ---------------------------------------------------------------------------

@dataclass
class SplitResult:
    """split の結果。

    body            METADATA を取り除いた本文
    metadata        読めた dict。無ければ None（空 dict は「空と申告した」であって None ではない）
    tier            ブロックが見つかった段。1=印一致 / 2=印の幻覚（別 hex の対）/ 3=終了の印欠落 / None=無し
    matched_marker  実際にブロックに付いていた印（Tier-2/3 では渡した印と違いうる）
    note            何が起きたかの一行（ログ・デバッグ用）
    json_text       ブロックの中身の生の文字列（JSON が読めなかった時の調査用）
    rescue          JSON をどう読んだか。"strict"＝素で通った／それ以外＝梯子の段の名前／None＝読めず
    """

    body: str
    metadata: dict | None
    tier: int | None
    matched_marker: str | None
    note: str
    json_text: str | None = None
    rescue: str | None = None


def split(text: str, marker: str, keys: frozenset[str] | set[str] = DEFAULT_KEYS) -> SplitResult:
    """返事を本文と METADATA に分ける。

    三段のブロック探索:
      Tier-1  開始・終了が共に渡した印と一致
      Tier-2  印が違っても、開始と終了が同じ hex で揃っている（印の幻覚）
      Tier-3  終了の印が欠けている（開始…末尾）。渡した印でも、任意の hex でも試す
    本文の `<<<METADATA>>>` という固定の字面（hex 無し）はどの段にも掛からない。

    本文の掃除は「実際に当たった印」で行い、さらに残った任意 hex のブロックも全部落とす
    （ブロックを二つ書いた・取り損ねた残骸を確実に拾う）。中身は素の json.loads →
    梯子（lenient_json_loads）の順。dict でなければ None。
    """
    if not text:
        return SplitResult("", None, None, None, "empty reply")

    start_re = re.escape(start_marker(marker))
    end_re = re.escape(end_marker(marker))

    json_text: str | None = None
    tier: int | None = None
    matched = marker
    notes: list[str] = []

    full = re.search(rf"{start_re}(.+?){end_re}", text, re.DOTALL)
    if full:
        json_text = full.group(1).strip()
        tier = 1
        notes.append("tier1: marker matched")
    else:
        loose = re.search(
            rf"<<<METADATA:({MARKER_HEX_RE})>>>(.+?)<<<END_METADATA:\1>>>", text, re.DOTALL
        )
        if loose:
            json_text = loose.group(2).strip()
            matched = loose.group(1)
            tier = 2
            notes.append(f"tier2: marker mismatch (expected={marker} actual={matched})")
            logger.warning("[METADATA] block written with a different marker -> rescued (expected=%s actual=%s)",
                           marker, matched)
        else:
            partial = re.search(rf"{start_re}(.+)$", text, re.DOTALL)
            if partial:
                json_text = partial.group(1).strip()
                tier = 3
                notes.append("tier3: end marker missing (start marker matched)")
                logger.warning("[METADATA] end marker missing -> start...EOF (len=%d)", len(json_text))
            else:
                loose_partial = re.search(rf"<<<METADATA:({MARKER_HEX_RE})>>>(.+)$", text, re.DOTALL)
                if loose_partial:
                    json_text = loose_partial.group(2).strip()
                    matched = loose_partial.group(1)
                    tier = 3
                    notes.append(f"tier3: end marker missing and marker mismatch (expected={marker} actual={matched})")
                    logger.warning("[METADATA] end marker missing + marker mismatch -> rescued (expected=%s actual=%s)",
                                   marker, matched)

    if json_text is not None:
        m_start = re.escape(start_marker(matched))
        m_end = re.escape(end_marker(matched))
        cleaned = remove_metadata_blocks(text, re.compile(rf"{m_start}.*?(?:{m_end}|$)", re.DOTALL))
    else:
        cleaned = text
    # 保険: 残った任意 hex のブロックも全部落とす（hex 無しの固定文字列は対象外）。
    cleaned = remove_metadata_blocks(
        cleaned,
        re.compile(rf"<<<METADATA:{MARKER_HEX_RE}>>>.*?(?:<<<END_METADATA:{MARKER_HEX_RE}>>>|$)", re.DOTALL),
    )
    cleaned = strip_orphan_fence(cleaned).strip()

    if json_text is None:
        notes.append("no block")
        return SplitResult(cleaned, None, None, None, "; ".join(notes))

    parsed, label = _loads_with_ladder(json_text, keys)
    if parsed is None:
        notes.append("json unreadable")
        logger.warning("[METADATA] JSON unreadable marker=%s head=%r", matched, json_text[:120])
        return SplitResult(cleaned, None, tier, matched, "; ".join(notes), json_text, None)
    notes.append("json: strict" if label == "strict" else f"json: rescued by {label}")
    return SplitResult(cleaned, parsed, tier, matched, "; ".join(notes), json_text, label)
