# MODEL.md — health-tools（健檢數據誌）模型層

> 給任何接手的 agent（Claude Code／Codex／headless pipeline）的**單一版本真相**。
> `README.md` 講架構、指令、部署；**本檔只講程式擋不住的那半**：你操作的是什麼資料、哪些事實不准自己補、哪些線不能碰。
> ⛔ 刻意不寫：PR 歷史、頁數、功能清單、里程碑進度（那些在 CoWork／記憶）。本檔只放不隨 PR 變動的契約。

---

## 1. 資料契約 — 真相來源只有 `data/`

| 檔 | 是什麼 | 每列必有 | ⛔ 沒有、也不准加 |
|---|---|---|---|
| `data/sources/manifest.json` | 來源登記簿（一份文件一筆） | `id`／`org`／`url`／`version_or_date`／`fetched_at`／`sha256`／`license_bucket` | 摘要、我們對它的評價 |
| `data/criteria/<indicator>.json` | 判準**明細列**（一機構×一文件×一判定類別＝一列） | `indicator_id`／`org`／`doc_id`／`category`／`lower`／`upper`／`unit`／`population`／`page_or_table`／`quote` | **任何彙總欄**（正常值、建議值、平均、「多數機構認為」） |
| `data/criteria/<indicator>-history.json` | 判準變更事件 | `year`／`org`／`change`／`doc_id`／`quote`／`status` | 未證實的事件（`status` 不是 verified 就不渲染） |
| `data/criteria/<indicator>-interference.json` | 使數值失真的因素 | `direction`／`factor`／`org`／`doc_id`／`quote` | 猜的方向（來源沒說就 `unspecified`） |

- **頁面上的每個數字都必須回指到某一列，該列的 `quote` 必須 grep 得回該來源的快照**（`scripts/check-receipts.py`）。沒有列＝不渲染，不是「先寫再補」。
- `quote` 逐字照抄來源，含來源自己的 ≧／≥、mg/dl／mg/dL 不一致；**不美化、不翻譯、不合併兩段**（不連續的原文用 `quote_extra`）。
- 「正常／偏高」是對明細列 filter 出來的結果，**永遠不是一個存起來的欄位**。
- 同一指標多機構判準不一致時**並列、各綁版本，不選邊**；WHO 沒訂前期＝`no_criterion_stated`，不是空白也不是套 ADA 的值。

## 2. 來源契約 — 三桶授權，抓法有雷

| `license_bucket` | 誰 | 快照 |
|---|---|---|
| `us-federal-pd` | MedlinePlus／NIH／CDC／USPSTF／PMC | 入版控 |
| `tw-gov` | 國健署／食藥署／衛福部 | 入版控 |
| `licensed-cite-only` | ADA／WHO／DAROC 學會指引／NGSP／期刊 | **只引不轉載：快照留本機、`.gitignore`、版控只有 sha256**（public repo，整段重製＝著作權問題）；CI 對這些列印 SKIP，合併前本機跑滿 |

- **`hpa.gov.tw` 對 curl 回 WAF 攔截頁、`diabetesjournals.org` 回 403**：兩者只能用瀏覽器抓文字快照（`retrieval: browser-text`）。`fetch-health-source.py` 偵測到攔截頁會拒絕落地——**拿到 HTTP 200 不等於拿到內容**，落地後先用「該頁必然存在的字串」探針。
- **LLM 網搜或模型記憶產出的事實不得進 `data/`**。事實只從快照來；二手媒體（含維基）是線索不是收據。
- 舊文件只能引「定義句」不能引判準（例：2003 國健局手冊可引「反映 2–3 個月平均血糖」，不可引它的診斷閾值）。

## 3. 內容契約 — 衛教，不是醫療廣告

- 定位＝醫療法 §87 第 2 項「醫學新知或研究報告之發表、病人衛生教育」；唯一殘餘風險是 §87 第 1 項「暗示或影射醫療業務」。
- **coverage window（不上線）**：治療建議、用藥、就醫科別／機構導引、保健品、任何商品名（試驗設計轉述除外）、民眾資料輸入。
- 禁詞 gate `scripts/check-health-terms.py`（資料 `config/banned-terms.json`，五類）；`absolute` 命中 exit 1。**gate 擋不住的**：語意升級（「相關」→「導致」、「建議考慮」→「應該」）、品牌名窮舉、119 例外句前面有沒有真的列急症徵象——這些只能人審，寫手 brief 的語意強度鎖表是人審的依據。
- 指標頁六段固定結構（是什麼／各機構判準並列／何時改過／何時失真／可以和醫師討論什麼／來源與版本）；判準表與來源段**由生成器從 `data/` 產出**，正文 md 內出現手寫表格＝build fail（防雙源）。
- 衛教句統一「可以和醫師討論」，不用「建議就診」。

## 4. 發布契約

- `config/site.json` `published:false`＝dormant：頁面照生，但不進 sitemap／llms.txt／導覽。翻開關前 build 必須 byte-identical，翻開關後才接線；兩態都有測試。
- 生成器跑兩次 SHA-256 必須全同（禁時間戳）。
- 個資：本站**不蒐集任何民眾健康資料**（個資法 §6 特種個資）。任何要民眾輸入數值的功能都是另一個產品決策，先過律師再動。

## 5. 交接條款

1. 動 `data/` 前先看該來源的 `license_bucket` 與 `retrieval`。
2. 收據 gate 紅了：不准改 `quote` 遷就快照、不准塞例外清單；回報主席裁決。
3. 「查不到」要先驗陽性對照（探針字串命中）才算查不到。
4. 別把站群其他站的譯名／fallback 政策搬過來：本站英文＝canonical、台灣官方用詞優先、**查無不用陸譯 fallback，留原文**。
