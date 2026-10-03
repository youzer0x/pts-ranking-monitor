# RUNTIME CONTRACT — PTS 日次ルーチンの実行契約

日次の無人実行が**日次セッションで読む唯一の手順書**。方法論の正本は `AGENTS.md` にあるが、
**日次では再読しない**（トークンを二重に払わないため）。本書と矛盾を見つけたら停止して報告する。

対話・開発作業ではこの例外を使わず `AGENTS.md` を読む。

## 0. 前提と停止条件

- `<SESSION>` は §1 が出力するセッション日。`<R>` は `.work/<SESSION>/research` を指す。
- 次のいずれかに当たったら**先へ進まず停止して報告する**：
  SKIP／`build_ranking.py` の異常終了／`build_research_plan.py` が exit 2（初期 pending 超過）／
  `reserve_dispatch.py` が exit 0 以外／`compile_research_results.py` の MISSING が解消しない／
  `merge_factors.py` の MISSING・REJECTED が残る／factor が空の row が残る／
  `validate_ranking_quality.py` の指摘が残る／push・Pages 反映・Gmail の失敗。
- 長文の方法論・runbook をタスクプロンプトへ複製しない。

## 1. 営業日ゲート

```bash
python scripts/check_gate.py
```

`SKIP` なら Pages もメールも更新せず即終了する。`SESSION=YYYY-MM-DD` ならその日付を `<SESSION>` として続行。

## 2. 素データ生成

```bash
python scripts/build_ranking.py --date <SESSION> --out docs/tmp/ranking.json
```

抽出条件（スクリプトが適用済み）：東証個別株のみ・上昇率≥+3% かつ 売買代金≥¥10,000,000・
時価総額≥100億円・**掲載は上昇率上位20銘柄**。各 row には TDnet 開示（15:30以降）と
株探ニュース見出し（`kabutan_news`）が事前充填される。

時価総額は J-Quants valuation の MktCap（東証終値×自己株式控除後株式数）。欠損銘柄だけYahoo補完し
`mcap_source` を記録する。新規データに†照合は行わない。表示は1兆円未満が億円、以上が兆円の小数1桁。

`ranking.json` は**手編集しない**。

## 3. 変動要因の裏取り（Stage2）

### 3.1 調査計画の生成

```bash
python scripts/build_research_plan.py --ranking docs/tmp/ranking.json --research-dir .work/<SESSION>/research
```

exit 2 なら停止して報告する。生成物：`<R>/manifest.json`・`<R>/batches/`・`<R>/inline.json`。

### 3.2 インライン分（委譲しない）

`<R>/inline.json` を読む。**`ranking.json` 全体を読み直さない。** ここに載る行は開示タイトルだけで
上昇が説明できる行なので、親が `factor`（具体的に・である調）/`factor_kind="開示"` を起こし、
`docs/tmp/inline_factors.json` に `[{"code","factor","factor_kind","sources"}]` の配列で保存する。

### 3.3 バッチ委譲

`<R>/manifest.json` の `batches[]` のうち `status=="pending"` のものだけを対象にする。
**各バッチの委譲直前に必ず実行する**：

```bash
python scripts/reserve_dispatch.py --research-dir .work/<SESSION>/research --batch <batch_id>
```

exit 0 以外なら**そのバッチを委譲せず停止して報告する**（3=予算枯渇／4=誤用／1=IOエラー）。

予約できたバッチを `pts-factor-batch-researcher` へ並列委譲する。
**1タスクには `batch_id` と `batch_path`（`<R>/batches/<batch_id>.json`）だけを渡し、
ranking row・plan・本書・長文仕様を貼り付けない。** 返却 JSON をそのまま
`<R>/results/<batch_id>.json` に保存する（加工しない）。

### 3.4 集約とマージ

```bash
python scripts/compile_research_results.py --research-dir .work/<SESSION>/research \
    --out docs/tmp/factors.json --inline docs/tmp/inline_factors.json
python scripts/merge_factors.py --ranking docs/tmp/ranking.json --factors docs/tmp/factors.json
```

`compile_research_results.py` が exit 3（MISSING）なら、**該当バッチだけ** 3.3 からやり直す
（予約は毎回必要。`per_batch_limit=3` を超えると予約できず停止）。
`UNRESOLVED` は材料未確認として許容する（`factor` は埋まっている）。
`merge_factors.py` の `MERGED n/total` を確認し、`MISSING`／`REJECTED` が残る場合は
該当行を親が調査して `docs/tmp/inline_factors.json` を更新し、3.4 を再実行する。

**factor が空の row を残さない。** 材料が確認できなければ「当日固有の材料は確認できず」と正直に記す。
検索結果の要約をそのまま出典にしない・個人発信は引用も参照もしない・数値は実測のみ・
創作禁止・投資助言をしない・「開示なし」等の定型注記は書かない（親にもサブエージェントにも適用）。

### 3.5 表示品質検査

factor は**表示250字以内**（Markdownリンクはラベルのみ。自動の[開示PDF]は除外）。自社名からの
書き出し、内部フィールド名・業種コード、「材料窓」「窓内」「窓外」、自明な休場日等の背景を省く。
必要な事実と出典を残して凝縮する。材料未確認の例外は `テーマ` の冒頭に所定の一文を記す場合のみ
（背景は句点で区切る）。根拠のない推定や機械的な切り詰めは行わない。
海外企業名は日経等の定着表記で書く（例：米マイクロン、SKハイニックス）。英語の資料だけを読んでも
社名を自前で音訳せず、定着表記が不明なら英語の正式名のまま書く（`RANK_FACTOR_NOTATION` で検出）。

```bash
python scripts/validate_ranking_quality.py docs/tmp/ranking.json
```

exit 1 なら指摘された銘柄だけを `inline_factors.json` で修正し、3.4のcompile・mergeと本検査を再実行する。
**exit 0 になるまで公開しない。** `publish.py` も保存前に同じ検査を実行する。

## 4. 公開ファイルの生成（メールはまだ送らない）

```bash
python scripts/publish.py docs/tmp/ranking.json --no-email
```

## 5. commit & push（必ず main へ）

```bash
git add docs/index.html docs/data && git commit -m "Update PTS gainers <SESSION>" && git push origin HEAD:main
```

GitHub Pages は main/docs を配信するため `claude/` ブランチに push しても反映されない。
クラウドセッションが `claude/` ブランチ上にいても main へ直接 push する（PR は作らない）。
`docs/tmp/` と `.work/` はコミットしない。

## 6. メール通知（Pages 反映を待ってから）

```bash
python scripts/publish.py docs/tmp/ranking.json --notify
```

`data/manifest.json` の最新日付が `<SESSION>` になるまで最大5分ポーリングしてから Gmail を送る。
**必ず §5 の push の後に実行する**（push 前に送るとリンク先が前営業日のままになる）。

## 7. 報告形式

最後に1段落で簡潔に報告する：`<SESSION>`／該当社数／主要な変動要因の要約／
`batches` 数と `total_reserved`／`UNRESOLVED` があればその銘柄。エラー時は原因と対処を報告する。
