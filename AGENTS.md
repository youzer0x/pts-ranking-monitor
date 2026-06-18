# AGENTS.md — PTS ナイト 値上がりランキング 日次自動生成（Claude クラウドルーチン）

このリポジトリは、**日本株の PTS ナイトタイムセッション（前営業日17:00→当日06:00）の株価上昇率
ランキング（値上がり専用）**を、**東証の営業日ベースで日次・無人**に生成し、**GitHub Pages（Web）
＋ Gmail 通知**で配信する。Claude がこのファイルの手順に厳密に従って実行する。

> 方法論の単一の真実源は本 `AGENTS.md`。対話版スキル
> `news-financial-market/skills/pts-ranking-digest/SKILL.md` と同一の抽出条件・品質ゲートを用いる。

---

## 0. 実行サマリ（毎回この順）

```
1. 営業日ゲート     python scripts/check_gate.py        → SKIP なら何もせず終了
2. 素データ生成      python scripts/build_ranking.py --date <SESSION> --out docs/tmp/ranking.json
3. 変動要因の裏取り   各 row の factor / factor_kind を埋める（★Claude の中核作業・後述 §3）
4. 公開＋通知        python scripts/publish.py docs/tmp/ranking.json
5. commit & push    docs/ を main にコミットし git push origin HEAD:main（claude/ ブランチ不可）
```

`TZ=Asia/Tokyo` 前提。`JQUANTS_API_KEY`・`GMAIL_CLIENT_ID`・`GMAIL_CLIENT_SECRET`・
`GMAIL_REFRESH_TOKEN`・`GMAIL_ADDRESS`・`NOTIFY_TO` はカスタム環境の環境変数から供給される
（メール送信は Gmail API＝HTTPS。クラウドは SMTP 不可）。

---

## 1. 営業日ゲート

```bash
python scripts/check_gate.py
```
- 出力が `SKIP` のとき（＝前日が休場で新規ナイトセッション無し）は**生成せず終了**する（Pages もメールも更新しない）。
- 出力が `SESSION=YYYY-MM-DD` のとき、その日付を **SESSION（セッション日）**として以降に用いる。

## 2. 素データ生成（決定的パイプライン）

```bash
python scripts/build_ranking.py --date <SESSION> --out docs/tmp/ranking.json
```
- 株探 PTS ナイト値上がり＋J-Quants 時価総額＋TDnet 開示突合を結合し、抽出条件を満たす銘柄を JSON 化する。
- 抽出条件（確定）：**東証個別株のみ**（J-Quants `ProdCat=011`＋`Mkt∈{0111,0112,0113}`／ETF・REIT・地方単独上場は除外）、**PTS上昇率≥+3% かつ 売買代金(=PTS気配×夜間出来高)≥¥5,000,000**、**時価総額≥100億円**。
- 時価総額＝**J-Quants 当日終値×発行済株式数×分割/併合補正**（億円・四捨五入。1兆円以上も億円表示）。増資/自己株で株探最新株数と>1%乖離する銘柄は `mcap_flag="†"` が付き、`mcap_kabutan_oku`・`shares_kabutan` も入る。
- 銘柄名は **J-Quants 正式名称（`CoName`・「株式会社」は付けない）** を用いる。**略称は使わない**（例：9984＝ソフトバンクグループ、6981＝村田製作所、6920＝レーザーテック）。
- 出力 JSON：`rows`（採用銘柄）、`dropped_turnover`（≥+3%だが薄商い）、`dropped_mcap`（<100億）。各 row の `disclosures` には**当日15:30以降の TDnet 開示**が入っている。**この段階に変動要因は無い**（`factor`・`factor_kind` は空）。
- 株探は次のナイト開始（17:00）まで当該セッションを表示する。06:06 実行なら確定済み。

## 3. 変動要因の裏取り（★Claude の中核作業）

`docs/tmp/ranking.json` の **各 row** について「**なぜ PTS ナイトで上昇したか**」を特定し、
`factor`（日本語の説明文）と `factor_kind`（`開示`/`報道`/`テーマ` のいずれか）を埋める。
次の優先順で当たる：

1. **[開示]＝当該 SESSION 日 15:30 以降の TDnet 開示**（`row.disclosures` に格納済み）。東証通常取引の引けは **15:30**。15:30 以降の開示こそが PTS ナイト（17:00〜翌6:00）の材料になり得る（15:30 より前は日中に織り込み済み）。決算・上方/下方修正・TOB・新株予約権(MSワラント等)・優待・子会社化・大型受注などを**具体的に**記す。**根拠が適時開示のときは `factor_kind="開示"` とすること**（Web 表示で当該開示の **[開示PDF]** リンクが自動付与される。報道/テーマには付与しない）。
2. **[報道]＝主要メディアの一次記事**。WebSearch で探し、**検索結果の要約をそのまま出典にしない**。日経等の**具体的な記事本文と配信時刻**を確認し、**配信時刻が当該ナイトのセッション窓（SESSION 15:30以降〜翌06:00）に整合**するかで因果を裏取りする。TOB 価格への収斂等も報道で確認する。
3. **[テーマ]＝個別の新規材料が確認できない場合**のみ。半導体/AI・防衛/宇宙・地合い・需給(薄商い)等の文脈に位置づける。**[テーマ] は最後の手段**——必ず 1・2 を当たってから。
4. **材料が確認できなければ `factor` に「当日固有の材料は確認できず（…）」と正直に記し、`factor_kind="テーマ"`**。創作・憶測で埋めない。

**ソース規律（厳守）**：採用は確立した経済報道機関と一次情報（TDnet・企業 IR・取引所・中銀・統計当局）のみ。
**個人発信（X/Twitter 個人・note.com・個人ブログ/Substack・Reddit/掲示板・YouTube 個人・匿名まとめ・生成系）は引用も参照もしない**。判断に迷うソースは不採用。数値は実測のみ・創作禁止・投資助言をしない。

JSON 編集後は `docs/tmp/ranking.json` を**上書き保存**する。**`factor`/`factor_kind` 以外のフィールド（`code`/`name`/`market`/`mcap_oku`/`pct`/`pts`/`close`/`turnover_m`/`disclosures` 等）と `rows` の順序は一切変更しない**。特に **`name` を株探の略称で上書きしない**（最終的に `publish.py` が J-Quants 正式名称＝`CoName` へ自動正規化するが、そもそも書き換えないこと）。

## 4. 公開＋通知

```bash
python scripts/publish.py docs/tmp/ranking.json
```
- `docs/data/<SESSION>.json` を保存、`manifest.json` を更新、`docs/index.html` を再生成し、**Gmail 通知**を送る。
- Pages URL は環境変数 `PAGES_URL`（無ければ `GITHUB_REPOSITORY_OWNER`/`GITHUB_REPOSITORY` から推定）。
- 動作確認だけでメールを送りたくない場合は `--no-email` を付ける。

## 5. commit & push（必ず main へ）

- `docs/index.html` と `docs/data/`（`*.json`・`manifest.json`）をコミットし、**デフォルトブランチ `main` に push** する。
- GitHub Pages は **main/docs** を配信するため、`claude/...` ブランチへ push しても反映されない。クラウドセッションが `claude/...` ブランチ上にいても、**必ず次で main へ直接 push する**（本リポジトリは unrestricted branch push 許可済み）。**PR は作らない**。
  ```bash
  git add docs/index.html docs/data
  git commit -m "Update PTS gainers <SESSION>"
  git push origin HEAD:main
  ```
- `docs/tmp/` は `.gitignore` 済み（コミットしない）。

---

## 品質ゲート（出力前チェック）

- [ ] ゲートが `SESSION=...` を返したか（`SKIP` なら何もしない）。
- [ ] 抽出条件（上昇率≥+3% かつ 売買代金≥¥5M／東証個別／時価総額≥100億）を満たす銘柄のみ `rows` にあるか。
- [ ] 各 row の `factor`/`factor_kind` を、**[開示]（15:30以降）→[報道]（一次記事＋配信時刻でセッション窓と整合）→[テーマ]** の順で裏取りして埋めたか。**検索要約を出典にしていないか**。材料が無ければ正直に「材料未確認」としたか。
- [ ] 個人発信を引用・参照していないか。数値は実測のみで創作がないか。投資助言をしていないか。
- [ ] `publish.py` が成功し、`docs/data/<SESSION>.json`・`manifest.json`・`index.html` が更新されたか。Gmail が送信されたか。
- [ ] `docs/` を **main** にコミット＆プッシュしたか（`git push origin HEAD:main`。`claude/...` ブランチではない）。

## データソースと役割（再掲）

| データ | ソース |
| --- | --- |
| PTS気配・上昇率・出来高・順位 | 株探 J-Market `kabutan.jp/warning/pts_night_price_increase` |
| 市場区分・当日終値・発行済株式数・時価総額 | J-Quants V2 API（`api.jquants.com`） |
| 適時開示（一次情報） | TDnet `www.release.tdnet.info` |
| 報道（裏取り） | ホワイトリスト主要メディア（日経・Bloomberg・ロイター・WSJ・FT・CNBC 等） |

本ランキングは**上場株式**の値動きを扱う。暗号資産そのもの（BTC/ETH 価格動向）の分析はしないが、
ランキング結果に暗号資産関連の上場企業（メタプラネット等）が入る場合は上場株の事実として要因に記してよい。
