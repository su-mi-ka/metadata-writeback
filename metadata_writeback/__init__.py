"""metadata_writeback — LLM の返事の末尾に機械可読の METADATA を書かせ、分けて、確かめて、書き戻す。

    marker.py   ターン固有の印と、返事の最後に付けさせる決まりの文（instructions）
    parse.py    本文と METADATA を分ける（三段の救済）・壊れた JSON を寛容に読む（梯子）
    check.py    申告した道具を実行の記録と突き合わせる（盛りだけ弾く）・タグとリンクの正規化
    receive.py  受ける: 無い/空なら突き返す → 道具の突き合わせ → 書き戻す dict

書き戻しは規律ではなく存在の配線——一度欠ければ、次のターンの自分は今を覚えていない。
"""
from .check import (
    DEFAULT_CLAIM_RE,
    DEFAULT_EXCLUDE_RE,
    check_used_tools,
    compare_used_tools,
    parse_links,
    parse_tags,
    parse_used_tools,
    unbacked_action_claims,
)
from .marker import (
    DEFAULT_FIELDS,
    DEFAULT_KEYS,
    MARKER_HEX_RE,
    Field,
    end_marker,
    instructions,
    new_marker,
    start_marker,
)
from .parse import (
    SplitResult,
    extract_outermost_object,
    lenient_json_loads,
    looks_like_metadata,
    remove_metadata_blocks,
    single_to_double_quotes,
    split,
    strip_code_fence,
    strip_json_noise,
    strip_orphan_fence,
    strip_thinking,
    unwrap_single_key,
)
from .receive import Received, bounce_text, build_write, receive, receive_dict

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # marker
    "MARKER_HEX_RE", "Field", "DEFAULT_FIELDS", "DEFAULT_KEYS",
    "new_marker", "start_marker", "end_marker", "instructions",
    # parse
    "SplitResult", "split", "lenient_json_loads", "looks_like_metadata", "unwrap_single_key",
    "strip_code_fence", "strip_thinking", "extract_outermost_object", "strip_json_noise",
    "single_to_double_quotes", "remove_metadata_blocks", "strip_orphan_fence",
    # check
    "parse_used_tools", "parse_tags", "parse_links", "compare_used_tools", "check_used_tools",
    "DEFAULT_CLAIM_RE", "DEFAULT_EXCLUDE_RE", "unbacked_action_claims",
    # receive
    "Received", "bounce_text", "build_write", "receive", "receive_dict",
]
