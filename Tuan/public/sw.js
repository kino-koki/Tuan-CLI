/* Tuan PWA Service Worker（T-6.3）
 * 策略：
 *  - 静态资源（HTML/JS/CSS/字体/图标）：缓存优先，命中即离线可用；
 *  - 其它请求（引擎 API /api/*、外部模型接口）：直接走网络，绝不缓存
 *    （会话数据必须实时，缓存会导致删除/导出状态错乱）；
 *  - 缓存版本号升级时清掉旧缓存。
 * 兼容 Android 8 Chrome 68：不用 ES6+ 语法之外的新特性。
 */
const CACHE_NAME = 'tuan-shell-v1';
const PRECACHE = [
  './',
  './index.html',
];

// 安装：预缓存外壳
self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function (cache) { return cache.addAll(PRECACHE); })
      .then(function () { return self.skipWaiting(); })
  );
});

// 激活：清掉旧版本缓存
self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k !== CACHE_NAME; })
            .map(function (k) { return caches.delete(k); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

// 请求：API 直通网络；其余缓存优先
self.addEventListener('fetch', function (event) {
  var url = event.request.url;

  // 引擎会话/聊天等接口永不缓存，避免删除后仍读到旧列表
  if (url.indexOf('/api/') !== -1) return;

  // 非 GET 不干预
  if (event.request.method !== 'GET') return;

  event.respondWith(
    caches.match(event.request).then(function (cached) {
      if (cached) return cached;
      return fetch(event.request).then(function (resp) {
        // 只缓存同源成功响应（静态资源），失败响应绝不入库
        if (!resp || resp.status !== 200 || resp.type !== 'basic') return resp;
        var copy = resp.clone();
        caches.open(CACHE_NAME).then(function (cache) { cache.put(event.request, copy); });
        return resp;
      }).catch(function () {
        // 离线且无缓存：页面请求回退到外壳
        if (event.request.mode === 'navigate') return caches.match('./index.html');
        return Response.error();
      });
    })
  );
});
