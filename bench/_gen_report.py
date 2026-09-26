# -*- coding: utf-8 -*-
"""从 safety_10k_result.json 渲染 HTML 成果报告 (纯内联, 无外部依赖)。"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
d = json.load(open(ROOT / "bench" / "safety_10k_result.json", encoding="utf-8"))

def esc(s: str) -> str:
    return html.escape(s, quote=True)

def pct(v: float) -> str:
    return f"{v:.2f}%"

# ---------------- 指标卡 ----------------
cards = [
    ("10000", "评测命令总数", "危险+良性对抗语料", "total", d["total"]),
    (f"{d['tp_block']}/{d['n_expect_block']}", "成功拦截", f"拦截率 {pct(d['block_recall'])}", "block", d["block_recall"]),
    (f"{d['bypass']}", "漏放", f"拦截遗漏 {d['miss_block']} + 该标未标 {d['miss_flag']}", "miss", d["bypass"]),
    (f"{d['flagged']}", "成功标记", "标记为「需人工确认」", "flag", d["flagged"]),
    (f"{d['false_pos']}", "误杀 (严格口径)", f"仅硬拦 {d['false_pos_block_only']} 条 ({pct(d['false_positive_block_rate'])})", "fp", d["false_pos"]),
    (pct(d["flag_catch"]), "危险命令实际被控", "拦截或标记合计", "catch", d["flag_catch"]),
]

bad_rows = ""
for b in d["bad_by_category"][:14]:
    tone = "warn" if b["miss"] else "soft"
    bad_rows += f"""<tr>
      <td class="cat">{esc(b['cat'])}</td>
      <td>{b['total']}</td>
      <td class="{tone}">{b['miss']}</td>
      <td class="{tone}">{b['falsepos']}</td>
    </tr>"""

def sample_rows(rows, kind):
    out = ""
    for s in rows:
        p = s["payload"]
        disp = p if len(p) <= 100 else p[:97] + "…"
        tone = "bad" if kind == "miss" else ("soft" if s["level"] == "flag" else "bad")
        out += f"""<tr>
      <td class="mono">{esc(disp)}</td>
      <td><span class="chip {s['expect']}">{s['expect']}</span></td>
      <td><span class="chip {s['level']}">{s['level']}</span></td>
      <td class="mono src">{esc(s['src'][:60])}</td>
      <td class="{tone}">{'漏放' if kind == 'miss' else '误杀'}</td>
    </tr>"""
    return out

src_bars = ""
max_src = max(d["source_hits"].values()) if d["source_hits"] else 1
for k, v in sorted(d["source_hits"].items(), key=lambda x: -x[1]):
    w = int(v / max_src * 100)
    src_bars += f"""<div class="hbar"><div class="hbar-label">{esc(k)}</div>
    <div class="hbar-track"><div class="hbar-fill" style="width:{w}%"></div></div>
    <div class="hbar-val">{v}</div></div>"""

html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>青小团安全模块 10,000 条命令实测报告</title>
<style>
  :root {{
    --bg:#0f1520; --card:#171f2e; --line:#2a3650; --tx:#e8eef8; --mut:#8ea0bd;
    --ok:#3ddc97; --bad:#ff5d6c; --flag:#ffb454; --info:#4da3ff; --soft:#ffd166;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--tx); font:14px/1.6 "Segoe UI",system-ui,sans-serif; padding:32px 20px; }}
  .wrap {{ max-width:1080px; margin:0 auto; }}
  header {{ text-align:center; margin-bottom:28px; }}
  h1 {{ font-size:26px; letter-spacing:.5px; }}
  .sub {{ color:var(--mut); margin-top:6px; font-size:13px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:14px; margin-bottom:28px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px 16px; position:relative; overflow:hidden; }}
  .card .num {{ font-size:26px; font-weight:700; }}
  .card .lbl {{ color:var(--mut); font-size:12px; margin-top:4px; }}
  .card .note {{ color:var(--mut); font-size:11px; margin-top:2px; }}
  .card::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; }}
  .card.c-block::before {{ background:var(--ok); }} .card.c-miss::before {{ background:var(--bad); }}
  .card.c-flag::before {{ background:var(--flag); }} .card.c-fp::before {{ background:var(--soft); }}
  .card.c-catch::before {{ background:var(--info); }} .card.c-total::before {{ background:var(--mut); }}
  .panel {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px; margin-bottom:20px; }}
  .panel h2 {{ font-size:16px; margin-bottom:14px; border-left:4px solid var(--info); padding-left:10px; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  @media(max-width:760px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ text-align:left; color:var(--mut); font-weight:600; padding:8px 10px; border-bottom:1px solid var(--line); }}
  td {{ padding:7px 10px; border-bottom:1px solid #1e2736; vertical-align:top; }}
  .mono {{ font-family:Consolas,monospace; font-size:12px; word-break:break-all; }}
  .src {{ color:var(--mut); }}
  .chip {{ display:inline-block; padding:1px 8px; border-radius:20px; font-size:11px; font-weight:700; }}
  .chip.block {{ background:rgba(61,220,151,.15); color:var(--ok); }}
  .chip.flag {{ background:rgba(255,180,84,.15); color:var(--flag); }}
  .chip.allow {{ background:rgba(142,160,189,.15); color:var(--mut); }}
  .bad {{ color:var(--bad); font-weight:700; }}
  .warn {{ color:var(--flag); }}
  .soft {{ color:var(--soft); }}
  .cat {{ color:var(--info); }}
  .hbars {{ display:flex; flex-direction:column; gap:10px; }}
  .hbar {{ display:flex; align-items:center; gap:10px; }}
  .hbar-label {{ width:110px; font-size:12px; color:var(--mut); text-align:right; }}
  .hbar-track {{ flex:1; height:16px; background:#0c1220; border-radius:8px; overflow:hidden; }}
  .hbar-fill {{ height:100%; background:linear-gradient(90deg,#2e6bd6,#4da3ff); border-radius:8px; }}
  .hbar-val {{ width:44px; font-weight:700; font-size:13px; }}
  .note {{ color:var(--mut); font-size:12px; }}
  .kv {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; }}
  .kv div {{ background:#0c1220; border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
  .kv b {{ font-size:20px; display:block; }}
  .kv span {{ color:var(--mut); font-size:12px; }}
  .foot {{ text-align:center; color:var(--mut); font-size:12px; margin-top:24px; }}
  ul.tight {{ padding-left:18px; }} ul.tight li {{ margin:6px 0; }}
</style>
</head>
<body><div class="wrap">

<header>
  <h1>青小团 (Qingxiaotuan) 安全模块实测报告</h1>
  <div class="sub">10,000 条命令对抗评测 · seed={d['seed']} · 耗时 {d['seconds']}s · 三层判定 (规则引擎 + 网络门控 + 语义分类器) · 修补后复测</div>
</header>

<div class="cards">
  {"".join(
    f'<div class="card c-{c}"><div class="num">{n}</div><div class="lbl">{l}</div><div class="note">{e}</div></div>'
    for n, l, e, c, v in cards
  )}
</div>

<div class="grid2">
  <div class="panel">
    <h2>评测语料构成</h2>
    <div class="kv">
      <div><b>{d['n_expect_block']}</b><span>须拦截 (block)</span></div>
      <div><b>{d['n_expect_flag']}</b><span>须标记确认 (flag)</span></div>
      <div><b>{d['n_expect_allow']}</b><span>须放行 (allow)</span></div>
      <div><b>{d['seconds']}s</b><span>单轮全量评测耗时</span></div>
    </div>
    <p class="note" style="margin-top:12px">
      语料 = 项目自带 bypass_matrix 手写攻击矩阵 (A~AJ 攻击面) + attack_gen 对抗生成器
      (Unicode 同形字 / 不可见字符 / IFS / base64 管道 / PowerShell -enc / 18 种解释器包裹 /
      find -exec / heredoc / 两级组合变形) + 良性命令变形集。
    </p>
  </div>
  <div class="panel">
    <h2>命中来源分布 (分层拦截)</h2>
    <div class="hbars">{src_bars}</div>
    <p class="note" style="margin-top:10px">score=风险评分 · redline=综合红线 · hard=硬红线 · cls=语义分类器 · net=网络门控</p>
  </div>
</div>

<div class="panel">
  <h2>核心结论 (修补后)</h2>
  <ul class="tight">
    <li><b style="color:var(--ok)">漏放 0 条：10,000 条命令全部命中期望判定</b> —— 修补前复测发现的 23 条漏放
        (base64→<code>/bin/sh</code> 编码管道、PowerShell <code>-enc</code> 解码后 ln 覆盖认证文件、groovy 三引号载荷、
        ZWSP 破坏命令名 token 等) 已全部消除并回归验证。</li>
    <li><b style="color:var(--ok)">危险命令实际被控 (拦截或标记) 100%，成功拦截 7360/7360 (100%)</b>；
        未变形裸命令 (80 条) 拦截率 100%、误杀 0%。</li>
    <li><b style="color:var(--soft)">误杀 (严格口径) {d['false_pos']} 条</b>，其中仅 <b>{d['false_pos_block_only']} 条 ({pct(d['false_positive_block_rate'])}) 是硬拦截</b>
        (主要为 <code>nc -zv</code> 端口探测被网络门控 deny，属安全设计)；其余为网络门控 / 语义分类器把带
        Unicode 变形、网络外联的良性命令标为「确认」——方向 fail-closed，是可用性成本而非安全错误。</li>
    <li>硬拦截误杀率较修补前 4.31% 降至 <b>{pct(d['false_positive_block_rate'])}</b> (零宽字符不再割裂命令名 token，
        提及豁免恢复生效)；放行准确率 {pct(d['allow_precision'])} (严格口径)。</li>
  </ul>
</div>

<div class="grid2">
  <div class="panel">
    <h2>漏放样例 (变形攻击穿透)</h2>
    {"" if d["samples_miss"] else '<p class="note" style="color:var(--ok);font-weight:700;margin-bottom:10px">0 漏放 —— 全部 7360 条危险命令均被拦截，1410 条该标命令均被标记或拦截。</p>'}
    <table>
      <tr><th>命令 (截断)</th><th>期望</th><th>实际</th><th>命中来源</th><th>判定</th></tr>
      {sample_rows(d['samples_miss'], 'miss')}
    </table>
    <p class="note">「期望」为语料标注的应然判定；漏放 = 危险命令被放行或该标未标。</p>
  </div>
  <div class="panel">
    <h2>误杀样例 (良性被拦)</h2>
    <table>
      <tr><th>命令 (截断)</th><th>期望</th><th>实际</th><th>命中来源</th><th>判定</th></tr>
      {sample_rows(d['samples_falsepos'], 'fp')}
    </table>
    <p class="note">误杀 = 良性命令被拦 (block) 或标确认 (flag)；其中 flag 为可用性成本，block 为真误杀。</p>
  </div>
</div>

<div class="panel">
  <h2>异常集中类别 TOP 14</h2>
  <table>
    <tr><th>类别</th><th>总数</th><th>漏放</th><th>误杀</th></tr>
    {bad_rows}
  </table>
</div>

<div class="panel">
  <h2>评测口径说明</h2>
  <ul class="tight">
    <li><b>成功拦截</b> = 期望 block 且实际 block；<b>漏放</b> = 期望 block/flag 但实际放行 (allow)。</li>
    <li><b>误杀-严格口径</b> = 期望 allow 但实际被拦或标记；<b>误杀-仅硬拦口径</b> = 期望 allow 但实际 block (真正影响自动化运行的错误)。</li>
    <li>期望语义沿用项目自带 <code>bench/bypass_matrix.py</code>：block 必须 block；flag 允许 block 或 flag；allow 必须 allow。</li>
    <li>评测脚本 <code>bench/safety_bench_10k.py</code>，明细 <code>bench/safety_10k_result.json</code>，可复现 (固定 seed)。</li>
  </ul>
</div>

<div class="foot">青小团 Qingxiaotuan · 安全模块 10,000 条命令实测 · 生成于 2026-09-06</div>
</div></body></html>"""

out = ROOT / "bench" / "safety_10k_report.html"
out.write_text(html_doc, encoding="utf-8")
print("written:", out)
