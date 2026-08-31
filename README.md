# health-tools — 健檢數據誌（health.twtools.cc）

健康檢查報告上的數字，逐項並列不同機構公布的判準值；每一列都綁「機構＋文件＋版本＋頁碼」，
四項不齊備的數字不渲染。100% 靜態、server-rendered、零 client fetch（為被 AI 引用而設計）。

- 站台：https://health.twtools.cc/ （**尚未部署**，見下方「目前狀態」）
- 定位：不替讀者選邊、不下醫療判斷；本站整理的是「公開文件寫了什麼」。

## 目前狀態（M5 索引＋折疊＋勘誤，2026-08-28）

**M5 加了三件事**：`/indicators/` 索引頁（`scripts/gen-indicators-index.py`，卡片上的列數／機構數／來源數
／沿革年份全由資料算，跑在 `gen-indicator.py` 之後）；判準表改成「指標→判定類別」分組的原生 `<details>`
折疊（診斷／分級／風險門檻預設展開，整頁 ≤12 列全展開，無 JS、內容都在 DOM）；勘誤機制（見下）。
`published` 已於 2026-08-28 翻 true（Story 6，Charlie 授權公開）；翻開關前後 186 tests 皆綠。

**5 個指標頁已生成（dormant，未部署）**：`/indicators/hba1c/`（M3 定調）、`/indicators/blood-pressure/`
（sbp＋dbp）、`/indicators/lipids/`（total-chol／ldl-c／hdl-c／tg）、`/indicators/uric-acid/`、
`/indicators/bmi-waist/`（bmi＋waist）。來源 manifest 52 份（M6 補 6 份未落地來源；licensed-cite-only 快照本機留、CI SKIP），
判準明細＋沿革＋失真列全部過收據 gate。M4 落地時的紀律與坑：

- **一頁多指標**：frontmatter `indicator_ids`＋`indicator_labels`，資料檔以 slug 定位；每個 indicator_id
  一條數線，座標軸在 `gen-indicator.py` 的 `AXIS`（呈現層）指定，未列名者由資料推導。
- **`gen-indicator.py <slug>` 只生成該頁，不清別人的輸出**；只有不帶參數的全量 build 才 prune。
  （平行寫手各跑自己的 slug 時互相刪頁，踩過。）
- **收據 gate 與 `tests/test_receipts.py` 動態掃 `data/criteria/*.json`**，新指標不必回來登記檔名。
- **hpa.gov.tw 的 `List.aspx` 頁 curl 抓得到，`Detail.aspx` 會被導回首頁**——後者仍走瀏覽器。
- **雙欄排版 PDF（JFMA 等）`pdftotext -layout` 會左右欄交錯**，整句 grep 必失；把同一句的相鄰片段
  放 `quote`＋`quote_extra`，每段各自受 gate。含 `≥` 的 PDF 常抽成控制字元，登記純文字快照時 note 寫明。
- **代謝症候群「五項符合三項」不落在任何單一指標頁**（在 mmHg／cm 表裡會讀成該指標的診斷線）；
  各因子門檻以 `risk_threshold` 落在對應指標頁，note 標明非診斷。
- 治療目標（LDL 目標值、降尿酸目標、血壓治療目標）與用藥立場**不進判準表**（MODEL.md §3）。
- `check-health-terms.py` 目前 14 個 WARN 全是「預防」出現在文件名（初級預防指引），非療效語境，放行。
- **勘誤機制**：公開後改過的數字或說明文字＝`data/errata.json` 一列（schema 在 `data/errata-schema.json`，
  收據 gate 對有 `doc_id` 的列一樣逐句 grep）。有勘誤的指標頁自動多一段「勘誤紀錄」，站級清單在 `/errata/`
  （`published` 才進 sitemap／llms.txt／頁尾）。目前是 `[]`——上線前的修改不是勘誤，不補記。

`config/site.json` 的 `published` 仍為 `false`，`public-health/` 只有骨架與 dormant 指標頁。
`config/site.json` 的 `published` 為 `false`，帶 `"requires": "published"` 的導覽與頁尾
入口一律不輸出——翻開關之前，站上不會出現任何連到未生成頁面的死連結。

## 三層架構

1. **來源快照層**：`scripts/fetch-health-source.py` 把官方 PDF／網頁抓成快照落到
   `data/sources/<id>.{pdf,html}`，並在 `data/sources/manifest.json` 登記一列
   （id／機構／版本／抓取日／sha256／授權分桶）。schema：`data/sources/schema.json`。
2. **判準明細層**：`data/criteria/<slug>.json`（＋`<slug>-history.json`、
   `<slug>-interference.json`），一列＝某機構在某份文件的某個位置對某個指標、某個族群
   給出的一組界線，必帶原文引句。schema：`data/criteria/schema.json`。
   **只存明細，不存統計**——頁面要顯示「幾個機構」就對明細做 `len()`，不預先存一個數字。
   檔名認的是**頁面 slug**，一個檔可以裝多個 `indicator_id`（血壓頁＝sbp＋dbp）。
3. **靜態產出層**：`articles/<slug>/index.md` → `scripts/build-articles.py` → 靜態頁；
   指標頁另有一條：`articles/indicators/<slug>.md`（只有敘事）＋ `data/criteria/` →
   `scripts/gen-indicator.py` → `/indicators/<slug>/`。判準表、判準數線、沿革時間軸、
   失真卡全部由資料生成，**md 內不得再寫一份表格**（寫了就中止）。
   sitemap 走 manifest 合併（各生成器只寫 `data/sitemap-parts/<owner>.txt`，
   `scripts/build-sitemap.py` 統一合併）。部署走 Cloudflare Workers static assets。

### 指標頁 frontmatter（`articles/indicators/<slug>.md`）

| 欄位 | 必填 | 說明 |
|---|---|---|
| `slug` | 是 | 頁面網址與三個資料檔的檔名前綴 |
| `indicator_ids` | 多指標頁必填 | `[sbp, dbp]`——這頁收 `data/criteria/<slug>.json` 裡哪些 `indicator_id`。單數的 `indicator_id` 仍支援（＝單元素）；兩者都沒有＝用 slug |
| `indicator_labels` | 多指標頁必填 | `{sbp: 收縮壓, dbp: 舒張壓}`——判準表「指標」欄與各數線標題的中文短標籤。**缺一個就中止**，生成器不從 id 造中文、不從單位猜 |
| `criteria_chart_caption` | 單指標頁必填 | 判準數線的標題（單指標頁的標題是編輯下的判斷，推導不出來）。多指標頁不吃這欄：每條數線的標題＝短標籤＋單位 |
| `sources` | 是 | 第⑥段「來源與版本」的順序，指向 `data/sources/manifest.json` 的 id |

多指標頁的判準表最前面多一欄「指標」，每個 `indicator_id` 各畫一條數線（座標軸在
`gen-indicator.py` 的 `AXIS`，以 `indicator_id` 為鍵，未列名者由該指標的資料推導）；
沿革時間軸與失真卡整頁共用一份（`<slug>-history.json`／`<slug>-interference.json`）。

圖上的**顏色語意是「機構屬性」**（`ORG_FAMILY_COLOR`：`tw-gov`／`tw-society`／`intl`／
`us`／`other`），不是逐個機構挑色票——新指標會帶進新機構，逐一挑遲早撞色或輪替，
讀者就得重學一次圖例。名單外的機構走 fallback 灰＋機構全名。

## 常用指令

```bash
# 重建（不部署）。跑序固定：文章 → 指標頁（含 /errata/）→ 指標索引 → sitemap 合併
python3 scripts/build-articles.py
python3 scripts/gen-indicator.py
python3 scripts/gen-indicators-index.py
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

## 來源改版監測

`scripts/check-source-drift.py` 由 `.github/workflows/source-drift.yml` 每週一
01:00 UTC（台北 09:00）跑一次，也能 `workflow_dispatch` 手動觸發。

**驗的不是任何一種 sha256（raw bytes 也好、正規化後的文字也好），是判準列引用的那句
話還在不在**。理由跟上面「快照不入版控只留 sha256」是同一個：52 份來源裡 19 份是
瀏覽器抽出的純文字快照，跟線上 raw bytes 本來就對不上；線上 HTML 每次抓也可能因
nonce／時間戳／廣告位變動，raw sha 比對只會天天假警報。PDF 也一樣不穩——EULAR 的
PDF 實測連續 curl 三次，同 size 卻出現兩種不同 raw sha256。2026-08-28 CI 首次實跑
（Ubuntu runner）又推翻了「那就比正規化後的文字 sha」這個退而求其次的方案：5 份 PDF
被判 drift，但內容根本沒變——**baseline 是在本機 macOS 建的，CI 在 Ubuntu 比對，兩邊
的 `pdftotext`（poppler-utils）版本不保證一致，同一份 PDF 抽出來的文字本身就可能有
斷行／空白差異**，跟文件有沒有改版無關。所以 `remote_sha256`／`text_sha256` 這兩個
欄位在監測裡只當資訊，不當 drift 訊號——警報疲勞後沒人看＝等於沒監測，HTML 跟 PDF
用同一條規則，不分家。站的唯一承諾是「每個數字都能回查原文」，會傷到這個承諾的只
有一種事——判準列引用的那句話從線上版消失了。監測就定在這一層（D6：驗在缺陷顯現
那層）。

```bash
# 全量檢查，印摘要表，寫報告（預設寫到 ROOT/.drift/，該目錄已 .gitignore）
python3 scripts/check-source-drift.py

# 只查一份
python3 scripts/check-source-drift.py --only <id>

# 重建 baseline（平常執行只讀不寫，CI 不會、也不准 commit）
python3 scripts/check-source-drift.py --update-baseline
# ⚠️ --update-baseline 會把整份 baseline 重寫成「這次跑到的來源」——不要跟 --only 一起用，
#    否則 baseline 只剩那一筆；新增來源後一律全量重建（52 份約 3 分鐘）。

# 指定報告輸出位置
python3 scripts/check-source-drift.py --report PATH.md --json PATH.json
```

狀態語意（一個欄位一種語意，不准混）：

| 狀態 | 意思 |
|---|---|
| `ok` | 可抓、baseline 裡驗過在的引句這次全在 |
| `changed-quotes-intact` | 引句全在，但 `remote_sha256`／`text_sha256` 跟 baseline 不同——純資訊，不算 drift。sha 類欄位天生不穩（HTML 的 nonce／廣告位、PDF 重新打包時 raw bytes 本身就會變、甚至只是換一台機器跑 `pdftotext` 版本不同就讓 `text_sha256` 跟著變），不能拿來當改版訊號 |
| `drift` | baseline 裡驗過在的引句現在找不到——HTML／PDF 同一條規則，不看 sha |
| `never-verified` | baseline 建立當下這份文件的引句本來就沒對齊（通常是 JS 渲染或 PDF 抽字差異）——這些引句不納入 drift 判定，但報告會單獨列出，不准默默吞掉 |
| `blocked` | 403／WAF 攔截頁／人機挑戰頁（hpa.gov.tw `Detail.aspx`、diabetesjournals.org、PMC 對 GitHub runner IP 回的 reCAPTCHA 頁這一類）——監測不到，報告寫「無法確認，需瀏覽器」，**不是** `ok`，也**不是** `drift`（挑戰頁的引句本來就一句都不在，判成改版是假警報） |
| `unreachable` | 網路錯誤或逾時；curl exit 60（SSL 憑證鏈驗不過）會先改用 `-k` 不驗證憑證重抓一次，成功則正常分類（結果多一個 `tls_verified: false`，報告會單獨列一節），兩次都失敗才算 unreachable |
| `no-quotes` | manifest 有登記、`data/criteria/` 沒引用到——只比 sha，變了記 `changed-quotes-intact`，不算 drift |

exit code：`0` 無 drift；`1` 至少一份 `drift`；`2` 全部 `unreachable`／`blocked`（監測
本身失效，CI 不准當綠燈）；`3` 設定錯（baseline 缺、manifest 壞）。

**`tls_verified: false` 是什麼**：2026-08-28 CI 首次實跑發現 hpa.gov.tw 在 Ubuntu
runner 上對 curl 回 `exit 60`（`SSL certificate problem: unable to get local issuer
certificate`）——hpa 的憑證鏈缺中繼憑證，本機 macOS 靠系統鑰匙圈（額外信任存放區）
矇混過去，Ubuntu 的 curl 只認標準 CA bundle，10 份全判成 unreachable。腳本改成 exit
60 時自動改用 `-k` 重抓一次；成功的話正常判定狀態，但把 `tls_verified` 標 `false`，
報告加一節列出「TLS 憑證鏈驗不過、已改不驗證憑證重抓」的 id，讓人知道這份資料是繞
過憑證驗證抓到的（不影響 drift 判定，判定只看引句）。這個欄位只在當次報告／JSON
裡，不進 `drift-baseline.json`——它是「這次怎麼抓到的」診斷資訊，不是「上次驗過
什麼」的事實。

### 收到 drift issue 之後：人要做什麼

CI 對 exit 1／2 用 label `source-drift` 找開著的 issue，有就貼新報告當 comment，沒有
就開一份——同一個 label 去重，不會每週疊新 issue。收到之後：

1. 開瀏覽器看 issue 裡列出的線上版網址。
2. 對照判準列引用的那句話還在不在、意思有沒有變。
3. **真的變了**：改對應的 `data/criteria/*.json`（或 `*-history.json`）→ 在
   `data/errata.json` 加一列（schema：`data/errata-schema.json`，收據 gate 對有
   `doc_id` 的列一樣逐句 grep）→ `scripts/fetch-health-source.py` 重抓快照、更新
   manifest → `python3 scripts/check-source-drift.py --update-baseline` → 開 PR。
4. **只是排版或改版但那句話沒變**（`changed-quotes-intact`）：直接
   `python3 scripts/check-source-drift.py --update-baseline` 即可，不必動
   `data/criteria/` 或 `errata.json`。
5. `blocked`／`unreachable` 的來源監測不到訊號，只能靠人定期拿瀏覽器複查。名單以每週
   報告為準，不要從 manifest 的 `retrieval` 欄推——2026-08-28 首次建 baseline 時
   `blocked` 只有 3 份（全是 diabetesjournals.org 的 403），hpa.gov.tw 當天 curl 抓得到；
   網域政策會變，下週可能反過來。2026-08-29 M6 重建 baseline（52 份）：`blocked` 7 份——
   多出的 4 份是用瀏覽器抓的指引原文（ahajournals 2017／2025、jamanetwork JNC 8、Lancet
   2004 摘要），這些本來就只能人工複查。見 MODEL.md §5。

## 部署方式

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
- **分類就是判準**：`category` 走 `data/criteria/schema.json` 的白名單，不得就地自創。
  易混的兩對——`classification`（來源把連續數值切成具名等級：高血壓第一期、BMI 過重）
  與 `risk_threshold`（來源說超過此值風險升高、但沒說它構成診斷：腰圍 ≥90 cm）都**不是**
  `diagnosis`；`risk_threshold` 也不是 `screening_triage`（那是指向下一項檢查的流程門檻）。
- **引句照抄**：不做繁簡、標點、單位大小寫的美化。原文的 `≧`／`≥`、`mg/dl`／`mg/dL`
  不一致就照抄，那是回查原文的鑰匙。
- **只存明細**：判準層禁止任何統計／彙總欄位（schema 已用 `additionalProperties: false`
  與測試雙重擋）。變更史（`*-history.json`）與已知限制（`*-interference.json`）同規。
- **方向不猜**：干擾因子的 `direction` 只收來源明講的；來源只說「會影響」就標
  `unspecified`。方向寫反是這一層最貴的錯（腎病在 WHO Annex 1 是讓 A1C 偏**高**）。
- **零密鑰**：token 全走環境變數／GitHub Secrets。

## 里程碑

`task-prd.md` 有 Story 1–7 的逐項驗收條件。M0（Story 1）已完成。
