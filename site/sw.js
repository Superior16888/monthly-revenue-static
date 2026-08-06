/* 台股月營收 — service worker
 *
 * 快取策略刻意分成兩類，不要合併：
 *
 *   殼層 (SHELL)  precache，cache-first + 背景更新（stale-while-revalidate）
 *                 含 plotly.min.js 4.7MB —— 離線能看圖就是靠它，值得一次付清。
 *   月份資料      **絕不** precache。site/data/ 有 324 個檔、共 54MB，全抓會塞爆
 *                 使用者的儲存空間。改用 network-first + LRU 上限 DATA_MAX 筆。
 *
 * HTML 走 stale-while-revalidate：growth.html 每月重新產生，若用 cache-first 而
 * 不回寫，使用者會永遠停在第一次安裝時的那份報告。
 */
const VERSION = 'v1';
const SHELL_CACHE = `shell-${VERSION}`;
const DATA_CACHE = `data-${VERSION}`;
const DATA_MAX = 12;                     // 約 2.4MB（每檔 ~200KB）

const SHELL = [
  './',
  './index.html',
  './growth.html',
  './plotly.min.js',
  './manifest.json',                     // treemap 的月份索引（非 PWA manifest）
  './app.webmanifest',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-512.png',
  './apple-touch-icon.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(SHELL_CACHE)
      // 逐一 add：任一項 404 時 addAll 會整批失敗，安裝就永遠不會完成
      .then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== SHELL_CACHE && k !== DATA_CACHE)
            .map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

async function trimCache(name, max) {
  const c = await caches.open(name);
  const keys = await c.keys();
  for (let i = 0; i < keys.length - max; i++) await c.delete(keys[i]);
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // 月份資料：先連網（要拿到最新公布的月份），失敗才回快取
  if (url.pathname.includes('/data/')) {
    e.respondWith((async () => {
      try {
        const res = await fetch(req);
        if (res.ok) {
          const c = await caches.open(DATA_CACHE);
          await c.put(req, res.clone());
          trimCache(DATA_CACHE, DATA_MAX);
        }
        return res;
      } catch (err) {
        const hit = await caches.match(req);
        if (hit) return hit;
        throw err;
      }
    })());
    return;
  }

  // 殼層：先給快取（秒開），同時背景抓新版寫回，下次進來就是新的
  e.respondWith((async () => {
    const cached = await caches.match(req);
    const fresh = fetch(req).then(async (res) => {
      if (res.ok) (await caches.open(SHELL_CACHE)).put(req, res.clone());
      return res;
    }).catch(() => null);
    return cached || (await fresh) || new Response(
      '<meta charset="utf-8"><p style="font-family:sans-serif;padding:2em">'
      + '離線中，且這個頁面尚未快取。</p>',
      { headers: { 'Content-Type': 'text/html; charset=utf-8' }, status: 503 }
    );
  })());
});
