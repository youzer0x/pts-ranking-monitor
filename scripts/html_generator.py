"""GitHub Pages 用 HTML と Gmail 本文 HTML の生成（PTS 夜間 値上がり率ランキング）。

公開データ（docs/data/YYYY-MM-DD.json）は build_ranking.py の出力に各行の変動要因（factor /
factor_kind）を埋めたもの。Pages は manifest.json から日付一覧を読み、選択日の JSON を描画する。
時価総額は要件により **常に億円の整数（カンマ区切り、1兆円以上も億円表示）** とする。

Pages のデザインは tse-ranking-monitor の「金融紙エディトリアル」デザイン（生成りの紙面風背景・
明朝見出し・ヘアライン罫線・tabular-nums）と統一している。見た目を変更する際は両リポで揃えること
（市場分析ビューと pct5 は東証版のみ。PTS 側にはデータが無いため移植しない）。

表示ルール:
  - 数値（コード・時価総額・上昇率・PTS気配・東証終値・売買代金）は Arial・千区切り。
  - 売買代金（百万円）は四捨五入して整数表示。
  - 市場区分は英語表記（Prime / Standard / Growth）。
  - 変動要因の根拠が適時開示（factor_kind="開示"）で PDF がある場合のみ [開示PDF] リンクを添付する。
"""
import html
import re
from datetime import date

_MD_LINK_RE = re.compile(r'\[([^\[\]]+)\]\((https?://[^\s()]+)\)')


def linkify_factor(text):
    """factor 本文の [出典名](URL) を <a> タグへ変換する。
    それ以外の文字は HTML エスケープする（factor は LLM 生成の自由文のため）。"""
    escaped = html.escape(text)

    def _repl(m):
        label, url = m.group(1), m.group(2)
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'

    return _MD_LINK_RE.sub(_repl, escaped)


def fmt_mcap(oku, flag=""):
    if oku is None:
        return "—"
    return f"{oku:,}{flag or ''}"


def fmt_pct(pct):
    if pct is None:
        return "—"
    return f"+{pct:.2f}%"


# ----------------------------------------------------------------------------- email

def _kind_badge(kind):
    k = (kind or "").strip("[]")
    color = {"開示": "#1b7f3b", "報道": "#1a6fd0", "テーマ": "#8a6d00"}.get(k, "#777")
    return (f'<span style="display:inline-block;font-size:10px;color:#fff;background:{color};'
            f'border-radius:3px;padding:1px 5px;margin-right:4px;white-space:nowrap;">{k or "—"}</span>') if k else ""


def generate_email_html(data, pages_url, max_items=25):
    rows = data.get("rows", [])
    display = rows[:max_items] if max_items else rows
    n = len(rows)
    win = data.get("session_window", "")
    date_str = data.get("session_date", "")
    trs = []
    for r in display:
        factor = linkify_factor((r.get("factor") or "（材料未確認）").strip())
        badge = _kind_badge(r.get("factor_kind"))
        trs.append(f"""<tr>
          <td style="padding:7px 8px;border-bottom:1px solid #eee;text-align:right;font-family:Arial,sans-serif;">{r.get('rank','')}</td>
          <td style="padding:7px 8px;border-bottom:1px solid #eee;font-family:Arial,sans-serif;white-space:nowrap;">{r.get('code','')}</td>
          <td style="padding:7px 8px;border-bottom:1px solid #eee;white-space:nowrap;">{r.get('name','')}</td>
          <td style="padding:7px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;font-family:Arial,sans-serif;">{fmt_mcap(r.get('mcap_oku'), r.get('mcap_flag'))}</td>
          <td style="padding:7px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;font-family:Arial,sans-serif;color:#c0392b;font-weight:600;">{fmt_pct(r.get('pct'))}</td>
          <td class="col-factor" style="padding:7px 8px;border-bottom:1px solid #eee;font-size:12px;line-height:1.5;">{badge}{factor}</td>
        </tr>""")
    table_rows = "\n".join(trs)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>@media screen and (max-width:600px){{ .col-factor{{display:none!important;}} }}</style>
</head>
<body style="font-family:'Helvetica Neue',Arial,'Hiragino Sans',sans-serif;color:#333;margin:0;padding:0;background:#f5f5f5;">
  <div style="max-width:980px;margin:20px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
    <div style="background:#11243f;color:#fff;padding:18px 22px;">
      <h1 style="margin:0;font-size:19px;font-weight:600;">📈 PTS 夜間 値上がり率ランキング</h1>
      <p style="margin:6px 0 0;font-size:13px;opacity:0.9;">{date_str}｜該当 {n} 社｜{win}</p>
      <p style="margin:4px 0 0;font-size:11px;opacity:0.7;">条件：上昇率≥+3% かつ 売買代金≥10百万円／東証個別・時価総額≥100億円</p>
    </div>
    <div style="padding:16px 20px;">
      <div style="text-align:center;margin:0 0 14px;">
        <a href="{pages_url}" target="_blank" style="display:inline-block;background:#11243f;color:#fff;padding:9px 26px;border-radius:6px;text-decoration:none;font-size:14px;">全件・詳細を表示 →</a>
      </div>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:13px;">
        <thead><tr style="background:#f6f8fa;">
          <th style="padding:8px;text-align:right;border-bottom:2px solid #11243f;">#</th>
          <th style="padding:8px;text-align:left;border-bottom:2px solid #11243f;white-space:nowrap;">コード</th>
          <th style="padding:8px;text-align:left;border-bottom:2px solid #11243f;">銘柄</th>
          <th style="padding:8px;text-align:right;border-bottom:2px solid #11243f;white-space:nowrap;">時価総額<br>(億円)</th>
          <th style="padding:8px;text-align:right;border-bottom:2px solid #11243f;white-space:nowrap;">上昇率</th>
          <th class="col-factor" style="padding:8px;text-align:left;border-bottom:2px solid #11243f;width:40%;">変動要因</th>
        </tr></thead>
        <tbody>
{table_rows}
        </tbody>
      </table>
      <p style="margin:14px 0 0;font-size:11px;color:#888;">時価総額・終値・株数＝J-Quants V2／PTS気配・上昇率・出来高＝株探(J-Market)／開示＝TDnet。† は増資・自己株で株探最新株数と乖離。本情報は参考であり投資助言ではない。</p>
    </div>
    <div style="background:#f6f8fa;padding:11px 20px;font-size:11px;color:#999;text-align:center;">PTS ランキング・モニター｜Claude 定期実行（自動送信）</div>
  </div>
</body></html>"""


# ----------------------------------------------------------------------------- pages

def generate_pages_html():
    return r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PTS 夜間 値上がり率ランキング</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=Noto+Serif+JP:wght@600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#f5f2ea;--card:#fefcf7;--primary:#11243f;--accent:#ae2b23;--down:#186a3b;--text:#262420;--sub:#6b6558;--border:#e2e6ea;--hairline:#ddd6c7;--rule:#11243f;--hover:#f5f8ff;--wash:#f3efe4;--serif:'Noto Serif JP','Hiragino Mincho ProN','Yu Mincho',serif;--sans:'Noto Sans JP',sans-serif;--numfont:'Helvetica Neue',Arial,'Noto Sans JP',sans-serif;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:var(--sans);background:var(--bg);color:var(--text);line-height:1.6;}
.header{background:var(--card);color:var(--text);border-top:4px solid var(--primary);border-bottom:1px solid var(--rule);padding:20px 28px 0;position:relative;}
.header-inner{max-width:1280px;margin:0 auto;display:flex;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;gap:14px;}
.tabs{display:inline-flex;align-items:flex-end;flex-wrap:wrap;}
.tabs .tab{margin:0 26px 0 0;padding:6px 2px 12px;border-bottom:3px solid transparent;font-size:15px;font-weight:500;line-height:1.35;text-decoration:none;color:var(--sub);white-space:nowrap;}
.tabs h1.tab{font-family:var(--serif);font-size:20px;font-weight:700;letter-spacing:.01em;color:var(--primary);}
.tabs .tab.active{color:var(--primary);border-bottom-color:var(--primary);}
.tabs a.tab:hover{color:var(--primary);}
.date-selector{display:flex;align-items:center;gap:8px;margin-bottom:12px;}
.date-selector label{font-size:12px;color:var(--sub);letter-spacing:.04em;}
.date-selector select{padding:7px 30px 7px 12px;font-size:13.5px;font-family:var(--numfont);border:1px solid var(--hairline);border-radius:3px;background:var(--card);color:var(--primary);cursor:pointer;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M2 4l4 4 4-4' stroke='%2311243f' stroke-width='1.5' fill='none'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center;}
.date-selector select option{background:var(--card);color:var(--text);}
.summary{max-width:1280px;margin:16px auto 0;padding:0 16px;display:flex;gap:10px;flex-wrap:wrap;}
.chip{background:var(--card);border:1px solid var(--hairline);border-radius:3px;padding:8px 14px;font-size:13px;}
.chip .num{font-family:var(--numfont);font-weight:700;font-size:16px;color:var(--primary);}
.container{max-width:1280px;margin:14px auto 28px;padding:0 16px;}
.card{background:var(--card);border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.06);overflow:hidden;}
.note{padding:10px 8px 12px;font-size:12px;color:var(--sub);}
table{width:100%;border-collapse:collapse;font-size:13px;}
thead th{padding:9px 10px;text-align:left;background:#f6f8fc;border-bottom:2px solid var(--primary);font-size:12px;color:var(--sub);white-space:nowrap;position:sticky;top:0;}
thead th.r{text-align:right;}
tbody td{padding:9px 10px;border-bottom:1px solid var(--border);vertical-align:top;}
tbody tr:hover td{background:var(--hover);}
.rank{font-family:Arial,sans-serif;text-align:right;color:var(--sub);}
.code{font-family:Arial,sans-serif;white-space:nowrap;}
.code a{color:var(--primary);text-decoration:none;}
.code a:hover{text-decoration:underline;}
.name{white-space:nowrap;font-weight:500;}
.name .mcap{display:block;font-family:Arial,'Noto Sans JP',sans-serif;font-size:11px;font-weight:400;color:#5b6573;margin-top:1px;letter-spacing:.2px;}
.code-inline{display:none;}
.mkt{white-space:nowrap;}
.num{font-family:Arial,sans-serif;text-align:right;white-space:nowrap;}
.pct{font-family:Arial,sans-serif;text-align:right;white-space:nowrap;color:var(--accent);font-weight:600;}
.factor{font-size:12.5px;line-height:1.55;min-width:240px;}
.kind{display:inline-block;font-size:10px;color:#fff;border-radius:3px;padding:1px 6px;margin-right:5px;white-space:nowrap;}
.kind.k開示{background:#1b7f3b;} .kind.k報道{background:#1a6fd0;} .kind.kテーマ{background:#8a6d00;}
.factor a{color:#1a6fd0;text-decoration:none;} .factor a:hover{text-decoration:underline;}
.dropped{margin-top:18px;}
.dropped summary{cursor:pointer;font-size:13px;color:var(--sub);padding:8px 4px;}
.footer{max-width:1280px;margin:12px auto 0;text-align:center;padding:16px 16px 24px;font-size:11px;color:var(--sub);border-top:1px solid var(--hairline);letter-spacing:.02em;}
.loading,.empty{text-align:center;padding:50px 20px;color:var(--sub);}
.num,.pct,.rank,.code,.chip .num,#dateSelect{font-variant-numeric:tabular-nums lining-nums;}
@media(max-width:820px){
 .header{padding:14px 14px 0;} .header-inner{flex-direction:column;align-items:stretch;gap:0;}
 .tabs{width:100%;overflow-x:auto;flex-wrap:nowrap;-webkit-overflow-scrolling:touch;}
 .tabs .tab{margin-right:18px;padding-bottom:10px;}
 .tabs h1.tab{font-size:17px;}
 .date-selector{width:100%;margin:10px 0 12px;} .date-selector select{flex:1;}
 #viewRanking table,#viewRanking thead,#viewRanking tbody,#viewRanking tr,#viewRanking td{display:block;width:100%;}
 #viewRanking thead{display:none;}
 #viewRanking .card{background:transparent;box-shadow:none;border-radius:0;overflow:visible;}
 #viewRanking tbody tr{background:var(--card);border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.06);margin:0 0 12px;padding:12px 14px;border:none;}
 #viewRanking tbody td{padding:0;border:none;text-align:left!important;}
 #tableArea td.rank{display:block;font-size:13px;color:var(--sub);font-family:Arial,sans-serif;}
 #tableArea td.rank::before{content:'#';}
 #tableArea td.code{display:none;}
 #tableArea td.name{display:block;font-size:15px;font-weight:700;}
 #tableArea td.name .code-inline{display:inline;font-weight:700;}
 #tableArea td.name .mcap{font-size:12px;}
 #tableArea td.mkt{display:block;font-size:12px;color:var(--sub);}
 #viewRanking td.pct,#viewRanking td.num{display:inline-block;width:49%;font-size:14px;margin-top:8px;text-align:left;vertical-align:top;}
 #viewRanking td.pct::before,#viewRanking td.num::before{content:attr(data-label)'\00a0';display:block;color:var(--sub);font-size:11px;font-weight:400;font-family:'Noto Sans JP';}
 #viewRanking td.factor{min-width:0;margin-top:10px;padding-top:9px;border-top:1px solid var(--border)!important;}
}
</style></head>
<body>
<div class="header"><div class="header-inner">
  <nav class="tabs">
    <a class="tab" href="https://youzer0x.github.io/tse-ranking-monitor/">東証 値上がり率ランキング</a>
    <a class="tab" href="https://youzer0x.github.io/tse-ranking-monitor/#market">市場分析</a>
    <h1 class="tab active">PTS 夜間 値上がり率ランキング</h1>
  </nav>
  <div class="date-selector"><label for="dateSelect">セッション日:</label>
  <select id="dateSelect" onchange="loadDate(this.value)"><option>読み込み中...</option></select></div>
</div></div>
<div id="viewRanking">
<div class="summary" id="summary"></div>
<div class="container">
  <div class="note" id="note"></div>
  <div class="card">
  <div id="tableArea"><div class="loading">データを読み込んでいます…</div></div>
  </div>
<div class="container" style="margin-top:0;"><div id="droppedArea"></div></div>
</div>
</div>
<div class="footer">PTS ランキング・モニター｜Claude 定期実行で自動生成｜時価総額・終値・株数＝J-Quants V2／PTS＝株探(J-Market)／開示＝TDnet｜本情報は参考であり投資助言ではない</div>
<script>
let data=null;
function fmtMcap(o,f){if(o==null)return '—';return o.toLocaleString('ja-JP')+(f||'');}
function fmtPct(p){return p==null?'—':'+'+Number(p).toFixed(2)+'%';}
function fmtNum(x){return x==null?'—':Number(x).toLocaleString('ja-JP');}
function fmtTurnover(t){return t==null?'—':Math.round(Number(t)).toLocaleString('ja-JP');}
function fmtMarket(m){m=m||'';if(m.indexOf('プライム')>=0)return 'Prime';if(m.indexOf('スタンダード')>=0)return 'Standard';if(m.indexOf('グロース')>=0)return 'Growth';return m;}
function fmtCode(c){c=(c==null?'':String(c));return (c.length===5&&c.endsWith('0'))?c.slice(0,4):c;}
function fmtMcapCell(o,f){if(o==null)return '—';o=Number(o);var s=o>=10000?(o/10000).toFixed(1)+'兆円':Math.round(o).toLocaleString('ja-JP')+'億円';return s+(f||'');}
function riseYen(r){if(r==null||r.pts==null||r.close==null)return null;return Math.round(Number(r.pts)-Number(r.close));}
function fmtSigned(v){if(v==null)return '—';var n=Number(v);return (n>=0?'+':'')+n.toLocaleString('ja-JP');}
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
function linkifyFactor(s){var t=esc(s==null?'':s);return t.replace(/\[([^\[\]]+)\]\((https?:\/\/[^\s()]+)\)/g,function(_,label,url){return '<a href="'+url.replace(/"/g,'&quot;')+'" target="_blank" rel="noopener noreferrer">'+label+'</a>';});}
function kindBadge(k){k=(k||'').replace(/[\[\]]/g,'');if(!k)return '';return '<span class="kind k'+k+'">'+k+'</span>';}
async function init(){
  try{
    const m=await (await fetch('data/manifest.json?'+Date.now())).json();
    const sel=document.getElementById('dateSelect');sel.innerHTML='';
    if(!m.dates||!m.dates.length){sel.innerHTML='<option>データなし</option>';document.getElementById('tableArea').innerHTML='<div class="empty">まだデータがありません。</div>';return;}
    m.dates.forEach((d,i)=>{const o=document.createElement('option');o.value=d;const dt=new Date(d+'T00:00:00');o.textContent=d+' ('+['日','月','火','水','木','金','土'][dt.getDay()]+')';if(i===0)o.selected=true;sel.appendChild(o);});
    loadDate(m.dates[0]);
  }catch(e){document.getElementById('tableArea').innerHTML='<div class="empty">データの読み込みに失敗しました。</div>';}
}
async function loadDate(d){
  if(!d)return;
  document.getElementById('tableArea').innerHTML='<div class="loading">読み込み中…</div>';
  try{data=await (await fetch('data/'+d+'.json?'+Date.now())).json();render();}
  catch(e){document.getElementById('tableArea').innerHTML='<div class="empty">この日付のデータを読み込めませんでした。</div>';}
}
function render(){
  const rows=data.rows||[];
  document.getElementById('summary').innerHTML=
    '<div class="chip"><span class="num">'+rows.length+'</span> 社該当</div>'+
    '<div class="chip">'+esc(data.session_window||'')+'</div>'+
    (data.generated_at?'<div class="chip">生成 '+esc(data.generated_at)+'</div>':'');
  const c=data.criteria||{};
  document.getElementById('note').textContent=
    '抽出条件：PTS上昇率≥+'+(c.min_pct??3)+'% かつ 売買代金≥'+((c.min_turnover_yen??10e6)/1e6)+'百万円／東証個別株のみ・時価総額≥'+(c.min_mcap_oku??100)+'億円。時価総額は当日終値×発行済株式数（億円・四捨五入）。† は増資・自己株で株探最新株数と>1%乖離。';
  let h='<table><thead><tr><th class="r">#</th><th>コード</th><th>銘柄</th><th>市場</th><th class="r">上昇率</th><th class="r">上昇幅<br>(円)</th><th class="r">PTS気配<br>(円)</th><th class="r">東証終値<br>(円)</th><th class="r">売買代金<br>(百万円)</th><th>変動要因</th></tr></thead><tbody>';
  rows.forEach(r=>{
    let factor=linkifyFactor(r.factor||'（材料未確認）');
    const fk=(r.factor_kind||'').replace(/[\[\]]/g,'');
    if(fk==='開示'&&r.disclosures&&r.disclosures.length&&r.disclosures[0].pdf_url){factor=factor+' <a href="'+esc(r.disclosures[0].pdf_url)+'" target="_blank">[開示PDF]</a>';}
    const code=fmtCode(r.code);
    h+='<tr>'+
      '<td class="rank">'+(r.rank||'')+'</td>'+
      '<td class="code rankcode" data-rank="'+(r.rank||'')+'"><a href="https://kabutan.jp/stock/?code='+esc(code)+'" target="_blank">'+esc(code)+'</a></td>'+
      '<td class="name" data-code="'+esc(code)+'">'+esc(r.name)+'<span class="code-inline">（'+esc(code)+'）</span><span class="mcap">'+fmtMcapCell(r.mcap_oku,r.mcap_flag)+'</span></td>'+
      '<td class="mkt">'+esc(fmtMarket(r.market))+'</td>'+
      '<td class="pct" data-label="上昇率">'+fmtPct(r.pct)+'</td>'+
      '<td class="num" data-label="上昇幅(円)">'+fmtSigned(riseYen(r))+'</td>'+
      '<td class="num" data-label="PTS気配(円)">'+fmtNum(r.pts)+'</td>'+
      '<td class="num" data-label="東証終値(円)">'+fmtNum(r.close)+'</td>'+
      '<td class="num" data-label="売買代金(百万円)">'+fmtTurnover(r.turnover_m)+'</td>'+
      '<td class="factor">'+kindBadge(r.factor_kind)+factor+'</td>'+
    '</tr>';
  });
  h+='</tbody></table>';
  document.getElementById('tableArea').innerHTML=h;
  // dropped (薄商い) を折りたたみで
  const dt=data.dropped_turnover||[];
  let dh='';
  if(dt.length){
    dh='<details class="dropped card" style="padding:0 14px 10px;"><summary>参考：上昇率≥+3% だが売買代金&lt;10百万円 で除外（薄商い'+dt.length+'件）</summary><table><thead><tr><th>コード</th><th>銘柄</th><th class="r">上昇率</th><th class="r">売買代金<br>(百万円)</th></tr></thead><tbody>';
    dt.forEach(r=>{dh+='<tr><td class="code">'+esc(fmtCode(r.code))+'</td><td class="name">'+esc(r.name)+'</td><td class="pct" data-label="上昇率">'+fmtPct(r.pct)+'</td><td class="num" data-label="売買代金(百万円)">'+fmtTurnover(r.turnover_m)+'</td></tr>';});
    dh+='</tbody></table></details>';
  }
  document.getElementById('droppedArea').innerHTML=dh;
}
init();
</script>
</body></html>"""
