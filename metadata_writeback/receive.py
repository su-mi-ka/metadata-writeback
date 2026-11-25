"""receive — 返事を受けて、本文・METADATA・突き返し・書き戻す dict を一度に出す。

出口が text（本文の末尾のブロック）でも tool（構造化出力）でも、下流が受けるのは
dict 一個。`receive` は text の出口の入口で、`receive_dict` は tool の出口から来た dict を
同じ検査に通す。どちらも Received を返し、下流は出口の別を知らない。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .check import check_used_tools, parse_links, parse_tags, unbacked_action_claims
from .marker import DEFAULT_FIELDS, DEFAULT_KEYS, Field, instructions
from .parse import SplitResult, split

__all__ = ["Received", "bounce_text", "build_write", "receive", "receive_dict"]


@dataclass
class Received:
    """受けた結果。

    body       METADATA を取り除いた本文（突き返す時もそのまま使える）
    metadata   読めた dict（無ければ None）
    bounce     突き返す文。None なら受理
    write      書き戻す dict（受理した時だけ）。new_memory が空でも dict は返す——書くかは呼び手が決める
    unbacked   道具を使っていないのに完了形で報告している文（観測のみ・罰しない）
    split      分けた時の詳細（tier・救った段など）。tool の出口から来た時は None
    """

    body: str
    metadata: dict | None
    bounce: str | None
    write: dict | None
    unbacked: list[str] = field(default_factory=list)
    split: SplitResult | None = None

    @property
    def accepted(self) -> bool:
        return self.bounce is None

    @property
    def should_write(self) -> bool:
        """書き戻す記憶の本文があるか（受理していて new_memory が空でない）。"""
        return self.write is not None and bool(self.write.get("new_memory"))


def bounce_text(
    marker: str,
    reason: str,
    fields: tuple[Field, ...] = DEFAULT_FIELDS,
    lang: str = "ja",
    only_prefix: str | None = None,
) -> str:
    """突き返しの文。理由＋「本文はそのままで、最後に決まりどおりの METADATA を付けてもう一度」＋決まりの文。"""
    if lang == "en":
        head = (f"[METADATA bounce / marker={marker}] {reason}\n"
                "Keep the body of your reply as it is. Append the METADATA block in the prescribed form "
                "and send the reply again.\n")
    else:
        head = (f"〔METADATA bounce・marker={marker}〕{reason}\n"
                "本文はそのままで構いません。最後に決まりどおりの METADATA を付けて、もう一度返事をしてください。\n")
    return head + instructions(marker, fields=fields, lang=lang, only_prefix=only_prefix)


def _importance(value: object) -> int:
    """memory_importance を 0〜1000 の整数へ。読めない物は 0。"""
    try:
        n = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(1000, n))


def build_write(metadata: dict) -> dict:
    """受理した METADATA から書き戻す dict を作る。

    new_memory          文字列へ寄せて前後の空白を落とす（null は ""）
    memory_importance   0〜1000 の整数（読めなければ 0）
    memory_type         無ければ "episodic"
    memory_tags         正規化したタグ。`#k/<memory_type>` が無ければ足す（分類の軸を必ず一本持たせる）
    memory_links        正規化したリンク
    """
    memory_type = str(metadata.get("memory_type") or "episodic").strip() or "episodic"
    tags = parse_tags(metadata.get("memory_tags"))
    kind_tag = f"#k/{memory_type}"
    if kind_tag not in tags:
        tags.append(kind_tag)
    new_memory = metadata.get("new_memory")
    return {
        "new_memory": "" if new_memory is None else str(new_memory).strip(),
        "memory_importance": _importance(metadata.get("memory_importance")),
        "memory_type": memory_type,
        "memory_tags": tags,
        "memory_links": parse_links(metadata.get("memory_links")),
    }


def _reasons(lang: str) -> dict[str, str]:
    if lang == "en":
        return {
            "missing": "No METADATA block was attached.",
            "unreadable": "A METADATA block was found but its JSON could not be read.",
            "empty": "The METADATA block is empty.",
            "no_memory": "`new_memory` is empty; this turn requires a memory to be written.",
        }
    return {
        "missing": "METADATA が付いていません。",
        "unreadable": "METADATA のブロックはありましたが、中の JSON が読めませんでした。",
        "empty": "METADATA が空です。",
        "no_memory": "`new_memory` が空です。このターンは記憶を一つ残す必要があります。",
    }


def receive_dict(
    body: str,
    metadata: dict | None,
    marker: str,
    executed_tools: list[str] | None,
    only_prefix: str | None = None,
    require_memory: bool = False,
    require_complete: bool = False,
    fields: tuple[Field, ...] = DEFAULT_FIELDS,
    lang: str = "ja",
    split_result: SplitResult | None = None,
) -> Received:
    """dict になった METADATA を検査する（text の出口も tool の出口もここへ合流する）。"""
    reasons = _reasons(lang)

    def bounce(reason: str) -> Received:
        return Received(body, metadata, bounce_text(marker, reason, fields, lang, only_prefix), None,
                        [], split_result)

    if metadata is None:
        had_block = split_result is not None and split_result.tier is not None
        return bounce(reasons["unreadable"] if had_block else reasons["missing"])
    if not metadata:
        return bounce(reasons["empty"])
    issue = check_used_tools(metadata.get("used_tools"), executed_tools, only_prefix,
                             require_complete=require_complete, lang=lang)
    if issue:
        return bounce(issue)
    write = build_write(metadata)
    if require_memory and not write["new_memory"]:
        return bounce(reasons["no_memory"])
    unbacked = unbacked_action_claims(body, executed_tools)
    return Received(body, metadata, None, write, unbacked, split_result)


def receive(
    reply: str,
    marker: str,
    executed_tools: list[str] | None,
    only_prefix: str | None = None,
    require_memory: bool = False,
    require_complete: bool = False,
    fields: tuple[Field, ...] = DEFAULT_FIELDS,
    keys: frozenset[str] | set[str] | None = None,
    lang: str = "ja",
) -> Received:
    """返事（text の出口）を受ける。分ける → 無い/読めない/空なら突き返す → 道具を突き合わせる → 書く dict。

    reply           LLM の返事の全文
    marker          このターンに配った印（instructions に入れた物）
    executed_tools  このターンに実際に実行した道具の名前。None＝記録を渡せない経路（突き合わせない）
    only_prefix     突き合わせる道具をこの接頭辞に限る（例 "mcp__"）。器に元から付いている道具を外す
    require_memory  True なら new_memory が空の返事も突き返す
    require_complete True なら過少申告（実行したのに申告していない）も突き返す（フィオ本体の現行の形）
    fields / keys   欄の定義と、寛容パースの関所に使う既知のキー（既定は DEFAULT_FIELDS の名前）
    lang            突き返しの文の言語（"ja" / "en"）
    """
    key_set = frozenset(f.name for f in fields) if keys is None else frozenset(keys)
    if key_set == frozenset(f.name for f in DEFAULT_FIELDS):
        key_set = DEFAULT_KEYS
    result = split(reply or "", marker, key_set)
    return receive_dict(result.body, result.metadata, marker, executed_tools, only_prefix,
                        require_memory, require_complete, fields, lang, result)
