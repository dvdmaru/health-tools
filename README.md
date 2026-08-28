# health-tools — 健檢數據誌（health.twtools.cc）

健康檢查報告上的數字，逐項並列不同機構公布的判準值；每一列都綁「機構＋文件＋版本＋頁碼」，
四項不齊備的數字不渲染。100% 靜態、server-rendered、零 client fetch（為被 AI 引用而設計）。

- 站台：https://health.twtools.cc/ （**尚未部署**，見下方「目前狀態」）
- 定位：不替讀者選邊、不下醫療判斷；本站整理的是「公開文件寫了什麼」。

## 目前狀態（M0 地基，2026-08-28）

地基已就緒，**零內容頁、未部署、未建 GitHub remote**。`public-health/` 目前只有骨架
（首頁殼、文章索引殼、feed、llms.txt、robots.txt、sitemap.xml、共用 CSS）。
`config/site.json` 的 `published` 為 `false`，帶 `"requires": "published"` 的導覽與頁尾
入口一律不輸出——翻開關之前，站上不會出現任何連到未生成頁面的死連結。

## 三層架構

1. **來源快照層**：`scripts/fetch-health-source.py` 把官方 PDF／網頁抓成快照落到
   `data/sources/<id>.{pdf,html}`，並在 `data/sources/manifest.json` 登記一列
   （id／機構／版本／抓取日／sha256／授權分桶）。schema：`data/sources/schema.json`。
2. **判準明細層**：`data/criteria/<indicator>.json`，一列＝某機構在某份文件的某個位置
   對某個族群給出的一組界線，必帶原文引句。schema：`data/criteria/schema.json`。
   **只存明細，不存統計**——頁面要顯示「幾個機構」就對明細做 `len()`，不預先存一個數字。
3. **靜態產出層**：`articles/<slug>/index.md` → `scripts/build-articles.py` → 靜態頁；
   指標頁另有一條：`articles/indicators/<slug>.md`（只有敘事）＋ `data/criteria/` →
   `scripts/gen-indicator.py` → `/indicators/<slug>/`。判準表、判準數線、沿革時間軸、
   失真卡全部由資料生成，**md 內不得再寫一份表格**（寫了就中止）。
   sitemap 走 manifest 合併（各生成器只寫 `data/sitemap-parts/<owner>.txt`，
   `scripts/build-sitemap.py` 統一合併）。部署走 Cloudflare Workers static assets。

## 常用指令

```bash
# 重建（不部署）。跑序固定：文章 → 指標頁 → sitemap 合併
python3 scripts/build-articles.py
python3 scripts/gen-indicator.py
python3 scripts/build-sitemap.py

# 禁詞 gate（絕對禁詞命中 exit 1；需附條件的詞印 WARN 不擋）
python3 scripts/check-health-terms.py
python3 scripts/check-health-terms.py --verbose      # 連被放行的命中一起列出

# 測試（需 markdown 與 jsonschema）
python3 -m unittest discover -s tests

# 決定性驗收：同輸入連跑兩次，全站產物 SHA-256 必須全同
python3 scripts/build-articles.py && python3 scripts/gen-indicator.py && python3 scripts/build-sitemap.py
find public-health -type f -exec shasum -a 256 {} + | sort -k2 > /tmp/b1.sha
python3 scripts/build-articles.py && python3 scripts/gen-indicator.py && python3 scripts/build-sitemap.py
find public-health -type f -exec shasum -a 256 {} + | sort -k2 > /tmp/b2.sha
diff /tmp/b1.sha /tmp/b2.sha && echo "byte-identical"

# 收據 gate：每一條判準／變更史／限制列的引句都要 grep 得回快照
python3 scripts/check-receipts.py
python3 scripts/check-receipts.py --verbose        # 連 PASS 的列一起列出

# 抓一份來源快照（被防火牆擋會 fail-honest 中止，不存攔截頁）
python3 scripts/fetch-health-source.py --id <id> --url <url> \
  --title "<原文標題>" --org "<機構全名>" --doc-type pdf \
  --version "<文件標示的版本>" --license-bucket tw-gov
```

## 引句回查（收據 gate）

`scripts/check-receipts.py` 對 `data/criteria/` 的每一列做四件事：doc_id 必須指得到
`data/sources/manifest.json`；quote（含 `quote_extra`、`corroboration`）非空；
快照在磁碟上時每一句都必須 grep 得到；快照不在時印 **SKIP 而不是 PASS**。

- **PDF 比對前要正規化空白**：`pdftotext -layout` 會在中文與數字之間插入或吃掉空白
  （例：`糖化血色素≧ 6.5%`）。gate 對引句與快照雙方都做 `re.sub(r"\s+", "", …)`。
  用原樣 grep 判定「引句不存在」是假陰性，踩過就知道。
- **全形半形不轉換**：來源自己的 `≧`／`≥`、`mg/dl`／`mg/dL` 不一致是回查原文的指紋。
  gate 只吃空白，不折疊字形——把 `≥` 寫成 `≧` 就該紅（`tests/test_receipts.py` 有這條）。
- **不要用 curl 重驗 diabetesjournals.org 與 hpa.gov.tw**：兩者對 curl 回 403／攔截頁，
  會把「引句存在」誤判成「不存在」。這兩批快照是瀏覽器抽出的純文字
  （`doc_type: html-text`、`retrieval: browser-text`）。
- **licensed-cite-only 的快照不入版控**：本 repo 是 public 的，整份 ADA／WHO／DAROC／NGSP
  文件推上公開 repo 就是整段重製。快照留在本機，manifest 保留 sha256（偵測上游改版的
  訊號是雜湊，不是檔案）。CI 上這些列印 SKIP，完整驗證在本機跑。
- **沒有例外清單，也不准加**：引句 grep 不中只有兩種可能——引句抄錯了，或快照不是那份
  文件。兩種都停下來給人裁決，不准塞例外，也不准反過來改 quote 去遷就快照。

## 部署方式（本輪未執行）

Cloudflare Workers static assets ＋ custom domain，與姊妹站同一套：

```bash
CLOUDFLARE_API_TOKEN=$(cat ~/.config/cloudflare/<token 檔>) \
CLOUDFLARE_ACCOUNT_ID=<account id> \
npx wrangler deploy -c wrangler-health.jsonc </dev/null
```

`wrangler-health.jsonc` 的 `routes` 設了 `health.twtools.cc` 的 custom domain，
Cloudflare 會自動建 DNS 記錄與憑證（前提：`twtools.cc` zone 在同一帳號）。
Token 與 account id 永不入 repo，走環境變數或 GitHub Secrets
（`CLOUDFLARE_API_TOKEN`／`CLOUDFLARE_ACCOUNT_ID`）。

### 驗證部署（不要自己挑哨兵字串）

```bash
python3 scripts/verify-deploy.py public-health/index.html
```

拿本機剛 build 好的檔案跟線上**整檔 byte 比對**，不符會印出第一個差異點的前後文。
不要用「grep 一個自己想的關鍵字」驗部署：本站群為此踩過 5 次以上，每次挑到的字串
在舊版本裡也存在 → 假陽性。HTTP 200 同樣不能當訊號：決定性靜態產出幾乎永遠回 200。

## 紅線

- **不下醫療判斷**：本站只整理公開文件寫了什麼，不做診斷、不給個人化處置建議。
  指標頁固定六段結構，不得夾帶第七段（治療建議／用藥／科別／機構）。
- **禁詞 gate**：`config/banned-terms.json` 五類（招徠／療效／產品／自我標榜／gate 語言），
  由 `scripts/check-health-terms.py` 在 CI 強制。唯一的導引就醫例外是
  「客觀列出具體急症徵象後接 119／急診」句型，且機器只驗得了句型，用在非緊急情境
  擋不住——那要人工核。
- **四項出處**：判準值必須齊備機構、文件、版本、頁碼；缺一即不渲染。
- **引句照抄**：不做繁簡、標點、單位大小寫的美化。原文的 `≧`／`≥`、`mg/dl`／`mg/dL`
  不一致就照抄，那是回查原文的鑰匙。
- **只存明細**：判準層禁止任何統計／彙總欄位（schema 已用 `additionalProperties: false`
  與測試雙重擋）。變更史（`*-history.json`）與已知限制（`*-interference.json`）同規。
- **方向不猜**：干擾因子的 `direction` 只收來源明講的；來源只說「會影響」就標
  `unspecified`。方向寫反是這一層最貴的錯（腎病在 WHO Annex 1 是讓 A1C 偏**高**）。
- **零密鑰**：token 全走環境變數／GitHub Secrets。

## 里程碑

`task-prd.md` 有 Story 1–7 的逐項驗收條件。M0（Story 1）已完成。
