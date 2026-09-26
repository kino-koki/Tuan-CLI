# -*- coding: utf-8 -*-
"""Web 前端 (内联 HTML/CSS/JS, 无外链 CDN, 断网可用)。

DeepSeek-harness 原版视觉语言: 近黑蓝灰底 + DeepSeek 蓝紫 accent (#4D6BFE)、
紧凑密度、细边框圆角、左栏会话 + 中央对话流 + 工具调用折叠 + 流式 SSE。
保留既有功能: 会话持久化/上传(拖拽)/Markdown 渲染/安全面板/主题切换/导出/快捷键。

v0.2.017 重设计 (对齐 deepseek-ai/deepseek-harness web UI):
- 视觉: DSH 色板与间距体系、顶栏模型/模式徽标、composer 圆角框
- 交互: 会话删除按钮常显、模式徽标 (standard/yolo/plan 取自启动参数)、
  推理档位徽标、顶部品牌 "harness" 标签
"""
from __future__ import annotations

FRONTEND_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>青小团 · Web 工作台</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 64 64%27%3E%3Crect width=%2764%27 height=%2764%27 rx=%2714%27 fill=%27%234D6BFE%27/%3E%3Ctext x=%2732%27 y=%2744%27 font-size=%2734%27 text-anchor=%27middle%27 fill=%27white%27 font-family=%27sans-serif%27%3E青%3C/text%3E%3C/svg%3E">
<style>
  /* ===== DeepSeek-harness 色板 ===== */
  :root, [data-theme="dark"] {
    --bg:#0f1115; --panel:#15181d; --card:#1a1e26; --card2:#20242e;
    --border:#262b33; --border2:#313846;
    --text:#e6e8ec; --sub:#9aa3b2; --dim:#6b7484;
    --accent:#4D6BFE; --accent2:#6d86ff; --accent-dim:rgba(77,107,254,.14);
    --ok:#3fb68b; --warn:#d9a441; --err:#e5534b;
    --user:#3347b5; --user2:#4259c9;
    --mono:"JetBrains Mono","Cascadia Code",Consolas,"SFMono-Regular",monospace;
    --radius:10px;
  }
  [data-theme="light"] {
    --bg:#f4f5f7; --panel:#ffffff; --card:#ffffff; --card2:#f0f1f4;
    --border:#e2e4ea; --border2:#d3d7e0;
    --text:#1b1e27; --sub:#5a6272; --dim:#8b93a3;
    --accent:#4D6BFE; --accent2:#3a55d8; --accent-dim:rgba(77,107,254,.1);
    --ok:#1f9d6f; --warn:#c28a22; --err:#d6453d;
    --user:#4D6BFE; --user2:#3a55d8;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:"Segoe UI","Microsoft YaHei",system-ui,-apple-system,sans-serif;
       background:var(--bg);color:var(--text);height:100vh;display:flex;overflow:hidden;
       font-size:14px;line-height:1.6}
  ::-webkit-scrollbar{width:8px;height:8px}
  ::-webkit-scrollbar-thumb{background:var(--border2);border-radius:4px}
  ::-webkit-scrollbar-track{background:transparent}

  /* ===== 左栏 (DSH 侧边栏) ===== */
  #sidebar{width:264px;min-width:264px;background:var(--panel);border-right:1px solid var(--border);
           display:flex;flex-direction:column}
  .brand{display:flex;align-items:center;gap:8px;padding:16px 14px 10px;font-size:14px;font-weight:600}
  .brand .dot{width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent)}
  .brand .tag{margin-left:auto;font-size:10px;font-weight:500;color:var(--accent);
              background:var(--accent-dim);border:1px solid var(--border2);border-radius:20px;padding:1px 8px}
  #newbtn{margin:4px 12px 10px;padding:8px 12px;border:1px solid var(--border2);border-radius:8px;
          background:var(--card);color:var(--text);cursor:pointer;font-size:13px;text-align:left;transition:all .15s}
  #newbtn:hover{border-color:var(--accent);background:var(--accent-dim);color:var(--accent2)}
  .ws-label{padding:2px 14px;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim)}
  #ws-name{padding:2px 14px 8px;font-size:12px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #searchbox{margin:4px 12px 8px;padding:6px 10px;border:1px solid var(--border);border-radius:8px;
             background:var(--bg);color:var(--text);font-size:12.5px;width:calc(100% - 24px);outline:none;transition:border-color .15s}
  #searchbox:focus{border-color:var(--accent)}
  #searchbox::placeholder{color:var(--dim)}
  #sessions{flex:1;overflow-y:auto;padding:0 8px}
  .sess{display:flex;align-items:center;border-radius:8px;cursor:pointer;font-size:13px;color:var(--sub);margin-bottom:2px}
  .sess .t{flex:1;padding:8px 6px 8px 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sess .del{padding:8px 8px 8px 2px;color:var(--dim);opacity:.55;font-size:13px}
  .sess:hover{background:var(--card)}
  .sess:hover .del{opacity:1}
  .sess .del:hover{color:var(--err)}
  .sess.active{background:var(--accent-dim);color:var(--text)}
  .sess.active .t{color:var(--accent2)}
  #safety{display:none;margin:8px 10px 6px;padding:9px 11px;border:1px solid var(--border);border-radius:10px;
          background:var(--card);font-size:11px;color:var(--sub);line-height:1.7}
  #safety b{color:var(--text);font-weight:600}
  #safety .ok{color:var(--ok);font-weight:600}
  #sidebar .foot{padding:9px 14px 12px;font-size:10.5px;color:var(--dim);border-top:1px solid var(--border);word-break:break-all}

  /* ===== 主区 ===== */
  #main{flex:1;display:flex;flex-direction:column;min-width:0}
  #topbar{height:46px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px;
          padding:0 16px;font-size:12.5px;color:var(--sub);background:var(--panel)}
  #topbar .crumb{color:var(--dim);font-size:12px}
  #topbar .sp{flex:1}
  .chip{background:var(--card);border:1px solid var(--border);border-radius:20px;padding:2px 10px;
        font-size:11.5px;color:var(--sub);white-space:nowrap;font-family:var(--mono)}
  .chip b{color:var(--accent2);font-weight:600}
  .tb-btn{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:4px 10px;
          color:var(--sub);cursor:pointer;font-size:12px;transition:all .15s}
  .tb-btn:hover{background:var(--accent-dim);color:var(--accent2);border-color:var(--accent)}
  #t-model{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

  /* ===== 对话流 ===== */
  #msgs{flex:1;overflow-y:auto;padding:26px 7vw 12px}
  .msg{max-width:840px;margin:0 auto 22px;display:flex;flex-direction:column;gap:6px}
  .msg .meta{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim)}
  .msg .meta .who{font-weight:600;color:var(--sub)}
  .msg .meta .tm{font-size:11px;color:var(--dim)}
  .bubble{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
          padding:12px 15px;font-size:14px;line-height:1.7;word-break:break-word}
  .bubble p{margin:0 0 9px}
  .bubble p:last-child{margin-bottom:0}
  .bubble h1,.bubble h2,.bubble h3{margin:13px 0 7px;line-height:1.35;font-weight:600}
  .bubble h1{font-size:17px}.bubble h2{font-size:15.5px}.bubble h3{font-size:14.5px}
  .bubble ul,.bubble ol{margin:5px 0 9px;padding-left:22px}
  .bubble li{margin:2px 0}
  .bubble blockquote{border-left:3px solid var(--border2);margin:7px 0;padding:2px 13px;color:var(--sub)}
  .bubble code{font-family:var(--mono);font-size:12.5px;background:var(--card2);
               border:1px solid var(--border);border-radius:5px;padding:1px 5px}
  .bubble pre{background:#0d1017;border:1px solid var(--border);border-radius:8px;padding:11px 13px;
              overflow-x:auto;margin:9px 0;font-family:var(--mono);font-size:12.5px;line-height:1.55}
  [data-theme="light"] .bubble pre{background:#f0f1f4}
  .bubble pre code{background:none;border:none;padding:0}
  .bubble a{color:var(--accent2);text-decoration:none}
  .bubble a:hover{text-decoration:underline}
  .bubble hr{border:none;border-top:1px solid var(--border);margin:10px 0}
  .msg.user{align-items:flex-end}
  .msg.user .meta{flex-direction:row-reverse}
  .msg.user .bubble{background:linear-gradient(180deg,var(--user),var(--user2));
                    border-color:transparent;color:#fff}
  .msg.user .bubble code{background:rgba(255,255,255,.16);border-color:rgba(255,255,255,.22)}
  .msg.user .bubble pre{background:rgba(0,0,0,.28);border-color:rgba(255,255,255,.16)}

  /* 工具调用 (DSH 折叠块) */
  .tool{margin:8px 0 4px;background:var(--card2);border:1px solid var(--border);border-radius:8px;overflow:hidden}
  .tool-head{padding:6px 12px;font-family:var(--mono);font-size:12px;color:var(--accent2);cursor:pointer;
             display:flex;align-items:center;gap:8px;user-select:none}
  .tool-head .caret{transition:transform .15s;color:var(--dim);font-size:10px}
  .tool.open .caret{transform:rotate(90deg)}
  .tool-head .tname{font-weight:600}
  .tool-body{display:none;padding:0 12px 10px;font-family:var(--mono);font-size:12px;color:var(--sub);
             border-top:1px solid var(--border)}
  .tool.open .tool-body{display:block}
  .tool-body pre{white-space:pre-wrap;word-break:break-all;margin:6px 0;color:var(--text)}
  .tool-body .lbl{color:var(--dim);margin-top:8px;font-size:11px;letter-spacing:.05em}
  .tool-result{color:#c8d3e8}
  [data-theme="light"] .tool-result{color:#3a4659}

  /* ===== 输入区 ===== */
  #inputbar{border-top:1px solid var(--border);padding:14px 7vw 16px;background:var(--panel)}
  #composer{max-width:840px;margin:0 auto;background:var(--card);border:1px solid var(--border2);
            border-radius:12px;display:flex;align-items:flex-end;padding:10px 10px 10px 12px;
            box-shadow:0 1px 0 rgba(255,255,255,.02);transition:border-color .15s}
  #composer:focus-within{border-color:var(--accent)}
  #composer.dragover{border-color:var(--ok);background:var(--accent-dim)}
  #inp{flex:1;background:transparent;border:none;outline:none;color:var(--text);font-size:14px;
       resize:none;max-height:180px;font-family:inherit;line-height:1.55;padding:4px 6px}
  #send{margin-left:8px;padding:8px 20px;border:none;border-radius:9px;background:var(--accent);color:#fff;
        font-size:13px;cursor:pointer;font-weight:600;transition:background .15s}
  #send:hover{background:var(--accent2)}
  #send:disabled{opacity:.4;cursor:not-allowed}
  #stop{display:none;margin-left:8px;padding:8px 16px;border:1px solid var(--err);border-radius:9px;
        background:transparent;color:var(--err);font-size:13px;cursor:pointer}
  #hint{max-width:840px;margin:7px auto 0;font-size:11px;color:var(--dim)}
  #upload-btn{background:transparent;border:1px solid var(--border);border-radius:8px;padding:3px 9px;
              color:var(--sub);cursor:pointer;font-size:15px;margin-left:4px;line-height:1.2;transition:all .15s}
  #upload-btn:hover{background:var(--card2);color:var(--text);border-color:var(--accent)}
  #file-input{display:none}
  .file-tag{display:inline-flex;align-items:center;gap:4px;background:var(--card2);border:1px solid var(--border);
            border-radius:6px;padding:2px 8px;margin:4px 2px;font-size:12px;color:var(--sub)}
  .file-tag .name{max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .file-tag .remove{cursor:pointer;color:var(--err);font-size:14px}
  .file-tag img{height:32px;width:auto;border-radius:4px;object-fit:cover}
  .bubble .chat-img{max-width:320px;max-height:240px;border-radius:8px;margin:6px 0;cursor:pointer;transition:transform .15s}
  .bubble .chat-img:hover{transform:scale(1.02)}
  .bubble .img-grid{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
  .bubble .img-grid img{max-width:160px;max-height:120px;border-radius:6px;object-fit:cover;cursor:pointer;transition:transform .15s}
  .bubble .img-grid img:hover{transform:scale(1.05)}
  #lightbox{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:9999;justify-content:center;align-items:center;cursor:zoom-out}
  #lightbox.open{display:flex}
  #lightbox img{max-width:90vw;max-height:90vh;border-radius:8px;box-shadow:0 4px 40px rgba(0,0,0,.6)}
  .stream-cursor{display:inline-block;width:8px;height:15px;background:var(--accent);vertical-align:-2px;animation:blink 1s step-start infinite}
  @keyframes blink{50%{opacity:0}}
  @media (max-width:760px){
    #sidebar{width:200px;min-width:200px}
    #msgs,#inputbar{padding-left:4vw;padding-right:4vw}
    .chip{display:none}
  }
  @media (max-width:640px){
    #sidebar{width:132px;min-width:132px}
    .ws-label,#ws-name,#hint{display:none}
    #inp,#searchbox{font-size:16px}
    #msgs{padding-top:14px}
    .brand{padding:12px 10px 8px;font-size:13px}
    #newbtn{font-size:12px;padding:7px 10px}
  }
</style>
</head>
<body>
  <aside id="sidebar">
    <div class="brand"><span class="dot"></span>青小团<span class="tag">harness</span></div>
    <button id="newbtn">＋ 新建会话</button>
    <div class="ws-label">工作区</div>
    <div id="ws-name">…</div>
    <input id="searchbox" type="text" placeholder="搜索会话... (Ctrl+K)">
    <div id="sessions"></div>
    <div id="safety"></div>
    <div class="foot" id="sidefoot">…</div>
  </aside>
  <main id="main">
    <header id="topbar">
      <span id="t-model" class="chip" title="当前模型"><b>模型</b> …</span>
      <span id="t-mode" class="chip"><b>mode</b> standard</span>
      <span id="t-effort" class="chip"><b>effort</b> medium</span>
      <span class="sp"></span>
      <button class="tb-btn" id="btn-export" title="导出 Markdown (Ctrl+E)">导出</button>
      <button class="tb-btn" id="btn-theme" title="切换主题">主题</button>
      <span id="t-engine" class="chip">qingxiaotuan</span>
    </header>
    <div id="msgs"></div>
    <div id="inputbar">
      <div id="composer">
        <div id="file-area"></div>
        <textarea id="inp" rows="1" placeholder="输入消息，Enter 发送 · Shift+Enter 换行 · / 斜杠命令"></textarea>
        <input type="file" id="file-input" multiple accept="image/*,.txt,.md,.py,.js,.ts,.json,.yaml,.yml,.csv,.log">
        <button id="upload-btn" title="上传文件">＋</button>
        <button id="send">发送</button>
        <button id="stop">■ 停止</button>
      </div>
      <div id="hint">本地运行 · 模型无关 · 安全优先 · /clear 清空 · Ctrl+E 导出 · Ctrl+N 新会话</div>
    </div>
  </main>

<script>
(function(){
  var msgsEl=document.getElementById('msgs');
  var inp=document.getElementById('inp');
  var send=document.getElementById('send');
  var stopBtn=document.getElementById('stop');
  var sessionsEl=document.getElementById('sessions');
  var searchBox=document.getElementById('searchbox');
  var current=null, running=false, abortCtrl=null, allSessions=[], pendingFiles=[];
  function esc(s){return String(s==null?'':s).replace(/[&<>" ]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function nowStr(){return new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}

  /* 图片灯箱 */
  var lightbox=document.createElement('div');lightbox.id='lightbox';lightbox.innerHTML='<img src="" alt="preview">';document.body.appendChild(lightbox);
  lightbox.addEventListener('click',function(){lightbox.classList.remove('open');});
  function openLightbox(src){lightbox.querySelector('img').src=src;lightbox.classList.add('open');}
  function autoGrow(){inp.style.height='auto';inp.style.height=Math.min(inp.scrollHeight,180)+'px';}
  inp.addEventListener('input',autoGrow);

  /* ---- 文件上传 ---- */
  var fileInput=document.getElementById('file-input');
  var uploadBtn=document.getElementById('upload-btn');
  var fileArea=document.getElementById('file-area');
  var composer=document.getElementById('composer');
  uploadBtn.addEventListener('click',function(){fileInput.click();});
  fileInput.addEventListener('change',function(){addFiles(fileInput.files);fileInput.value='';});
  function addFiles(files){
    for(var i=0;i<files.length;i++){
      var f=files[i];
      if(pendingFiles.some(function(p){return p.name===f.name&&p.size===f.size;}))continue;
      pendingFiles.push({file:f,dataUrl:null});
    }
    renderFileTags();loadPreviews();
  }
  function loadPreviews(){
    pendingFiles.forEach(function(pf){
      if(pf.dataUrl||!pf.file.type.match(/^image\//))return;
      var reader=new FileReader();
      reader.onload=function(e){pf.dataUrl=e.target.result;renderFileTags();};
      reader.readAsDataURL(pf.file);
    });
  }
  function renderFileTags(){
    fileArea.innerHTML='';
    pendingFiles.forEach(function(pf,i){
      var f=pf.file;
      var tag=document.createElement('span');tag.className='file-tag';
      if(pf.dataUrl){
        tag.innerHTML='<img src="'+pf.dataUrl+'" alt="'+esc(f.name)+'"><span class="name" title="'+esc(f.name)+'">'+esc(f.name)+'</span><span class="remove" data-idx="'+i+'">✕</span>';
      }else{
        tag.innerHTML='<span class="name" title="'+esc(f.name)+' ('+Math.round(f.size/1024)+'KB)">'+esc(f.name)+'</span><span class="remove" data-idx="'+i+'">✕</span>';
      }
      fileArea.appendChild(tag);
    });
    fileArea.querySelectorAll('.remove').forEach(function(el){
      el.addEventListener('click',function(){pendingFiles.splice(parseInt(el.dataset.idx),1);renderFileTags();});
    });
  }
  composer.addEventListener('dragover',function(e){e.preventDefault();e.stopPropagation();composer.classList.add('dragover');});
  composer.addEventListener('dragleave',function(e){e.preventDefault();composer.classList.remove('dragover');});
  composer.addEventListener('drop',function(e){e.preventDefault();e.stopPropagation();composer.classList.remove('dragover');if(e.dataTransfer.files.length){addFiles(e.dataTransfer.files);}});

  /* ---- 主题切换 ---- */
  function getTheme(){return localStorage.getItem('qxt-theme')||'dark';}
  function setTheme(t){document.documentElement.setAttribute('data-theme',t);localStorage.setItem('qxt-theme',t);
    document.getElementById('btn-theme').textContent=t==='light'?'浅色':'深色';}
  setTheme(getTheme());
  document.getElementById('btn-theme').addEventListener('click',function(){setTheme(getTheme()==='dark'?'light':'dark');});

  /* ---- 轻量 Markdown 渲染 (安全: 先转义再处理标记) ---- */
  function inline(s){
    s=esc(s);
    s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
    s=s.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
    s=s.replace(/\*([^*]+)\*/g,'<em>$1</em>');
    s=s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
    return s;
  }
  function renderMd(text){
    var lines=String(text==null?'':text).split('\\n');
    var out=[], inCode=false, codeBuf=[];
    function flushCode(){ if(codeBuf.length){ out.push('<pre><code>'+esc(codeBuf.join('\\n'))+'</code></pre>'); codeBuf=[]; } }
    for(var i=0;i<lines.length;i++){
      var line=lines[i];
      if(line.indexOf('```')===0){
        if(inCode){ flushCode(); inCode=false; }
        else { inCode=true; }
        continue;
      }
      if(inCode){ codeBuf.push(line); continue; }
      var t=line.trim();
      if(!t){ continue; }
      if(/^#{1,4}\s/.test(t)){ var lvl=t.match(/^(#+)\s/)[1].length; out.push('<h'+lvl+'>'+inline(t.replace(/^#+\s/,''))+'</h'+lvl+'>'); }
      else if(/^[-*]\s/.test(t)){ out.push('<ul><li>'+inline(t.replace(/^[-*]\s/,''))+'</li></ul>'); }
      else if(/^\d+\.\s/.test(t)){ out.push('<ol><li>'+inline(t.replace(/^\d+\.\s/,''))+'</li></ol>'); }
      else if(/^&gt;\s?/.test(t)){ out.push('<blockquote>'+inline(t.replace(/^&gt;\s?/,''))+'</blockquote>'); }
      else if(/^---+$/.test(t)){ out.push('<hr>'); }
      else { out.push('<p>'+inline(t)+'</p>'); }
    }
    if(inCode){ flushCode(); }
    return out.join('\\n');
  }

  /* ---- Markdown 导出 ---- */
  function exportMarkdown(){
    if(!current||!allSessions.length){return;}
    var sess=allSessions.find(function(s){return s.id===current;});
    var title=sess?sess.title:'未命名会话';
    fetch('/api/history?session='+encodeURIComponent(current))
      .then(function(r){return r.json();})
      .then(function(j){
        if(!j.ok)return;
        var md='# '+title+'\n\n';
        md+='> 导出时间: '+new Date().toLocaleString()+'\\n> 模型: '+document.getElementById('t-model').textContent.replace('模型 ','')+'\\n\\n';
        md+='---\\n\\n';
        (j.messages||[]).forEach(function(m){
          if(m.role==='user'){
            md+='## 你\\n\\n'+m.content+'\\n\\n';
          }else{
            md+='## 青小团\\n\\n'+m.content+'\\n\\n';
          }
        });
        var blob=new Blob([md],{type:'text/markdown;charset=utf-8'});
        var a=document.createElement('a');
        a.href=URL.createObjectURL(blob);
        a.download=title.replace(/[\\/:*?"<>|]/g,'_')+'.md';
        a.click();
        URL.revokeObjectURL(a.href);
      });
  }
  document.getElementById('btn-export').addEventListener('click',exportMarkdown);

  /* ---- 会话搜索 ---- */
  function filterSessions(q){
    if(!q){return allSessions;}
    q=q.toLowerCase();
    return allSessions.filter(function(s){
      return s.title.toLowerCase().indexOf(q)!==-1;
    });
  }

  function msgEl(role){
    var m=document.createElement('div');m.className='msg '+role;
    var meta=document.createElement('div');meta.className='meta';
    var who=document.createElement('span');who.className='who';who.textContent=role==='user'?'你':'青小团';
    var tm=document.createElement('span');tm.className='tm';tm.textContent=nowStr();
    meta.appendChild(who);meta.appendChild(tm);
    var b=document.createElement('div');b.className='bubble';
    m.appendChild(meta);m.appendChild(b);msgsEl.appendChild(m);return b;
  }
  function toolEl(name,args){
    var t=document.createElement('div');t.className='tool';
    t.innerHTML='<div class="tool-head"><span class="caret">▸</span><span class="tname"></span></div><div class="tool-body"></div>';
    t.querySelector('.tname').textContent=name;
    var body=t.querySelector('.tool-body');
    var a=document.createElement('div');a.className='lbl';a.textContent='参数';
    var ap=document.createElement('pre');ap.textContent=args||'';
    var rl=document.createElement('div');rl.className='lbl';rl.textContent='结果';
    var rp=document.createElement('pre');rp.className='tool-result';rp.textContent='…';
    body.appendChild(a);body.appendChild(ap);body.appendChild(rl);body.appendChild(rp);
    t.querySelector('.tool-head').addEventListener('click',function(){t.classList.toggle('open');});
    msgsEl.appendChild(t);
    return {setResult:function(out){rp.textContent=out||'';},el:t};
  }

  function renderMsgContent(bubble,role,content){
    var text=(content||'').replace(/\n?\[附件: [^\]]+\]/g,'').replace(/\n?\[图片: [^\]]+\]/g,'').trim();
    if(role==='assistant'){
      bubble.innerHTML=renderMd(text||'');
    }else{
      bubble.textContent=text||'';
    }
    if(role==='user'&&window._sessionImages&&window._sessionImages.length){
      var grid=document.createElement('div');grid.className='img-grid';
      window._sessionImages.forEach(function(src){
        var img=document.createElement('img');img.src=src;img.alt='uploaded';
        img.addEventListener('click',function(){openLightbox(src);});
        grid.appendChild(img);
      });
      bubble.appendChild(grid);
      window._sessionImages=[];
    }
  }
  function addMsg(role,content,tools){
    var b=msgEl(role);
    renderMsgContent(b,role,content);
    (tools||[]).forEach(function(tc){toolEl(tc.name,tc.args).setResult(tc.out);});
    return b;
  }
  function renderHistory(msgs){
    msgsEl.innerHTML='';
    (msgs||[]).forEach(function(m){addMsg(m.role,m.content,m.tools);});
    scrollBottom();
  }
  function scrollBottom(){msgsEl.scrollTop=msgsEl.scrollHeight;}

  function loadSessions(){
    fetch('/api/sessions').then(function(r){return r.json();}).then(function(j){
      allSessions=j.sessions||[];
      var filtered=filterSessions(searchBox.value.trim());
      sessionsEl.innerHTML='';
      filtered.forEach(function(s){
        var d=document.createElement('div');d.className='sess'+(s.id===current?' active':'');
        var t=document.createElement('span');t.className='t';t.textContent=s.title;
        var x=document.createElement('span');x.className='del';x.textContent='✕';x.title='删除会话';
        d.appendChild(t);d.appendChild(x);
        d.addEventListener('click',function(ev){ if(ev.target===x) return; current=s.id;loadHistory();loadSessions(); });
        x.addEventListener('click',function(ev){ ev.stopPropagation();
          fetch('/api/sessions?session='+encodeURIComponent(s.id),{method:'DELETE'}).then(function(r){return r.json();}).then(function(j){
            if(j.ok){ if(current===s.id){current=null;msgsEl.innerHTML='';} loadSessions(); }
          });
        });
        sessionsEl.appendChild(d);
      });
    }).catch(function(){});
  }
  searchBox.addEventListener('input',function(){loadSessions();});

  function loadHistory(){
    if(!current){msgsEl.innerHTML='';return;}
    fetch('/api/history?session='+encodeURIComponent(current)).then(function(r){return r.json();}).then(function(j){
      if(j.ok){renderHistory(j.messages);}
    }).catch(function(){});
  }

  function loadInfo(){
    fetch('/api/info').then(function(r){return r.json();}).then(function(j){
      var model=(j.model||'?').split('/').slice(-1)[0]||j.model;
      document.getElementById('t-model').innerHTML='<b>模型</b> '+esc(model);
      document.getElementById('ws-name').textContent=j.workspace||'';
      document.getElementById('sidefoot').textContent='青小团 qingxiaotuan · '+(j.workspace||'');
      if(j.mode){document.getElementById('t-mode').innerHTML='<b>mode</b> '+esc(j.mode);}
      if(j.effort){document.getElementById('t-effort').innerHTML='<b>effort</b> '+esc(j.effort);}
      var sf=document.getElementById('safety');
      if(j.security&&j.security.available){
        var b=j.security.benchmark||{};
        var core=b.core||{};
        var ps=b.ps||{};
        sf.style.display='block';
        sf.innerHTML='<b>安全基准</b><br>对抗拦截 <span class="ok">'+fmtPct(core.adversarial_recall)+'</span> · 绕过 <span class="ok">'+fmtNum(core.bypass_count)+'</span><br>PS 5k 正确率 <span class="ok">'+fmtPct(ps.accuracy)+'</span>';
      } else { sf.style.display='none'; }
    }).catch(function(){});
  }
  function fmtPct(v){ return v==null?'-':(Math.round(Number(v)*100)+'%'); }
  function fmtNum(v){ return v==null?'-':v; }

  function sendMsg(){
    var msg=inp.value.trim();if(!msg||running)return;
    if(msg==='/clear'){
      if(current){ fetch('/api/sessions/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:current})}).catch(function(){}); }
      msgsEl.innerHTML='';inp.value='';return;
    }
    var fileMsg=msg;
    var imgDataUrls=[];
    if(pendingFiles.length>0){
      var names=[];
      pendingFiles.forEach(function(pf){
        names.push(pf.file.name);
        if(pf.dataUrl){imgDataUrls.push(pf.dataUrl);}
      });
      fileMsg=msg+'\n\n[附件: '+names.join(', ')+']';
    }
    window._sessionImages=imgDataUrls;
    addMsg('user',fileMsg,[]);
    inp.value='';autoGrow();pendingFiles=[];renderFileTags();
    setRunning(true);
    var b=msgEl('assistant');var cursor=document.createElement('span');cursor.className='stream-cursor';b.appendChild(cursor);
    var text='';var tools=[];
    abortCtrl=new AbortController();
    var sid=current||'';
    fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({session:sid,message:fileMsg}),signal:abortCtrl.signal})
    .then(function(resp){
      if(!resp.ok||!resp.body){throw new Error('HTTP '+resp.status);}
      var reader=resp.body.getReader();
      var dec=new TextDecoder();var buf='';
      function pump(){
        return reader.read().then(function(r){
          if(r.done){finish();return;}
          buf+=dec.decode(r.value,{stream:true});
          var idx;
          while((idx=buf.indexOf('\n\n'))>=0){
            var chunk=buf.slice(0,idx);buf=buf.slice(idx+2);
            handleSSE(chunk);
          }
          return pump();
        });
      }
      return pump();
    }).catch(function(e){
      if(e.name!=='AbortError'){cursor.remove();b.innerHTML+='<p>[错误] '+esc(e.message)+'</p>';}
      finish();
    });

    function handleSSE(chunk){
      var lines=chunk.split('\n');var ev='',data='';
      lines.forEach(function(l){
        if(l.startsWith('event:'))ev=l.slice(6).trim();
        else if(l.startsWith('data:'))data=l.slice(5).trim();
      });
      if(!data)return;
      var j;try{j=JSON.parse(data);}catch(e){return;}
      if(ev==='session'){current=j.id;loadSessions();}
      else if(ev==='delta'){text+=j;cursor.remove();b.innerHTML=renderMd(text);b.appendChild(cursor);scrollBottom();}
      else if(ev==='tool'){tools.push({name:j.name,args:j.args,out:''});toolEl(j.name,j.args);scrollBottom();}
      else if(ev==='tool_result'){var t=document.querySelector('.tool:last-of-type .tool-result');if(t)t.textContent=j.out||'(无输出)';scrollBottom();}
      else if(ev==='reason'){}
      else if(ev==='error'){cursor.remove();b.innerHTML+='<p>[错误] '+esc(j.message)+'</p>';}
    }
    function finish(){cursor.remove();setRunning(false);loadSessions();loadHistory();}
  }

  function setRunning(v){
    running=v;send.disabled=v;stopBtn.style.display=v?'block':'none';
  }
  stopBtn.addEventListener('click',function(){if(abortCtrl){abortCtrl.abort();}fetch('/api/stop',{method:'POST'}).catch(function(){});});

  /* ---- 键盘快捷键 ---- */
  document.addEventListener('keydown',function(e){
    if(e.ctrlKey&&e.key==='e'){e.preventDefault();exportMarkdown();}
    if(e.ctrlKey&&e.key==='k'){e.preventDefault();searchBox.focus();searchBox.select();}
    if(e.ctrlKey&&e.key==='n'){e.preventDefault();current=null;msgsEl.innerHTML='';loadSessions();inp.focus();}
  });

  send.addEventListener('click',sendMsg);
  inp.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}
  });
  document.getElementById('newbtn').addEventListener('click',function(){current=null;msgsEl.innerHTML='';loadSessions();});

  loadInfo();loadSessions();
})();
</script>
</body>
</html>
"""
