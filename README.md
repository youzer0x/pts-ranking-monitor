# PTS ナイト 値上がりランキング・モニター

日本株の **PTS ナイトタイムセッション（前営業日 17:00 → 当日 06:00）の株価上昇率ランキング（値上がり専用）** を、**東証の営業日ベースで毎朝・無人**に生成し、**Web ページ（GitHub Pages）と Gmail 通知**で配信するシステムです。各銘柄の**変動要因**（なぜ上がったか）を適時開示・主要メディアの一次情報で裏取りして付けます。

- 抽出条件：**東証個別株のみ**（ETF・REIT・地方単独上場は除外）／**PTS上昇率 ≥ +3% かつ 売買代金 ≥ ¥5,000,000**／**時価総額 ≥ 100億円**
- 時価総額＝**当日終値 × 発行済株式数**（J-Quants V2 API・億円・四捨五入。1兆円以上も億円表示）
- データ：PTS＝株探(J-Market)／時価総額・終値・株数・市場区分＝J-Quants V2／適時開示＝TDnet／報道＝主要メディア

---

## システム構成

```
Claude スケジュール・クラウドルーチン（毎日 06:06 JST・Sonnet 4.6・effort=max）
  └─ リポジトリ pts-ranking-monitor ＋ カスタム環境（シークレット/ネット許可/setup）に紐づけ
       └─ クラウドで Claude が AGENTS.md の手順を無人実行
            1. 営業日ゲート（前営業日が東証営業日のときだけ生成）
            2. 株探PTS＋J-Quants時価総額＋TDnet開示 を結合（決定的パイプライン）
            3. 各銘柄の変動要因を一次情報・主要メディアで裏取り（★毎回フル）
            4. GitHub Pages（Web）更新 ＋ Gmail 通知
            5. docs/ を commit & push
```

> なぜ GitHub Actions ではなく Claude ルーチンか：変動要因の裏取り（記事の配信時刻の確認・材料の取捨選択）には Web 検索と判断が要るため、Claude が毎回フルに行う構成にしています。

---

## セットアップ手順（順番に実施してください）

はじめてでも進められるよう、クリック単位で書いています。**Step 1〜9 を上から順に**実施してください。
所要 30〜45 分程度。途中で詰まったら末尾の「困ったとき」を参照してください。

> 用意するもの：GitHub アカウント／Gmail アカウント（2段階認証ON）／J-Quants の Light 以上のプランの API キー／Claude（Max プラン・Claude Code ルーチンが使えるアカウント）。

### Step 1：GitHub にリポジトリを作る

1. ブラウザで https://github.com にログインする。
2. 右上の「**＋**」→「**New repository**」をクリック。
3. 次を入力：
   - **Repository name**：`pts-ranking-monitor`
   - 公開範囲：**Public**（GitHub Pages を無料で使うため）
   - 「**Add a README file**」のチェックは**外す**（自分のファイルを入れるため）
4. 「**Create repository**」をクリック。次の画面に出る URL（`https://github.com/あなたの名前/pts-ranking-monitor.git`）を控える。

### Step 2：このフォルダの中身を GitHub にアップロードする

ファイル一式はすでに手元の `C:\Users\YujiroOkawa\project-private\pts-ranking-monitor` にあります。
**いちばん簡単な方法：Claude Code に「このリポジトリを GitHub にプッシュして」と頼む**（git の初期化・コミット・プッシュを代行します）。

自分で行う場合（Git Bash でこのフォルダに入って実行）：
```bash
cd /c/Users/YujiroOkawa/project-private/pts-ranking-monitor
git init
git add .
git commit -m "Initial commit: PTS ranking monitor"
git branch -M main
git remote add origin https://github.com/あなたの名前/pts-ranking-monitor.git
git push -u origin main
```
> GitHub Desktop（https://desktop.github.com）を使うなら、「Add Local Repository」でこのフォルダを選び、「Publish repository」でも OK です。

アップロード後、GitHub のリポジトリ画面に `scripts/`・`docs/`・`AGENTS.md`・`README.md` 等が表示されていれば成功です。

### Step 3：Claude の GitHub App をリポジトリに入れる（クラウドから読み書きするため）

1. https://github.com/apps/claude を開く（または Claude の設定からも辿れます）。
2. 「**Install**」（導入済みなら「**Configure**」）をクリック。
3. 対象に「**Only select repositories**」を選び、`pts-ranking-monitor` を選択。
4. 権限は **Contents: Read and write**（リポジトリへの書き込み）を許可して保存。
   - これによりクラウドの Claude がリポジトリを clone し、`docs/` を push できます。

### Step 4：GitHub Pages を有効にする（Web ページ公開）

1. リポジトリの「**Settings**」タブ → 左メニュー「**Pages**」。
2. **Source**：「**Deploy from a branch**」。
3. **Branch**：「**main**」、フォルダは「**/docs**」を選び「**Save**」。
4. 数分後、`https://あなたの名前.github.io/pts-ranking-monitor/` で公開されます（初回はデータがあるので
   サンプルの 2026-06-15 が表示されます）。

### Step 5：Gmail のアプリパスワードを取得する（通知メール送信用）

1. https://myaccount.google.com/security で「**2段階認証プロセス**」が**ON**であることを確認（OFF なら先に ON）。
2. https://myaccount.google.com/apppasswords を開く。
3. アプリ名に「**PTS Ranking Monitor**」と入力 →「**作成**」。
4. 表示される **16桁のパスワード**をコピーして控える（スペースは入れない）。

### Step 6：J-Quants の API キーを用意する

- J-Quants（https://jpx-jquants.com）の **Light プラン以上**の API キー（リフレッシュトークン/ID トークンではなく、`x-api-key` に使うキー）を控えます。
  - Free プランは当日値が取得できない（遅延）ため**不可**。

### Step 7：Claude に「カスタム環境」を作る（シークレット・ネット許可・初期化）

> ルーチン作成フォームからは環境を編集できないため、**先に環境を作ります**。

1. https://claude.ai を開き、**Settings → Environments**（環境）を開く。
2. 「**New environment / 新規作成**」を選び、名前を `pts-ranking-env` などにする。
3. **Secrets / 環境変数**に次の4つを追加（名前は完全一致で）：
   | 名前 | 値 |
   |------|----|
   | `JQUANTS_API_KEY` | Step 6 の J-Quants API キー |
   | `GMAIL_ADDRESS` | 送信元の Gmail アドレス |
   | `GMAIL_APP_PASSWORD` | Step 5 の16桁パスワード |
   | `NOTIFY_TO` | 通知の宛先メールアドレス（自分宛なら GMAIL_ADDRESS と同じでOK） |
   - 任意：`TZ` = `Asia/Tokyo`（日付計算を JST に固定。設定推奨）。
   - 任意：`PAGES_URL` = `https://あなたの名前.github.io/pts-ranking-monitor/`（メールのリンク用。未設定でも自動推定します）。
4. **ネットワーク許可**（外部接続の許可リスト）に次を追加：
   - `kabutan.jp`（株探：PTSランキング・銘柄ページ）
   - `api.jquants.com`（J-Quants API）
   - `www.release.tdnet.info`（TDnet 適時開示）
   - `smtp.gmail.com`（メール送信）
   - **Web 検索／記事閲覧を有効化**し、報道裏取り用に主要メディアを許可：`nikkei.com`・`reuters.com`・`bloomberg.com`・`wsj.com`・`ft.com`・`cnbc.com`・`asia.nikkei.com`・`jiji.com`・`kyodonews.jp`・`toyokeizai.net`・`diamond.jp`（広めに許可できる設定ならそれでも可）。
5. **セットアップ・スクリプト**（環境構築時に1回走るコマンド）に次を設定：
   ```bash
   pip install -r requirements.txt
   ```
6. 保存する。

### Step 8：スケジュール・ルーチンを作る

1. claude.ai で **Code のルーチン（Routines / スケジュール実行）**の作成画面を開く（Claude Code → スケジュール、または `/schedule` 相当の入口）。
2. 次を設定：
   - **リポジトリ**：`pts-ranking-monitor`
   - **環境**：Step 7 で作った `pts-ranking-env`
   - **モデル**：**Sonnet 4.6**
   - **effort**：**max**
   - **スケジュール（cron）**：毎日 **06:06 JST**（UTC 表記なら `6 21 * * *` ＝ 21:06 UTC。タイムゾーン指定欄があれば Asia/Tokyo で `6 6 * * *`）
   - **プロンプト**：`ROUTINE_PROMPT.md` の```で囲まれた本文をそのまま貼り付け。
3. 保存する。

> 06:00 ちょうどではなく **06:06** にするのは、PTS ナイトが 06:00 に終わり株探が 06:02 ごろに確定するためです（確定後・寄り付き 09:00 の十分前）。

### Step 9：初回テスト

1. ルーチンの「**今すぐ実行 / Run now**」で手動実行する（平日の朝以外でも、前営業日があれば最新セッションで動きます）。
2. 実行ログにエラーが無いことを確認。
3. 次を確認：
   - Web：`https://あなたの名前.github.io/pts-ranking-monitor/` に当日のランキングと変動要因が出る。
   - メール：`NOTIFY_TO` 宛に「【PTS夜間値上がり】… 値上がりランキング（N社）」が届く。
   - リポジトリ：`docs/data/` に新しい `YYYY-MM-DD.json` が追加されている。

以上で日次自動が稼働します。以後は毎朝 06:06 JST に自動生成されます（休場明けで前営業日が無い朝はスキップ）。

---

## 手元での手動実行（任意・動作確認用）

このリポジトリは手元でも単体で動きます（`JQUANTS_API_KEY` を設定済みであること）。

```bash
cd /c/Users/YujiroOkawa/project-private/pts-ranking-monitor
python scripts/check_gate.py                                   # 営業日ゲート確認
python scripts/build_ranking.py --date 2026-06-15 --out docs/tmp/ranking.json
# （必要なら docs/tmp/ranking.json の各 row の factor/factor_kind を編集）
python scripts/publish.py docs/tmp/ranking.json --no-email     # メールを送らず Pages だけ更新
```

---

## ファイル構成

```
pts-ranking-monitor/
├── AGENTS.md            # ルーチンの方法論（クラウド Claude が従う単一の真実源）
├── ROUTINE_PROMPT.md    # Scheduled トリガに貼り付けるプロンプト本文
├── README.md            # このファイル（セットアップ手順）
├── requirements.txt     # 依存（jpholiday のみ。他は標準ライブラリ）
├── scripts/
│   ├── check_gate.py    # 営業日ゲート（前営業日が営業日か）
│   ├── build_ranking.py # Stage1: 株探+J-Quants+TDnet を結合し素データJSON（変動要因なし）
│   ├── kabutan_pts.py   # 株探 PTS ナイト値上がりの取得・パース
│   ├── jquants.py       # J-Quants V2（時価総額・市場区分・終値・株数）
│   ├── tdnet.py         # TDnet 適時開示（15:30以降の突合）
│   ├── business_day.py  # 東証営業日判定・セッション日導出
│   ├── html_generator.py# GitHub Pages / メール本文 HTML
│   ├── gmail_sender.py  # Gmail 送信（SMTP）
│   └── publish.py       # Stage2: JSON→docs/data・manifest・index.html・メール
└── docs/                # GitHub Pages（自動更新）
    ├── index.html
    └── data/            # 日次 JSON（直近90日保持）＋ manifest.json
```

---

## 仕組み（ポイント）

- **タイミング**：cron 06:06 JST。PTS ナイトは 06:00 終了、株探は 06:02 ごろ確定。確定後・寄り付き前に生成。
- **営業日ゲート**：前営業日（＝ナイトを始めた日）が東証営業日のときだけ生成。土日・祝日・年末年始は `jpholiday` で判定し、新規セッションが無い朝はスキップ。
- **時価総額**：J-Quants の当日終値×発行済株式数×分割/併合補正（億円・四捨五入）。**増資・自己株消却**で株探の最新株数と **>1% 乖離**する銘柄は **†** を付け、参考値を注記。
- **変動要因**：当日 15:30 以降の TDnet 開示を最優先、次に主要メディアの一次記事を**配信時刻でセッション窓と整合確認**して裏取り。材料が無ければ「材料未確認」と正直に記載。**個人発信は不使用**。
- **使用モデル**：Sonnet 4.6＋effort=max（Opus より単価が低く、変動要因の検証・判断の品質を確保）。

---

## 困ったとき

| 症状 | 対処 |
|------|------|
| ルーチンが動かない | スケジュール（cron）とタイムゾーン、リポジトリ/環境の紐づけを確認。手動「Run now」でログを見る |
| Pages が表示されない | Settings → Pages が **main / /docs** か確認。初回反映に数分かかる |
| メールが届かない | 環境のシークレット（`GMAIL_ADDRESS`/`GMAIL_APP_PASSWORD`/`NOTIFY_TO`）を再確認。アプリパスワードにスペースが入っていないか |
| 時価総額が出ない/少ない | `JQUANTS_API_KEY` が **Light 以上**か（Free は当日値なし）。ネット許可に `api.jquants.com` があるか |
| PTS が取得できない | ネット許可に `kabutan.jp` があるか。06:06 より大幅に早い時刻だと未確定の可能性 |
| 変動要因が薄い | 環境で **Web 検索が有効**か、主要メディアのドメインが許可されているか確認 |
| push できない | Step 3 の Claude GitHub App が **Contents: Read and write** で入っているか |

---

## 免責

本システムの出力は参考情報であり、投資助言ではありません。数値・事実は各自で最新の一次情報を確認のうえ、投資判断は自己責任で行ってください。確認できない項目は「取得不可」「材料未確認」と明記しています。
