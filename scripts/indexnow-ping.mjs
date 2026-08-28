#!/usr/bin/env node
/**
 * IndexNow ping — 把新增/更新的 URL 推給 IndexNow（api.indexnow.org 分發給
 * Bing/Yandex/Naver/Seznam 等參與引擎；Bing 索引另餵 ChatGPT search / Copilot）。
 *
 * 用法：node scripts/indexnow-ping.mjs <url> [url...]
 *   - URL 必須屬於 HOST，其他一律拒收（避免誤 ping 別人的站吃信譽懲罰）
 *   - 回 200/202 都算成功（202 = key 驗證排程中，正常）
 *
 * 站群共通腳本，只改 HOST/KEY。
 *
 * ⚠️ M0 尚未配發本站的 IndexNow key：KEY 未設時直接中止並說明要做什麼，
 * 不假裝送出。金鑰是公開值（要放在站根 <KEY>.txt），但仍不寫死在這裡——
 * 產生 key 與落地 key 檔是 SEO 基建里程碑的工作，接線先備好。
 */
const HOST = process.env.INDEXNOW_HOST ?? 'health.twtools.cc';
const KEY = process.env.INDEXNOW_KEY ?? '';

if (!KEY) {
  console.error(
    `ABORT: 尚未設定 INDEXNOW_KEY（${HOST}）。\n` +
    '請先產生 32 碼十六進位金鑰，落地成 public-health/<key>.txt（內容即金鑰本身），\n' +
    '再把金鑰填進本檔或以 INDEXNOW_KEY 環境變數傳入。');
  process.exit(1);
}

const urls = [...new Set(process.argv.slice(2))];
const bad = urls.filter((u) => !u.startsWith(`https://${HOST}/`) && u !== `https://${HOST}`);
if (bad.length) {
  console.error(`ABORT: URL 不屬於 ${HOST}：\n${bad.join('\n')}`);
  process.exit(1);
}
if (!urls.length) {
  console.error('用法：node scripts/indexnow-ping.mjs <url> [url...]');
  process.exit(1);
}

const res = await fetch('https://api.indexnow.org/indexnow', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
  body: JSON.stringify({
    host: HOST,
    key: KEY,
    keyLocation: `https://${HOST}/${KEY}.txt`,
    urlList: urls,
  }),
});

const body = await res.text();
console.log(`IndexNow → HTTP ${res.status} ${body || '(empty body)'}`);
console.log(urls.map((u) => `  ✓ ${u}`).join('\n'));
if (res.status !== 200 && res.status !== 202) process.exit(1);
