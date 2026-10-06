# -*- coding: utf-8 -*-
"""Web 前端 (内联 HTML/CSS/JS, 无外链 CDN, 断网可用)。

v0.2.018 重设计 —— 视觉语言取自项目站 ``web/index.html`` 的设计系统
(米色纸感 + 金色 accent + 衬线字体 + 刻尺/几何装饰), 并按 Anthropic
"Design with Claude" 原则收束:

- 单一强调色: 全站只用金 (#B89662 系) 一种 accent, 其余为米/墨/灰
- 克制装饰: 圆角 ≤4px、阴影极淡、动效只做边框/位移过渡, 不空转
- 内容优先: 真实数据直接展示 (会话/模型/安全基准), 无 lorem、无 emoji 堆砌
- 清晰层级: eyebrow(10px 金 uppercase) → 衬线标题 → 14px 正文 → 12.5px 代码
- 深浅双主题: 浅色默认米纸 (与项目站一致), 深色为暖深褐夜晚调, 均不刺眼
- 断网可用: 零外链字体/CDN, 字体栈全部本地 fallback

功能不变: 会话持久化 / 上传(拖拽) / Markdown 渲染 / 安全面板 / 主题切换 /
导出 / 快捷键 / SSE 流式。
"""
from __future__ import annotations

FRONTEND_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>青小团 · Web 工作台</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='6' fill='%23B89662'/%3E%3Ctext x='32' y='44' font-family='Georgia,serif' font-size='34' font-weight='bold' fill='%23FFFDF7' text-anchor='middle'%3E%E9%9D%92%3C/text%3E%3C/svg%3E">
<style>
  /* ===== 设计系统 (取自 web/assets/style.css) ===== */
  :root {
    --bg:#F5F1EA; --bg-warm:#EFE8DC; --cream:#FBF8F2;
    --ink:#2A2620; --ink-soft:#5C554A; --ink-faint:#8A8275;
    --gold:#B89662; --gold-light:#D4B98B; --gold-dark:#8C6E3E;
    --gold-soft:rgba(184,150,98,.12);
    --line:#D9D0C1; --line-soft:#E8E0D3;
    --err:#A54A3A; --err-soft:rgba(165,74,58,.10);
    --btn-bg:#2A2620; --btn-fg:#FBF8F2;
    --serif:'Cormorant Garamond','Noto Serif SC','Songti SC','SimSun',Georgia,serif;
    --sans:'Inter','Noto Serif SC','Microsoft YaHei',system-ui,sans-serif;
    --mono:'JetBrains Mono','Cascadia Code',Consolas,'SFMono-Regular',monospace;
    --ease:cubic-bezier(.4,0,.2,1);
  }
  /* 深色: 暖深褐夜晚调 (取自 style.css dark 变量) */
  html[data-theme="dark"] {
    --bg:#201D18; --bg-warm:#2A2620; --cream:#28241E;
    --ink:#E8E0D3; --ink-soft:#B5AB97; --ink-faint:#8A8070;
    --gold:#C9A972; --gold-light:#E3CDA4; --gold-dark:#D4B98B;
    --gold-soft:rgba(212,185,139,.12);
    --line:#3A352B; --line-soft:#332F26;
    --err:#D98B7C; --err-soft:rgba(217,139,124,.12);
    --btn-bg:#E8E0D3; --btn-fg:#28241E;
  }

  *{box-sizing:border-box;margin:0;padding:0}
  html,body{width:100%;height:100%}
  body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-weight:300;
       letter-spacing:.01em;display:flex;overflow:hidden;font-size:14px;line-height:1.6;
       -webkit-font-smoothing:antialiased;transition:background-color .5s var(--ease),color .5s var(--ease)}
  /* 极淡纸纹 (与项目站一致) */
  body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:1000;opacity:.05;
    background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 400 400' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    background-size:300px 300px;mix-blend-mode:multiply}
  html[data-theme="dark"] body::before{opacity:.06;mix-blend-mode:screen}

  ::-webkit-scrollbar{width:10px;height:10px}
  ::-webkit-scrollbar-thumb{background:var(--line);border:3px solid var(--bg);border-radius:8px}
  ::-webkit-scrollbar-thumb:hover{background:var(--gold-light)}
  ::-webkit-scrollbar-track{background:transparent}

  /* ===== 左栏 ===== */
  #sidebar{width:264px;min-width:264px;background:var(--bg-warm);border-right:1px solid var(--line-soft);
           display:flex;flex-direction:column;position:relative}
  /* 左栏刻尺 (顶部编号线) */
  #sidebar::before{content:'01';position:absolute;top:0;left:0;right:0;height:20px;
    border-top:1px solid var(--line);color:var(--ink-faint);font-size:10px;font-weight:300;
    letter-spacing:.2em;padding-top:24px;padding-left:18px;pointer-events:none;
    background-image:repeating-linear-gradient(to right,var(--line) 0,var(--line) 1px,transparent 1px,transparent 40px);
    background-position:0 0;background-size:auto 1px;background-repeat:no-repeat}
  .brand{display:flex;align-items:baseline;gap:8px;padding:52px 18px 0;font-family:var(--serif)}
  .brand .qxt{font-size:20px;font-weight:500;letter-spacing:.10em;color:var(--ink);text-transform:uppercase}
  .brand .qxt em{font-style:italic;font-weight:400;color:var(--gold-dark)}
  .brand .tag{margin-left:auto;font-size:10px;font-weight:400;letter-spacing:.24em;text-transform:uppercase;
              color:var(--gold-dark);font-family:var(--sans)}
  #newbtn{display:flex;align-items:center;gap:8px;margin:20px 18px 6px;padding:9px 14px;
          font-family:var(--sans);font-size:11px;font-weight:500;letter-spacing:.2em;text-transform:uppercase;
          color:var(--gold-dark);background:transparent;border:1px solid var(--gold);
          cursor:pointer;transition:all .3s var(--ease)}
  #newbtn:hover{background:var(--gold);color:var(--cream)}
  .ws-label{padding:14px 18px 4px;font-size:10px;font-weight:400;letter-spacing:.4em;
            text-transform:uppercase;color:var(--ink-faint);font-family:var(--sans)}
  #ws-name{padding:0 18px 10px;font-size:12px;color:var(--ink-soft);white-space:nowrap;
           overflow:hidden;text-overflow:ellipsis;letter-spacing:.02em}
  #searchbox{margin:4px 18px 8px;padding:7px 11px;border:1px solid var(--line);border-radius:2px;
             background:var(--cream);color:var(--ink);font-size:12.5px;width:calc(100% - 36px);
             outline:none;font-family:var(--sans);transition:border-color .2s var(--ease)}
  #searchbox:focus{border-color:var(--gold)}
  #searchbox::placeholder{color:var(--ink-faint)}
  #sessions{flex:1;overflow-y:auto;padding:0 10px}
  .sess{display:flex;align-items:center;border-radius:2px;cursor:pointer;font-size:13px;
        color:var(--ink-soft);margin-bottom:1px;border-left:2px solid transparent;transition:all .2s var(--ease)}
  .sess .t{flex:1;padding:8px 4px 8px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sess .del{padding:8px 8px 8px 2px;color:var(--ink-faint);opacity:.5;font-size:13px;transition:color .2s}
  .sess:hover{background:var(--gold-soft)}
  .sess:hover .del{opacity:1}
  .sess .del:hover{color:var(--err)}
  .sess.active{background:var(--gold-soft);border-left-color:var(--gold);color:var(--ink)}
  .sess.active .t{color:var(--gold-dark);font-weight:500}
  #safety{display:none;margin:8px 18px 6px;padding:11px 13px;border:1px solid var(--line-soft);
          border-left:2px solid var(--gold);background:var(--cream);font-size:11px;
          color:var(--ink-soft);line-height:1.8;letter-spacing:.02em}
  #safety .t{font-size:10px;letter-spacing:.32em;text-transform:uppercase;color:var(--gold-dark);display:block;margin-bottom:2px}
  #safety b{color:var(--ink);font-weight:500}
  #safety .ok{color:var(--gold-dark);font-weight:500}
  #sidebar .foot{padding:12px 18px 16px;font-size:10.5px;color:var(--ink-faint);border-top:1px solid var(--line-soft);
                 word-break:break-all;letter-spacing:.03em;line-height:1.7}

  /* ===== 主区 ===== */
  #main{flex:1;display:flex;flex-direction:column;min-width:0;position:relative}
  #topbar{height:52px;border-bottom:1px solid var(--line-soft);display:flex;align-items:center;gap:12px;
          padding:0 26px;font-size:12.5px;color:var(--ink-soft);background:var(--bg);position:relative}
  #topbar::before{content:'';position:absolute;top:0;left:26px;right:26px;height:1px;
    background-image:repeating-linear-gradient(to right,var(--line) 0,var(--line) 1px,transparent 1px,transparent 48px)}
  #topbar .crumb{color:var(--ink-faint);font-size:12px}
  #topbar .sp{flex:1}
  .chip{background:transparent;border:1px solid var(--line);border-radius:2px;padding:2px 10px;
        font-size:11px;color:var(--ink-soft);white-space:nowrap;font-family:var(--mono);
        letter-spacing:.02em}
  .chip b{color:var(--gold-dark);font-weight:500}
  .tb-btn{background:transparent;border:1px solid var(--line);border-radius:2px;padding:4px 12px;
          color:var(--ink-soft);cursor:pointer;font-size:11px;letter-spacing:.12em;
          font-family:var(--sans);transition:all .25s var(--ease)}
  .tb-btn:hover{border-color:var(--gold);color:var(--gold-dark)}
  #t-model{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

  /* ===== 对话流 ===== */
  #msgs{flex:1;overflow-y:auto;padding:30px 6vw 14px}
  .msg{max-width:820px;margin:0 auto 24px;display:flex;flex-direction:column;gap:6px}
  .msg .meta{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--ink-faint)}
  .msg .meta .who{font-weight:500;color:var(--gold-dark);letter-spacing:.18em;font-size:10.5px;
                  text-transform:uppercase}
  .msg .meta .tm{font-size:11px;color:var(--ink-faint);font-family:var(--mono)}
  .bubble{background:var(--cream);border:1px solid var(--line);border-radius:2px;
          padding:14px 18px;font-size:14px;line-height:1.9;word-break:break-word;color:var(--ink-soft);
          letter-spacing:.02em}
  .bubble p{margin:0 0 10px}
  .bubble p:last-child{margin-bottom:0}
  .bubble h1,.bubble h2,.bubble h3{margin:15px 0 8px;line-height:1.4;font-weight:500;color:var(--ink);
                                   font-family:var(--serif);letter-spacing:.04em}
  .bubble h1{font-size:19px}.bubble h2{font-size:17px}.bubble h3{font-size:15.5px}
  .bubble ul,.bubble ol{margin:6px 0 10px;padding-left:24px}
  .bubble li{margin:3px 0}
  .bubble blockquote{border-left:3px solid var(--gold-light);margin:8px 0;padding:2px 14px;color:var(--ink-faint)}
  .bubble code{font-family:var(--mono);font-size:12.5px;background:var(--bg-warm);
               border:1px solid var(--line-soft);border-radius:2px;padding:1px 5px;color:var(--ink)}
  .bubble pre{background:var(--bg-warm);border:1px solid var(--line);border-radius:2px;padding:12px 14px;
              overflow-x:auto;margin:10px 0;font-family:var(--mono);font-size:12.5px;line-height:1.6;color:var(--ink)}
  .bubble pre code{background:none;border:none;padding:0;color:inherit}
  .bubble a{color:var(--gold-dark);text-decoration:none;border-bottom:1px solid var(--gold-light)}
  .bubble a:hover{color:var(--gold);border-bottom-color:var(--gold)}
  .bubble hr{border:none;border-top:1px solid var(--line);margin:12px 0}
  .msg.user{align-items:flex-end}
  .msg.user .meta{flex-direction:row-reverse}
  /* 用户消息: 纸面气泡 + 金色描边 (高对比, 金色仅作 accent) */
  .msg.user .bubble{background:var(--cream);border:1px solid var(--gold);color:var(--ink)}
  .msg.user .bubble code{background:var(--bg-warm);border-color:var(--gold-light);color:var(--ink)}
  .msg.user .bubble pre{background:var(--bg-warm);border-color:var(--gold-light);color:var(--ink)}
  .msg.user .bubble h1,.msg.user .bubble h2,.msg.user .bubble h3{color:var(--ink)}
  .msg.user .bubble a{color:var(--gold-dark);border-bottom-color:var(--gold-light)}

  /* 工具调用 (克制折叠块) */
  .tool{margin:8px 0 4px;background:var(--bg-warm);border:1px solid var(--line);border-radius:2px;overflow:hidden}
  .tool-head{padding:6px 12px;font-family:var(--mono);font-size:12px;color:var(--gold-dark);cursor:pointer;
             display:flex;align-items:center;gap:8px;user-select:none}
  .tool-head .caret{transition:transform .18s var(--ease);color:var(--ink-faint);font-size:10px}
  .tool.open .caret{transform:rotate(90deg)}
  .tool-head .tname{font-weight:500}
  .tool-body{display:none;padding:0 12px 10px;font-family:var(--mono);font-size:12px;color:var(--ink-soft);
             border-top:1px solid var(--line-soft)}
  .tool.open .tool-body{display:block}
  .tool-body pre{white-space:pre-wrap;word-break:break-all;margin:6px 0;color:var(--ink)}
  .tool-body .lbl{color:var(--ink-faint);margin-top:8px;font-size:10px;letter-spacing:.14em;
                  text-transform:uppercase}
  .tool-result{color:var(--gold-dark)}

  /* ===== 输入区 ===== */
  #inputbar{border-top:1px solid var(--line-soft);padding:16px 6vw 18px;background:var(--bg)}
  #composer{max-width:820px;margin:0 auto;background:var(--cream);border:1px solid var(--line);
            border-radius:2px;display:flex;align-items:flex-end;padding:10px 10px 10px 14px;
            transition:border-color .2s var(--ease)}
  #composer:focus-within{border-color:var(--gold)}
  #composer.dragover{border-color:var(--gold-dark);background:var(--gold-soft)}
  #inp{flex:1;background:transparent;border:none;outline:none;color:var(--ink);font-size:14px;
       resize:none;max-height:180px;font-family:var(--sans);line-height:1.7;padding:4px 6px;font-weight:300}
  #send{margin-left:8px;padding:9px 22px;border:1px solid var(--gold);border-radius:2px;
        background:var(--btn-bg);color:var(--btn-fg);
        font-size:11px;cursor:pointer;font-weight:500;letter-spacing:.2em;text-transform:uppercase;
        transition:box-shadow .25s var(--ease)}
  #send:hover{box-shadow:0 4px 16px rgba(184,150,98,.35)}
  #send:disabled{opacity:.35;cursor:not-allowed;box-shadow:none}
  #stop{display:none;margin-left:8px;padding:8px 16px;border:1px solid var(--err);border-radius:2px;
        background:transparent;color:var(--err);font-size:11px;letter-spacing:.12em;cursor:pointer;
        font-family:var(--sans);transition:all .2s var(--ease)}
  #stop:hover{background:var(--err-soft)}
  #hint{max-width:820px;margin:9px auto 0;font-size:11px;color:var(--ink-faint);letter-spacing:.04em}
  #upload-btn{background:transparent;border:1px solid var(--line);border-radius:2px;padding:2px 9px;
              color:var(--ink-soft);cursor:pointer;font-size:14px;margin-left:4px;line-height:1.4;
              transition:all .2s var(--ease)}
  #upload-btn:hover{color:var(--gold-dark);border-color:var(--gold)}
  #file-input{display:none}
  #file-area{display:flex;flex-wrap:wrap;gap:5px;width:100%;margin-bottom:4px}
  .file-tag{display:inline-flex;align-items:center;gap:5px;background:var(--bg-warm);border:1px solid var(--line);
            border-radius:2px;padding:2px 9px;margin:3px 2px 0;font-size:12px;color:var(--ink-soft)}
  .file-tag .name{max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .file-tag .remove{cursor:pointer;color:var(--ink-faint);font-size:13px;transition:color .2s}
  .file-tag .remove:hover{color:var(--err)}
  .file-tag img{height:30px;width:auto;border-radius:2px;object-fit:cover}
  .bubble .chat-img{max-width:320px;max-height:240px;border-radius:2px;margin:6px 0;cursor:pointer;transition:transform .2s var(--ease)}
  .bubble .chat-img:hover{transform:scale(1.015)}
  .bubble .img-grid{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
  .bubble .img-grid img{max-width:160px;max-height:120px;border-radius:2px;object-fit:cover;cursor:pointer;transition:transform .2s var(--ease)}
  .bubble .img-grid img:hover{transform:scale(1.03)}
  #lightbox{display:none;position:fixed;inset:0;background:rgba(32,29,24,.9);z-index:9999;
            justify-content:center;align-items:center;cursor:zoom-out}
  #lightbox.open{display:flex}
  #lightbox img{max-width:90vw;max-height:90vh;border-radius:2px;box-shadow:0 6px 44px rgba(0,0,0,.4)}
  .stream-cursor{display:inline-block;width:8px;height:15px;background:var(--gold-dark);
                 vertical-align:-2px;animation:blink 1s step-start infinite}
  @keyframes blink{50%{opacity:0}}
  @media (max-width:760px){
    #sidebar{width:200px;min-width:200px}
    #msgs,#inputbar{padding-left:4vw;padding-right:4vw}
    .chip{display:none}
  }
  @media (max-width:640px){
    #sidebar{width:132px;min-width:132px}
    .ws-label,#ws-name,#hint,#topbar .crumb{display:none}
    #inp,#searchbox{font-size:16px}
    #msgs{padding-top:18px}
    .brand{padding:48px 12px 0;font-size:13px}
    #newbtn{font-size:10px;padding:8px 10px;margin:16px 12px 6px}
    #sidebar::before{padding-left:12px}
  }
</style>
</head>
<body>
  <aside id="sidebar">
    <div class="brand"><span class="qxt">青<em>小团</em></span><span class="tag">workbench</span></div>
    <button id="newbtn">＋ 新建会话</button>
    <div class="ws-label">工作区</div>
    <div id="ws-name">…</div>
    <input id="searchbox" type="text" placeholder="搜索会话… (Ctrl+K)">
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

  /* ---- 主题切换 (默认浅色, 与项目站米纸主调一致) ---- */
  function getTheme(){return localStorage.getItem('qxt-theme')||'light';}
  function setTheme(t){document.documentElement.setAttribute('data-theme',t);localStorage.setItem('qxt-theme',t);
    document.getElementById('btn-theme').textContent=t==='dark'?'浅色':'深色';}
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
      document.getElementById('sidefoot').textContent='青小团 Tuan-CLI · '+(j.workspace||'');
      if(j.mode){document.getElementById('t-mode').innerHTML='<b>mode</b> '+esc(j.mode);}
      if(j.effort){document.getElementById('t-effort').innerHTML='<b>effort</b> '+esc(j.effort);}
      var sf=document.getElementById('safety');
      if(j.security&&j.security.available){
        var b=j.security.benchmark||{};
        var core=b.core||{};
        var ps=b.ps||{};
        sf.style.display='block';
        sf.innerHTML='<span class="t">安全基准</span>对抗拦截 <b class="ok">'+fmtPct(core.adversarial_recall)+'</b> · 绕过 <b class="ok">'+fmtNum(core.bypass_count)+'</b><br>PS 5k 正确率 <b class="ok">'+fmtPct(ps.accuracy)+'</b>';
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
