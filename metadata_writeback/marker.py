"""marker — ターン固有の印と、返事の最後に METADATA を付けさせる「決まりの文」。

印（marker）はターンごとに新しく作る 8 桁の hex。開始と終了の二本の行で JSON を挟む::

    <<<METADATA:ab12cd34>>>
    { ... }
    <<<END_METADATA:ab12cd34>>>

なぜ固定の文字列ではなくターン固有の印か:
  本文の中で LLM が「METADATA の仕組み」そのものを説明すると、`<<<METADATA>>>` という
  字面が本文に現れる。印が固定なら、その言及をブロックと取り違えて本文を削る。
  ターン固有の hex を要求すれば、本文の言及（hex 無し）はどの段にも掛からない。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

__all__ = [
    "MARKER_HEX_RE",
    "Field",
    "DEFAULT_FIELDS",
    "DEFAULT_KEYS",
    "new_marker",
    "start_marker",
    "end_marker",
    "instructions",
]

#: 印として受け付ける hex の形（8〜64 桁）。Tier-2/3 の救済はこの形で「何らかの印」を探す。
MARKER_HEX_RE = r"[0-9a-fA-F]{8,64}"


def new_marker() -> str:
    """ターン固有の印。8 桁の英小文字と数字（uuid4 の先頭 8 桁）。"""
    return uuid.uuid4().hex[:8]


def start_marker(marker: str) -> str:
    """開始の印の行。"""
    return f"<<<METADATA:{marker}>>>"


def end_marker(marker: str) -> str:
    """終了の印の行。"""
    return f"<<<END_METADATA:{marker}>>>"


@dataclass(frozen=True)
class Field:
    """METADATA の欄一つ分。名前（JSON のキー）と、言語別の説明・例。"""

    name: str
    description_ja: str
    description_en: str
    example_ja: object
    example_en: object

    def description(self, lang: str = "ja") -> str:
        return self.description_en if lang == "en" else self.description_ja

    def example(self, lang: str = "ja") -> object:
        return self.example_en if lang == "en" else self.example_ja


#: 既定の欄。フィオ本体は 13 欄だが、ここでは「記憶の書き戻し」に要る最小の 7 欄にした。
DEFAULT_FIELDS: tuple[Field, ...] = (
    Field(
        "thinking",
        "このターンの主な判断を一文で。",
        "The main judgement of this turn, in one sentence.",
        "このターンで考えたことの要約（一文）",
        "A one-sentence summary of what you decided this turn",
    ),
    Field(
        "used_tools",
        "このターンで実際に実行した道具の名前の配列。実行の記録と機械で突き合わせます。"
        "実行していない道具を書くと突き返されます。使っていなければ空配列 []。",
        "Names of the tools you actually executed this turn. Checked mechanically against the "
        "execution log; naming a tool you did not run gets the reply bounced. Use [] if none.",
        ["このターンで実際に使った道具の名前（使っていなければ []）"],
        ["tool names you actually ran this turn ([] if none)"],
    ),
    Field(
        "new_memory",
        "次のターンの自分に残す記憶の本文。無ければ null。",
        "The memory to hand to your next turn. null if nothing is worth keeping.",
        "次のターンの自分に残す記憶の本文（無ければ null）",
        "What your next turn should remember (null if nothing)",
    ),
    Field(
        "memory_importance",
        "0〜1000 の整数。大きいほど長く残る。",
        "Integer 0-1000. Higher values are kept longer.",
        0,
        0,
    ),
    Field(
        "memory_type",
        '"episodic"（出来事）/ "semantic"（知識・好み）/ "procedural"（手順）。',
        '"episodic" (events) / "semantic" (knowledge, preferences) / "procedural" (how-to).',
        "episodic",
        "episodic",
    ),
    Field(
        "memory_tags",
        "この記憶を整理するタグの配列（`#ctx/話題` `#mode/状態` など）。思い浮かばなければ []。",
        "Tags to file this memory under (e.g. `#ctx/topic`, `#mode/state`). [] if none.",
        ["#ctx/話題"],
        ["#ctx/topic"],
    ),
    Field(
        "memory_links",
        "結びつけたい過去の記憶の要旨や slug の配列。無ければ []（解決しないリンクは無視され無害）。",
        "Short gists or slugs of past memories to link to. [] if none (unresolved links are harmless).",
        ["繋ぐ過去の記憶の要旨や slug"],
        ["gist or slug of a past memory to link"],
    ),
)

#: 「この dict は METADATA か」を見る関所が使う既知のキー。既定の欄の名前。
DEFAULT_KEYS: frozenset[str] = frozenset(f.name for f in DEFAULT_FIELDS)


_RULES_JA = (
    "書き方: コードフェンス（```json）で囲まず、印の行を生で書く。JSON は二重引用符・末尾カンマ無し・コメント無し。",
    "何も記憶しないターンも、ブロック自体は必ず一つ書く（new_memory は null、memory_importance は 0）。",
    "本文が先、METADATA が最後。本文の途中に挟まない。",
)
_RULES_EN = (
    "Rules: do not wrap the block in a code fence (```json); write the marker lines raw. "
    "JSON uses double quotes, no trailing commas, no comments.",
    "Even on a turn with nothing to remember, write the block once (new_memory null, memory_importance 0).",
    "Body first, METADATA last. Never place it in the middle of the body.",
)


def instructions(
    marker: str,
    fields: tuple[Field, ...] = DEFAULT_FIELDS,
    lang: str = "ja",
    only_prefix: str | None = None,
) -> str:
    """返事の最後に付けさせる決まりの文。プロンプトの末尾（動的な部分）に足して渡す。

    印は開始と終了の二度、そのまま現れる。「印の行は一字も変えない」と明示するのは、
    モデルが HEX の部分を自分の思いついた値に置き換える癖（印の幻覚）があるため。

    only_prefix を渡すと「突き合わせるのはこの接頭辞の道具だけ」の一文が付く
    （例: 器に元から付いている道具は外し、外から足した `mcp__` の道具だけを見る）。
    """
    example = {f.name: f.example(lang) for f in fields}
    body = json.dumps(example, ensure_ascii=False, indent=2)
    if lang == "en":
        lines = [
            "---- METADATA to append at the very end of your reply (replies without it are bounced) ----",
            "After the body of your reply, append exactly one JSON object wrapped in the marker lines below. "
            "Copy the marker lines character for character; do not alter them.",
            start_marker(marker),
            body,
            end_marker(marker),
            "Fields:",
            *[f"- {f.name}: {f.description('en')}" for f in fields],
        ]
        if only_prefix:
            lines.append(
                f"Only tools whose names start with `{only_prefix}` are checked against the execution log; "
                "other tools may be listed or omitted freely."
            )
        lines.extend(_RULES_EN)
        lines.append("---- end of METADATA rules ----")
    else:
        lines = [
            "―――― 返事の最後に付ける METADATA（付けないと突き返されます）――――",
            "返事の本文のあとに、次の印で挟んだ JSON を一つ付けてください。印の行は一字も変えないでください。",
            start_marker(marker),
            body,
            end_marker(marker),
            "欄の意味:",
            *[f"- {f.name}: {f.description('ja')}" for f in fields],
        ]
        if only_prefix:
            lines.append(
                f"used_tools は、名前が `{only_prefix}` で始まる道具だけを実行の記録と突き合わせます。"
                "それ以外の道具は書いても書かなくても構いません。"
            )
        lines.extend(_RULES_JA)
        lines.append("―――― METADATA の決まりここまで ――――")
    return "\n".join(lines)
