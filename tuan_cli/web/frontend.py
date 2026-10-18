# -*- coding: utf-8 -*-
"""Web 前端 (内联 HTML/CSS/JS + 自研设计令牌表, 无外链 CDN, 断网可用)。

样式来源: **原创** `assets/tuan-web.css` —— 按前端实际引用的令牌逐个定义
(颜色/间距/圆角/字号/字重/版式/动效/层级), 深浅主题由 `[data-color-scheme]`
自动切换。此前的实现是从第三方 npm 包 dist 目录拷贝的 minified CSS (640KB),
对 MIT 项目属版权风险, 已移除; 现文件约 7KB 且来源干净。

主题机制: localStorage "tuan-web.color-scheme" + <html data-color-scheme> 属性;
首次启动会从旧键 "kimi-web.color-scheme" 迁移一次 (老用户主题偏好不丢)。

品牌: TUAN; 欢迎屏为 "TUAN" 呼吸粒子 (canvas 采样文字像素, 粒子呼吸脉动,
随鼠标移动被推开/回位)。

功能: 会话持久化 / 上传(拖拽) / Markdown 渲染(含表格) / 安全面板 /
主题切换 / 导出 / 快捷键 / SSE 流式 / 右侧文件树·Diff 面板 / @ 引用文件 /
! 执行 shell / 会话分支 / 上下文与 token 监控 / MCP 状态 / 权限审批弹窗 / i18n。
"""
from __future__ import annotations

FRONTEND_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content">
<meta name="color-scheme" content="light dark">
<title>TUAN · Web Workbench</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%231783FF'/%3E%3Ctext x='32' y='44' font-family='Arial,sans-serif' font-size='30' font-weight='bold' fill='%23FFFFFF' text-anchor='middle'%3ET%3C/text%3E%3C/svg%3E">
<script>
/* 预涂 color-scheme, 避免首屏闪烁; 顺带从旧键 kimi-web.color-scheme 迁移一次 */
(function(){try{
  var K='tuan-web.color-scheme', OLD='kimi-web.color-scheme';
  var v=localStorage.getItem(K);
  if(v===null){var old=localStorage.getItem(OLD);
    if(old!==null){v=old;localStorage.setItem(K,old);localStorage.removeItem(OLD);}}
  if(v==='light'||v==='dark'||v==='system'){document.documentElement.dataset.colorScheme=v;}
  else{document.documentElement.dataset.colorScheme='light';}
}catch(e){document.documentElement.dataset.colorScheme='light';}})();
</script>
<link rel="stylesheet" href="/assets/tuan-web.css">
<style>
  /* =================================================================
     TUAN 工作台骨架 —— 全部引用官方 Kimi 设计系统变量, 深浅自动适配
     ================================================================= */
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{width:100%;height:100%}
  body{background:var(--color-bg);color:var(--color-text);font-family:var(--font-ui);
       font-size:var(--text-base);font-weight:var(--weight-regular);line-height:1.6;
       display:flex;overflow:hidden;
       -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
       transition:background-color var(--duration-base) var(--ease-out),color var(--duration-base) var(--ease-out)}

  ::-webkit-scrollbar{width:5px;height:5px}
  ::-webkit-scrollbar-thumb{background:var(--color-text-faint);border-radius:var(--radius-full)}
  ::-webkit-scrollbar-thumb:hover{background:var(--color-text-muted)}
  ::-webkit-scrollbar-track{background:transparent}

  /* ===== 左栏 (官方: --color-sidebar-bg / --p-sidebar-w 264px) ===== */
  #sidebar{width:var(--p-sidebar-w);min-width:var(--p-sidebar-w);background:var(--color-sidebar-bg);
           border-right:var(--p-hairline) solid var(--color-line);
           display:flex;flex-direction:column;position:relative}
  .brand{display:flex;align-items:center;gap:var(--space-2-5,10px);padding:var(--space-5) var(--space-5) 0}
  .brand .dot{width:9px;height:9px;border-radius:50%;background:var(--color-accent);flex:none;
              box-shadow:0 0 0 3px var(--color-accent-soft)}
  .brand .tuan{font-size:15px;font-weight:var(--weight-semibold);letter-spacing:.03em;
              color:var(--color-text-strong);font-family:var(--font-ui)}
  #newbtn{display:flex;align-items:center;gap:var(--space-2);margin:var(--space-4) var(--space-3) var(--space-2);
          padding:var(--space-2) var(--space-3);font-family:var(--font-ui);font-size:var(--text-sm);
          font-weight:var(--weight-medium);color:var(--color-text);background:var(--color-surface-raised);
          border:var(--p-hairline) solid var(--color-line-strong);border-radius:var(--radius-md);
          cursor:pointer;transition:background var(--duration-base) var(--ease-out),
          border-color var(--duration-base) var(--ease-out),color var(--duration-base) var(--ease-out)}
  #newbtn:hover{background:var(--color-hover);border-color:var(--color-line-strong)}
  #newbtn svg{flex:none;color:var(--color-text-muted)}
  #searchbox{margin:var(--space-05,2px) var(--space-3) var(--space-3);padding:var(--space-2) var(--space-3);
             border:var(--p-hairline) solid var(--color-line);border-radius:var(--radius-md);
             background:var(--color-bg);color:var(--color-text);font-size:var(--text-sm);
             width:calc(100% - 2 * var(--space-3));outline:none;font-family:var(--font-ui);
             transition:border-color var(--duration-base) var(--ease-out),box-shadow var(--duration-base) var(--ease-out)}
  #searchbox:focus{border-color:var(--color-accent);box-shadow:var(--p-focus-ring)}
  #searchbox::placeholder{color:var(--color-text-faint)}
  .ws-label{padding:var(--space-2) var(--space-5) var(--space-1);font-size:var(--text-2xs);
            font-weight:var(--weight-section-label);letter-spacing:.05em;color:var(--color-text-faint);
            font-family:var(--font-ui);text-transform:uppercase}
  #ws-name{padding:0 var(--space-5) var(--space-3);font-size:var(--text-xs);color:var(--color-text-muted);
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #sessions{flex:1;overflow-y:auto;padding:0 var(--space-2);scrollbar-width:thin}
  .sess{display:flex;align-items:center;border-radius:var(--radius-md);cursor:pointer;font-size:var(--text-sm);
        color:var(--color-text-muted);margin-bottom:var(--space-05,2px);
        transition:background var(--duration-base) var(--ease-out),color var(--duration-base) var(--ease-out)}
  .sess .t{flex:1;padding:var(--space-2) var(--space-1) var(--space-2) var(--space-3);
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sess .del{padding:var(--space-2) var(--space-2) var(--space-2) var(--space-05,2px);
             color:var(--color-text-faint);opacity:0;font-size:var(--text-sm);transition:opacity var(--duration-base)}
  .sess:hover{background:var(--color-hover);color:var(--color-text)}
  .sess:hover .del{opacity:1}
  .sess .del:hover{color:var(--color-danger)}
  .sess.active{background:var(--color-accent-soft);color:var(--color-text)}
  .sess.active .t{color:var(--color-text);font-weight:var(--weight-medium)}
  #sidebar .foot{padding:var(--space-3) var(--space-3) var(--space-4);border-top:var(--p-hairline) solid var(--color-line);
                 display:flex;align-items:center;gap:var(--space-1)}
  #sidebar .foot .tb-btn{background:transparent;border:var(--p-hairline) solid transparent;
        border-radius:var(--radius-md);padding:var(--space-1-5) var(--space-2);color:var(--color-text-muted);
        cursor:pointer;font-size:var(--text-xs);font-family:var(--font-ui);
        display:inline-flex;align-items:center;justify-content:center;gap:var(--space-1-5);
        transition:background var(--duration-base) var(--ease-out),color var(--duration-base) var(--ease-out)}
  #sidebar .foot .tb-btn:hover{background:var(--color-hover);color:var(--color-text)}
  #sidebar .foot .tb-btn svg{flex:none}
  #sidebar .foot .sp{flex:1}
  #sidefoot{flex:1;display:block;padding:0 var(--space-5) var(--space-3);font-size:10px;color:var(--color-text-faint);
            word-break:break-all;line-height:1.6}

  /* ===== 主区 ===== */
  #main{flex:1;display:flex;flex-direction:column;min-width:0;position:relative;background:var(--color-bg)}

  /* ===== 对话流 ===== */
  #msgs{flex:1;overflow-y:auto;padding:var(--space-8) 6vw var(--space-3);display:flex;flex-direction:column;scrollbar-width:thin}
  /* 欢迎屏: TUAN 呼吸粒子 (与官方 Kimi Chat 首页一致: 仅粒子主视觉, 无提示文案) */
  #welcome{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;
           text-align:center;width:100%;height:100%;min-height:340px;margin:auto}
  #tuan-canvas{position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none}
  /* 问候语 (hero 态显示, 每次新建会话随机一句, 每 6s 轮换) */
  #greet{display:none}
  .msg{max-width:var(--p-content-max);margin:0 auto var(--space-5);display:flex;flex-direction:column;gap:var(--space-1-5);width:100%}
  .msg .meta{display:flex;align-items:center;gap:var(--space-3);font-size:var(--text-xs);color:var(--color-text-faint)}
  .msg .meta .who{font-weight:var(--weight-semibold);color:var(--color-text);letter-spacing:.02em;font-size:var(--text-xs)}
  .msg .meta .tm{font-size:var(--text-2xs);color:var(--color-text-faint);font-family:var(--font-mono)}
  .bubble{background:var(--color-surface-raised);border:var(--p-hairline) solid var(--color-line);
          border-radius:var(--radius-lg);padding:var(--space-4) var(--space-4);
          font-size:var(--text-sm);line-height:1.75;word-break:break-word;color:var(--color-text)}
  .bubble p{margin:0 0 var(--space-3)}
  .bubble p:last-child{margin-bottom:0}
  .bubble h1,.bubble h2,.bubble h3{margin:var(--space-4) 0 var(--space-2);line-height:1.4;
                                   font-weight:var(--weight-semibold);color:var(--color-text-strong);font-family:var(--font-ui)}
  .bubble h1{font-size:21px}.bubble h2{font-size:19px}.bubble h3{font-size:18px}
  .bubble ul,.bubble ol{margin:var(--space-1-5) 0 var(--space-3);padding-left:var(--space-6)}
  .bubble li{margin:var(--space-1) 0}
  .bubble blockquote{border-left:3px solid var(--color-accent-bd);margin:var(--space-2) 0;
                     padding:var(--space-05,2px) var(--space-4);color:var(--color-text-muted)}
  .bubble code{font-family:var(--font-mono);font-size:var(--text-xs);background:var(--color-inline-code-bg);
               border-radius:var(--radius-xs);padding:1px var(--space-1);color:var(--color-text)}
  .bubble pre{background:var(--color-surface);border:var(--p-hairline) solid var(--color-line);
              border-radius:var(--radius-lg);padding:var(--space-3) var(--space-4);overflow-x:auto;
              margin:var(--space-3) 0;font-family:var(--font-mono);font-size:var(--text-xs);line-height:1.6;color:var(--color-text)}
  .bubble pre code{background:none;border:none;padding:0;color:inherit;font-size:inherit}
  .bubble a{color:var(--color-accent);text-decoration:none}
  .bubble a:hover{text-decoration:underline;color:var(--color-accent-hover)}
  .bubble hr{border:none;border-top:var(--p-hairline) solid var(--color-line);margin:var(--space-3) 0}
  .msg.user{align-items:flex-end}
  .msg.user .meta{flex-direction:row-reverse}
  .edit-btn{cursor:pointer;color:var(--color-text-faint);font-size:var(--text-xs);
            margin-left:var(--space-1);opacity:0;transition:opacity var(--duration-base)}
  .msg:hover .edit-btn{opacity:1}
  .edit-btn:hover{color:var(--color-accent)}
  /* 用户消息: 官方 --color-user-bubble-bg 气泡 */
  .msg.user .bubble{background:var(--color-user-bubble-bg);border-color:transparent;color:var(--color-text)}
  .msg.user .bubble code{background:var(--color-bg)}
  .msg.user .bubble pre{background:var(--color-bg);border-color:var(--color-line)}
  /* 助手消息: 无边框 (官方简洁风格) */
  .msg.assistant .bubble{background:transparent;border:none;padding:0;display:flex;flex-direction:column;gap:var(--space-2)}
  .msg.assistant .bubble>.md{font-size:var(--text-sm);line-height:1.75;word-break:break-word;color:var(--color-text)}
  .msg.assistant .bubble>.md>*:first-child{margin-top:0}
  .msg.assistant .bubble>.md>*:last-child{margin-bottom:0}

  /* 工具调用 (折叠块) */
  .tool{margin:var(--space-2) 0 var(--space-1);background:var(--color-surface);border:var(--p-hairline) solid var(--color-line);
        border-radius:var(--radius-lg);overflow:hidden}
  .tool-head{padding:var(--space-2) var(--space-3);font-family:var(--font-mono);font-size:var(--text-xs);
             color:var(--color-text-muted);cursor:pointer;display:flex;align-items:center;gap:var(--space-2);
             user-select:none;transition:background var(--duration-base) var(--ease-out)}
  .tool-head:hover{background:var(--color-hover)}
  .tool-head .caret{transition:transform var(--duration-base) var(--ease-out);color:var(--color-text-faint);font-size:10px}
  .tool.open .caret{transform:rotate(90deg)}
  .tool-head .tname{font-weight:var(--weight-medium);color:var(--color-text)}
  .tool-body{display:none;padding:0 var(--space-3) var(--space-3);font-family:var(--font-mono);
             font-size:var(--text-xs);color:var(--color-text-muted);border-top:var(--p-hairline) solid var(--color-line)}
  .tool.open .tool-body{display:block}
  .tool-body pre{white-space:pre-wrap;word-break:break-all;margin:var(--space-1-5) 0;color:var(--color-text)}
  .tool-body .lbl{color:var(--color-text-faint);margin-top:var(--space-2);font-size:var(--text-2xs);letter-spacing:.04em}
  .tool-result{color:var(--color-success)}
  .tools{display:flex;flex-direction:column;gap:var(--space-1-5)}
  .tools:empty{display:none}
  .reason{border:var(--p-hairline) solid var(--color-line);border-radius:var(--radius-lg);
          overflow:hidden;margin:var(--space-2) 0 var(--space-1)}
  .reason-head{padding:var(--space-1-5) var(--space-3);font-size:var(--text-xs);color:var(--color-text-faint);
               cursor:pointer;display:flex;align-items:center;gap:var(--space-2);user-select:none;
               transition:background var(--duration-base) var(--ease-out)}
  .reason-head:hover{background:var(--color-hover)}
  .reason-head .caret{transition:transform var(--duration-base) var(--ease-out);font-size:10px}
  .reason.open .caret{transform:rotate(90deg)}
  .reason-body{display:none;padding:var(--space-05,2px) var(--space-3) var(--space-3);font-size:var(--text-xs);
               color:var(--color-text-muted);white-space:pre-wrap;line-height:1.75;
               border-top:var(--p-hairline) solid var(--color-line)}
  .reason.open .reason-body{display:block}
  /* 思考过程流式态: 思考中 = 品牌蓝描边 + 脉冲点; 思考结束自动折叠, 头部留字数 */
  .reason.streaming{border-color:var(--color-accent);background:var(--color-accent-soft)}
  .reason.streaming .reason-head{color:var(--color-accent)}
  .reason-head .dot{width:6px;height:6px;border-radius:50%;background:var(--color-accent);flex:none;
                    animation:pulse 1.2s var(--ease-out) infinite}
  .reason:not(.streaming) .reason-head .dot{display:none}
  @keyframes pulse{0%,100%{opacity:.25;transform:scale(.8)}50%{opacity:1;transform:scale(1.15)}}
  .reason-len{margin-left:auto;color:var(--color-text-faint);font-size:var(--text-2xs);
              font-variant-numeric:tabular-nums}
  /* 输入栏上方的思考状态 pill: 首 token 到达前也让用户看到"还在思考" + 已用秒数,
     避免长思考(推理模型静默期可逾分钟)被误判为卡死/中断。 */
  #think-pill{display:none;align-items:center;gap:var(--space-2);width:100%;
              padding:var(--space-1) var(--space-3) 0;font-size:var(--text-xs);color:var(--color-text-muted)}
  #think-pill.on{display:inline-flex}
  #think-pill .dot{width:6px;height:6px;border-radius:50%;background:var(--color-accent);flex:none;
                   animation:pulse 1.2s var(--ease-out) infinite}
  #think-pill .tt{font-variant-numeric:tabular-nums}
  .bubble pre[data-lang]::before{content:attr(data-lang);display:block;font-size:10px;letter-spacing:.08em;
                                 text-transform:uppercase;color:var(--color-text-faint);margin-bottom:var(--space-1-5)}
  .bubble del{color:var(--color-text-faint)}
  /* 表格 (CLI 输出常用, 此前会退化成竖线文本) */
  .bubble table{border-collapse:collapse;margin:var(--space-3) 0;font-size:var(--text-xs);
                display:block;overflow-x:auto;max-width:100%}
  .bubble th,.bubble td{border:var(--p-hairline) solid var(--color-line);padding:var(--space-1-5) var(--space-3);
                        text-align:left;vertical-align:top;white-space:nowrap}
  .bubble th{background:var(--color-surface);color:var(--color-text-strong);
             font-weight:var(--weight-section-label)}
  .bubble tbody tr:nth-child(even){background:var(--color-hover)}
  .bubble .chat-img{max-width:320px;max-height:240px;border-radius:var(--radius-md);margin:var(--space-1-5) 0;
                    cursor:pointer;transition:transform var(--duration-base) var(--ease-out)}
  .bubble .chat-img:hover{transform:scale(1.01)}
  .bubble .img-grid{display:flex;flex-wrap:wrap;gap:var(--space-1-5);margin:var(--space-1-5) 0}
  .bubble .img-grid img{max-width:160px;max-height:120px;border-radius:var(--radius-sm);object-fit:cover;
                        cursor:pointer;transition:transform var(--duration-base) var(--ease-out)}
  .bubble .img-grid img:hover{transform:scale(1.02)}
  #lightbox{display:none;position:fixed;inset:0;background:var(--color-scrim-strong);z-index:var(--z-max);
            justify-content:center;align-items:center;cursor:zoom-out}
  #lightbox.open{display:flex}
  #lightbox img{max-width:90vw;max-height:90vh;border-radius:var(--radius-lg);box-shadow:var(--shadow-lg)}
  .stream-cursor{display:inline-block;width:7px;height:15px;background:var(--color-accent);
                 border-radius:1px;vertical-align:-2px;animation:blink 1s step-start infinite}
  @keyframes blink{50%{opacity:0}}
  /* 兜底: 流式结束 (body 打上 .streaming-off) 后若光标因任何异常仍留在 DOM,
     立刻停止闪烁动画 —— 无限动画只要元素还在就永远闪, 这是「输出结束后
     蓝块还在闪」最刺眼的表现。JS 侧已在 endStream() 里移除元素, 这里
     是不依赖 JS 路径的第二道保险。 */
  body.streaming-off .stream-cursor{animation:none;opacity:0}

  /* ===== 输入区 (官方 composer: 32px 大圆角 + 右下模型标识) ===== */
  #inputbar{border-top:var(--p-hairline) solid var(--color-line);padding:var(--space-4) 6vw var(--space-4);
            background:var(--color-bg);flex:none}
  #composer{max-width:var(--p-content-max);margin:0 auto;background:var(--color-composer-bg);
            border:var(--p-hairline) solid var(--color-composer-line);border-radius:var(--radius-composer);
            display:flex;flex-wrap:wrap;align-items:flex-end;padding:var(--space-3) var(--space-3) var(--space-3) var(--space-5);
            box-shadow:var(--shadow-input);transition:border-color var(--duration-base) var(--ease-out),
            box-shadow var(--duration-base) var(--ease-out)}
  #composer:focus-within{border-color:var(--color-composer-focus-line);box-shadow:var(--shadow-input)}
  #composer.dragover{border-color:var(--color-accent);background:var(--color-accent-soft)}
  #inp{flex:1;background:transparent;border:none;outline:none;color:var(--color-text);font-size:var(--text-base);
       resize:none;max-height:180px;font-family:var(--font-ui);line-height:1.7;padding:var(--space-1) var(--space-1-5);
       font-weight:var(--weight-regular)}
  #inp::placeholder{color:var(--color-text-faint)}
  #file-input{display:none}
  /* 附件区: 默认空(隐藏) 不挤占输入行 —— 此前 width:100% 的空 div 把 textarea 挤成 0 宽,
     导致"输入框无法输入"。改为 flex-wrap 布局: 有文件时占最上整行(order:-1), 空时 display:none。 */
  #file-area{display:flex;flex-wrap:wrap;gap:var(--space-1);order:-1;flex-basis:100%;width:100%;
             margin-bottom:var(--space-1)}
  #file-area:empty{display:none}
  .file-tag{display:inline-flex;align-items:center;gap:var(--space-1);background:var(--color-surface);
            border:var(--p-hairline) solid var(--color-line);border-radius:var(--radius-md);
            padding:var(--space-05,2px) var(--space-2);margin:var(--space-1) var(--space-05,2px) 0;
            font-size:var(--text-xs);color:var(--color-text-muted)}
  .file-tag .name{max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .file-tag .remove{cursor:pointer;color:var(--color-text-faint);font-size:var(--text-sm);
                    transition:color var(--duration-base)}
  .file-tag .remove:hover{color:var(--color-danger)}
  .file-tag img{height:30px;width:auto;border-radius:var(--radius-xs);object-fit:cover}
  .composer-btn{background:transparent;border:var(--p-hairline) solid transparent;border-radius:var(--radius-md);
                padding:var(--space-1-5) var(--space-2);color:var(--color-text-faint);cursor:pointer;
                font-size:var(--text-sm);line-height:1.4;display:inline-flex;align-items:center;
                justify-content:center;flex:none;transition:background var(--duration-base) var(--ease-out),
                color var(--duration-base) var(--ease-out);font-family:var(--font-ui)}
  .composer-btn:hover{color:var(--color-accent);background:var(--color-accent-soft)}
  /* 发送键: 官方 --color-send-bg / --color-send-icon (浅色黑底白箭头, 深色白底黑箭头) */
  #send{margin-left:var(--space-1-5);width:32px;height:32px;border:var(--p-hairline) solid transparent;
        border-radius:50%;background:var(--color-send-bg);color:var(--color-send-icon);cursor:pointer;flex:none;
        display:inline-flex;align-items:center;justify-content:center;
        box-shadow:var(--shadow-send);transition:background var(--duration-base) var(--ease-out),
        box-shadow var(--duration-base) var(--ease-out),opacity var(--duration-base) var(--ease-out)}
  #send:hover{opacity:.9;background:var(--color-send-bg-hover);box-shadow:var(--shadow-send-hover)}
  #send:disabled{opacity:.35;cursor:not-allowed;background:var(--color-send-bg-disabled);color:var(--color-send-icon-disabled)}
  #send svg{flex:none}
  #stop{display:none;margin-left:var(--space-1-5);padding:var(--space-1-5) var(--space-3);
        border:var(--p-hairline) solid var(--color-line);border-radius:var(--radius-md);
        background:transparent;color:var(--color-text-muted);font-size:var(--text-xs);cursor:pointer;
        font-family:var(--font-ui);transition:border-color var(--duration-base) var(--ease-out),
        color var(--duration-base) var(--ease-out),background var(--duration-base) var(--ease-out);flex:none}
  #stop:hover{border-color:var(--color-danger);color:var(--color-danger);background:var(--color-danger-soft)}
  #upload-btn{background:transparent;border:none;border-radius:var(--radius-md);padding:var(--space-1) var(--space-2);
              color:var(--color-text-faint);cursor:pointer;font-size:var(--text-sm);margin-left:var(--space-1);
              line-height:1.4;display:inline-flex;align-items:center;justify-content:center;
              transition:background var(--duration-base) var(--ease-out),color var(--duration-base) var(--ease-out)}
  #upload-btn:hover{color:var(--color-accent);background:var(--color-accent-soft)}

  /* ===== 右侧工作面板 (文件 / Diff / 上下文 / MCP / 安全) ===== */
  #rpanel{width:0;min-width:0;overflow:hidden;background:var(--color-sidebar-bg);
          border-left:var(--p-hairline) solid var(--color-line);display:flex;flex-direction:column;
          transition:width var(--duration-base) var(--ease-out),min-width var(--duration-base) var(--ease-out)}
  #rpanel.open{width:340px;min-width:340px}
  .rp-tabs{display:flex;gap:var(--space-05,2px);padding:var(--space-3) var(--space-2) 0;flex:none}
  .rp-tab{flex:1;background:transparent;border:none;border-bottom:2px solid transparent;cursor:pointer;
          padding:var(--space-1-5) var(--space-1);font-size:var(--text-xs);color:var(--color-text-faint);
          font-family:var(--font-ui);white-space:nowrap;transition:color var(--duration-base) var(--ease-out),
          border-color var(--duration-base) var(--ease-out)}
  .rp-tab:hover{color:var(--color-text)}
  .rp-tab.active{color:var(--color-text);border-bottom-color:var(--color-accent);font-weight:var(--weight-medium)}
  .rp-body{flex:1;overflow-y:auto;padding:var(--space-3);font-size:var(--text-xs);color:var(--color-text-muted);
           scrollbar-width:thin;line-height:1.7}
  .rp-body.hidden{display:none}
  .rp-sec{font-size:var(--text-2xs);letter-spacing:.05em;text-transform:uppercase;color:var(--color-text-faint);
          margin:var(--space-3) 0 var(--space-1);font-weight:var(--weight-section-label)}
  .rp-sec:first-child{margin-top:0}
  .rp-row{display:flex;align-items:center;gap:var(--space-2);padding:var(--space-1) var(--space-1-5);
          border-radius:var(--radius-sm);cursor:default;word-break:break-all}
  .rp-row.dir{cursor:pointer}
  .rp-row:hover{background:var(--color-hover)}
  .rp-row .ico{flex:none;color:var(--color-text-faint);font-family:var(--font-mono);font-size:var(--text-xs)}
  .rp-row .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--color-text)}
  .rp-row .sz{flex:none;color:var(--color-text-faint);font-family:var(--font-mono);font-size:10px}
  .rp-empty{color:var(--color-text-faint);padding:var(--space-3) 0}
  .rp-pre{background:var(--color-surface);border:var(--p-hairline) solid var(--color-line);
          border-radius:var(--radius-md);padding:var(--space-2) var(--space-3);overflow-x:auto;
          font-family:var(--font-mono);font-size:10px;line-height:1.6;color:var(--color-text);
          white-space:pre;max-height:52vh}
  .rp-bar{height:6px;border-radius:var(--radius-full);background:var(--color-surface);
          overflow:hidden;margin:var(--space-1) 0 var(--space-2)}
  .rp-bar i{display:block;height:100%;background:var(--color-accent);border-radius:var(--radius-full);
            transition:width var(--duration-base) var(--ease-out)}
  .rp-bar.warn i{background:var(--color-danger)}
  .rp-kv{display:flex;justify-content:space-between;gap:var(--space-2);padding:1px 0}
  .rp-kv b{color:var(--color-text);font-weight:var(--weight-medium);font-family:var(--font-mono)}
  .gate{display:flex;gap:var(--space-2);padding:var(--space-1-5) 0;border-bottom:var(--p-hairline) dashed var(--color-line)}
  .gate:last-child{border-bottom:none}
  .gate .n{width:16px;flex:none;color:var(--color-accent);font-family:var(--font-mono)}
  .gate .t{color:var(--color-text);font-weight:var(--weight-medium)}
  .gate .d{color:var(--color-text-faint);font-size:10px}
  .blk{border-left:2px solid var(--color-danger);padding:var(--space-1) var(--space-2);margin:var(--space-1) 0;
       background:var(--color-danger-soft);border-radius:0 var(--radius-sm) var(--radius-sm) 0}
  .blk .h{color:var(--color-text);font-weight:var(--weight-medium)}
  #rp-toggle{position:absolute;right:var(--space-3);top:var(--space-3);z-index:var(--z-tooltip)}

  /* ===== 审批弹窗 (allow / deny) ===== */
  #approve,#trust{display:none;position:fixed;inset:0;background:var(--color-scrim-strong);z-index:var(--z-modal);
           justify-content:center;align-items:center;padding:var(--space-5)}
  #approve.open,#trust.open{display:flex}
  #approve .box,#trust .box{background:var(--color-surface-raised);border:var(--p-hairline) solid var(--color-line-strong);
                border-radius:var(--radius-lg);box-shadow:var(--shadow-lg);max-width:560px;width:100%;
                max-height:86vh;overflow-y:auto;padding:var(--space-5)}
  #approve .hd,#trust .hd{font-size:var(--text-base);font-weight:var(--weight-semibold);color:var(--color-text-strong);
               margin-bottom:var(--space-2)}
  #approve .risk{display:inline-block;padding:1px var(--space-2);border-radius:var(--radius-full);
                 font-size:var(--text-2xs);font-weight:var(--weight-medium);margin-bottom:var(--space-3)}
  #approve .risk.critical,#approve .risk.high{background:var(--color-danger-soft);color:var(--color-danger)}
  #approve .risk.medium{background:var(--color-accent-soft);color:var(--color-accent)}
  #approve .cmd,#trust .cmd{font-family:var(--font-mono);font-size:var(--text-xs);background:var(--color-surface);
                border:var(--p-hairline) solid var(--color-line);border-radius:var(--radius-md);
                padding:var(--space-2) var(--space-3);white-space:pre-wrap;word-break:break-all;
                color:var(--color-text);margin-bottom:var(--space-3)}
  #approve .lbl{font-size:var(--text-2xs);letter-spacing:.05em;text-transform:uppercase;
                color:var(--color-text-faint);margin:var(--space-3) 0 var(--space-1)}
  #approve ul{margin:0;padding-left:var(--space-5);color:var(--color-text-muted)}
  #approve li{margin:var(--space-05,2px) 0}
  #approve .acts{display:flex;gap:var(--space-2);justify-content:flex-end;margin-top:var(--space-5)}
  #approve .acts button{padding:var(--space-2) var(--space-4);border-radius:var(--radius-md);
                        font-size:var(--text-sm);font-family:var(--font-ui);cursor:pointer;
                        border:var(--p-hairline) solid var(--color-line-strong);background:transparent;
                        color:var(--color-text);transition:background var(--duration-base) var(--ease-out)}
  #approve .acts button:hover{background:var(--color-hover)}
  #approve .acts button.allow{background:var(--color-danger);color:#fff;border-color:transparent}
  #approve .acts button.allow:hover{opacity:.9}

  /* ===== @ 文件提及下拉 ===== */
  #mention{display:none;position:absolute;left:0;right:0;bottom:calc(100% + var(--space-1));
           background:var(--color-surface-raised);border:var(--p-hairline) solid var(--color-line-strong);
           border-radius:var(--radius-md);box-shadow:var(--shadow-lg);max-height:220px;overflow-y:auto;
           z-index:var(--z-tooltip)}
  #mention.open{display:block}
  #mention .mi{padding:var(--space-1-5) var(--space-3);font-size:var(--text-xs);cursor:pointer;
               color:var(--color-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
               font-family:var(--font-mono)}
  #mention .mi:hover,#mention .mi.sel{background:var(--color-accent-soft)}
  #composer{position:relative}

  /* ===== 空会话 Hero 态 (Kimi 官网经典版式: 粒子在上, 输入框居中) =====
     由 body.hero 驱动: 对话未开始时输入区脱离底部、与粒子一起垂直居中;
     发出第一条消息后移除 hero, 输入区回落到底部, 布局与常规对话一致。 */
  body.hero #main{justify-content:center}
  body.hero #msgs{flex:none;overflow:visible;padding:0 6vw}
  body.hero #welcome{height:236px;min-height:0;margin:0;padding:0;justify-content:flex-end}
  body.hero #tuan-canvas{position:absolute;inset:0}
  body.hero #greet{display:block;width:100%;text-align:center;font-family:var(--font-ui);
      font-size:22px;font-weight:var(--weight-semibold);color:var(--color-text-strong);
      letter-spacing:.01em;line-height:1.3;padding:0 0 var(--space-3);animation:greetIn .5s var(--ease-out)}
  @keyframes greetIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
  body.hero #inputbar{border-top:none;background:transparent;padding-bottom:var(--space-2)}
  body.hero #composer{box-shadow:var(--shadow-lg)}
    /* 常规态: 粒子区不占高度 (欢迎屏仅作隐藏占位) */
  body:not(.hero) #welcome{height:0;min-height:0;overflow:hidden}

  /* ===== 插件面板 (可视化热插拔) ===== */
  .pl-group{font-size:var(--text-2xs);letter-spacing:.05em;text-transform:uppercase;
            color:var(--color-text-faint);margin:var(--space-3) 0 var(--space-1);
            font-weight:var(--weight-section-label);display:flex;justify-content:space-between}
  .pl{display:flex;align-items:center;gap:var(--space-2);padding:var(--space-1-5) var(--space-2);
      border-radius:var(--radius-sm);transition:background var(--duration-base) var(--ease-out)}
  .pl:hover{background:var(--color-hover)}
  .pl .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
          color:var(--color-text);font-family:var(--font-mono);font-size:var(--text-xs)}
  .pl .tag{font-size:10px;color:var(--color-text-faint);flex:none;font-family:var(--font-mono)}
  /* 开关 */
  .sw{position:relative;width:32px;height:18px;flex:none;border-radius:var(--radius-full);
      background:var(--color-line-strong);cursor:pointer;border:none;padding:0;
      transition:background var(--duration-base) var(--ease-out)}
  .sw::after{content:'';position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
             background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);
             transition:transform var(--duration-base) var(--ease-out)}
  .sw.on{background:var(--color-accent)}
  .sw.on::after{transform:translateX(14px)}
  .sw:disabled{opacity:.45;cursor:not-allowed}

  /* ===== 圆角化微调 (面板 / 气泡 / 控件) ===== */
  .bubble{border-radius:var(--radius-lg)}
  .msg.user .bubble{border-radius:var(--radius-lg) var(--radius-lg) var(--radius-xs) var(--radius-lg)}
  .tool,.reason{border-radius:var(--radius-lg)}
  .file-tag,.chip{border-radius:var(--radius-full)}
  #newbtn,#searchbox,.sess{border-radius:var(--radius-md)}
  #rpanel{--rp-w:340px}
  #rpanel.open{width:var(--rp-w);min-width:var(--rp-w)}

  @media (max-width:760px){
    #sidebar{width:208px;min-width:208px}
    #msgs,#inputbar{padding-left:4vw;padding-right:4vw}
    #rpanel.open{width:280px;min-width:280px}
  }
  @media (max-width:640px){
    #sidebar{width:64px;min-width:64px}
    .brand .tuan,#searchbox,.ws-label,#ws-name,
    #newbtn{justify-content:center;padding:var(--space-2) 0}
    #newbtn .lbl{display:none}
    #inp{font-size:16px}
    #msgs{padding-top:var(--space-5)}
    .brand{padding:var(--space-4) var(--space-3) 0}
    #sidebar .foot{flex-direction:column;align-items:flex-start;gap:0}
    #sidefoot{display:none}
    #rpanel.open{position:absolute;right:0;top:0;bottom:0;z-index:var(--z-modal);width:86vw;min-width:86vw}
  }

  /* ===== 代码块: 语言标签 + 复制按钮 + 语法高亮 (离线零依赖) ===== */
  .md pre{margin:var(--space-2) 0;padding:var(--space-3);background:var(--color-code-bg,#0d1117);
          border:var(--p-hairline) solid var(--color-line);border-radius:var(--radius-md);
          overflow:auto;scrollbar-width:thin;max-height:520px}
  .md pre code{font-family:var(--font-mono);font-size:var(--text-sm);line-height:1.6;
               color:var(--color-code,#e6edf3);white-space:pre;display:block}
  .code-block{margin:var(--space-2) 0}
  .code-block>.code-head{display:flex;align-items:center;justify-content:space-between;
          background:var(--color-code-bg,#0d1117);border:var(--p-hairline) solid var(--color-line);
          border-bottom:none;border-radius:var(--radius-md) var(--radius-md) 0 0;padding:var(--space-1) var(--space-2)}
  .code-block>.code-head .code-lang{font-family:var(--font-mono);font-size:var(--text-2xs);
          color:var(--color-text-faint);text-transform:uppercase;letter-spacing:.04em}
  .code-block>.code-head .code-copy{background:transparent;border:var(--p-hairline) solid var(--color-line);
          color:var(--color-text-faint);font-size:var(--text-2xs);border-radius:var(--radius-sm);
          padding:2px var(--space-2);cursor:pointer;font-family:var(--font-ui);transition:all var(--duration-base) var(--ease-out)}
  .code-block>.code-head .code-copy:hover{color:var(--color-accent);border-color:var(--color-accent)}
  .code-block>.md pre{border-radius:0 0 var(--radius-md) var(--radius-md);margin:0}
  /* 语法高亮 token (TUI 蓝调; 浅色主题用下方规则覆盖) */
  .tk-c{color:#8c8475;font-style:italic}
  .tk-s{color:#7fbf95}
  .tk-n{color:#79c0ff}
  .tk-k{color:#c89fe0}
  .tk-b{color:#79c0ff}
  .tk-f{color:#7fa8e0}
  .tk-o{color:#79c0ff}
  :root[data-color-scheme="light"] .md pre{background:var(--color-code-bg,#f6f8fa)}
  :root[data-color-scheme="light"] .code-block>.code-head{background:var(--color-code-bg,#f6f8fa);border-color:var(--color-line)}
  :root[data-color-scheme="light"] .md pre code{color:var(--color-code,#24292f)}
  :root[data-color-scheme="light"] .tk-c{color:#998f7e}
  :root[data-color-scheme="light"] .tk-s{color:#3f7d5a}
  :root[data-color-scheme="light"] .tk-n{color:#0550ae}
  :root[data-color-scheme="light"] .tk-k{color:#9b5fb0}
  :root[data-color-scheme="light"] .tk-b{color:#0550ae}
  :root[data-color-scheme="light"] .tk-f{color:#3563a8}
  :root[data-color-scheme="light"] .tk-o{color:#0550ae}

  /* ===== 斜杠命令面板 (对标 TUI /cmd 补全) ===== */
  #slash{display:none;position:absolute;left:0;right:0;bottom:calc(100% + var(--space-1));
         background:var(--color-surface);border:var(--p-hairline) solid var(--color-line);
         border-radius:var(--radius-lg);box-shadow:var(--shadow-pop,0 8px 28px rgba(0,0,0,.28));
         max-height:320px;overflow:auto;scrollbar-width:thin;z-index:var(--z-pop,40);padding:var(--space-1)}
  #slash.open{display:block}
  #slash .sl-head{font-size:var(--text-2xs);color:var(--color-text-faint);padding:var(--space-1) var(--space-2);
          text-transform:uppercase;letter-spacing:.05em}
  #slash .sl{display:flex;align-items:baseline;gap:var(--space-2);padding:var(--space-1-5) var(--space-2);
          border-radius:var(--radius-md);cursor:pointer}
  #slash .sl.sel{background:var(--color-accent-soft)}
  #slash .sl .nm{font-family:var(--font-mono);font-size:var(--text-sm);color:var(--color-accent);flex:none}
  #slash .sl .ds{font-size:var(--text-2xs);color:var(--color-text-muted);line-height:1.4;
          overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #slash .sl-empty{padding:var(--space-3);color:var(--color-text-faint);font-size:var(--text-xs)}

  /* ===== 工作区信任对话框 (对标 TUI prompt_trust) ===== */
  #trust .box{max-width:440px}
  #trust .lvls{display:flex;gap:var(--space-2);margin-top:var(--space-3)}
  #trust .lvl{flex:1;background:var(--color-surface);border:var(--p-hairline) solid var(--color-line);
          border-radius:var(--radius-md);padding:var(--space-3);cursor:pointer;text-align:left;
          transition:all var(--duration-base) var(--ease-out)}
  #trust .lvl:hover{border-color:var(--color-accent)}
  #trust .lvl h4{margin:0 0 var(--space-1);font-size:var(--text-sm);font-family:var(--font-ui)}
  #trust .lvl p{margin:0;font-size:var(--text-2xs);color:var(--color-text-muted);line-height:1.5}
  #trust .lvl[data-lvl="trusted"]:hover{border-color:var(--color-success,#2da44e)}
  #trust .lvl[data-lvl="untrusted"]:hover{border-color:var(--color-danger)}

  /* ===== 设置面板 (对标 TUI /config /model /permissions) ===== */
  #settings{display:none;position:fixed;inset:0;background:var(--color-scrim-strong);z-index:var(--z-modal);
            justify-content:center;align-items:center;padding:var(--space-5)}
  #settings.open{display:flex}
  #settings .sbox{background:var(--color-surface-raised);border:var(--p-hairline) solid var(--color-line-strong);
            border-radius:var(--radius-lg);box-shadow:var(--shadow-lg);width:min(780px,94vw);height:auto;
            max-height:min(660px,90vh);display:flex;flex-direction:column;overflow:hidden}
  #settings .shead{display:flex;align-items:center;justify-content:space-between;padding:var(--space-4) var(--space-5);
            border-bottom:var(--p-hairline) solid var(--color-line);flex:none}
  #settings .stitle{font-size:var(--text-base);font-weight:var(--weight-semibold);color:var(--color-text-strong);font-family:var(--font-ui)}
  #settings .sclose{background:transparent;border:none;color:var(--color-text-muted);font-size:16px;cursor:pointer;line-height:1}
  #settings .sclose:hover{color:var(--color-text)}
  #settings .sbody{flex:1;display:flex;min-height:0}
  #settings .snav{width:150px;flex:none;border-right:var(--p-hairline) solid var(--color-line);padding:var(--space-3);
            overflow-y:auto;display:flex;flex-direction:column;gap:2px}
  #settings .snav button{text-align:left;background:transparent;border:none;border-radius:var(--radius-md);
            padding:var(--space-2) var(--space-3);font-size:var(--text-sm);color:var(--color-text-muted);cursor:pointer;font-family:var(--font-ui)}
  #settings .snav button:hover{background:var(--color-hover);color:var(--color-text)}
  #settings .snav button.active{background:var(--color-accent-soft);color:var(--color-accent);font-weight:var(--weight-medium)}
  #settings .scontent{flex:1;overflow-y:auto;padding:var(--space-4) var(--space-5);min-width:0}
  #settings .ssec{font-size:var(--text-2xs);text-transform:uppercase;letter-spacing:.05em;color:var(--color-text-faint);
            margin:var(--space-4) 0 var(--space-1);font-weight:var(--weight-section-label)}
  #settings .ssec:first-child{margin-top:0}
  #settings .srow{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);
            padding:var(--space-2-5) 0;border-bottom:var(--p-hairline) solid var(--color-line);flex-wrap:wrap}
  #settings .srow.col{flex-direction:column;align-items:stretch}
  #settings .srow .lab{font-size:var(--text-sm);color:var(--color-text)}
  #settings .srow .hint{font-size:var(--text-2xs);color:var(--color-text-faint);width:100%;margin-top:2px;line-height:1.5}
  #settings select,#settings input[type=text],#settings input[type=number],#settings input[type=password]{
            background:var(--color-bg);color:var(--color-text);border:var(--p-hairline) solid var(--color-line-strong);
            border-radius:var(--radius-md);padding:var(--space-1-5) var(--space-2);font-size:var(--text-sm);
            font-family:var(--font-ui);min-width:200px;max-width:340px;outline:none}
  #settings select:focus,#settings input:focus{border-color:var(--color-accent)}
  #settings input[type=checkbox]{width:16px;height:16px;accent-color:var(--color-accent);cursor:pointer}
  #settings .btn{background:var(--color-accent);color:#fff;border:none;border-radius:var(--radius-md);
            padding:var(--space-2) var(--space-4);font-size:var(--text-sm);cursor:pointer;font-family:var(--font-ui)}
  #settings .btn:hover{opacity:.9}
  #settings .btn.ghost{background:transparent;color:var(--color-text);border:var(--p-hairline) solid var(--color-line-strong)}
  #settings .btn.sm{padding:var(--space-1) var(--space-2-5);font-size:var(--text-xs)}
  #settings .badge{font-size:var(--text-2xs);padding:1px var(--space-2);border-radius:var(--radius-full);font-family:var(--font-ui)}
  #settings .badge.ok{background:var(--color-success);color:#fff}
  #settings .badge.no{background:var(--color-hover);color:var(--color-text-muted)}
  #settings .kv{font-size:var(--text-xs);color:var(--color-text-muted);font-family:var(--font-mono);word-break:break-all}
  #settings .note{font-size:var(--text-2xs);color:var(--color-success);margin-top:var(--space-2);min-height:14px}
  #settings .note.err{color:var(--color-danger)}
  #settings .cs-opt{display:inline-flex;gap:var(--space-2)}
  #settings .cs-opt label{display:inline-flex;align-items:center;gap:var(--space-1);font-size:var(--text-sm);
            color:var(--color-text);cursor:pointer;padding:var(--space-1) var(--space-2);border:var(--p-hairline) solid var(--color-line);
            border-radius:var(--radius-md)}
  #settings .cs-opt input{accent-color:var(--color-accent)}
  /* 快捷键速查: 键帽 + 说明, 与设置面板其余行保持同一栅格 */
  #settings .srow.kbd-row{gap:var(--space-3);border-bottom:var(--p-hairline) solid var(--color-line)}
  #settings .kbd-row .kbd{flex:none;font-family:var(--font-mono);font-size:var(--text-xs);
            background:var(--color-hover);color:var(--color-text);border:var(--p-hairline) solid var(--color-line-strong);
            border-radius:var(--radius-sm);padding:2px var(--space-2);min-width:120px;text-align:center;
            box-shadow:0 1px 0 var(--color-line-strong)}
  #settings .kbd-row .lab{flex:1;min-width:0}
</style>
</head>
<body>
  <aside id="sidebar">
    <div class="brand"><span class="dot"></span><span class="tuan">TUAN</span></div>
    <button id="newbtn">
      <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M8 2.5v11M2.5 8h11"/></svg>
      <span class="lbl" data-i18n="web.new_session">新建会话</span>
    </button>
    <input id="searchbox" type="text" data-i18n-ph="web.search" placeholder="搜索会话… (Ctrl+K)">
    <div class="ws-label" data-i18n="web.sessions">会话</div>
    <div id="ws-name"></div>
    <div id="sessions"></div>
    <div class="foot">
      <button class="tb-btn" id="btn-theme" title="切换主题">
        <svg class="ico-sun" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/></svg>
        <svg class="ico-moon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="display:none"><path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11z"/></svg>
      </button>
      <button class="tb-btn" id="btn-export" title="导出 Markdown (Ctrl+E)">
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v8.5M4.5 7l3.5 3.5L11.5 7"/><path d="M2.5 13.5h11"/></svg>
        <span data-i18n="web.export">导出</span>
      </button>
      <button class="tb-btn" id="btn-panel" title="工作面板 (Ctrl+B)">
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="1.8" y="2.5" width="12.4" height="11" rx="1.6"/><path d="M10 2.5v11"/></svg>
        <span data-i18n="web.panel">面板</span>
      </button>
      <button class="tb-btn" id="btn-settings" title="设置">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.09a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.09a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        <span data-i18n="web.settings">设置</span>
      </button>
      <span class="sp"></span>
    </div>
    <div class="foot" style="padding-top:var(--space-05,2px)"><div id="sidefoot">…</div></div>
  </aside>
  <main id="main">
    <div id="msgs">
      <div id="welcome">
        <canvas id="tuan-canvas"></canvas>
        <div id="greet"></div>
      </div>
    </div>
    <div id="inputbar">
      <div id="think-pill"><span class="dot"></span><span id="think-label" data-i18n="web.thinking">思考中</span><span class="tt" id="think-time">0.0s</span></div>
      <div id="composer">
        <div id="file-area"></div>
        <textarea id="inp" rows="1" data-i18n-ph="web.input" placeholder="输入消息..."></textarea>
        <input type="file" id="file-input" multiple accept="image/*,.txt,.md,.py,.js,.ts,.json,.yaml,.yml,.csv,.log">
        <button class="composer-btn" id="upload-btn" title="上传文件">
          <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7.5 1.5v8.5M4.5 3.5l3-2.5 3 2.5"/><path d="M2.5 9v4a1.5 1.5 0 0 0 1.5 1.5h8a1.5 1.5 0 0 0 1.5-1.5V9"/></svg>
        </button>
        <button id="send" title="发送">
          <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 8L14 2.5 8 13.5V8.5"/><path d="M2.5 8l5.5.5"/></svg>
        </button>
        <button id="stop">■ 停止</button>
      </div>
    </div>
  </main>
  <aside id="rpanel">
    <div class="rp-tabs">
      <button class="rp-tab active" data-tab="files" data-i18n="web.tab_files">文件</button>
      <button class="rp-tab" data-tab="diff" data-i18n="web.tab_diff">Diff</button>
      <button class="rp-tab" data-tab="ctx" data-i18n="web.tab_ctx">上下文</button>
      <button class="rp-tab" data-tab="mcp" data-i18n="web.tab_mcp">MCP</button>
      <button class="rp-tab" data-tab="plugins" data-i18n="web.tab_plugins">插件</button>
      <button class="rp-tab" data-tab="sec" data-i18n="web.tab_sec">安全</button>
    </div>
    <div class="rp-body" id="rp-files"><div class="rp-empty">加载中…</div></div>
    <div class="rp-body hidden" id="rp-diff"><div class="rp-empty">加载中…</div></div>
    <div class="rp-body hidden" id="rp-ctx"><div class="rp-empty">加载中…</div></div>
    <div class="rp-body hidden" id="rp-mcp"><div class="rp-empty">加载中…</div></div>
    <div class="rp-body hidden" id="rp-plugins"><div class="rp-empty">加载中…</div></div>
    <div class="rp-body hidden" id="rp-sec"><div class="rp-empty">加载中…</div></div>
  </aside>

<div id="approve"><div class="box">
  <div class="hd" data-i18n="web.approve_title">需要你确认</div>
  <div id="ap-risk"></div>
  <div class="cmd" id="ap-cmd"></div>
  <div id="ap-reasons"></div>
  <div id="ap-blast"></div>
  <div id="ap-sugg"></div>
  <div class="acts">
    <button id="ap-deny" data-i18n="web.approve_deny">拒绝</button>
    <button id="ap-allow" class="allow" data-i18n="web.approve_allow">允许执行</button>
  </div>
</div></div>

<div id="mention"></div>

<div id="slash"><div class="sl-head" data-i18n="web.cmd_palette">命令面板 · 输入筛选, ↑↓ 选择, 回车插入</div><div id="slash-list"></div></div>

<div id="trust"><div class="box">
  <div class="hd" data-i18n="web.trust_title">信任此工作区？</div>
  <div id="trust-path" class="cmd"></div>
  <div id="trust-desc" class="rp-empty">首次打开该目录，请选择信任级别。信任级别决定 Agent 在此目录的权限边界。</div>
  <div class="lvls">
    <button class="lvl" data-lvl="trusted"><h4 data-i18n="web.trust_trusted">完全信任</h4><p data-i18n="web.trust_trusted_d">完整权限（仍受安全引擎约束），可执行 shell 与写操作。</p></button>
    <button class="lvl" data-lvl="limited"><h4 data-i18n="web.trust_limited">受限</h4><p data-i18n="web.trust_limited_d">只读与规划可用，shell 需每次确认。</p></button>
    <button class="lvl" data-lvl="untrusted"><h4 data-i18n="web.trust_untrusted">不信任</h4><p data-i18n="web.trust_untrusted_d">只读，禁止执行 shell 命令。</p></button>
  </div>
</div></div>

<div id="settings"><div class="sbox">
  <div class="shead"><span class="stitle" data-i18n="web.settings">设置</span><button class="sclose" id="settings-close" title="关闭">✕</button></div>
  <div class="sbody">
    <nav class="snav" id="settings-nav"></nav>
    <div class="scontent" id="settings-content"><div class="rp-empty">加载中…</div></div>
  </div>
</div></div>

<script>
(function(){
  var msgsEl=document.getElementById('msgs');
  var inp=document.getElementById('inp');
  var send=document.getElementById('send');
  var stopBtn=document.getElementById('stop');
  var sessionsEl=document.getElementById('sessions');
  var searchBox=document.getElementById('searchbox');
  var welcomeEl=document.getElementById('welcome');
  var current=null, running=false, abortCtrl=null, allSessions=[], pendingFiles=[];
  var modelLabel='';
  /* hero 态 = 对话未开始: 输入区脱离底部、与粒子一起垂直居中 (Kimi 官网经典版式)。
     发出第一条消息即移除, 输入区回落到常规底部布局。 */
  /* 欢迎页随机问候语 (每次新建会话随机一句, hero 态每 6s 轮换一条) */
  var GREETINGS=[
    '今天想干什么呢？','今天想做点什么？','有什么可以帮你？','来聊聊吧，今天从哪开始？',
    '准备开始了吗？','今天的目标是什么？','我能帮你做些什么？','有什么新想法？',
    '从哪儿开始呢？','今天想攻克点什么？','需要我帮你做点什么？','聊聊你的计划吧',
    '今天状态如何，想做什么？','我准备好了，你说','有什么想让我看看的？','开始今天的探索吧',
    '想写点代码，还是聊聊天？','今天有什么难题？','我在这儿，随时开始','先从哪件事说起？',
    '今天想学点或做点什么？','给我个任务吧','准备好了吗，开始？','今天想实现什么？'
  ];
  var greetTimer=null;
  function pickGreet(){
    var el=document.getElementById('greet');if(!el)return;
    el.textContent=GREETINGS[Math.floor(Math.random()*GREETINGS.length)];
    /* 重放入场动画: 先清掉再强制回流, 让 CSS animation 重新触发 */
    el.style.animation='none';void el.offsetWidth;el.style.animation='';
  }
  function showWelcome(){
    document.body.classList.add('hero');welcomeEl.style.display='flex';startParticles();
    pickGreet();
    if(greetTimer)clearInterval(greetTimer);
    greetTimer=setInterval(pickGreet,6000);
  }
  function hideWelcome(){
    document.body.classList.remove('hero');welcomeEl.style.display='none';stopParticles();
    if(greetTimer){clearInterval(greetTimer);greetTimer=null;}
  }
  /* 清空消息区, 但**保留** #welcome —— 它是 #msgs 的子节点。
     此前 6 处直接 msgsEl.innerHTML='' 会把 welcome 一起删掉: welcomeEl 变量仍指向
     那个已脱离文档的孤儿节点, 之后 showWelcome() 只是给孤儿设 display:flex, 而
     startParticles 里 `!welcomeEl.offsetParent` 直接 return。结果: 新建会话 /
     Ctrl+N / /clear / 删会话之后, 欢迎屏与粒子动画**永久消失**, 只能刷新页面恢复。 */
  function clearMessages(){
    Array.prototype.slice.call(msgsEl.children).forEach(function(el){
      if(el!==welcomeEl)el.remove();
    });
  }

  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function nowStr(){return new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}

  /* ---- TUAN 呼吸粒子 (欢迎屏, 替换原 KIMI 标识) ----
     粒子采样 "TUAN" 文字像素, 各自围绕锚点呼吸脉动,
     鼠标靠近时被推开 (斥力), 移开后弹簧回位。
     颜色取自官方 token: 浅色文字 rgba(0,0,0,.9) / 品牌蓝 #1783ff;
     深色文字 rgba(255,255,255,.84) / 品牌蓝 #1a88ff。 */
  var particle = {raf:null, cv:null, ctx:null, parts:[], mouse:{x:-9999,y:-9999}, run:false};
  function buildParticleTargets(W,H){
    var off=document.createElement('canvas');
    var S=760, SH=240;
    off.width=S; off.height=SH;
    var octx=off.getContext('2d');
    octx.fillStyle='#000';
    /* 更小的字号 + 更密的采样步长 → 细砂感 (对标 Kimi 官网经典版的粒子字) */
    var fs=Math.min(92, S/7.6);
    octx.font='700 '+fs+'px system-ui,-apple-system,"Segoe UI",Arial,sans-serif';
    octx.textAlign='center'; octx.textBaseline='middle';
    octx.fillText('TUAN',S/2,SH/2+4);
    var img=octx.getImageData(0,0,S,SH), data=img.data;
    var targets=[], step=3;
    var scaleX=W/S, scaleY=H/SH;
    for(var y=0;y<SH;y+=step){
      for(var x=0;x<S;x+=step){
        if(data[(y*S+x)*4+3]>110){
          targets.push([x*scaleX, y*scaleY]);
        }
      }
    }
    return targets;
  }
  function startParticles(){
    var cv=document.getElementById('tuan-canvas');
    if(!cv||!welcomeEl.offsetParent)return;
    if(particle.run){resizeParticles();return;}
    particle.cv=cv;
    var ctx=cv.getContext('2d');
    particle.ctx=ctx; particle.run=true;
    var W,H,DPR=Math.min(2,window.devicePixelRatio||1);
    function resize(){
      W=welcomeEl.clientWidth||window.innerWidth;
      H=welcomeEl.clientHeight||Math.max(190,window.innerHeight*0.5);
      /* 尺寸未就绪 (display:none / 布局未完成) 时跳过, 避免按 0 尺寸建位图 */
      if(W<40||H<40){particle.run=false;return;}
      particle.run=true;
      /* 位图必须与显示尺寸**完全一致**: 此前有 Math.max(320,·) 的最小值钳制,
         而 hero 态粒子区只有 190px 高 —— 位图 320 被压到 190 显示,
         所有粒子整体上移且纵向压缩 (观感"粒子错位")。 */
      cv.width=W*DPR; cv.height=H*DPR;
      cv.style.width=W+'px'; cv.style.height=H+'px';
      ctx.setTransform(DPR,0,0,DPR,0,0);
      var targets=buildParticleTargets(W,H);
      particle.parts=targets.map(function(t){
        /* 初始位置贴近锚点 (±30px), 首帧即成型, 呼吸/鼠标交互仍自然 */
        var jx=t[0]+(Math.random()*2-1)*30, jy=t[1]+(Math.random()*2-1)*30;
        return {tx:t[0], ty:t[1], x:jx, y:jy, vx:0, vy:0,
                ph:Math.random()*Math.PI*2, sp:0.7+Math.random()*1.4,
                amp:0.8+Math.random()*1.4, r:0.5+Math.random()*0.8};
      });
    }
    particle.resize=resize;
    resize();
    function frame(){
      if(!particle.run)return;
      var w=welcomeEl.clientWidth, h=welcomeEl.clientHeight;
      ctx.clearRect(0,0,w,h);
      var dark=document.documentElement.getAttribute('data-color-scheme')==='dark';
      /* 主题 token: 浅色 text rgba(0,0,0,.9) + accent #1783ff ; 深色 text rgba(255,255,255,.84) + accent #1a88ff */
      var base=dark?'255,255,255':'0,0,0';
      var brand=dark?'26,136,255':'23,131,255';
      var t=performance.now()/1000;
      var mx=particle.mouse.x, my=particle.mouse.y;
      var parts=particle.parts;
      for(var i=0;i<parts.length;i++){
        var p=parts[i];
        var br=Math.sin(t*p.sp+p.ph)*p.amp;
        var btx=p.tx+Math.sin(t*p.sp*0.7+p.ph)*p.amp*0.6;
        var bty=p.ty+Math.cos(t*p.sp*0.5+p.ph)*p.amp*0.6;
        /* 弹簧回锚点 */
        var dx=btx-p.x, dy=bty-p.y;
        p.vx+=dx*0.018; p.vy+=dy*0.018;
        /* 鼠标斥力 */
        var mdx=p.x-mx, mdy=p.y-my;
        var dist2=mdx*mdx+mdy*mdy;
        var MR=140;
        if(dist2<MR*MR){
          var d=Math.sqrt(dist2)||1;
          var f=(1-d/MR)*2.6;
          p.vx+=mdx/d*f; p.vy+=mdy/d*f;
        }
        /* 阻尼 */
        p.vx*=0.88; p.vy*=0.88;
        p.x+=p.vx; p.y+=p.vy;
        /* 绘制: 细砂感 —— 半径小、透明度低, 靠密度而非颗粒体积成型 */
        var alpha=0.42+Math.sin(t*p.sp+p.ph)*0.22;
        var isBrand=(i%9===0);
        ctx.beginPath();
        ctx.arc(p.x,p.y,p.r*(1+br*0.12),0,Math.PI*2);
        ctx.fillStyle='rgba('+(isBrand?brand:base)+','+alpha.toFixed(3)+')';
        ctx.fill();
      }
      particle.raf=requestAnimationFrame(frame);
    }
    particle.raf=requestAnimationFrame(frame);
  }
  function resizeParticles(){
    if(particle.resize)particle.resize();
  }
  function stopParticles(){
    if(!particle.run)return;
    particle.run=false;
    if(particle.raf)cancelAnimationFrame(particle.raf);
    particle.raf=null;
    if(particle.ctx&&particle.cv)particle.ctx.clearRect(0,0,particle.cv.width,particle.cv.height);
  }
  /* resize / mousemove 监听器**只绑一次** (在 IIFE 作用域内)。
     此前它们写在 startParticles 里: 每显示一次欢迎屏就新增一组, 而 stopParticles
     只 cancelAnimationFrame、从不 removeEventListener。反复新建会话十几轮后,
     每次 mousemove 都会执行十几次 getBoundingClientRect(), 明显卡顿。
     现用 particle.run 守卫: 未运行时直接 return, 零开销。 */
  window.addEventListener('resize',function(){ if(!particle.run)return; resizeParticles(); });
  window.addEventListener('mousemove',function(e){
    if(!particle.run)return;
    var r=welcomeEl.getBoundingClientRect();
    particle.mouse.x=e.clientX-r.left; particle.mouse.y=e.clientY-r.top;
  },{passive:true});

  /* ---- 图片灯箱 ---- */
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
      el.addEventListener('click',function(){pendingFiles.splice(parseInt(el.dataset.idx,10),1);renderFileTags();});
    });
  }
  composer.addEventListener('dragover',function(e){e.preventDefault();e.stopPropagation();composer.classList.add('dragover');});
  composer.addEventListener('dragleave',function(e){e.preventDefault();e.stopPropagation();composer.classList.remove('dragover');});
  composer.addEventListener('drop',function(e){e.preventDefault();e.stopPropagation();composer.classList.remove('dragover');if(e.dataTransfer.files.length){addFiles(e.dataTransfer.files);}});

  /* ---- 主题切换 (data-color-scheme + tuan-web.color-scheme) ---- */
  var THEME_KEY='tuan-web.color-scheme';
  function getTheme(){var t=localStorage.getItem(THEME_KEY);return t==='dark'?'dark':(t==='system'?'system':'light');}
  function setTheme(t){
    document.documentElement.setAttribute('data-color-scheme',t);
    localStorage.setItem(THEME_KEY,t);
    var dark=t==='dark'||(t==='system'&&window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches);
    var btn=document.getElementById('btn-theme');
    btn.querySelector('.ico-sun').style.display=dark?'none':'block';
    btn.querySelector('.ico-moon').style.display=dark?'block':'none';
    if(particle.run&&particle.ctx&&particle.cv){
      particle.ctx.clearRect(0,0,particle.cv.width,particle.cv.height);
    }
  }
  setTheme(getTheme());
  document.getElementById('btn-theme').addEventListener('click',function(){setTheme(getTheme()==='dark'?'light':'dark');});

  /* ---- 轻量 Markdown 渲染 (安全: 先转义再处理标记) ---- */
  function inline(s){
    s=esc(s);
    s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
    s=s.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
    s=s.replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>');
    s=s.replace(/~~([^~]+)~~/g,'<del>$1</del>');
    s=s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
    return s;
  }
  function isBlockStart(t){
    return /^```/.test(t)||/^#{1,4}\s/.test(t)||/^>/.test(t)||/^[-*+]\s+/.test(t)||
           /^\d+[.)]\s+/.test(t)||/^(-{3,}|\*{3,}|_{3,})$/.test(t)||/^\|.*\|$/.test(t);
  }
  /* ---- 离线语法高亮 (零依赖, 正则分词; 覆盖常见语言) ---- */
  var KEYWORDS={
    _default:{},
    python:{'def':'1','class':'1','return':'1','if':'1','elif':'1','else':'1','for':'1','while':'1','in':'1',
      'import':'1','from':'1','as':'1','with':'1','try':'1','except':'1','finally':'1','raise':'1','yield':'1',
      'lambda':'1','and':'1','or':'1','not':'1','is':'1','None':'1','pass':'1','break':'1','continue':'1',
      'global':'1','nonlocal':'1','assert':'1','del':'1','async':'1','await':'1','self':'1'},
    js:{'function':'1','return':'1','if':'1','else':'1','for':'1','while':'1','var':'1','let':'1','const':'1',
      'new':'1','class':'1','extends':'1','import':'1','export':'1','from':'1','async':'1','await':'1','try':'1',
      'catch':'1','finally':'1','throw':'1','typeof':'1','instanceof':'1','of':'1','in':'1','this':'1','switch':'1',
      'case':'1','break':'1','continue':'1','default':'1','do':'1','void':'1','delete':'1','yield':'1'},
    ts:{'function':'1','return':'1','if':'1','else':'1','for':'1','while':'1','var':'1','let':'1','const':'1',
      'new':'1','class':'1','extends':'1','implements':'1','interface':'1','type':'1','enum':'1','import':'1',
      'export':'1','from':'1','async':'1','await':'1','try':'1','catch':'1','finally':'1','throw':'1','typeof':'1',
      'instanceof':'1','of':'1','in':'1','this':'1','public':'1','private':'1','readonly':'1','namespace':'1'},
    go:{'func':'1','return':'1','if':'1','else':'1','for':'1','range':'1','package':'1','import':'1','var':'1',
      'const':'1','type':'1','struct':'1','interface':'1','map':'1','go':'1','defer':'1','chan':'1','select':'1',
      'switch':'1','case':'1','default':'1','break':'1','continue':'1','go':'1','func':'1'},
    rust:{'fn':'1','let':'1','mut':'1','if':'1','else':'1','for':'1','while':'1','loop':'1','match':'1','return':'1',
      'struct':'1','enum':'1','impl':'1','trait':'1','pub':'1','use':'1','mod':'1','const':'1','static':'1','self':'1',
      'Self':'1','ref':'1','move':'1','async':'1','await':'1','where':'1','as':'1'},
    sql:{'select':'1','from':'1','where':'1','insert':'1','update':'1','delete':'1','create':'1','table':'1',
      'drop':'1','alter':'1','join':'1','left':'1','right':'1','inner':'1','outer':'1','on':'1','group':'1','by':'1',
      'order':'1','limit':'1','values':'1','into':'1','set':'1','and':'1','or':'1','not':'1','null':'1','as':'1',
      'distinct':'1','count':'1','sum':'1','avg':'1'}
  };
  function normalizeLang(lang){
    lang=String(lang||'').toLowerCase();
    if(lang==='py'||lang==='python3')return 'python';
    if(lang==='js'||lang==='javascript'||lang==='jsx'||lang==='node'||lang==='mjs'||lang==='cjs')return 'js';
    if(lang==='ts'||lang==='typescript'||lang==='tsx')return 'ts';
    if(lang==='golang')return 'go';
    if(lang==='rs'||lang==='rust')return 'rust';
    if(lang==='sh'||lang==='bash'||lang==='shell'||lang==='zsh'||lang==='console'||lang==='cmd'||lang==='powershell')return 'bash';
    if(lang==='yml')return 'yaml';
    if(lang==='htm')return 'html';
    if(lang==='sql'||lang==='postgres'||lang==='mysql'||lang==='sqlite')return 'sql';
    if(lang==='json'||lang==='jsonc'||lang==='yaml'||lang==='toml'||lang==='ini'||lang==='xml'||lang==='html'
      ||lang==='css'||lang==='bash'||lang==='dockerfile'||lang==='makefile')return lang;
    return lang||'text';
  }
  function hlCode(code,lang){
    var fam=normalizeLang(lang);
    var kw=KEYWORDS[fam]||KEYWORDS._default;
    var re=/(\/\*[\s\S]*?\*\/|\/\/[^\n]*|#[^\n]*|--[^\n]*)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d[\d_.]*\b)|([A-Za-z_$][\w$]*)|(\s+)|([^\s\w])/g;
    var out='',m;
    while((m=re.exec(code))){
      if(m[1]){out+='<span class="tk-c">'+esc(m[1])+'</span>';}
      else if(m[2]){out+='<span class="tk-s">'+esc(m[2])+'</span>';}
      else if(m[3]){out+='<span class="tk-n">'+esc(m[3])+'</span>';}
      else if(m[4]){
        var w=m[4];
        if(kw[w]){out+='<span class="tk-k">'+esc(w)+'</span>';}
        else if(/^(true|false|null|None|True|False|nil|undefined|NaN|NULL)$/.test(w)){out+='<span class="tk-b">'+esc(w)+'</span>';}
        else if(code[re.lastIndex]==='('){out+='<span class="tk-f">'+esc(w)+'</span>';}
        else{out+=esc(w);}
      }
      else if(m[5]){out+=m[5];}
      else{out+=esc(m[0]);}
    }
    return out;
  }

  function renderMd(text){
    var lines=String(text==null?'':text).split('\n');
    var out=[], i=0;
    while(i<lines.length){
      var raw=lines[i], t=raw.trim();
      /* 围栏代码块 */
      if(/^```/.test(t)){
        var lang=t.replace(/^```+/,'').trim();
        var buf=[]; i++;
        while(i<lines.length && !/^```/.test(lines[i].trim())){ buf.push(lines[i]); i++; }
        i++;
        var _code=buf.join('\n');
        out.push('<div class="code-block"><div class="code-head"><span class="code-lang">'
          +esc(lang||'text')+'</span><button class="code-copy" type="button">复制</button></div>'
          +'<pre'+(lang?' data-lang="'+esc(lang)+'"':'')+'><code>'+hlCode(_code,lang)+'</code></pre></div>');
        continue;
      }
      if(!t){ i++; continue; }
      var hm=t.match(/^(#{1,4})\s+(.*)$/);
      if(hm){ var lv=hm[1].length; out.push('<h'+lv+'>'+inline(hm[2])+'</h'+lv+'>'); i++; continue; }
      if(/^(-{3,}|\*{3,}|_{3,})$/.test(t)){ out.push('<hr>'); i++; continue; }
      /* 引用块: 合并连续 > 行 */
      if(/^>/.test(t)){
        var qb=[];
        while(i<lines.length && /^\s*>/.test(lines[i])){ qb.push(lines[i].replace(/^\s*>\s?/,'')); i++; }
        out.push('<blockquote>'+qb.map(inline).join('<br>')+'</blockquote>');
        continue;
      }
      /* 无序列表: 合并连续项 */
      if(/^[-*+]\s+/.test(t)){
        var ul=[];
        while(i<lines.length && /^\s*[-*+]\s+/.test(lines[i])){ ul.push(lines[i].replace(/^\s*[-*+]\s+/,'')); i++; }
        out.push('<ul>'+ul.map(function(x){return '<li>'+inline(x)+'</li>';}).join('')+'</ul>');
        continue;
      }
      /* 有序列表: 合并连续项 */
      if(/^\d+[.)]\s+/.test(t)){
        var ol=[];
        while(i<lines.length && /^\s*\d+[.)]\s+/.test(lines[i])){ ol.push(lines[i].replace(/^\s*\d+[.)]\s+/,'')); i++; }
        out.push('<ol>'+ol.map(function(x){return '<li>'+inline(x)+'</li>';}).join('')+'</ol>');
        continue;
      }
      /* 表格: 表头行 + |---|---| 分隔行, 之后连续 | 行都是数据 */
      if(/^\|.*\|$/.test(t) && i+1<lines.length && /^\|[\s:|-]+\|$/.test(lines[i+1].trim())){
        var cells=function(row){return row.replace(/^\||\|$/g,'').split('|').map(function(x){return x.trim();});};
        var head=cells(t); i+=2; var rows=[];
        while(i<lines.length && /^\|.*\|$/.test(lines[i].trim())){ rows.push(cells(lines[i].trim())); i++; }
        out.push('<table><thead><tr>'
          +head.map(function(x){return '<th>'+inline(x)+'</th>';}).join('')
          +'</tr></thead><tbody>'
          +rows.map(function(r){return '<tr>'+r.map(function(x){return '<td>'+inline(x)+'</td>';}).join('')+'</tr>';}).join('')
          +'</tbody></table>');
        continue;
      }
      /* 段落: 合并连续普通行 (软换行按空格拼) */
      var para=[t]; i++;
      while(i<lines.length){
        var nt=lines[i].trim();
        if(!nt||isBlockStart(nt))break;
        para.push(nt); i++;
      }
      out.push('<p>'+inline(para.join(' '))+'</p>');
    }
    return out.join('\n');
  }

  /* ---- 消息流 ---- */
  function msgEl(role){
    /* 兜底: 只要产生了消息, 欢迎屏就不该再显示 (否则粒子 canvas 会叠在对话上)。
       集中在此处保证任何新增的渲染路径都不会漏掉隐藏。 */
    if(welcomeEl.style.display!=='none')hideWelcome();
    var m=document.createElement('div');m.className='msg '+role;
    var meta=document.createElement('div');meta.className='meta';
    var who=document.createElement('span');who.className='who';who.textContent=role==='user'?'你':'TUAN';
    var tm=document.createElement('span');tm.className='tm';tm.textContent=nowStr();
    meta.appendChild(who);meta.appendChild(tm);
    var body=document.createElement('div');body.className=role==='user'?'bubble':'bubble flow';
    m.appendChild(meta);m.appendChild(body);
    msgsEl.appendChild(m);
    return {el:m,body:body};
  }
  function appendText(body,text){
    var d=document.createElement('div');d.className='md';d.innerHTML=renderMd(text);
    body.appendChild(d);return d;
  }
  function appendTool(body,name,args){
    var t=document.createElement('div');t.className='tool';
    t.innerHTML='<div class="tool-head"><span class="caret">▸</span><span class="tname"></span></div><div class="tool-body"></div>';
    t.querySelector('.tname').textContent=name;
    var tb=t.querySelector('.tool-body');
    var a=document.createElement('div');a.className='lbl';a.textContent='参数';
    var ap=document.createElement('pre');ap.textContent=args||'';
    var rl=document.createElement('div');rl.className='lbl';rl.textContent='结果';
    var rp=document.createElement('pre');rp.className='tool-result';rp.textContent='…';
    tb.appendChild(a);tb.appendChild(ap);tb.appendChild(rl);tb.appendChild(rp);
    t.querySelector('.tool-head').addEventListener('click',function(){t.classList.toggle('open');});
    body.appendChild(t);
    return {setResult:function(out){rp.textContent=out||'(无输出)';},el:t};
  }
  function appendReason(body,text){
    var r=document.createElement('div');r.className='reason';
    r.innerHTML='<div class="reason-head"><span class="caret">▸</span><span class="dot"></span><span>'+esc(tr('web.thinking_process','思考过程'))+'</span><span class="reason-len"></span></div><div class="reason-body"></div>';
    var t=text||'';
    r.querySelector('.reason-body').textContent=t;
    r.querySelector('.reason-len').textContent=t.length>999?(Math.round(t.length/1000)+'k 字'):(t.length+' 字');
    r.querySelector('.reason-head').addEventListener('click',function(){r.classList.toggle('open');});
    body.appendChild(r);
    return r;
  }
  function renderParts(body,parts){
    (parts||[]).forEach(function(p){
      if(!p)return;
      if(p.type==='tool'){appendTool(body,p.name,p.args).setResult(p.out);}
      else if(p.type==='reason'){appendReason(body,p.text);}
      else{appendText(body,p.text);}
    });
  }
  function cleanUserText(content){
    return String(content||'').replace(/\n?\[附件: [^\]]+\]/g,'').replace(/\n?\[图片: [^\]]+\]/g,'').trim();
  }
  function appendUserImages(body){
    if(!window._sessionImages||!window._sessionImages.length)return;
    var grid=document.createElement('div');grid.className='img-grid';
    window._sessionImages.forEach(function(src){
      var img=document.createElement('img');img.src=src;img.alt='uploaded';
      img.addEventListener('click',function(){openLightbox(src);});
      grid.appendChild(img);
    });
    body.appendChild(grid);
    window._sessionImages=[];
  }
  function addMsg(role,content,tools,parts,idx){
    var m=msgEl(role);
    if(role==='assistant'){
      if(parts&&parts.length){renderParts(m.body,parts);}
      else{
        if(tools&&tools.length){tools.forEach(function(tc){appendTool(m.body,tc.name,tc.args).setResult(tc.out);});}
        appendText(m.body,content);
      }
    }else{
      m.body.textContent=cleanUserText(content);
      appendUserImages(m.body);
      /* 已发送消息可编辑: 从该条**之前**分叉出新分支, 文本回填输入框改完重发 ——
         原会话完整保留 (与"会话分支"同一机制, 不做破坏性修改)。 */
      if(typeof idx==='number'&&role==='user'){
        var eb=document.createElement('span');eb.className='edit-btn';eb.textContent='✎';
        eb.title='编辑并重新发送 (从此处分叉, 原会话保留)';
        eb.addEventListener('click',function(){editMessage(idx,content);});
        m.el.querySelector('.meta').appendChild(eb);
      }
    }
    return m.body;
  }
  function editMessage(idx,content){
    var text=cleanUserText(content);
    if(!current){inp.value=text;inp.focus();autoGrow();return;}
    fetch('/api/sessions/fork',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({session:current,upto:idx-1})})
    .then(function(r){return r.json();}).then(function(j){
      if(j.ok){current=j.id;loadSessions();loadHistory();}
      inp.value=text;inp.focus();autoGrow();
    }).catch(function(){inp.value=text;inp.focus();autoGrow();});
  }
  function renderHistory(msgs){
    clearMessages();
    if(!msgs||!msgs.length){showWelcome();return;}
    /* 有历史 → 必须显式隐藏欢迎屏。
       clearMessages() 按设计**保留** #welcome (它是 #msgs 的子节点), 若不在此隐藏,
       重开有历史的会话时粒子 canvas 会继续占位并叠在对话上方 (观感"一坨大的")。
       此前 msgsEl.innerHTML='' 会把 welcome 一起删掉, 所以掩盖了这个缺口。 */
    hideWelcome();
    (msgs||[]).forEach(function(m,i){addMsg(m.role,m.content,m.tools,m.parts,i);});
    scrollBottom();
  }
  function scrollBottom(){msgsEl.scrollTop=msgsEl.scrollHeight;}

  /* ---- 会话列表 ---- */
  function loadSessions(){
    fetch('/api/sessions').then(function(r){return r.json();}).then(function(j){
      allSessions=j.sessions||[];
      var filtered=filterSessions(searchBox.value.trim());
      sessionsEl.innerHTML='';
      filtered.forEach(function(s){
        var d=document.createElement('div');d.className='sess'+(s.id===current?' active':'');
        var t=document.createElement('span');t.className='t';
        t.textContent=(s.forked_from?'⑂ ':'')+s.title;
        if(s.forked_from){t.title='分支自 '+(allSessions.find(function(x){return x.id===s.forked_from;})||{}).title||s.forked_from;}
        var sh=document.createElement('span');sh.className='del';sh.textContent='⇪';sh.title='分享 (生成只读快照页)';
        var f=document.createElement('span');f.className='del';f.textContent='⑂';f.title='从此会话分叉 (fork)';
        var x=document.createElement('span');x.className='del';x.textContent='✕';x.title='删除会话';
        d.appendChild(t);d.appendChild(sh);d.appendChild(f);d.appendChild(x);
        d.addEventListener('click',function(ev){ if(ev.target===x||ev.target===f||ev.target===sh) return; current=s.id;loadHistory();loadSessions(); });
        sh.addEventListener('click',function(ev){ ev.stopPropagation(); window.open('/api/share?session='+encodeURIComponent(s.id),'_blank'); });
        f.addEventListener('click',function(ev){ ev.stopPropagation(); forkSession(s.id); });
        x.addEventListener('click',function(ev){ ev.stopPropagation();
          fetch('/api/sessions?session='+encodeURIComponent(s.id),{method:'DELETE'}).then(function(r){return r.json();}).then(function(j){
            if(j.ok){ if(current===s.id){current=null;clearMessages();showWelcome();} loadSessions(); }
          });
        });
        sessionsEl.appendChild(d);
      });
    }).catch(function(){});
  }
  function filterSessions(q){
    if(!q){return allSessions;}
    q=q.toLowerCase();
    return allSessions.filter(function(s){return String(s.title||'').toLowerCase().indexOf(q)!==-1;});
  }
  searchBox.addEventListener('input',function(){loadSessions();});

  function loadHistory(){
    if(!current){clearMessages();showWelcome();return;}
    fetch('/api/history?session='+encodeURIComponent(current)).then(function(r){return r.json();}).then(function(j){
      if(j.ok){renderHistory(j.messages);}
    }).catch(function(){});
  }

  function fmtPct(v){ return v==null?'-':(Math.round(Number(v)*100)+'%'); }
  function fmtNum(v){ return v==null?'-':v; }
  /* ---- i18n: 语言包由 /api/info 下发 (与 CLI 共用同一份 locale, 10 语言) ---- */
  var T={};
  function tr(k,fb){return T[k]||fb||k;}
  function applyI18n(){
    Array.prototype.forEach.call(document.querySelectorAll('[data-i18n]'),function(el){
      var v=T[el.dataset.i18n];if(v)el.textContent=v;
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-i18n-ph]'),function(el){
      var v=T[el.getAttribute('data-i18n-ph')];if(v)el.placeholder=v;
    });
  }
  function loadInfo(){
    fetch('/api/info').then(function(r){return r.json();}).then(function(j){
      T=j.i18n||{};applyI18n();
      modelLabel=(j.model||'?').split('/').slice(-1)[0]||j.model||'';
      document.getElementById('ws-name').textContent=j.workspace||'';
      document.getElementById('sidefoot').textContent='TUAN Tuan-CLI · '+(j.workspace||'');
      /* 工作区信任: 首次打开未知目录时弹确认 (对标 TUI prompt_trust) */
      if(j.trust && j.trust.needs_confirmation){ showTrust(j.trust); }
      /* 注: 侧栏原有一张"安全基准"静态卡片, 已移除 —— 未跑过 bench 时它只会显示
         一排破折号 (对抗拦截 - · 绕过 - · PS 5k 正确率 -), 既不简洁也不明了。
         安全信息统一收在右侧「安全」面板 (基准 + 闸门 + 近期拦截)。 */
    }).catch(function(){});
  }

  /* ---- 模式 / 推理投入 chip (可点击切换) ---- */
  var MODE_ORDER=['standard','plan','yolo'];
  var EFFORT_ORDER=['low','medium','high'];
  var MODE_LABEL={standard:'standard',plan:'plan 只读',yolo:'yolo 放权'};
  function updateModeChip(mode){
    var el=document.getElementById('t-mode');if(!el)return;
    el.innerHTML='<b>mode</b> '+esc(mode||'standard');
    el.className='chip btn'+(mode==='plan'?' mode-plan':(mode==='yolo'?' mode-yolo':''));
    el._mode=mode||'standard';
  }
  function updateEffortChip(effort){
    var el=document.getElementById('t-effort');if(!el)return;
    el.innerHTML='<b>effort</b> '+esc(effort||'high');
    el._effort=effort||'high';
  }
  function cycleMode(){
    var el=document.getElementById('t-mode');if(!el)return;
    var i=MODE_ORDER.indexOf(el._mode||'standard');
    var next=MODE_ORDER[(i+1)%MODE_ORDER.length];
    fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode:next})}).then(function(r){return r.json();}).then(function(j){
      if(j.ok){updateModeChip(j.mode);}else{updateModeChip(el._mode);}
    }).catch(function(){updateModeChip(el._mode);});
  }
  function cycleEffort(){
    var el=document.getElementById('t-effort');if(!el)return;
    var i=EFFORT_ORDER.indexOf(el._effort||'high');
    var next=EFFORT_ORDER[(i+1)%EFFORT_ORDER.length];
    fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({effort:next})}).then(function(r){return r.json();}).then(function(j){
      if(j.ok){updateEffortChip(j.effort);}else{updateEffortChip(el._effort);}
    }).catch(function(){updateEffortChip(el._effort);});
  }
  /* chip 已从界面移除 (mode/effort/git 改由斜杠命令 /plan /mode /effort /diff 驱动),
     此处仅保留点击入口以防将来重新加回 chips; 元素不存在则跳过。 */
  var _tModeEl=document.getElementById('t-mode');if(_tModeEl)_tModeEl.addEventListener('click',cycleMode);
  var _tEffortEl=document.getElementById('t-effort');if(_tEffortEl)_tEffortEl.addEventListener('click',cycleEffort);

  /* ---- git 分支 chip ---- */
  function updateGitChip(git){
    var el=document.getElementById('git-chip');if(!el)return;
    if(git && git.repo && git.branch){
      el.innerHTML='<b>⑂</b> '+esc(git.branch)+(git.dirty?' <span style="opacity:.8">[±]</span>':'');
      el.className='chip'+(git.dirty?' dirty':'');
      el.title='git 分支: '+git.branch+(git.dirty?' (有未提交改动)':' (干净)');
    }else{
      el.innerHTML='';
      el.className='chip';
      el.title='非 git 仓库';
    }
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
        md+='> 导出时间: '+new Date().toLocaleString()+'\n> 模型: '+modelLabel+'\n\n';
        md+='---\n\n';
        (j.messages||[]).forEach(function(m){
          if(m.role==='user'){
            md+='## 你\n\n'+cleanUserText(m.content)+'\n\n';
          }else{
            md+='## TUAN\n\n';
            if(m.parts&&m.parts.length){
              m.parts.forEach(function(p){
                if(p.type==='tool'){md+='> 工具 `'+p.name+'`\n>\n> 参数: `'+(p.args||'').replace(/\n/g,' ')+'`\n>\n> 结果: '+(p.out||'(无输出)').replace(/\n/g,'\n> ')+'\n\n';}
                else if(p.type==='reason'){md+='<details><summary>思考过程</summary>\n\n'+(p.text||'')+'\n\n</details>\n\n';}
                else if(p.type==='text'){md+=p.text+'\n\n';}
              });
            }else{md+=(m.content||'')+'\n\n';}
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

  /* ---- 发送 / SSE 流式 ---- */
  function setRunning(v){
    running=v;send.disabled=v;stopBtn.style.display=v?'block':'none';
    /* 同步 body 标记, 供 CSS 兜底关停光标闪烁 (见 .streaming-off 规则) */
    if(document.body)document.body.classList.toggle('streaming-off',!v);
  }
  function sendMsg(){
    var msg=inp.value.trim();if(!msg||running)return;
    /* ! 前缀 = 直接执行 shell (经安全引擎, 高危先弹审批) */
    if(msg.charAt(0)==='!'){
      inp.value='';autoGrow();
      var cmd=msg.slice(1).trim();
      if(cmd)runShell(cmd,false);
      return;
    }
    /* 斜杠命令: 已知命令在 Web 端本地处理 (/clear 在此分支里走既有逻辑) */
    if(msg.charAt(0)==='/'){
      if(handleSlash(msg)){ inp.value='';autoGrow();return; }
      /* handleSlash 仅对 /clear 返回 false, 其余已知命令已 return; 这里继续处理 /clear */
    }
    if(msg==='/clear'){
      if(current){ fetch('/api/sessions/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:current})}).catch(function(){}); }
      clearMessages();showWelcome();inp.value='';return;
    }
    var fileMsg=msg, imgDataUrls=[];
    if(pendingFiles.length>0){
      var names=[];
      pendingFiles.forEach(function(pf){
        names.push(pf.file.name);
        if(pf.dataUrl){imgDataUrls.push(pf.dataUrl);}
      });
      fileMsg=msg+'\n\n[附件: '+names.join(', ')+']';
    }
    window._sessionImages=imgDataUrls;
    hideWelcome();
    addMsg('user',fileMsg,[],null);
    inp.value='';autoGrow();pendingFiles=[];renderFileTags();
    setRunning(true);

    var am=msgEl('assistant');
    var flow=am.body;
    var cursor=document.createElement('span');cursor.className='stream-cursor';
    var curSeg=null, curText='', lastTool=null;
    /* 思考过程 (reasoning) 实时累积: 模型每个 reasoning delta 都新建一个折叠块
       会堆出几百个碎片块 (观感即"思考过程不可见")。改为与正文文本一样累积 ——
       一个流式块随 delta 生长, 正文/工具到来时自动折叠, 头部留字数。 */
    var curReasonText='', curReasonEl=null, curReasonBody=null, curReasonLen=null;
    var reasonUserToggled=false, reasonQueued=false, reasonRaf=0;
    var gotAny=false;   /* 本轮是否已收到任何内容 (区分"输出中断"与"空回复") */
    function ensureReasonBlock(){
      if(curReasonEl){ if(!finished){flow.appendChild(cursor);} return curReasonEl; }
      /* 新思考阶段开始: 正文分段复位, 保证后续正文渲染在思考块**之后**
         (服务端 parts 顺序: reason → text → tool → reason → text ...)。 */
      curSeg=null; curText='';
      curReasonText=''; reasonUserToggled=false;
      var r=document.createElement('div');r.className='reason streaming';
      r.innerHTML='<div class="reason-head"><span class="caret">▸</span><span class="dot"></span>'
        +'<span>'+esc(tr('web.thinking_process','思考过程'))+'</span><span class="reason-len"></span></div>'
        +'<div class="reason-body"></div>';
      curReasonBody=r.querySelector('.reason-body');
      curReasonLen=r.querySelector('.reason-len');
      r.querySelector('.reason-head').addEventListener('click',function(){
        reasonUserToggled=true; r.classList.toggle('open');
      });
      r.classList.add('open');   /* 流式中默认展开, 让思考过程可见 */
      flow.appendChild(r);
      curReasonEl=r;
      if(!finished){flow.appendChild(cursor);}
      return r;
    }
    function reasonSchedule(){
      if(reasonQueued||finished)return;
      reasonQueued=true;
      reasonRaf=requestAnimationFrame(function(){
        reasonQueued=false;
        if(finished||!curReasonBody)return;
        curReasonBody.textContent=curReasonText;
        if(curReasonLen){
          curReasonLen.textContent=curReasonText.length>999
            ?(Math.round(curReasonText.length/1000)+'k 字'):(curReasonText.length+' 字');
        }
        flow.appendChild(cursor);scrollBottom();
      });
    }
    function closeReasonBlock(){
      if(reasonRaf){cancelAnimationFrame(reasonRaf);reasonRaf=0;}
      reasonQueued=false;
      var r=curReasonEl;
      curReasonEl=null; curReasonBody=null; curReasonLen=null;
      if(!r)return;
      if(curReasonBody)curReasonBody.textContent=curReasonText;
      r.classList.remove('streaming');   /* 去掉脉冲点/高亮, 变为普通折叠块 */
      if(curReasonLen){
        curReasonLen.textContent=curReasonText.length>999
          ?(Math.round(curReasonText.length/1000)+'k 字'):(curReasonText.length+' 字');
      }
      if(!reasonUserToggled)r.classList.remove('open');  /* 用户没手动展开过 → 自动折叠 */
    }
    /* 思考状态 pill: 从发送到首个增量 (reason/delta/tool) 之间显示"思考中 + 秒数" */
    var thinkPill=document.getElementById('think-pill'),
        thinkTime=document.getElementById('think-time'),
        thinkTimer=0, thinkStart=0;
    function startThinkPill(){
      if(!thinkPill)return;
      thinkStart=Date.now(); thinkPill.classList.add('on');
      if(thinkTimer)clearInterval(thinkTimer);
      thinkTimer=setInterval(function(){
        var s=(Date.now()-thinkStart)/1000;
        if(thinkTime)thinkTime.textContent=s<60?(s.toFixed(1)+'s'):(Math.floor(s/60)+'m '+(s%60).toFixed(0)+'s');
      },100);
    }
    function stopThinkPill(){
      if(thinkTimer){clearInterval(thinkTimer);thinkTimer=0;}
      if(thinkPill)thinkPill.classList.remove('on');
    }
    /* 流式渲染节流: 每个 token 都重渲染整段是 O(n²) —— 回复到 2000 字时累计解析
       量达百万字符级, 越流越卡。改为「一帧最多渲染一次」(rAF 合并), 视觉无差别。
       ⚠ 竞态修复: 早先 rAF 回调不保存句柄、finish() 也只置 renderQueued=false 而
       不取消已排队的帧, 于是「最后一个 delta 排的帧」会在 finish() 移除 cursor
       之后才执行, 把 cursor 又 appendChild 回 DOM —— 表现为输出结束后蓝色方块
       残留且持续闪烁(它靠 CSS animation infinite, 只要在 DOM 里就永远闪)。
       现在: 保存 rafId 供 finish() 取消, 并用 finished 标志兜住任何已在途的帧。 */
    var renderQueued=false, rafId=0, finished=false;
    function scheduleRender(){
      if(renderQueued||finished)return;
      renderQueued=true;
      rafId=requestAnimationFrame(function(){
        renderQueued=false;
        if(finished)return;
        if(curSeg)curSeg.innerHTML=renderMd(curText);
        flow.appendChild(cursor);scrollBottom();
      });
    }
    function flushRender(){
      if(renderQueued&&curSeg&&!finished){curSeg.innerHTML=renderMd(curText);}
      renderQueued=false;
    }
    flow.appendChild(cursor);
    scrollBottom();
    /* 首增量前的"思考中"指示: 推理模型静默期可达分钟级, 没有它用户会判死 */
    startThinkPill();

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
      if(e.name!=='AbortError'){appendText(flow,'[错误] '+e.message);}
      else if(gotAny){
        /* 用户点"停止": 半截输出要有明确标记, 否则被当成完整答案 */
        var note=document.createElement('div');note.className='md';
        note.innerHTML='<p style="color:var(--color-text-faint);font-size:var(--text-xs)">■ '
          +esc(tr('web.stopped','已停止'))+'</p>';
        flow.appendChild(note);
      }
      finish();
    });

    function handleSSE(chunk){
      var ev='',data='';
      chunk.split('\n').forEach(function(l){
        if(l.indexOf('event:')===0)ev=l.slice(6).trim();
        else if(l.indexOf('data:')===0)data=l.slice(5).trim();
      });
      if(!data)return;
      var j;try{j=JSON.parse(data);}catch(e){return;}
      if(ev==='session'){current=j.id;loadSessions();}
      else if(ev==='delta'){
        stopThinkPill();
        closeReasonBlock();
        gotAny=true;
        curText+=j;
        if(!curSeg){curSeg=appendText(flow,'');}
        scheduleRender();
      }
      else if(ev==='tool'){
        stopThinkPill();
        closeReasonBlock();
        gotAny=true;
        curSeg=null;curText='';
        lastTool=appendTool(flow,j.name,j.args);
        if(!finished){flow.appendChild(cursor);scrollBottom();}
      }
      else if(ev==='tool_result'){if(lastTool)lastTool.setResult(j.out);scrollBottom();}
      /* 服务端显式收尾(done): 正常路径由 reader.done 触发 finish(), 但若代理/
         中间层把连接保持住不关闭, 就会永远等不到 r.done —— 蓝色光标于是无限
         闪烁。收到 done 立即收口, 与 finish() 幂等。 */
      else if(ev==='done'){finish();}
      else if(ev==='reason'){
        /* 思考过程: 累积进同一个流式块 (见 ensureReasonBlock), 不逐 delta 新建 */
        stopThinkPill();
        gotAny=true;
        curReasonText+=(j&&j.text!=null?j.text:j);
        ensureReasonBlock();
        reasonSchedule();
      }
      else if(ev==='approval'){
        /* 危险工具需要确认: 弹审批窗, 把结果回填 /api/approve */
        showApproval({prompt:j.prompt,verdict:j.verdict},function(d){
          fetch('/api/approve',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({id:j.id,decision:d})}).catch(function(){});
        });
      }
      else if(ev==='error'){
        /* 出错也要把流式光标收掉并复位发送状态 —— 此前只有 done 事件才收,
           Agent 被打断/出错时蓝色光标一直闪, 让人误以为任务还在跑。 */
        endStream();
        /* 已流出部分内容再出错 = 输出中断 (与"完全没响应"区分开):
           给出醒目标记, 不让用户把半截输出当成完整答案。 */
        if(gotAny){
          var note=document.createElement('div');note.className='md';
          note.innerHTML='<p style="color:var(--color-danger);font-size:var(--text-xs)">⚠ '
            +esc(tr('web.interrupted','输出中断'))+' — '+esc(j.message||j)+'</p>';
          flow.appendChild(note);
        }else{
          appendText(flow,'[错误] '+(j.message||j));
        }
        setRunning(false);
      }
    }
    /* 流式结束统一收口: 先置 finished 再取消在途 rAF 帧, 确保任何已排队的帧
       都不会再把 cursor 挂回 DOM(它是 CSS infinite 动画, 残留即永久闪烁)。 */
    function endStream(){
      finished=true;
      if(rafId){cancelAnimationFrame(rafId);rafId=0;}
      renderQueued=false;
      closeReasonBlock();
      stopThinkPill();
      if(cursor.parentNode)cursor.parentNode.removeChild(cursor);
    }
    function finish(){
      if(finished)return;   /* 幂等: done 事件与 reader.done 可能都触发 */
      endStream();
      setRunning(false);loadSessions();
    }
  }

  stopBtn.addEventListener('click',function(){if(abortCtrl){abortCtrl.abort();}fetch('/api/stop',{method:'POST'}).catch(function(){});});

  /* ---- 键盘快捷键 ---- */
  document.addEventListener('keydown',function(e){
    if(e.ctrlKey&&e.key==='e'){e.preventDefault();exportMarkdown();}
    if(e.ctrlKey&&e.key==='k'){e.preventDefault();searchBox.focus();searchBox.select();}
    if(e.ctrlKey&&e.key==='n'){e.preventDefault();current=null;clearMessages();showWelcome();loadSessions();inp.focus();}
    if(e.ctrlKey&&e.key==='b'){e.preventDefault();togglePanel();}
    if(e.ctrlKey&&e.key==='/'){e.preventDefault();openSlash('');inp.focus();}
    if(e.ctrlKey&&e.key===','){e.preventDefault();if(SET.open){closeSettings();}else{openSettings();}}
    if(e.key==='Escape'&&SET.open){closeSettings();}
  });

  send.addEventListener('click',sendMsg);
  inp.addEventListener('keydown',function(e){
    if(slashOpen){
      if(e.key==='ArrowDown'){e.preventDefault();moveSlash(1);return;}
      if(e.key==='ArrowUp'){e.preventDefault();moveSlash(-1);return;}
      if(e.key==='Enter'||e.key==='Tab'){e.preventDefault();pickSlash(slashSel);return;}
      if(e.key==='Escape'){e.preventDefault();closeSlash();return;}
    }
    if(mentionOpen){
      if(e.key==='ArrowDown'){e.preventDefault();moveMention(1);return;}
      if(e.key==='ArrowUp'){e.preventDefault();moveMention(-1);return;}
      if(e.key==='Enter'||e.key==='Tab'){e.preventDefault();pickMention(mentionSel);return;}
      if(e.key==='Escape'){e.preventDefault();closeMention();return;}
    }
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}
  });
  inp.addEventListener('input',function(){autoGrow();updateMention();updateSlash();});
  inp.addEventListener('blur',function(){setTimeout(closeMention,150);});
  document.getElementById('newbtn').addEventListener('click',function(){current=null;clearMessages();showWelcome();loadSessions();});

  /* ================================================================
     右侧工作面板: 文件树 / Diff / 上下文与 token / MCP / 安全
     ================================================================ */
  var rpanel=document.getElementById('rpanel');
  var RP_BODY={files:'rp-files',diff:'rp-diff',ctx:'rp-ctx',mcp:'rp-mcp',plugins:'rp-plugins',sec:'rp-sec'};
  function fmtSize(n){
    if(n==null)return '';
    if(n<1024)return n+'B';
    if(n<1048576)return (n/1024).toFixed(1)+'K';
    return (n/1048576).toFixed(1)+'M';
  }
  function togglePanel(force){
    var open=(typeof force==='boolean')?force:!rpanel.classList.contains('open');
    rpanel.classList.toggle('open',open);
    if(open)loadTab(document.querySelector('.rp-tab.active').dataset.tab);
  }
  function loadTab(tab){
    if(tab==='files')loadFiles(currentDir);
    else if(tab==='diff')loadDiff();
    else if(tab==='ctx')loadCtx();
    else if(tab==='mcp')loadMcp();
    else if(tab==='plugins')loadPlugins();
    else if(tab==='sec')loadSec();
  }
  document.getElementById('btn-panel').addEventListener('click',function(){togglePanel();});
  Array.prototype.forEach.call(document.querySelectorAll('.rp-tab'),function(b){
    b.addEventListener('click',function(){
      Array.prototype.forEach.call(document.querySelectorAll('.rp-tab'),function(x){x.classList.remove('active');});
      b.classList.add('active');
      Object.keys(RP_BODY).forEach(function(k){
        document.getElementById(RP_BODY[k]).classList.toggle('hidden',k!==b.dataset.tab);
      });
      loadTab(b.dataset.tab);
    });
  });

  /* ---- 文件树 ---- */
  var currentDir='';
  function loadFiles(dir){
    currentDir=(dir==null)?currentDir:dir;
    var el=document.getElementById('rp-files');
    fetch('/api/files?path='+encodeURIComponent(currentDir)).then(function(r){return r.json();}).then(function(j){
      if(!j.ok){el.innerHTML='<div class="rp-empty">'+esc(j.error||'读取失败')+'</div>';return;}
      var h='<div class="rp-sec">'+(esc(j.path)||'工作区根目录')+'</div>';
      if(currentDir){
        h+='<div class="rp-row dir" data-nav="up"><span class="ico">↑</span><span class="nm">..</span></div>';
      }
      (j.entries||[]).forEach(function(e){
        h+='<div class="rp-row'+(e.dir?' dir':'')+'" data-path="'+esc(e.path)+'" data-dir="'+(e.dir?1:0)+'">'
          +'<span class="ico">'+(e.dir?'▸':'·')+'</span><span class="nm">'+esc(e.name)+'</span>'
          +'<span class="sz">'+(e.dir?'':fmtSize(e.size))+'</span></div>';
      });
      if(!(j.entries||[]).length)h+='<div class="rp-empty">'+esc(tr('web.empty_dir','(空目录)'))+'</div>';
      el.innerHTML=h;
      Array.prototype.forEach.call(el.querySelectorAll('.rp-row.dir'),function(row){
        row.addEventListener('click',function(){
          if(row.dataset.nav==='up'){var p=currentDir.split('/');p.pop();loadFiles(p.join('/'));}
          else loadFiles(row.dataset.path);
        });
      });
      Array.prototype.forEach.call(el.querySelectorAll('.rp-row:not(.dir)'),function(row){
        row.addEventListener('click',function(){insertMention('@'+row.dataset.path+' ');});
      });
    }).catch(function(){});
  }

  /* ---- Diff ---- */
  function loadDiff(){
    var el=document.getElementById('rp-diff');
    el.innerHTML='<div class="rp-empty">加载中…</div>';
    fetch('/api/diff').then(function(r){return r.json();}).then(function(j){
      var d=j.diff||'';
      el.innerHTML='<div class="rp-sec">git diff</div>'
        +(d?'<div class="rp-pre">'+esc(d)+'</div>':'<div class="rp-empty">工作区无改动</div>');
    }).catch(function(){el.innerHTML='<div class="rp-empty">读取失败</div>';});
  }

  /* ---- 上下文与 token 用量 ---- */
  function loadCtx(){
    var el=document.getElementById('rp-ctx');
    fetch('/api/context').then(function(r){return r.json();}).then(function(j){
      var w=j.window||128000, tot=j.total_est_tokens||0;
      var pct=Math.min(100,Math.round(tot/w*100));
      var h='<div class="rp-sec">总用量 (估算)</div>';
      h+='<div class="rp-bar'+(pct>80?' warn':'')+'"><i style="width:'+pct+'%"></i></div>';
      h+='<div class="rp-kv"><span>est. tokens</span><b>'+tot+'</b></div>';
      h+='<div class="rp-kv"><span>上下文窗口</span><b>'+w+'</b></div>';
      h+='<div class="rp-kv"><span>占比</span><b>'+pct+'%</b></div>';
      h+='<div class="rp-sec">按会话</div>';
      (j.sessions||[]).forEach(function(s){
        h+='<div class="rp-row"><span class="nm">'+esc(s.title||s.id)+'</span>'
          +'<span class="sz">'+s.messages+'条 · '+s.est_tokens+'t</span></div>';
      });
      if(!(j.sessions||[]).length)h+='<div class="rp-empty">暂无会话</div>';
      h+='<div class="rp-empty">token 为字符数估算 (~3 字符/token), 非精确分词。</div>';
      el.innerHTML=h;
    }).catch(function(){el.innerHTML='<div class="rp-empty">读取失败</div>';});
  }

  /* ---- MCP 状态 ---- */
  function loadMcp(){
    var el=document.getElementById('rp-mcp');
    fetch('/api/mcp').then(function(r){return r.json();}).then(function(j){
      var s=j.servers||[];
      if(!s.length){el.innerHTML='<div class="rp-empty">'+esc(tr('web.mcp_none','未接入 MCP server'))+'</div>';return;}
      var h='<div class="rp-sec">MCP servers ('+s.length+')</div>';
      s.forEach(function(x){
        h+='<div class="rp-row"><span class="ico" style="color:var(--color-success)">●</span>'
          +'<span class="nm">'+esc(x.name)+'</span><span class="sz">'+x.tool_count+' 工具</span></div>';
      });
      el.innerHTML=h;
    }).catch(function(){el.innerHTML='<div class="rp-empty">读取失败</div>';});
  }

  /* ---- 安全: 基准 + 四道闸门 + 近期拦截 (引擎真实信息, 非静态卡片) ---- */
  function loadSec(){
    var el=document.getElementById('rp-sec');
    fetch('/api/security').then(function(r){return r.json();}).then(function(j){
      var b=j.benchmark||{}, core=b.core||{}, ps=b.ps||{};
      var h='';
      if(j.available){
        h+='<div class="rp-sec">安全基准 (本地可复现)</div>';
        h+='<div class="rp-kv"><span>对抗拦截召回</span><b>'+fmtPct(core.adversarial_recall)+'</b></div>';
        h+='<div class="rp-kv"><span>绕过数</span><b>'+fmtNum(core.bypass_count)+'</b></div>';
        h+='<div class="rp-kv"><span>PS 5k 正确率</span><b>'+fmtPct(ps.accuracy)+'</b></div>';
        h+='<div class="rp-kv"><span>误杀率</span><b>'+fmtPct(core.fp_rate||core.false_positive_rate)+'</b></div>';
      }else{
        h+='<div class="rp-empty">未找到 bench/security-bench.json<br>(跑 tuan safe bench 生成)</div>';
      }
      h+='<div class="rp-sec">闸门 (每次工具调用前)</div>';
      (j.gates||[]).forEach(function(g,i){
        h+='<div class="gate"><span class="n">'+(i+1)+'</span><div><div class="t">'+esc(g.label)+'</div>'
          +'<div class="d">'+esc(g.desc)+'</div></div></div>';
      });
      var rc=j.recent||[];
      h+='<div class="rp-sec">近期拦截 ('+rc.length+')</div>';
      if(rc.length){
        rc.forEach(function(r){
          h+='<div class="blk"><div class="h">'+esc(r.tool)+'</div><div>'+esc(r.args)+'</div></div>';
        });
      }else{
        h+='<div class="rp-empty">本会话暂无拦截记录</div>';
      }
      el.innerHTML=h;
    }).catch(function(){el.innerHTML='<div class="rp-empty">读取失败</div>';});
  }

  /* ---- 插件 / 工具 热插拔 (不输命令, 面板直接开关) ---- */
  function loadPlugins(){
    var el=document.getElementById('rp-plugins');
    fetch('/api/plugins').then(function(r){return r.json();}).then(function(j){
      if(!j.ok){el.innerHTML='<div class="rp-empty">读取失败</div>';return;}
      var h='';
      (j.groups||[]).forEach(function(g){
        var items=g.items||[];
        if(!items.length)return;
        var on=items.filter(function(x){return x.enabled;}).length;
        h+='<div class="pl-group"><span>'+esc(g.title)+'</span><span>'+on+'/'+items.length+'</span></div>';
        items.forEach(function(x){
          h+='<div class="pl" title="'+esc(x.desc||'')+'">'
            +'<span class="nm">'+esc(x.name)+'</span>'
            +(x.tag?'<span class="tag">'+esc(x.tag)+'</span>':'')
            +'<button class="sw'+(x.enabled?' on':'')+'" data-kind="'+esc(g.kind)+'"'
            +' data-name="'+esc(x.name)+'"'+(x.locked?' disabled':'')
            +' aria-label="'+esc(x.name)+'"></button></div>';
        });
      });
      el.innerHTML=h||'<div class="rp-empty">无可用插件</div>';
      Array.prototype.forEach.call(el.querySelectorAll('.sw'),function(b){
        b.addEventListener('click',function(){
          var next=!b.classList.contains('on');
          b.disabled=true;
          fetch('/api/plugins/toggle',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({kind:b.dataset.kind,name:b.dataset.name,enabled:next})})
            .then(function(r){return r.json();})
            .then(function(res){
              if(!res.ok){b.disabled=false;appendLogLine('插件开关失败: '+(res.error||''));return;}
              loadPlugins();
            }).catch(function(){b.disabled=false;});
        });
      });
    }).catch(function(){el.innerHTML='<div class="rp-empty">读取失败</div>';});
  }
  function appendLogLine(msg){
    var d=document.createElement('div');d.className='rp-empty';d.textContent=msg;
    var el=document.getElementById('rp-plugins');if(el)el.appendChild(d);
  }

  /* ================================================================
     审批弹窗 (allow / deny) —— 把引擎的 risk/reasons/blast_radius/suggestions
     摊开给用户看, 而不是只弹一句"是否继续"
     ================================================================ */
  var pendingApproval=null;
  function showApproval(payload,onDecide){
    pendingApproval={onDecide:onDecide};
    var v=payload.verdict||{};
    document.getElementById('ap-cmd').textContent=payload.prompt||payload.command||'';
    var risk=v.risk||'unknown';
    document.getElementById('ap-risk').innerHTML=
      '<span class="risk '+esc(risk)+'">风险 '+esc(risk)+(v.score==null?'':' · score '+v.score)+'</span>';
    var rs=v.reasons||[];
    document.getElementById('ap-reasons').innerHTML=rs.length
      ?('<div class="lbl">'+esc(tr('web.reasons','判定原因'))+'</div><ul>'+rs.map(function(x){return '<li>'+esc(x)+'</li>';}).join('')+'</ul>'):'';
    var br=v.blast_radius||{}, bits=[];
    ['files','services','data'].forEach(function(k){
      var arr=br[k]||[];
      if(arr.length)bits.push('<b>'+esc(k)+'</b>: '+arr.slice(0,8).map(esc).join(', '));
    });
    document.getElementById('ap-blast').innerHTML=bits.length
      ?('<div class="lbl">'+esc(tr('web.blast','影响半径'))+'</div><div>'+bits.join('<br>')+'</div>'):'';
    var sg=v.suggestions||[];
    document.getElementById('ap-sugg').innerHTML=sg.length
      ?('<div class="lbl">'+esc(tr('web.suggestions','安全替代建议'))+'</div><ul>'+sg.map(function(x){return '<li>'+esc(x)+'</li>';}).join('')+'</ul>'):'';
    document.getElementById('approve').classList.add('open');
  }
  function closeApproval(decision){
    document.getElementById('approve').classList.remove('open');
    var p=pendingApproval;pendingApproval=null;
    if(p&&p.onDecide)p.onDecide(decision);
  }
  document.getElementById('ap-allow').addEventListener('click',function(){closeApproval('allow');});
  document.getElementById('ap-deny').addEventListener('click',function(){closeApproval('deny');});

  /* ================================================================
     ! 执行 shell (经安全引擎评估; 高危先弹审批)
     ================================================================ */
  function runShell(cmd,approved){
    hideWelcome();
    var am=msgEl('assistant');
    var pre=document.createElement('div');pre.className='md';
    pre.innerHTML=renderMd('**$ '+cmd+'**\n\n```\n'+tr('web.running','执行中…')+'\n```');
    am.body.appendChild(pre);
    setRunning(true);
    fetch('/api/shell',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({command:cmd,approved:!!approved})})
    .then(function(r){return r.json();}).then(function(j){
      setRunning(false);
      if(j.needs_approval){
        pre.innerHTML=renderMd('**$ '+cmd+'**\n\n> 该命令被安全引擎标记为高风险, 等待确认…');
        showApproval({prompt:cmd,verdict:j.verdict},function(d){
          if(d==='allow')runShell(cmd,true);
          else pre.innerHTML=renderMd('**$ '+cmd+'**\n\n> '+tr('web.denied','已拒绝执行。'));
        });
        return;
      }
      pre.innerHTML=renderMd('**$ '+cmd+'**\n\n```\n'+(j.output||'(无输出)')+'\n```\n\n> exit='+j.exit);
      scrollBottom();
    }).catch(function(e){
      setRunning(false);
      pre.innerHTML=renderMd('**$ '+cmd+'**\n\n> 执行失败: '+e.message);
    });
  }

  /* ================================================================
     @ 引用文件 (输入 @ 弹工作区文件下拉, ↑↓ 选, Enter/Tab 插入)
     ================================================================ */
  var mentionEl=document.getElementById('mention');
  var mentionItems=[],mentionSel=0,mentionOpen=false,mentionDir='',mentionBase='';
  function closeMention(){mentionOpen=false;mentionEl.classList.remove('open');mentionItems=[];}
  function insertMention(text){
    var pos=inp.selectionStart||inp.value.length;
    var before=inp.value.slice(0,pos), after=inp.value.slice(pos);
    var m=/(?:^|\s)@[^\s@]*$/.exec(before);
    if(m){before=before.slice(0,m.index+(m[0][0]===' '?1:0));}
    inp.value=before+text+after;
    inp.focus();
    inp.selectionStart=inp.selectionEnd=(before+text).length;
    closeMention();autoGrow();
  }
  function pickMention(i){
    var e=mentionItems[i];if(!e)return;
    insertMention('@'+e.path+(e.dir?'/':' '));
  }
  function updateMention(){
    var pos=inp.selectionStart||0;
    var m=/(?:^|\s)@([^\s@]*)$/.exec(inp.value.slice(0,pos));
    if(!m){closeMention();return;}
    var q=m[1],dir='',base=q;
    var slash=q.lastIndexOf('/');
    if(slash>=0){dir=q.slice(0,slash);base=q.slice(slash+1);}
    mentionDir=dir;mentionBase=base;
    fetch('/api/files?path='+encodeURIComponent(dir)).then(function(r){return r.json();}).then(function(j){
      if(!j.ok){closeMention();return;}
      var ql=base.toLowerCase();
      mentionItems=(j.entries||[]).filter(function(e){
        return !ql||e.name.toLowerCase().indexOf(ql)!==-1;
      }).slice(0,12);
      if(!mentionItems.length){closeMention();return;}
      mentionSel=0;mentionOpen=true;
      mentionEl.innerHTML=mentionItems.map(function(e,i){
        return '<div class="mi'+(i===0?' sel':'')+'" data-i="'+i+'">'+(e.dir?'▸ ':'· ')+esc(e.path)+'</div>';
      }).join('');
      mentionEl.classList.add('open');
      Array.prototype.forEach.call(mentionEl.querySelectorAll('.mi'),function(el){
        el.addEventListener('mousedown',function(ev){ev.preventDefault();pickMention(parseInt(el.dataset.i,10));});
      });
    }).catch(function(){closeMention();});
  }
  function moveMention(d){
    if(!mentionOpen||!mentionItems.length)return false;
    mentionSel=(mentionSel+d+mentionItems.length)%mentionItems.length;
    Array.prototype.forEach.call(mentionEl.querySelectorAll('.mi'),function(el,i){
      el.classList.toggle('sel',i===mentionSel);
    });
    return true;
  }

  /* ================================================================
     会话分支 (fork)
     ================================================================ */
  function forkSession(sid){
    fetch('/api/sessions/fork',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({session:sid})})
    .then(function(r){return r.json();}).then(function(j){
      if(j.ok){current=j.id;loadSessions();loadHistory();}
    }).catch(function(){});
  }

  /* ================================================================
     斜杠命令面板 (对标 TUI /cmd 补全: 输入 / 即弹出, ↑↓ 选, 回车插入)
     ================================================================ */
  var slashCommands=[], slashOpen=false, slashItems=[], slashSel=0;
  function loadSlash(){
    fetch('/api/slash').then(function(r){return r.json();}).then(function(j){
      slashCommands=j.commands||[];
    }).catch(function(){});
  }
  function openSlash(q){
    slashOpen=true; slashSel=0;
    q=(q||'').toLowerCase();
    slashItems=slashCommands.filter(function(c){
      if(!q)return true;
      return c.name.toLowerCase().indexOf(q)!==-1 || (c.desc||'').toLowerCase().indexOf(q)!==-1;
    });
    renderSlash();
  }
  function closeSlash(){slashOpen=false;document.getElementById('slash').classList.remove('open');}
  function renderSlash(){
    var el=document.getElementById('slash-list');
    if(!slashItems.length){el.innerHTML='<div class="sl-empty">无匹配命令</div>';document.getElementById('slash').classList.add('open');return;}
    el.innerHTML=slashItems.map(function(c,i){
      return '<div class="sl'+(i===0?' sel':'')+'" data-i="'+i+'"><span class="nm">'+esc(c.name)+'</span>'
        +'<span class="ds">'+esc(c.desc||'')+'</span></div>';
    }).join('');
    document.getElementById('slash').classList.add('open');
    Array.prototype.forEach.call(el.querySelectorAll('.sl'),function(row){
      row.addEventListener('mousedown',function(ev){ev.preventDefault();pickSlash(parseInt(row.dataset.i,10));});
    });
  }
  function moveSlash(d){
    if(!slashOpen||!slashItems.length)return;
    slashSel=(slashSel+d+slashItems.length)%slashItems.length;
    Array.prototype.forEach.call(document.querySelectorAll('#slash .sl'),function(el,i){
      el.classList.toggle('sel',i===slashSel);
    });
  }
  /* 无参命令: 选中即执行, 省掉"回车补全 → 再回车执行"的二次按键。
     其余命令仍只做补全 (填入输入框), 用户可继续输参数再回车。 */
  var SLASH_NOARG={ '/model':1,'/models':1,'/provider':1,'/export':1,'/diff':1,'/clear':1,'/plan':1 };
  function pickSlash(i){
    var c=slashItems[i];if(!c)return;
    inp.value=c.name+' ';closeSlash();autoGrow();
    if(SLASH_NOARG[c.name]){
      sendMsg();   /* 立即执行; sendMsg 内部会清空输入框 */
      return;
    }
    inp.focus();
  }
  function updateSlash(){
    var v=inp.value;
    if(/^\/[^\s]*$/.test(v)){openSlash(v.slice(1));}else{closeSlash();}
  }

  /* ================================================================
     工作区信任对话框 (对标 TUI prompt_trust)
     ================================================================ */
  function showTrust(info){
    document.getElementById('trust-path').textContent=(info&&info.path)||'';
    document.getElementById('trust').classList.add('open');
  }
  function closeTrust(){document.getElementById('trust').classList.remove('open');}
  Array.prototype.forEach.call(document.querySelectorAll('#trust .lvl'),function(b){
    b.addEventListener('click',function(){
      var lvl=b.dataset.lvl;
      fetch('/api/trust',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({level:lvl})}).then(function(){closeTrust();}).catch(function(){closeTrust();});
    });
  });

  /* ================================================================
     代码块复制按钮 (事件委托, 读取渲染后的 code 文本, 不依赖属性转义)
     ================================================================ */
  function copyText(t){
    try{ if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t);return true;} }catch(e){}
    try{ var ta=document.createElement('textarea');ta.value=t;ta.style.position='fixed';ta.style.opacity='0';
      document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);return true; }catch(e){ return false; }
  }
  document.addEventListener('click',function(e){
    var b=e.target&&e.target.closest?e.target.closest('.code-copy'):null;
    if(!b)return;
    var cb=b.closest('.code-block');if(!cb)return;
    var code=cb.querySelector('code');if(!code)return;
    if(copyText(code.textContent)){var o=b.textContent;b.textContent='已复制';setTimeout(function(){b.textContent=o;},1500);}
  });

  /* ================================================================
     斜杠命令本地处理 (/clear 已由 sendMsg 处理; 这里处理其余已知命令)
     ================================================================ */
  function handleSlash(msg){
    var parts=msg.slice(1).split(/\s+/);
    var cmd=(parts[0]||'').toLowerCase();
    var arg=parts.slice(1).join(' ').trim();
    if(cmd==='clear'){return false;} /* 交给 sendMsg 既有逻辑 */
    if(cmd==='export'){exportMarkdown();return true;}
    if(cmd==='diff'){togglePanel(true);loadTab('diff');return true;}
    if(cmd==='plan'){
      var _mEl=document.getElementById('t-mode');
      var cur=(_mEl&&_mEl._mode)||'standard';
      var next=cur==='plan'?'standard':'plan';
      fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({mode:next})}).then(function(r){return r.json();}).then(function(j){
        if(j.ok)updateModeChip(j.mode);
      }).catch(function(){});
      return true;
    }
    if(cmd==='mode'&&arg){
      fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({mode:arg})}).then(function(r){return r.json();}).then(function(j){
        if(j.ok)updateModeChip(j.mode);
      }).catch(function(){});
      return true;
    }
    if(cmd==='effort'&&arg){
      fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({effort:arg})}).then(function(r){return r.json();}).then(function(j){
        if(j.ok)updateEffortChip(j.effort);
      }).catch(function(){});
      return true;
    }
    /* /model 与 /provider: 直接打开设置面板的「模型与供应商」页选模型,
       而不是把 /model 当普通消息发给 Agent (那只会得到一句文字回复, 无法真正
       切换模型)。
       注意: 斜杠面板选中后会把命令补成 "<cmd> " (带尾空格) 再交回输入框, 所以
       这里既要认 "/model" 也要认 "/model " 两种形态 —— 否则用户第一次回车
       补全后必须再按一次回车才生效。 */
    if(cmd==='model'||cmd==='provider'||cmd==='models'){
      openSettings();
      SET.cat='模型与供应商';
      renderSettingsNav();
      renderSettings();
      if(arg){
        var _ps=document.getElementById('set-provider');
        if(_ps&&arg.indexOf('/')===-1){
          _ps.value=arg;
          _ps.dispatchEvent(new Event('change'));
        }
      }
      return true;
    }
    /* 其它斜杠命令 (如 /help /status /model ...) 作为普通消息发给 Agent 尝试 */
    return false;
  }

  /* ================================================================
     设置面板 (对标 TUI 的 /config /model /permissions 控制面)
     ================================================================ */
  var SET={data:null, cat:'模型与供应商', open:false};
  var SET_CATS=['外观','模型与供应商','模型参数','运行','上下文','权限','沙箱','验证与自治','记忆','技能与提示','网络','MCP','智能路由','后台任务','键盘快捷键','关于'];
  function openSettings(){
    SET.open=true;
    document.getElementById('settings').classList.add('open');
    if(!SET.data){loadSettings();}else{renderSettingsNav();renderSettings();}
  }
  function closeSettings(){SET.open=false;document.getElementById('settings').classList.remove('open');}
  document.getElementById('btn-settings').addEventListener('click',openSettings);
  document.getElementById('settings-close').addEventListener('click',closeSettings);
  document.getElementById('settings').addEventListener('click',function(e){if(e.target===this)closeSettings();});
  function loadSettings(){
    var c=document.getElementById('settings-content');
    c.innerHTML='<div class="rp-empty">加载中…</div>';
    fetch('/api/config').then(function(r){return r.json();}).then(function(j){
      SET.data=j; renderSettingsNav(); renderSettings();
    }).catch(function(e){ c.innerHTML='<div class="rp-empty">读取失败: '+esc(e.message)+'</div>'; });
  }
  function renderSettingsNav(){
    var nav=document.getElementById('settings-nav'); nav.innerHTML='';
    SET_CATS.forEach(function(cat){
      var b=document.createElement('button');
      b.textContent=cat;
      if(cat===SET.cat)b.classList.add('active');
      b.addEventListener('click',function(){SET.cat=cat;renderSettingsNav();renderSettings();});
      nav.appendChild(b);
    });
  }
  function setNote(el,ok,msg){ if(el){el.textContent=msg||'';el.className='note'+(ok?'':' err');} }
  function setConfig(key,value,noteEl){
    return fetch('/api/config/set',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:key,value:value})}).then(function(r){return r.json();}).then(function(j){
      if(j.ok&&SET.data){SET.data.values[key]=j.value;}
      setNote(noteEl,j.ok,j.ok?'已保存':('失败: '+(j.error||'')));
      return j;
    }).catch(function(e){ setNote(noteEl,false,'失败: '+e.message); return {ok:false}; });
  }
  function sec(t){return '<div class="ssec">'+esc(t)+'</div>';}
  function fieldRow(m){
    var v=(SET.data&&SET.data.values)?SET.data.values[m.key]:undefined;
    var h='<div class="srow"><span class="lab">'+esc(m.label)+'</span>';
    if(m.type==='enum'){
      h+='<select data-key="'+esc(m.key)+'">';
      (m.enum||[]).forEach(function(o){h+='<option value="'+esc(o)+'"'+(String(v)===o?' selected':'')+'>'+esc(o)+'</option>';});
      h+='</select>';
    }else if(m.type==='bool'){
      h+='<input type="checkbox" data-key="'+esc(m.key)+'"'+(v?' checked':'')+'>';
    }else if(m.type==='int'){
      h+='<input type="number" step="1" data-key="'+esc(m.key)+'" value="'+(v==null?'':v)+'" style="width:120px">';
    }else if(m.type==='float'){
      h+='<input type="number" step="0.1" data-key="'+esc(m.key)+'" value="'+(v==null?'':v)+'" style="width:120px">';
    }else if(m.type==='list'){
      h+='<input type="text" data-key="'+esc(m.key)+'" value="'+esc((v||[]).join(', '))+'">';
      h+='<button class="btn sm" data-savelist="'+esc(m.key)+'">保存</button>';
    }else{
      h+='<input type="text" data-key="'+esc(m.key)+'" value="'+esc(v==null?'':v)+'">';
    }
    h+='</div>';
    if(m.hint){h+='<div class="hint">'+esc(m.hint)+'</div>';}
    return h;
  }
  function wireFields(c){
    Array.prototype.forEach.call(c.querySelectorAll('select[data-key]'),function(el){
      el.addEventListener('change',function(){setConfig(el.dataset.key,el.value,document.getElementById('set-note'));});
    });
    Array.prototype.forEach.call(c.querySelectorAll('input[type=checkbox][data-key]'),function(el){
      el.addEventListener('change',function(){setConfig(el.dataset.key,el.checked,document.getElementById('set-note'));});
    });
    Array.prototype.forEach.call(c.querySelectorAll('input[type=number][data-key]'),function(el){
      el.addEventListener('change',function(){setConfig(el.dataset.key,el.value,document.getElementById('set-note'));});
    });
    Array.prototype.forEach.call(c.querySelectorAll('button[data-savelist]'),function(el){
      el.addEventListener('click',function(){
        var key=el.dataset.savelist, inp=c.querySelector('input[data-key="'+key+'"]');
        setConfig(key,inp?inp.value:'',document.getElementById('set-note'));
      });
    });
  }
  function renderSettings(){
    var c=document.getElementById('settings-content'), d=SET.data||{};
    if(SET.cat==='关于'){renderAbout(c,d);return;}
    if(SET.cat==='模型与供应商'){renderModel(c,d);return;}
    if(SET.cat==='外观'){renderAppearance(c,d);return;}
    if(SET.cat==='键盘快捷键'){renderShortcuts(c);return;}
    var metas=(d.meta||[]).filter(function(m){return m.sec===SET.cat;});
    var h=''; metas.forEach(function(m){h+=fieldRow(m);});
    h+='<div class="note" id="set-note"></div>';
    c.innerHTML=h||'<div class="rp-empty">暂无设置</div>';
    wireFields(c);
  }
  /* 键盘快捷键速查: 此前 6+ 个快捷键只在代码里存在, 界面无任何入口, 用户
     无从发现。集中列在设置面板, 与 TUI 快捷键面板对位。 */
  var SHORTCUTS=[
    ['全局',[
      ['Ctrl + K','聚焦会话搜索'],
      ['Ctrl + N','新建会话'],
      ['Ctrl + B','开合右侧工作面板'],
      ['Ctrl + /','打开斜杠命令面板'],
      ['Ctrl + ,','打开 / 关闭设置'],
      ['Ctrl + E','导出当前会话为 Markdown'],
    ]],
    ['输入框',[
      ['Enter','发送'],
      ['Shift + Enter','换行'],
      ['↑ / ↓','历史消息 / 命令面板游走'],
      ['Esc','关闭命令面板 / @ 提及 / 设置'],
      ['@','唤起工作区文件提及'],
      ['/', '开头','唤起斜杠命令面板'],
    ]],
    ['会话流',[
      ['拖动滚动条 / 滚轮','浏览历史'],
      ['点击代码块「复制」','复制代码到剪贴板'],
    ]],
  ];
  function renderShortcuts(c){
    var h='';
    SHORTCUTS.forEach(function(g){
      h+=sec(g[0]);
      h+='<div class="srow kbd-row"><span class="kbd">'+esc(g[1][0][0])+'</span><span class="lab">'+esc(g[1][0][1])+'</span></div>';
      g[1].slice(1).forEach(function(k){
        h+='<div class="srow kbd-row"><span class="kbd">'+esc(k[0])+'</span><span class="lab">'+esc(k[1])+'</span></div>';
      });
    });
    h+='<div class="hint" style="margin-top:var(--space-3)">快捷键在浏览器窗口聚焦于工作台时生效; '
      +'若输入框未响应, 先点击页面任意空白处聚焦。</div>';
    c.innerHTML=h;
  }
  function renderAppearance(c,d){
    var cur=document.documentElement.dataset.colorScheme||'light';
    function radio(val,label){return '<label><input type="radio" name="cs" value="'+val+'"'+(cur===val?' checked':'')+'>'+esc(label)+'</label>';}
    var h=sec('颜色方案')+'<div class="srow"><span class="lab">主题</span><span class="cs-opt">'
      +radio('light','浅色')+radio('dark','深色')+radio('system','跟随系统')+'</span></div>';
    (d.meta||[]).filter(function(m){return m.sec==='外观';}).forEach(function(m){h+=fieldRow(m);});
    h+='<div class="note" id="set-note"></div>';
    c.innerHTML=h; wireFields(c);
    Array.prototype.forEach.call(c.querySelectorAll('input[name=cs]'),function(r){
      r.addEventListener('change',function(){
        try{localStorage.setItem('tuan-web.color-scheme',r.value);}catch(e){}
        document.documentElement.dataset.colorScheme=r.value;
      });
    });
  }
  function renderModel(c,d){
    var model=d.model||{}, provs=d.providers||[], curProv=model.provider;
    var h=sec('供应商与模型');
    h+='<div class="srow"><span class="lab">供应商</span><select id="set-provider"></select></div>';
    h+='<div class="srow"><span class="lab">模型</span><select id="set-model"></select></div>';
    h+='<div class="srow col"><span class="lab">API Key</span><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
      +'<input type="password" id="set-apikey" placeholder="输入密钥后保存 (留空保存=清除)" style="flex:1;min-width:220px">'
      +'<span id="set-keystatus" class="badge no"></span>'
      +'<button class="btn sm" id="set-keysave">保存密钥</button>'
      +'<button class="btn sm ghost" id="set-keyclear">清除</button></div></div>';
    h+='<div class="srow"><span class="lab">端点 base_url</span><span class="kv" id="set-baseurl"></span></div>';
    h+='<div class="srow"><span class="lab">密钥环境变量</span><span class="kv" id="set-keyenv"></span></div>';
    h+='<div class="srow"><button class="btn" id="set-applymodel">切换到此模型</button><span class="note" id="set-modelnote" style="margin:0;flex:1"></span></div>';
    c.innerHTML=h;
    var psel=c.querySelector('#set-provider'), msel=c.querySelector('#set-model');
    var groups={};
    provs.forEach(function(p){var r=p.region||'global';(groups[r]=groups[r]||[]).push(p);});
    ['cn','global'].forEach(function(reg){
      if(!groups[reg])return;
      var og=document.createElement('optgroup'); og.label=(reg==='cn'?'国内':'海外');
      groups[reg].forEach(function(p){
        var o=document.createElement('option'); o.value=p.name;
        o.textContent=p.name+(p.free_tier?' · 免费额度':'');
        if(p.desc)o.title=p.desc;
        if(p.name===curProv)o.selected=true; og.appendChild(o);
      });
      psel.appendChild(og);
    });
    function selProv(){return provs.find(function(x){return x.name===psel.value;});}
    function fillModels(){
      var p=selProv(); msel.innerHTML='';
      var tags=(p&&p.tags)||{};
      (p&&p.models||[]).forEach(function(m){
        var o=document.createElement('option'); o.value=m;
        o.textContent=m+(tags[m]==='free'?' · 免费':(tags[m]==='paid'?' · 付费':''));
        if(p.name===curProv&&m===model.model)o.selected=true; msel.appendChild(o);
      });
      var st=c.querySelector('#set-keystatus');
      if(p&&p.key_set){st.textContent='已配置';st.className='badge ok';}else{st.textContent='未配置';st.className='badge no';}
      c.querySelector('#set-baseurl').textContent=(p&&p.base_url)||'';
      c.querySelector('#set-keyenv').textContent=(p&&p.api_key_env)||'';
    }
    psel.addEventListener('change',fillModels); fillModels();
    function keyAction(key){
      var p=selProv(); if(!p||!p.api_key_env){setNote(c.querySelector('#set-modelnote'),false,'该供应商无需密钥');return;}
      fetch('/api/config/apikey',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({env:p.api_key_env,key:key})}).then(function(r){return r.json();}).then(function(j){
        setNote(c.querySelector('#set-modelnote'),j.ok,j.ok?(key?'密钥已保存 (重启仍生效)':'密钥已清除'):('失败: '+(j.error||'')));
        if(j.ok){var st=c.querySelector('#set-keystatus');if(key){st.textContent='已配置';st.className='badge ok';}else{st.textContent='未配置';st.className='badge no';}}
      }).catch(function(e){setNote(c.querySelector('#set-modelnote'),false,'失败: '+e.message);});
    }
    c.querySelector('#set-keysave').addEventListener('click',function(){keyAction(c.querySelector('#set-apikey').value.trim());});
    c.querySelector('#set-keyclear').addEventListener('click',function(){c.querySelector('#set-apikey').value='';keyAction('');});
    c.querySelector('#set-applymodel').addEventListener('click',function(){
      var prov=psel.value, mdl=msel.value, key=c.querySelector('#set-apikey').value.trim();
      fetch('/api/config/model',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({provider:prov,model:mdl,api_key:key})}).then(function(r){return r.json();}).then(function(j){
        setNote(c.querySelector('#set-modelnote'),j.ok,j.ok?('已切换到 '+prov+'/'+mdl+(j.note?(' · '+j.note):'')):('失败: '+(j.error||'')));
      }).catch(function(e){setNote(c.querySelector('#set-modelnote'),false,'失败: '+e.message);});
    });
  }
  function renderAbout(c,d){
    var m=d.model||{};
    c.innerHTML=sec('关于')
      +'<div class="srow"><span class="lab">工作区</span><span class="kv">'+esc(d.workspace||'')+'</span></div>'
      +'<div class="srow"><span class="lab">引擎</span><span class="kv">'+esc(d.engine||'')+'</span></div>'
      +'<div class="srow"><span class="lab">当前模型</span><span class="kv">'+esc((m.provider||'')+'/'+(m.model||''))+'</span></div>'
      +'<div class="srow"><span class="lab">端点</span><span class="kv">'+esc(m.base_url||'')+'</span></div>'
      +'<div class="hint">Web 工作台与 TUI 共用同一份配置 (~/.tuan/config.yaml 与 ~/.tuan/.env)。此处改动即时持久化, 对当前及后续会话生效。</div>';
  }

  /* ---- 工作面板的初始加载 (面板打开时才拉, 省流量) ---- */
  togglePanel(false);

  loadSlash();
  loadInfo();loadSessions();
  /* 初始: 显示欢迎屏并启动粒子 */
  showWelcome();
})();
</script>
</body>
</html>
"""
