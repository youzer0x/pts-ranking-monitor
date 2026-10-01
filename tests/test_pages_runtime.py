"""生成HTMLのJavaScriptをNodeで実行して値・描画・日付切替を確認する。"""
import json
import shutil
import subprocess

import html_generator as hg


def run_js(expression):
    node = shutil.which("node")
    assert node, "Node.js が必要（CIはsetup-node、ローカルはNode.js 22以降を用意）"
    source = hg.generate_pages_html().split("<script>", 1)[1].split("</script>", 1)[0]
    source = source.rsplit("init();", 1)[0]
    program = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const nodes = {};
const context = vm.createContext({
  document: {
    getElementById(id) {return nodes[id] ||= {innerHTML: ''};},
    createElement() {return {textContent: '', get innerHTML() {
      return String(this.textContent).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }};}
  }, nodes
});
vm.runInContext(payload.source, context);
Promise.resolve(vm.runInContext(payload.expression, context))
  .then(value => process.stdout.write(JSON.stringify(value)))
  .catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run([node, "-e", program], input=json.dumps({"source": source, "expression": expression}),
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_prices_units_and_mcap_boundaries():
    actual = run_js("""({
      pts: [{pts:1234.5,close:1200}, {pts:1000,close:1000}, {pts:0,close:0},
            {pts:null,close:1000}, {pts:1000,close:null}].map(fmtPtsCell),
      close: [1234.5,0,null].map(fmtYen),
      turnover: [10.4,10.5,0,null].map(fmtTurnoverCell),
      mcaps: [null,9999,10000,123456].map(v=>fmtMcapCell(v,'†'))
    })""")
    assert actual["pts"] == [
        '1,234.5円<span class="chg">+35円</span>',
        '1,000円<span class="chg">+0円</span>', '0円<span class="chg">+0円</span>', "—", "1,000円"]
    assert actual["close"] == ["1,234.5円", "0円", "—"]
    assert actual["turnover"] == ["10百万円", "11百万円", "0百万円", "—"]
    assert actual["mcaps"] == ["—", "9,999億円†", "1.0兆円†", "12.3兆円†"]


def test_render_keeps_sources_and_explains_old_and_new_dates():
    result = run_js("""(async()=>{
      const old = {session_date:'2026-09-30', rows:[{
        rank:1,code:'1234',name:'テスト',mcap_oku:10000,mcap_flag:'†',pts:1100,close:1000,
        pct:10,turnover_m:10,factor:'[出典](https://example.com/article)',factor_kind:'開示',
        disclosures:[{pdf_url:'https://example.com/disclosure.pdf'}]
      }]};
      const newer = JSON.parse(JSON.stringify(old));
      newer.criteria={mcap_method:'jquants_valuation'};
      newer.rows[0].mcap_source='yahoo'; delete newer.rows[0].mcap_flag;
      const fixtures={'2026-09-30':old,'2026-10-01':newer};
      globalThis.fetch=async(url)=>({json:async()=>fixtures[url.slice(5,15)]});
      await loadDate('2026-09-30');
      const oldResult={table:nodes.tableArea.innerHTML,info:nodes.infoBody.innerHTML};
      await loadDate('2026-10-01');
      return {old:oldResult,newer:{table:nodes.tableArea.innerHTML,info:nodes.infoBody.innerHTML}};
    })()""")
    old, new = result["old"], result["newer"]
    for rendered in (old, new):
        assert "PTS気配<br>(東証終値比)" in rendered["table"]
        assert "上昇幅<br>" not in rendered["table"]
        assert 'data-label="東証終値">1,000円' in rendered["table"]
        assert 'href="https://example.com/article"' in rendered["table"]
        assert 'href="https://example.com/disclosure.pdf"' in rendered["table"]
        assert '<span class="chg">+100円</span>' in rendered["table"]
    assert "1.0兆円†" in old["table"] and "旧方式" in old["info"]
    assert "Yahoo参照" in new["table"] and "†" not in new["table"]
    assert "自己株式控除後株式数" in new["info"] and "旧方式" not in new["info"]
    assert "自己株式控除後とは限らない" in new["info"]


def test_python_and_browser_methodology_text_agree():
    docs = [{"rows": []}, {"criteria": {"mcap_method": "jquants_valuation"}, "rows": []},
            {"criteria": {"mcap_method": "jquants_valuation"}, "rows": [{"mcap_source": "yahoo"}]}]
    actual = run_js(json.dumps(docs) + ".map(mcapDescription)")
    assert actual == [hg.mcap_description(doc) for doc in docs]
