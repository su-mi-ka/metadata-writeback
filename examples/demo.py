"""demo — 返事の形が違う 8 例を receive に通し、どの段で拾い、どう判定したかを出す。

走らせ方（このフォルダで）: python examples/demo.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Windows のコンソール（cp932）でも記号が落ちないように。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.CRITICAL)  # 救済の WARNING は本番ではログへ残す。ここでは出力を読みやすく

from metadata_writeback import end_marker, instructions, new_marker, receive, start_marker  # noqa: E402

MARKER = new_marker()
S, E = start_marker(MARKER), end_marker(MARKER)

JSON_OK = (
    '{"thinking": "挨拶に答えた", "used_tools": [], "new_memory": "所有者は朝に挨拶する",'
    ' "memory_importance": 300, "memory_type": "episodic", "memory_tags": ["ctx/greeting"], "memory_links": []}'
)

CASES: list[tuple[str, str, list[str] | None]] = [
    # (見出し, 返事, 実行した道具の記録)
    ("1. 正常",
     f"おはようございます。\n{S}\n{JSON_OK}\n{E}", []),
    ("2. ブロックが ```json で包まれている",
     f"おはようございます。\n```json\n{S}\n{JSON_OK}\n{E}\n```", []),
    ("3. 印の幻覚（違う hex で揃った対）",
     f"おはようございます。\n<<<METADATA:deadbeef>>>\n{JSON_OK}\n<<<END_METADATA:deadbeef>>>", []),
    ("4. 終了の印が欠けている",
     f"おはようございます。\n{S}\n{JSON_OK}", []),
    ("5. METADATA が無い（本文で <<<METADATA>>> の仕組みを説明しているだけ）",
     "METADATA は本文の末尾に <<<METADATA>>> の印で挟んで書きます。", []),
    ("6. 空の {}",
     f"おはようございます。\n{S}\n{{}}\n{E}", []),
    ("7. 盛り（実行していない mcp__ の道具を申告）",
     f"天気を取得しました。\n{S}\n"
     '{"used_tools": ["mcp__weather__today", "Bash"], "new_memory": "今日は晴れ", "memory_importance": 100}'
     f"\n{E}", ["Bash"]),
    ("8. 本文自身がコードブロックで終わる",
     f"例です。\n```python\nprint(1)\n```\n{S}\n{JSON_OK}\n{E}", []),
]


def main() -> None:
    print("marker =", MARKER)
    print("--- instructions (what you append to the prompt) ---")
    print(instructions(MARKER, only_prefix="mcp__"))
    print()
    for title, reply, executed in CASES:
        r = receive(reply, MARKER, executed_tools=executed, only_prefix="mcp__")
        print("=" * 72)
        print(title)
        print(f"  tier={r.split.tier} matched_marker={r.split.matched_marker} rescue={r.split.rescue}")
        print(f"  note : {r.split.note}")
        print(f"  body : {r.body!r}")
        if r.accepted:
            print(f"  write: {r.write}")
            if r.unbacked:
                print(f"  unbacked claims (observed only): {r.unbacked}")
        else:
            print("  BOUNCE:", r.bounce.splitlines()[0])
    print("=" * 72)


if __name__ == "__main__":
    main()
