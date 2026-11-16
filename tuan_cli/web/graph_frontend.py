# -*- coding: utf-8 -*-
"""数据流图工作台 (阶段 13) —— 独立三栏前端页面。

服务路径 ``/web/graph`` (见 server.py)。纯内联 HTML/CSS/JS, 零 CDN, 断网可用;
消费既有 ``/api/graph/{list,get,save,validate,run}`` 后端契约。三栏布局:

  左: 节点类型面板 (text/identity/concat/llm_call/codeanim)
  中: 画布 (可拖拽节点、连边、选中/删除)
  右: 结果面板 (逐节点输出 + 图运行日志 + 媒体预览/导出)

**fail-closed**: 运行时任一节点失败 → 右侧红条显示首个失败, 不假装成功。
"""

GRAPH_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>青小团 · 数据流图工作台</title>
<style>
:root {
  --bg:#0d1117; --panel:#161b22; --panel2:#1f2630; --line:#2b3440;
  --text:#e6edf3; --muted:#8b98a5; --accent:#4f9cff; --accent2:#3fb950;
  --danger:#f85149; --warn:#d29922;
}
* { box-sizing:border-box; }
body { margin:0; font-family:"Segoe UI",system-ui,sans-serif; background:var(--bg);
  color:var(--text); height:100vh; display:flex; flex-direction:column; }
header { padding:10px 16px; background:var(--panel); border-bottom:1px solid var(--line);
  display:flex; align-items:center; gap:12px; }
header h1 { font-size:15px; margin:0; font-weight:600; }
header .sp { flex:1; }
header input { background:var(--panel2); border:1px solid var(--line); color:var(--text);
  padding:6px 10px; border-radius:6px; font-size:13px; width:180px; }
button { background:var(--panel2); color:var(--text); border:1px solid var(--line);
  padding:6px 12px; border-radius:6px; cursor:pointer; font-size:13px; }
button:hover { border-color:var(--accent); }
button.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
button.danger { background:transparent; color:var(--danger); border-color:var(--danger); }
main { flex:1; display:flex; min-height:0; }
aside { width:200px; background:var(--panel); border-right:1px solid var(--line);
  padding:12px; overflow:auto; }
aside h3 { font-size:12px; color:var(--muted); text-transform:uppercase; margin:0 0 8px; }
.palette-item { background:var(--panel2); border:1px solid var(--line); border-radius:6px;
  padding:8px 10px; margin-bottom:6px; cursor:grab; font-size:13px; }
.palette-item:hover { border-color:var(--accent); }
.palette-item small { display:block; color:var(--muted); font-size:11px; margin-top:2px; }
#canvas { flex:1; position:relative; background:
  radial-gradient(circle, #1c2430 1px, transparent 1px) 0 0/24px 24px, var(--bg); overflow:hidden; }
.node { position:absolute; width:200px; background:var(--panel); border:1px solid var(--line);
  border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,.4); }
.node.sel { border-color:var(--accent); }
.node.ok { border-color:#2ecc71; box-shadow:0 0 0 1px #2ecc71 inset; }
.node.failed { border-color:var(--danger); box-shadow:0 0 0 1px var(--danger) inset; }
.node .hd { padding:8px 10px; font-size:13px; font-weight:600; display:flex;
  justify-content:space-between; align-items:center; }
.node .hd .del { color:var(--muted); cursor:pointer; font-size:12px; }
.node .hd .del:hover { color:var(--danger); }
.node .bd { padding:6px 10px 10px; }
.node .bd label { font-size:11px; color:var(--muted); display:block; margin:6px 0 3px; }
.node .bd input, .node .bd select, .node .bd textarea { width:100%; background:var(--panel2);
  border:1px solid var(--line); color:var(--text); border-radius:4px; padding:4px 6px;
  font-size:12px; }
.node .bd textarea { resize:vertical; min-height:40px; font-family:monospace; }
.node .ports { display:flex; justify-content:space-between; padding:2px 10px 8px; }
.port { font-size:10px; color:var(--accent2); background:rgba(63,185,80,.12);
  border:1px solid rgba(63,185,80,.4); padding:1px 6px; border-radius:8px;
  cursor:crosshair; user-select:none; }
.port.in { color:var(--accent); background:rgba(79,156,255,.12); border-color:rgba(79,156,255,.4); }
.port.lk { border-style:dashed; border-color:var(--accent); }
.edge-x { fill:#fff; stroke:var(--danger); stroke-width:1; cursor:pointer; pointer-events:auto; }
.edge-x:hover { fill:var(--danger); }
#wireLine { stroke:var(--accent2); stroke-width:2; stroke-dasharray:6 4; fill:none; }
#ghost { position:fixed; width:18px; height:18px; border-radius:50%; background:var(--accent2);
  pointer-events:none; z-index:99; display:none; box-shadow:0 0 10px rgba(63,185,80,.9); }
#results { width:320px; background:var(--panel); border-left:1px solid var(--line);
  padding:12px; overflow:auto; }
#results h3 { font-size:12px; color:var(--muted); text-transform:uppercase; margin:0 0 8px; }
.log-item { font-size:12px; padding:4px 8px; border-left:3px solid var(--muted);
  margin-bottom:4px; background:var(--panel2); border-radius:0 4px 4px 0; }
.log-item.ok { border-color:var(--accent2); }
.log-item.failed { border-color:var(--danger); color:var(--danger); }
.node-out { font-size:12px; background:var(--panel2); border-radius:6px; padding:6px 8px;
  margin-bottom:6px; word-break:break-all; }
.node-out img { max-width:100%; border-radius:4px; }
.media-preview { margin-top:8px; }
.media-preview video, .media-preview img { max-width:100%; border-radius:6px; }
.bar { font-size:12px; padding:6px 10px; border-radius:6px; margin-bottom:8px; }
.bar.ok { background:rgba(63,185,80,.15); color:var(--accent2); }
.bar.err { background:rgba(248,81,73,.15); color:var(--danger); }
.muted { color:var(--muted); font-size:12px; }
.dl { color:var(--accent2); text-decoration:none; border:1px solid rgba(63,185,80,.4);
  padding:5px 10px; border-radius:6px; background:rgba(63,185,80,.08); }
.dl:hover { border-color:var(--accent2); background:rgba(63,185,80,.16); }
</style>
</head>
<body>
<header>
  <h1>数据流图工作台</h1>
  <input id="gname" placeholder="图名称 (如 demo)" value="demo">
  <button id="saveBtn" class="primary">保存</button>
  <button id="runBtn" class="primary">运行</button>
  <button id="validateBtn">校验</button>
  <button id="clearBtn" class="danger">清空</button>
  <div class="sp"></div>
  <button id="presetBtn">载入示例</button>
  <select id="presetList"></select>
  <button id="loadBtn">加载图</button>
  <select id="graphList"></select>
  <button id="runsBtn">运行历史</button>
  <select id="runsList" style="max-width:220px;"></select>
  <div class="sp"></div>
  <button id="exportBtn">导出 JSON</button>
  <button id="importBtn">导入 JSON</button>
  <input type="file" id="importFile" accept="application/json,.json" style="display:none">
</header>
<main>
  <aside>
    <h3>节点类型</h3>
    <div class="palette-item" draggable="true" data-type="text">text
      <small>常量文本输出</small></div>
    <div class="palette-item" draggable="true" data-type="identity">identity
      <small>透传输入</small></div>
    <div class="palette-item" draggable="true" data-type="concat">concat
      <small>拼接多输入</small></div>
    <div class="palette-item" draggable="true" data-type="llm_call">llm_call
      <small>经 ModelGateway 直调模型</small></div>
    <div class="palette-item" draggable="true" data-type="codeanim">codeanim
      <small>出单帧 / 整片视频</small></div>
  </aside>
  <div id="canvas"></div>
  <div id="results">
    <h3>结果 / 日志</h3>
    <div id="bars"></div>
    <div id="logs"></div>
    <h3 style="margin-top:14px">节点输出</h3>
    <div id="nodeOuts"></div>
    <h3 style="margin-top:14px">媒体预览</h3>
    <div id="media" class="media-preview"></div>
    <div id="mediaBar" style="margin-top:8px;display:none;">
      <a id="downloadBtn" class="dl" download style="font-size:13px;">⬇ 下载产物</a>
    </div>
  </div>
</main>
<svg id="edgeLayer" style="position:absolute;inset:0;pointer-events:none;width:100%;height:100%;"></svg>
<div id="ghost"></div>
<script>
const $ = (s) => document.querySelector(s);
const canvas = $("#canvas");
const edgeLayer = $("#edgeLayer");
let nodes = {};       // id -> {id,type,x,y,params,inputs,outputs}
let edges = [];       // {src,srcPort,dst,dstPort}
let selected = null;
let nextId = 1;
let drag = null;
let pending = null;   // 待连边: {from:"out"/"in", node, port}
let lastMedia = null; // 最近一次产物 {url, name, type} → 供下载按钮
let nodeStatus = {};  // 节点运行状态: id -> "ok"|"failed" (阶段23, 按 logs 权威状态上色)

const NODE_META = {
  text:    {inputs:[], outputs:["out"], params:{content:"hello"}},
  identity:{inputs:["in"], outputs:["out"], params:{}},
  concat:  {inputs:["a","b"], outputs:["out"], params:{separator:" "}},
  llm_call:{inputs:[], outputs:["out","project_json"], params:{prompt:"Explain AI in one line", intent:"", provider_id:"", max_tokens:200}},
  codeanim:{inputs:["project_json"], outputs:["out"], params:{mode:"frame", t:0, fps:30, project_json:{width:640,height:360,fps:30,duration:2,nodes:[{type:"bg",start:0,end:2,props:{type:"solid"}}]}}},
};

function nid(){ return "n" + (nextId++); }
function esc(s){ return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function addNode(type, x, y){
  const meta = NODE_META[type]; const id = nid();
  nodes[id] = {id, type, x, y, params:{...(meta.params||{})}, inputs:[...meta.inputs], outputs:[...meta.outputs]};
  render();
}
function removeNode(id){
  edges = edges.filter(e => e.src !== id && e.dst !== id);
  delete nodes[id]; render();
}
function render(){
  // 清理: 已不在 nodes 里的旧 DOM 节点 (applyGraph/清空后避免幽灵节点残留)
  [...canvas.querySelectorAll(".node")].forEach(el => { if(!nodes[el.id]) el.remove(); });
  // nodes
  Object.values(nodes).forEach(n => {
    let el = document.getElementById(n.id);
    if(!el){
      el = document.createElement("div"); el.className="node"; el.id=n.id;
      el.addEventListener("mousedown", e => {
        if(e.target.closest(".del")) return;
        selected = n.id; render();
        const startX = e.clientX - n.x, startY = e.clientY - n.y;
        const mv = ev => { n.x = ev.clientX - startX; n.y = ev.clientY - startY; render(); };
        const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); };
        document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up);
      });
      canvas.appendChild(el);
    }
    el.style.left = n.x+"px"; el.style.top = n.y+"px";
    el.classList.toggle("sel", n.id === selected);
    // 阶段23: 按运行状态上色 (ok→绿 / failed→红)
    el.classList.toggle("ok", nodeStatus[n.id] === "ok");
    el.classList.toggle("failed", nodeStatus[n.id] === "failed");
    const meta = NODE_META[n.type];
    el.innerHTML = `<div class="hd">${esc(n.type)}<span class="del" data-del="${n.id}">✕</span></div>
      <div class="bd">${meta.inputs.map((p,i)=>`<label>in·${esc(p)}</label><input data-in="${i}" value="">`).join("")}
      ${bodyFor(n)}</div>
      <div class="ports">${meta.inputs.map(p=>`<span class="port in" data-node="${esc(n.id)}" data-port="${esc(p)}" data-dir="in">${esc(p)}</span>`).join("")}
      ${meta.outputs.map(p=>`<span class="port" data-node="${esc(n.id)}" data-port="${esc(p)}" data-dir="out">${esc(p)}</span>`).join("")}</div>`;
    el.querySelectorAll("[data-del]").forEach(b => b.onclick = () => removeNode(b.dataset.del));
    bindBody(n, el);
    bindPorts(n, el);
  });
  // edges (data-idx 携带该边在 edges 中的真实下标, 供"删除连线"用)
  edgeLayer.innerHTML = edges.map((e,i) => {
    const a = portPos(e.src, e.srcPort, "out"), b = portPos(e.dst, e.dstPort, "in");
    if(!a || !b) return "";
    const mx=(a.x+b.x)/2;
    return `<path d="M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}" fill="none" stroke="rgba(79,156,255,.7)" stroke-width="2"/>
      <circle class="edge-x" cx="${(a.x+b.x)/2}" cy="${(a.y+b.y)/2}" r="7" data-idx="${i}">
        <title>删除连线</title></circle>`;
  }).join("") + `<path id="wireLine" d=""></path>`;
  edgeLayer.querySelectorAll("[data-idx]").forEach(c => c.addEventListener("mousedown", ev => {
    ev.stopPropagation();
    edges.splice(Number(c.dataset.idx), 1); render();
  }));
}
function bodyFor(n){
  const p = n.params || {};
  switch(n.type){
    case "text": return `<label>content</label><input data-param="content" value="${esc(p.content||"")}">`;
    case "concat": return `<label>separator</label><input data-param="separator" value="${esc(p.separator||"")}">`;
    case "llm_call": return `<label>prompt</label><textarea data-param="prompt">${esc(p.prompt||"")}</textarea>
      <label>intent</label><input data-param="intent" value="${esc(p.intent||"")}">
      <label>provider_id</label><input data-param="provider_id" list="providerOptions" value="${esc(p.provider_id||"")}">
      <datalist id="providerOptions"></datalist>
      <label>max_tokens</label><input data-param="max_tokens" value="${esc(p.max_tokens||"")}">`;
    case "codeanim": return `<label>mode</label><select data-param="mode">
      <option value="frame" ${p.mode==="frame"?"selected":""}>单帧</option>
      <option value="render" ${p.mode==="render"?"selected":""}>整片</option></select>
      <label>t</label><input data-param="t" value="${esc(p.t??"")}">
      <label>fps</label><input data-param="fps" value="${esc(p.fps??"")}">
      <label>project_json (JSON)</label><textarea data-param="project_json" data-json="1">${esc(JSON.stringify(p.project_json||{width:640,height:360,fps:30,duration:2,nodes:[{type:"bg",start:0,end:2,props:{type:"solid"}}]}))}</textarea>`;
    default: return "";
  }
}
function bindBody(n, el){
  el.querySelectorAll("[data-param]").forEach(inp => {
    inp.oninput = () => {
      let v = inp.value;
      if(inp.dataset.json){ try{ v = JSON.parse(v); }catch(e){ return; } }
      n.params[inp.dataset.param] = v;
    };
  });
  el.querySelectorAll("[data-in]").forEach(inp => {
    inp.oninput = () => { /* input ports read from edges at runtime; free-form text ignored */ };
  });
}
function portPos(id, port, dir){
  const n = nodes[id]; if(!n) return null;
  const el = document.getElementById(id); if(!el) return null;
  const ports = el.querySelectorAll(".port");
  let idx = -1;
  if(dir==="out"){ const outs=[...el.querySelectorAll(".port:not(.in)")]; idx = outs.findIndex(x=>x.textContent===port); }
  else { const ins=[...el.querySelectorAll(".port.in")]; idx = ins.findIndex(x=>x.textContent===port); }
  const r = el.getBoundingClientRect(), cr = canvas.getBoundingClientRect();
  const base = ports[idx] ? ports[idx].getBoundingClientRect() : null;
  if(base){ return {x: base.left-cr.left+base.width/2, y: base.top-cr.top+base.height/2}; }
  return {x: n.x+ (dir==="out"?200:0), y: n.y+30};
}

// ---- 端口连边: 按住输出/输入端口拖到对端端口, 松手即连 ----
const ghost = $("#ghost");
function bindPorts(n, el){
  el.querySelectorAll(".port").forEach(sp => {
    sp.addEventListener("mousedown", e => {
      e.stopPropagation();
      pending = {from: sp.dataset.dir, node: n.id, port: sp.dataset.port};
      ghost.style.display = "block";
      ghost.style.left = (e.clientX-9)+"px"; ghost.style.top = (e.clientY-9)+"px";
    });
  });
}
function dropTarget(e){
  const el = e.target && e.target.closest ? e.target.closest(".port") : null;
  if(!el) return null;
  return {from: el.dataset.dir, node: el.dataset.node, port: el.dataset.port};
}
function wire(a, b){
  if(!a || !b || a.from === b.from || a.node === b.node) return false;
  const out = a.from === "out" ? a : b, inn = a.from === "out" ? b : a;
  if(edges.some(x => x.src===out.node && x.srcPort===out.port && x.dst===inn.node && x.dstPort===inn.port)) return false;
  edges.push({src: out.node, srcPort: out.port, dst: inn.node, dstPort: inn.port});
  bar(`已连边: ${out.node}.${out.port} → ${inn.node}.${inn.port}`, true);
  render();
  return true;
}
document.addEventListener("mousemove", e => {
  if(!pending) return;
  ghost.style.left = (e.clientX-9)+"px"; ghost.style.top = (e.clientY-9)+"px";
  // 实时预览待连边 (虚线跟随光标)
  const start = portPos(pending.node, pending.port, pending.from);
  if(start){
    const cr = canvas.getBoundingClientRect();
    const d = `M${start.x},${start.y} L${e.clientX-cr.left},${e.clientY-cr.top}`;
    document.querySelector("#wireLine").setAttribute("d", d);
  }
});
document.addEventListener("mouseup", e => {
  if(!pending) return;
  const src = pending; pending = null;
  ghost.style.display = "none";
  const wl = document.querySelector("#wireLine"); if(wl) wl.setAttribute("d", "");
  wire(src, dropTarget(e));
});
document.addEventListener("keydown", e => {
  if(e.key !== "Escape" || !pending) return;
  pending = null; ghost.style.display = "none";
  const wl = document.querySelector("#wireLine"); if(wl) wl.setAttribute("d", "");
  render();
});

// ---- 拖放创建 ----
document.querySelectorAll(".palette-item").forEach(item => {
  item.addEventListener("dragstart", e => e.dataTransfer.setData("text/plain", item.dataset.type));
});
canvas.addEventListener("dragover", e => e.preventDefault());
canvas.addEventListener("drop", e => {
  e.preventDefault();
  const type = e.dataTransfer.getData("text/plain");
  const r = canvas.getBoundingClientRect();
  addNode(type, e.clientX - r.left - 20, e.clientY - r.top - 10);
});

// ---- 图序列化 (字段名须与 graph_api._from_dict_with_cache 的契约一致) ----
function collectGraph(){
  return { name: $("#gname").value || "demo", nodes: Object.values(nodes).map(n => ({
      node_id:n.id, ntype:n.type, params:n.params,
      inputs:(NODE_META[n.type].inputs||[]).map(p => ({name:p, ptype:"any"})),
      outputs:(NODE_META[n.type].outputs||[]).map(p => ({name:p, ptype:"any"})),
    })),
    edges: edges.map(e => ({src_node:e.src, src_port:e.srcPort, dst_node:e.dst, dst_port:e.dstPort})),
  };
}
async function api(path, opts){ const r = await fetch(path, opts); return r.json(); }

$("#saveBtn").onclick = async () => {
  const id = $("#gname").value.trim() || "demo";
  const data = collectGraph();
  const res = await api("/api/graph/save", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({id, data})});
  bar(res.ok ? "已保存 "+id : "保存失败: "+(res.error||""), res.ok);
  refreshList();
};
$("#validateBtn").onclick = async () => {
  const id = $("#gname").value.trim() || "demo";
  const res = await api("/api/graph/get?id="+encodeURIComponent(id));
  if(!res.ok){ bar("未找到图 "+id, false); return; }
  const v = await api("/api/graph/validate?id="+encodeURIComponent(id));
  bar(v.ok && v.valid ? "图合法" : "校验失败: "+(v.error||""), v.ok && v.valid);
};
$("#runBtn").onclick = async () => {
  const data = collectGraph();
  $("#logs").innerHTML=""; $("#nodeOuts").innerHTML=""; $("#media").innerHTML="";
  nodeStatus = {};  // 阶段23: 运行前清空节点状态
  const res = await api("/api/graph/run", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({data, graph_id: $("#gname").value.trim() || "demo",
                          name: $("#gname").value.trim() || "demo"})});
  // 阶段23: 按 logs 权威状态给节点上色 (ok→绿 / failed→红)
  (res.logs||[]).forEach(l => { if(l.node_id && l.status) nodeStatus[l.node_id] = (l.status==="ok"||l.status==="completed") ? "ok" : (l.status==="failed" ? "failed" : ""); });
  render();
  if(!res.ok){ bar("运行失败 (fail-closed): "+(res.error||""), false); showLog({node_id:"-",status:"failed",message:res.error}); refreshRuns(); return; }
  bar("运行成功 · "+Object.keys(res.results||{}).length+" 节点", true);
  refreshRuns();
  (res.logs||[]).forEach(showLog);
  Object.entries(res.results||{}).forEach(([k,v]) => showOut(k,v));
  // 找 codeanim 整片产物 → 预览 (用 media_rel 拼 /api/media 以便 HTTP 回放)
  lastMedia = null;
  Object.entries(res.results||{}).forEach(([k,v]) => {
    if(v && (v.media_rel || v.out_path || (v.png_data_url&&v.png_data_url.startsWith("data:")))){
      const isVid = v.media_rel ? /\\.(mp4|webm)$/i.test(v.media_rel) : /\\.(mp4|webm)$/i.test(String(v.out_path||""));
      let url = null, name = k+".bin", ctype = "application/octet-stream";
      if(v.media_rel){
        url = "/api/media?path="+encodeURIComponent(v.media_rel);
        name = v.media_rel.split(/[\\/]/).pop();
        ctype = isVid ? "video/mp4" : "image/png";
        $("#media").innerHTML += isVid
          ? `<video controls src="${url}"></video>`
          : `<img src="${url}">`;
      } else if(isVid){
        $("#media").innerHTML += `<video controls src="${esc(v.out_path)}"></video>`;
        url = v.out_path; name = k+".mp4"; ctype = "video/mp4";
      } else {
        $("#media").innerHTML += `<img src="${esc(v.png_data_url||v.out_path)}">`;
        url = v.out_path || v.png_data_url; name = k+".png"; ctype = "image/png";
      }
      if(url) lastMedia = {url, name, ctype};
    }
  });
  updateMediaBar();
};
function updateMediaBar(){
  const barEl = $("#mediaBar"); const btn = $("#downloadBtn");
  if(lastMedia){ barEl.style.display="block"; btn.href = lastMedia.url; btn.download = lastMedia.name; btn.textContent = "⬇ 下载 "+lastMedia.name; }
  else { barEl.style.display="none"; btn.removeAttribute("href"); }
}
$("#clearBtn").onclick = () => { nodes={}; edges=[]; nextId=1; render(); };
$("#loadBtn").onclick = async () => {
  const id = $("#graphList").value; if(!id) return;
  const res = await api("/api/graph/get?id="+encodeURIComponent(id));
  if(!res.ok){ bar("未找到图 "+id, false); return; }
  applyGraph(id, res.graph);
};
$("#presetBtn").onclick = async () => {
  const id = $("#presetList").value; if(!id) return;
  const res = await api("/api/graph/preset?id="+encodeURIComponent(id));
  if(!res.ok){ bar("未找到示例 "+id+": "+(res.error||""), false); return; }
  const pre = res.preset || {};
  applyGraph(id, {name: pre.name || id, data: pre.data || {}});
  bar(`已载入示例「${pre.name || id}」· 点「运行」即可出结果`, true);
  // 载入示例 → 自动落盘为自定义图 (presets→自定义图持久化闭环, 供「加载图」复用)
  const saved = await api("/api/graph/save", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({id, data: collectGraph()})});
  if(saved.ok){ refreshList(); bar(`已载入示例「${pre.name || id}」· 已同步保存为自定义图 ${id}`, true); }
  else { bar(`已载入示例「${pre.name || id}」· 自动保存失败: ${saved.error||""}`, false); }
};
$("#runsBtn").onclick = async () => {
  const rid = $("#runsList").value; if(!rid) return;
  const res = await api("/api/graph/runlog?id="+encodeURIComponent(rid));
  if(!res.ok){ bar("未找到运行记录 "+rid, false); return; }
  const rec = res.run || {};
  const data = rec.data || {nodes:[],edges:[]};
  const gid = rec.graph_id || "replay";
  applyGraph(gid, {name: rec.name || gid, data});
  bar(`已载入运行记录 ${rec.ok?"✓":"✗"} · ${rec.name||gid} (${data.nodes?.length||0}节点) · 点「运行」复现`, true);
};
// 把序列化图数据填进画布 (载入图 / 载入示例共用)
function applyGraph(id, graph){
  $("#gname").value = id;
  const data = graph.data || graph || {};
  nodes={}; edges=[]; nextId=1;
  (data.nodes||[]).forEach(n => { nodes[n.node_id] = {id:n.node_id,type:n.ntype,x:40+(nextId%5)*240,y:60+Math.floor(nextId/5)*90,params:n.params||{},inputs:(n.inputs||[]).map(p=>p.name),outputs:(n.outputs||[]).map(p=>p.name)}; nextId++; });
  edges = (data.edges||[]).map(e => ({
    src: e.src_node!==undefined? e.src_node : e.src,
    srcPort: e.src_port!==undefined? e.src_port : e.srcPort,
    dst: e.dst_node!==undefined? e.dst_node : e.dst,
    dstPort: e.dst_port!==undefined? e.dst_port : e.dstPort,
  }));
  autoLayout();  // 阶段24: 按 DAG 拓扑分层排列, 避免堆叠
  render();
}
// 阶段24: 自动布局 — 按拓扑深度分层 (左→右), 同层内纵向排布
function autoLayout(){
  const ids = Object.keys(nodes); if(!ids.length) return;
  const level = {}; ids.forEach(id=>level[id]=0);
  // Kahn 求层深: dst 层 = max(dst 层, src 层+1)
  const indeg = {}; ids.forEach(id=>indeg[id]=0);
  const adj = {}; ids.forEach(id=>adj[id]=[]);
  edges.forEach(e => { if(adj[e.src] && level[e.dst]!==undefined){ adj[e.src].push(e.dst); indeg[e.dst]=(indeg[e.dst]||0)+1; } });
  let q = ids.filter(id => (indeg[id]||0)===0);
  while(q.length){
    const nq=[];
    q.forEach(id => (adj[id]||[]).forEach(dst => {
      level[dst] = Math.max(level[dst]||0, (level[id]||0)+1);
      indeg[dst]--; if(indeg[dst]===0) nq.push(dst);
    }));
    q=nq;
  }
  // 按层分组
  const byLevel = {}; ids.forEach(id => { const L=level[id]||0; (byLevel[L]=byLevel[L]||[]).push(id); });
  const gapX=230, gapY=80, padX=40, padY=40;
  const maxRows = Math.max(...Object.values(byLevel).map(a=>a.length), 1);
  Object.keys(byLevel).forEach(L => {
    const row = byLevel[L];
    row.forEach((id, i) => {
      nodes[id].x = padX + (+L)*gapX;
      nodes[id].y = padY + i*gapY + (maxRows-row.length)*gapY/2;
    });
  });
}
async function refreshList(){
  const res = await api("/api/graph/list");
  const sel = $("#graphList"); sel.innerHTML = "";
  (res.graphs||[]).forEach(g => { const o=document.createElement("option"); o.value=g.id; o.textContent=g.name+" ("+g.nodes+"节点)"; sel.appendChild(o); });
}
async function refreshPresets(){
  const res = await api("/api/graph/presets");
  const sel = $("#presetList"); sel.innerHTML = "";
  (res.presets||[]).forEach(p => { const o=document.createElement("option");
    o.value=p.id; o.textContent=p.name+" ("+p.nodes+"节点/"+p.edges+"连线)"; sel.appendChild(o); });
}
async function refreshRuns(){
  const res = await api("/api/graph/runs");
  const sel = $("#runsList"); sel.innerHTML = "";
  (res.runs||[]).slice(0,20).forEach(r => {
    const o=document.createElement("option"); o.value=r.run_id;
    const t = new Date(r.ts||0); const hm = `${String(t.getHours()).padStart(2,"0")}:${String(t.getMinutes()).padStart(2,"0")}`;
    o.textContent = `${hm} · ${r.ok?"✓":"✗"} ${r.name||r.graph_id||"未命名"} (${Object.keys(r.summary?.node_states||{}).length||"?"}节点)`;
    sel.appendChild(o);
  });
}
// 阶段22: 拉取本机已启动的本地模型网关, 填充 llm_call 的 provider_id 下拉提示
async function refreshProviders(){
  try{
    const res = await api("/api/graph/models");
    const dl = $("#providerOptions"); if(!dl) return;
    dl.innerHTML = "";
    (res.providers||[]).forEach(p => { const o=document.createElement("option"); o.value=p.provider; o.textContent=p.label; dl.appendChild(o); });
  }catch(e){ /* 面板不可用时静默 */ }
}
function bar(msg, ok){ $("#bars").innerHTML = `<div class="bar ${ok?"ok":"err"}">${esc(msg)}</div>`; }
// ---- 图导出/导入 JSON (阶段21): 工作台图可移植, 与 collectGraph 契约一致 ----
$("#exportBtn").onclick = () => {
  const data = collectGraph();
  data.name = $("#gname").value || "demo";
  const blob = new Blob([JSON.stringify(data, null, 2)], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = ($("#gname").value || "graph") + ".json";
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
  bar("已导出 "+a.download+" (JSON)", true);
};
$("#importBtn").onclick = () => $("#importFile").click();
$("#importFile").onchange = async (e) => {
  const f = e.target.files && e.target.files[0];
  if(!f) return;
  try{
    const text = await f.text();
    const data = JSON.parse(text);
    if(!data || !Array.isArray(data.nodes) || !Array.isArray(data.edges)) throw new Error("缺 nodes/edges 数组");
    applyGraph(data.name || "imported", {name: data.name || "imported", data});
    bar("已导入 JSON: "+(data.name||"imported")+" ("+data.nodes.length+"节点/"+(data.edges||[]).length+"连线) · 点「保存」落盘", true);
  }catch(err){ bar("导入失败: "+err.message, false); }
  e.target.value = "";
};
function showLog(l){ $("#logs").innerHTML += `<div class="log-item ${l.status==="ok"?"ok":(l.status==="failed"?"failed":"")}">${esc(l.node_id)}·${esc(l.status)}${l.message?": "+esc(l.message):""}</div>`; }
function showOut(k,v){
  let txt = typeof v==="string"?v:(v && v.text? v.text : JSON.stringify(v).slice(0,300));
  $("#nodeOuts").innerHTML += `<div class="node-out"><b>${esc(k)}</b><br>${esc(txt)}</div>`;
}
// 初始: 放一个 demo 节点
addNode("text", 40, 60);
addNode("codeanim", 40, 260);
refreshList();
refreshPresets();
refreshRuns();
refreshProviders();
</script>
</body>
</html>
"""

__all__ = ["GRAPH_HTML"]
