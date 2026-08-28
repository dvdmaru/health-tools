# health.twtools.cc 建站（健檢數據誌，twtools 站群第 4 個「○○數據誌」）

**Task 起手日**：2026-08-28
**完工硬性條件**：所有 story 全部 ✅（內容 story 例外：PR 開好停等 Charlie cross-check
即算該階段完成）

---

## Story 1: Repo 骨架（M0，零新頁）✅

- [x] `git init`（main）＋ 站群共通引擎移植：`build-articles.py`／`build-sitemap.py`／
      `verify-deploy.py`／`indexnow-ping.mjs`／`healthlib.py`，零賽事殘留
- [x] `config/site.json`（base／org／website／nav／ga_id 空／`published: false`）
      與 `config/draft-exclude.json`
- [x] `wrangler-health.jsonc`（assets `public-health`、custom domain `health.twtools.cc`）
      ＋ `public-health/_headers`（CSP／HSTS／長快取 assets）
- [x] 禁詞 gate：`config/banned-terms.json`（Style Spec §3 五類）
      ＋ `scripts/check-health-terms.py` ＋ `tests/test_health_terms.py`（陽性＋陰性兩組）
- [x] 來源快照層：`data/sources/schema.json` ＋ `scripts/fetch-health-source.py`
      （防火牆／403 偵測 fail-honest，不存攔截頁）
- [x] 判準明細層：`data/criteria/schema.json` ＋ `tests/test_criteria_schema.py`
      （HbA1c facts pack 1A-#1／#5 手打 fixture）
- [x] `.github/workflows/tests.yml` ＋ `.github/dependabot.yml`
- [x] 零文章狀態 build 跑得完，連跑兩次全站 SHA-256 全同（禁時間戳）
- [x] 零密鑰：`grep -riE "(api[_-]?key|token|secret).{0,4}[:=]" scripts config *.jsonc`
      無密鑰值命中
- [x] 一次 initial commit 進 main（不 push、不建 remote）

## Story 2: 來源落地（M1）

- [ ] HbA1c facts pack 的 S1–S12 逐份落地成快照，`data/sources/manifest.json` 齊備
- [ ] hpa.gov.tw／diabetesjournals.org 走瀏覽器抓取，manifest 的 `retrieval` 標 `browser`
      並在 `note` 記錄取得方式
- [ ] 每份快照的 sha256 入 manifest；`license_bucket` 逐份具名裁決
      （`licensed-cite-only` 的快照不得公開發布）
- [ ] PDF 引句驗證流程寫進文件：`pdftotext -layout` 會在中文與數字間插入或吃掉空白，
      比對前要先正規化空白，不得用原樣 grep 就判定不符

## Story 3: 判準明細層（M2，一頁都不寫）

- [ ] `data/criteria/hba1c.json` 逐列落地（ADA／WHO／國健署／糖尿病學會），
      每列必帶四項出處與原文引句
- [ ] 引句可回查：每列的 `quote` 都能在對應快照裡 grep 到（PDF 走空白正規化）
- [ ] 不變量測試：`doc_id` 必須指得到 `data/sources/manifest.json` 的既有 id；
      指不到即 exit 1
- [ ] 例外即斷言：失敗集合必須恰好等於宣告的例外集合。
      **gate 紅了要停下回報，不准把錯誤塞進例外清單合法化**
- [ ] 分類正確性人工核：篩檢分流門檻（5.7／5.9／6.1%）不得標成 `diagnosis`
- [ ] 統計禁令的機器防線：AST 掃描測試，確認統計函式內不存任何彙總欄位

## Story 4: 單頁定調（M3）

- [ ] `/indicators/hba1c/` 單頁生成，固定六段結構（Style Spec §4），順序不可調換
- [ ] ②各機構判準並列表：每列四欄（機構｜判準值｜族群｜依據文件與版本）必填，缺一不渲染
- [ ] ③判準沿革：1997／2003／2009／2010 四次變更逐條附來源
- [ ] 禁詞 gate 全綠（絕對禁詞 0；WARN 逐條人工判定並留紀錄）
- [ ] 語意強度鎖表逐詞人工核（Style Spec §2）
- [ ] 給 Charlie 定調，**預期被打回 1–2 輪——這是 feature 不是 bug**

## Story 5: SEO/GEO 基建（M4）

- [ ] llms.txt（build-time 生成）、robots.txt、sitemap.xml manifest 合併
- [ ] IndexNow：產生本站金鑰、落地 `public-health/<key>.txt`、
      `indexnow-ping.mjs` 接上（M0 已備好接線，金鑰未配發時 fail-honest 中止）
- [ ] 姊妹站互連 footer 補上體育線各站（M0 只列了通用站；
      這是新站唯一可靠的被發現路徑，清單只增不減）
- [ ] JSON-LD `@graph` ＋ FAQPage 鏡射可見文字
- [ ] og-home.png 1200×630 ＋ favicon／icons／webmanifest

## Story 6: 展開與自動化（M5）

- [ ] 第二、第三個指標展開（先確定六段結構在不同指標上都站得住，再全量）
- [ ] `/indicators/` 索引頁；`config/site.json` 的 `published` 翻 true
      （翻開關前的行為必須 byte-identical，要有測試證明）
- [ ] `gh repo create` ＋ push main ＋ secrets 設定並 `gh secret list` 驗證
- [ ] `wrangler deploy` 上線，`verify-deploy.py` 整檔比對驗證（不挑哨兵字串、不信 200）
- [ ] 判準版本監測：來源 sha256 變動時發出訊號（上游改版不得靜默）

## Story 7: 收尾

- [ ] PUBLIC 終掃（含 git 歷史零密鑰）
- [ ] 記憶同步：CoWork L0 專案表＋L2、per-project 記憶新增本站行
- [ ] Charlie 手動待辦清單（🔴 粗體）：GA4 property／GSC／sites-dashboard／選題台
