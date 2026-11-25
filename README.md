# metadata-writeback

## Summary (English)

- Makes an LLM append a machine-readable **METADATA block** (a JSON object wrapped in turn-specific marker lines) to the end of every reply, then splits the body from the metadata.
- The marker is a fresh 8-digit hex per turn (`<<<METADATA:ab12cd34>>>` ... `<<<END_METADATA:ab12cd34>>>`), so a reply that merely *talks about* `<<<METADATA>>>` is never mistaken for a block.
- Three-tier block rescue: exact marker; a hallucinated-but-consistent marker pair; a missing end marker (start...EOF). The body is cleaned symmetrically, so a body that itself ends in a code block keeps its closing fence.
- A lenient JSON ladder runs **only when strict `json.loads` fails**: strip `<think>`, strip code fences, extract the outermost `{...}`, drop comments and trailing commas (never inside strings, so URLs survive), convert single quotes, unwrap a single-key wrapper. A gate rejects objects with no known key so a JSON example quoted in the body is never written as memory.
- Declared `used_tools` are cross-checked against the real execution log; **only inflation is bounced** (claiming a tool you did not run). Under-reporting is observed, not punished, unless you opt in to `require_complete=True`.
- `executed_tools=None` means "the log is not available on this path" and disables the check: reading unknown as "nothing ran" would turn every honest claim into inflation.
- `only_prefix="mcp__"` restricts the check to tools you added yourself and ignores the host's built-in tools (name drift such as `Bash` vs `Shell` disappears).
- Missing, unreadable or empty metadata (and inflation) produce a **bounce text**: the reason, "keep the body, re-append METADATA", and the full instructions again.
- `receive()` (text exit) and `receive_dict()` (structured/tool exit) converge on one `Received` object; downstream only ever sees one dict to write.
- Standard library only, Python 3.11+, 65 pytest tests. Extracted from the Fio system's `claude_client/metadata.py` and `staff_metadata.py`; design notes and the reasons behind each rule are kept below.

---

## 何か

LLM の返事の**末尾**に、機械が読める METADATA ブロック（ターン固有の印で挟んだ JSON）を書かせ、

1. 本文と METADATA を分け（`split`）、
2. 壊れた JSON を寛容に読み（`lenient_json_loads`）、
3. 申告した道具（`used_tools`）を実行の記録と突き合わせ（`check_used_tools`）、
4. 無い・読めない・空・盛りなら「突き返しの文」を作り（`receive` → `Received.bounce`）、
5. 受理したら書き戻す dict を一個返す（`Received.write`）

ところまでを、標準ライブラリだけでまとめた小さなパッケージ。LLM の呼び出しそのものは含まない。
どの器（API・ローカルモデル）にも挟める。

```
<<<METADATA:ab12cd34>>>
{"thinking": "...", "used_tools": [], "new_memory": "...", "memory_importance": 300,
 "memory_type": "episodic", "memory_tags": ["#ctx/..."], "memory_links": []}
<<<END_METADATA:ab12cd34>>>
```

## なぜ注目に値するか

**書き戻しは規律ではなく存在の配線**——出所のフィオシステムの設計文書にそう書かれている。
記憶を外に持つエージェントでは、ターンの終わりに「何を憶えるか」を自分で書き戻す経路が、
人格の連続性そのものになる。書き戻しが一度欠ければ、次のターンの自分は今のターンを覚えていない。

その経路を**本文と同じ一回の出力**に載せる（出口を text にする）のは手軽だが、構造的な強制はゼロで、
モデルは書き忘れ・JSON の破損・印の幻覚を日常的にやる。このパッケージは、その現実に対して
出所で実際に起きた壊れ方を一つずつ拾って作られた救済と、それでも拾えない日の突き返しを持つ。
救済は防止ではない、という線を引いたまま、である。

## どう動くか

### 名前の付いた考え方

| 考え方 | 中身 |
|---|---|
| **ターン固有の印** | 印は毎ターン `new_marker()` で作る 8 桁 hex。本文の中で LLM が METADATA の仕組みを説明すると `<<<METADATA>>>` という字面が本文に現れる。印が固定ならそれをブロックと取り違えて本文を削るが、hex を要求すれば本文の言及（hex 無し）はどの段にも掛からない。 |
| **三段の救済（ブロックの形）** | Tier-1: 開始・終了が共に印と一致。Tier-2: 印が違っても、開始と終了が**同じ hex で揃っている**（印の幻覚）。Tier-3: 終了の印が欠けている（開始…末尾）。無ければ `(本文, None)`。 |
| **対称なフェンスの掃除** | ブロックを包んだ ```` ```json ```` も一緒に落とす。ただし「直前のフェンス行を食う」と、本文自身がコードブロックで終わるターンの閉じフェンスを食う。その行より前のフェンス行の数が**偶数なら包み・奇数なら本文の閉じ**。閉じ側を食うのは開き側を食った時だけ——対称にしか手を出さない。 |
| **梯子（中身の書き癖）** | 素の `json.loads` が落ちた時だけ、壊れ方の軽い順に試す: `<think>` 除去 → フェンス剥がし → 最外の `{…}` 抽出 → コメント・末尾カンマ除去（文字列の中は触らない。URL の `//` を壊さない）→ 単引用符（二重引用符が無く単引用符が偶数の時だけ）。通った段で止め、`SplitResult.rescue` に段の名前を残す。 |
| **関所（偽の記憶を焼かない）** | 梯子で拾った dict が既知のキーを一つも持たなければ「本文に書かれた例」とみなして棄却する。キー一つの包み `{"metadata": {...}}` なら中身を開く。素で読めた `{}` はそのまま「空と申告した」として返す（None ではない）。 |
| **救済は防止ではない** | 三段と梯子で救えなかった日は `bounce` が立つ。救済が常態化しているなら、それはパーサで隠す物ではなく指示文かモデルの側を直す物——だから救った段を必ず記録に残す。 |
| **正直さを罰しない** | 弾くのは**盛り**（実行していない道具の申告）だけ。過少申告は観測のみ。記録を渡せない経路（`executed_tools=None`）では突き合わせない——未知を「一つも使っていない」と読むと、正直な申告が丸ごと盛りになる。改名の巻き添えを避ける `canonical` 関数も渡せる。 |
| **本文の実行主張の観測** | 道具を一つも実行していないターンで、本文に「〜しました」「I have read…」の文が在れば列挙する（`unbacked`）。否定・失敗・未来・意図・過去ターン参照は除く。**罰しない**——意味内容の機械判定には誤検知が必ず混ざる。 |
| **出口が違っても下流は dict 一個** | text の出口（返事の末尾）は `receive`、tool／構造化出力の出口は `receive_dict`。どちらも同じ `Received` に合流し、下流は出口の別を知らない。 |

### 流れ

```
instructions(marker) をプロンプトの末尾に足す
        ↓ LLM の返事
split(reply, marker)          → SplitResult(body, metadata, tier, matched_marker, note, json_text, rescue)
        ↓
receive_dict(...)             → 無い / 読めない / 空 → bounce
                              → check_used_tools(盛り) → bounce
                              → build_write(metadata)  → write dict（#k/<memory_type> のタグを必ず一本持たせる）
                              → unbacked_action_claims（観測のみ）
        ↓
Received(body, metadata, bounce, write, unbacked, split)
```

## 使い方

```python
from metadata_writeback import new_marker, instructions, receive

marker = new_marker()
prompt = SYSTEM_PROMPT + "\n\n" + instructions(marker, only_prefix="mcp__")   # lang="en" もある

reply = call_llm(prompt, user_message)                     # 任意の LLM 呼び出し
r = receive(reply, marker, executed_tools=tools_run_this_turn, only_prefix="mcp__")

if r.bounce:                                               # 無い・読めない・空・盛り
    reply = call_llm(prompt, user_message, followup=r.bounce)   # 本文はそのまま、METADATA だけ付け直させる
    r = receive(reply, marker, executed_tools=tools_run_this_turn, only_prefix="mcp__")

show(r.body)                                               # 本文だけを人へ
if r.should_write:                                         # new_memory が空でない
    memory.write(**r.write)   # new_memory / memory_importance / memory_type / memory_tags / memory_links
if r.unbacked:
    log.info("道具を使っていないのに完了形: %s", r.unbacked)
```

- 構造化出力（tool の出口）から dict が直に来るなら `receive_dict(body, metadata, marker, executed_tools, ...)`。
- 実行の記録が取れない経路では `executed_tools=None` を渡す（突き合わせを止める）。
- フィオ本体と同じ「過少申告も突き返す」形にしたいなら `require_complete=True`。
- 毎ターン必ず記憶を一つ残させたいなら `require_memory=True`。
- 欄を替えたいなら `Field(...)` の tuple を `fields=` に渡す（`instructions` と関所の既知キーが揃って変わる）。

動く例: `python examples/demo.py`（正常・```` ```json ````包み・印の幻覚・終了印欠落・METADATA 無し・空 `{}`・盛り・本文がコードブロックで終わる、の 8 例を通して tier と判定を出す）。

## 出所

フィオシステム本体の次の箇所を読み、単体で動く形に書き直した（`fio` は import しない）。

| このパッケージ | 本体の出所 |
|---|---|
| `marker.new_marker` / 印の形 | `fio/core/staff_metadata.py:35-38`（`印()`）、`fio/core/claude_client/__init__.py` の `uuid.uuid4().hex[:8]` |
| `marker.instructions` | `fio/core/staff_metadata.py:40-55`（`書き方`）、欄の説明は `fio/core/prompt.py:913-1020`（`_METADATA_OUTPUT_FORMAT`）を要約 |
| `parse.strip_code_fence` | `fio/core/claude_client/metadata.py:20-41` |
| `parse.remove_metadata_blocks`（対称なフェンス） | `fio/core/claude_client/metadata.py:43-74` |
| `parse.strip_orphan_fence` | `fio/core/claude_client/metadata.py:76-97` |
| `parse.extract_outermost_object` | `fio/core/claude_client/metadata.py:98-130` |
| `parse.strip_json_noise` | `fio/core/claude_client/metadata.py:131-178` |
| `parse.single_to_double_quotes` | `fio/core/claude_client/metadata.py:179-194` |
| `parse.looks_like_metadata` / `DEFAULT_KEYS` | `fio/core/claude_client/metadata.py:195-220` |
| `parse.strip_thinking` | `fio/core/claude_client/metadata.py:221-246` |
| `parse.unwrap_single_key` | `fio/core/claude_client/metadata.py:247-262` |
| `parse.lenient_json_loads`（梯子） | `fio/core/claude_client/metadata.py:263-320` |
| `parse.split`（三段） | `fio/core/claude_client/metadata.py:345-466`（`_split_metadata`） |
| `check.parse_used_tools` | `fio/core/claude_client/metadata.py:467-484` |
| `check.parse_tags` / `parse_links` | `fio/core/claude_client/metadata.py:485-525` |
| `check.check_used_tools` | `fio/core/claude_client/metadata.py:526-600`（`_check_used_tools`） |
| `check.unbacked_action_claims` | `fio/core/claude_client/metadata.py:674-706`（`_scan_unbacked_action_claims`） |
| `receive.receive` / 突き返しの文 / write dict | `fio/core/staff_metadata.py:57-109`（`_突き返しの文`・`受ける`・`書き戻す`） |
| text / tool の二つの出口が dict 一個に合流する考え方 | `fio/core/metadata_mode.py:1-30`、`fio/core/claude_client/metadata.py:1-12, 321-343` |

「書き戻しは規律ではなく、存在の配線そのもの」は本体の設計文書（システム全体アーキテクチャ・2026-09-16 版）の逐語。

## フィオ本体との違い

- **欄を 13 → 7 に絞った。** 本体の `used_memory_ids`・`consolidated_diff`・`pruning_candidates`・`action_plan`・`perception_gap`・`nerve_feedback`・`memory_attachments` は本体の記憶層・神経関数に結合しているので落とした。`Field` の tuple を差し替えれば増やせる。
- **既定を「盛りだけ弾く」にした。** 本体は 2026-06 に、モデルが「空にしておけば突合に引っかからない」を戦略として学習したため、過少申告も突き返す対称な形へ戻している。ここでは `require_complete=True` でその形を選べるようにし、既定は非対称（正直さを罰しない側）に置いた。
- **接頭辞の外した結果が空でも、記録は記録として扱う。** 本体の `staff_metadata.受ける` は、実行の記録に `mcp__` の名前が一つも無い時に「記録を渡せない経路」（None）へ倒す（実行環境が MCP の道具を表示名でしか記録しない実測への対処）。ここでは「記録を信じられるか」は呼び手の判断に戻した——信じられない経路では `executed_tools=None` を渡す。
- **道具の現行名への正規化は関数で渡す。** 本体は道具のレジストリ（`registry.canonical_name`）を直接引く。ここでは `canonical=` に任意の関数を渡す。本体の式神（道具を広げる扉）の除外も落とした。
- **素で読めた「キー一つの包み」も開く。** 本体は梯子で拾った時だけ包みを開く。ここでは素の `json.loads` が通った dict でも、既知のキーを一つも持たないキー一つの包みなら中身を採る（`rescue="unwrapped"`）。
- **突き返しの理由を三つに分けた。** 本体は「無い」と「空」の二つ。ここでは「ブロックは在ったが JSON が読めなかった」を分けた（`SplitResult.tier` が立っていて `metadata` が None）。
- **タグの正規化をここで済ませる。** 本体は adapter 側で `#` を補い slug 化する。ここでは `parse_tags` が `#` を一つ頭に揃え、空白を `_` に畳み、`build_write` が `#k/<memory_type>` を必ず一本足す。小文字化はしない。
- **英語の出力。** `instructions` と突き返しの文に `lang="en"`、実行主張の正規表現に英語の完了形を足した。
- **ログ。** 救済の WARNING は `logging.getLogger("metadata_writeback.parse")` に出る。本体のログの文面は写していない。
- **本体で見つけた物（報告のみ・本体は触っていない）。** 本体の `metadata.py:44` の `_TRAILING_FENCE_RE` は `\A` で始まり、`:69` で `.match(text, pos)` と途中から当てている。`\A` は文字列の本当の先頭にしか一致しないので、`pos>0` では決して当たらない（Python 3.13 で実測: `re.compile(r"\A\r?\n?[ \t]*`{3,}…").match("X>>>\n```", 4)` → `None`）。本体では後段の `_strip_orphan_fence` が奇数の末尾フェンスを落とすため症状が隠れている。ここでは `\A` を外した（`parse.py` の `_TRAILING_FENCE_RE`）。

## 柵

`tests/` に 65 本。

```
cd <このフォルダ>
python -m pytest tests -q -p no:cacheprovider
```

結果（2026-11-19・Python 3.13）:

```
65 passed in 0.10s
```

- `test_marker.py`（6）: 印の形・決まりの文に印が開始と終了で二度入る・欄の名前が揃う・`only_prefix` の一文
- `test_parse.py`（31）: 三段の救済・本文の `<<<METADATA>>>` の言及に反応しない・空 `{}` は None ではない・本文がコードブロックで終わる・二つのブロック・梯子の各段（単引用符・末尾カンマとコメントで URL が無事・`<think>`・前後の散文・包み）・Tier-3 が本文の JSON 例を採らない関所・フェンス掃除の対称性
- `test_check.py`（13）: 盛りだけ弾く・過少申告は既定で通す／`require_complete` で弾く・`executed=None` は突き合わせない・`only_prefix="mcp__"` で Bash/Read を外す・`canonical` で改名を罰しない・タグとリンクの正規化・実行主張の観測（「ましょう」を拾わない・否定と未来を除く・上限 5）
- `test_receive.py`（15）: 8 例の判定・突き返しの文の形（印が三度・決まりの文で終わる）・読めない JSON の理由・`require_memory`・`build_write` の既定と丸め・英語・`receive_dict`（tool の出口）が同じ契約

## 未了

- 実際の LLM を相手にした突き返しの往復（再送の回数の上限・上限到達後の fail-closed）は呼び手の側に置いたままで、このパッケージには含めていない。本体には上限がある。
- 本体の 13 欄のうち落とした 6 欄（`used_memory_ids`・`consolidated_diff` ほか）の検証は書いていない。
- `unbacked_action_claims` の英語の正規表現は少数の例しか当てていない（観測のみなので誤検知は記録に留まる）。
- 本体で見つけた `\A` の件は本体側に未反映（このフォルダの仕事は本体を読むだけ）。

ライセンス: [MIT](LICENSE)
