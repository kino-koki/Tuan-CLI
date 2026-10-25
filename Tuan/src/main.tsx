import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { initPwa } from './platform/pwa';

// PWA：注册 Service Worker + 拦截 beforeinstallprompt（失败静默，不影响主流程）
initPwa();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
