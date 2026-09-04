# MODEL.md — health-tools（健檢數據誌）模型層

> 給任何接手的 agent（Claude Code／Codex／headless pipeline）的**單一版本真相**。
> `README.md` 講架構、指令、部署；**本檔只講程式擋不住的那半**：你操作的是什麼資料、哪些事實不准自己補、哪些線不能碰。
> ⛔ 刻意不寫：PR 歷史、頁數、功能清單、里程碑進度（那些在 CoWork／記憶）。本檔只放不隨 PR 變動的契約。

---

## 1. 資料契約 — 真相來源只有 `data/`

| 檔 | 是什麼 | 每列必有 | ⛔ 沒有、也不准加 |
|---|---|---|---|
| `data/sources/manifest.json` | 來源登記簿（一份文件一筆） | `id`／`org`／`url`／`version_or_date`／`fetched_at`／`sha256`／`license_bucket` | 摘要、我們對它的評價 |
| `data/criteria/<slug>.json` | 判準**明細列**（一機構×一文件×一指標×一判定類別＝一列；一個檔可裝多個 `indicator_id`） | `indicator_id`／`org`／`doc_id`／`category`／`lower`／`upper`／`unit`／`population`／`page_or_table`／`quote` | **任何彙總欄**（正常值、建議值、平均、「多數機構認為」） |
| `data/criteria/<slug>-history.json` | 判準變更事件 | `year`／`org`／`change`／`doc_id`／`quote`／`status` | 未證實的事件（`status` 不是 verified 就不渲染） |
| `data/criteria/<slug>-interference.json` | 使數值失真的因素 | `direction`／`factor`／`org`／`doc_id`／`quote` | 猜的方向（來源沒說就 `unspecified`） |
| `data/errata.json` | **公開後**的勘誤明細列（一次更正＝一列；站級一個檔，不掛在任何指標底下） | `id`／`date`／`slug`／`section`／`was`／`now`／`reason`；有 `doc_id` 就必須有 `quote`（互為必填） | 彙總欄（勘誤次數、最後勘誤日）；**上線前的內部修正**（沒有讀者看過的版本，就沒有東西要勘） |

- **頁面上的每個數字都必須回指到某一列，該列的 `quote` 必須 grep 得回該來源的快照**（`scripts/check-receipts.py`）。沒有列＝不渲染，不是「先寫再補」。
- `quote` 逐字照抄來源，含來源自己的 ≧／≥、mg/dl／mg/dL 不一致；**不美化、不翻譯、不合併兩段**（不連續的原文用 `quote_extra`）。
- 「正常／偏高」是對明細列 filter 出來的結果，**永遠不是一個存起來的欄位**。
- 同一指標多機構判準不一致時**並列、各綁版本，不選邊**；WHO 沒訂前期＝`no_criterion_stated`，不是空白也不是套 ADA 的值。
- **三個資料檔以「頁面 slug」定位，不是 indicator_id**；「這頁收哪些 `indicator_id`」是 `articles/indicators/<slug>.md` frontmatter 的 `indicator_ids` 決定的（單數 `indicator_id` 仍支援）。多指標頁的中文短標籤只能來自 frontmatter 的 `indicator_labels`，**缺一個就中止**——生成器不從 id 造中文，也不從單位猜。
- **`classification` 與 `risk_threshold` 都不是 `diagnosis`**：前者＝來源把連續數值切成具名等級（高血壓第一期、BMI 過重），後者＝來源說超過此值風險升高但沒說它構成診斷（腰圍 ≥90 cm）。`risk_threshold` 也不是 `screening_triage`（那是指向下一項檢查的流程門檻）。☠️ 標錯就會在頁面上把「腰圍超標」講成一個診斷。

### 1-1. 判準列體例（2026-08-29 二審裁決，474 列逐列核出的規則；schema 描述為準、這裡是人讀版）
- **population 只能來自兩處**：引句本身，或該列 `page_or_table` 指到的表題／節名／章名，照原文字面抄。整份文件的標題不算。其餘一律「來源未標示」——「全體」「一般民眾」「成人（來源沒寫）」都是我們加的，二審一次清掉 40 多列。
- **definition 不帶數值**：來源用「定義為／defined as」把此值定義成某狀態、且那是該機構自己的判準＝`diagnosis`；若只是單一建議的射程定義、或回述他人調查所用的定義（NAHSIT 7.7／6.6、ACR 6.8）＝`definition` 且 lower／upper 皆 null，數字留在 quote。帶數值的 definition 會被「統一規則」誤升成診斷線。
- **用藥起始門檻＝紅線**，與治療目標同族：JSGNA 8.0／9.0、EULAR >8.0 這類「≥此值開始 ULT」的門檻整列不落地（曾以 `screening_triage` 混進判準表）。`screening_triage` 只收「接下來做哪一項檢查」的分流。
- **history 的 `org`＝做出變更的機構，不是轉述者**：回述列（status「已證實（需補充）」）的 doc 可以是別人的文件；測試對 criteria 嚴格要求 org＝manifest[doc].org，對 history 放行回述列。`change` 欄要自帶「依某某回顧」的限定語，因為 status／note 不上頁。
- **同機構新版取代舊版時舊列填 `superseded_by`**（2017 ACC/AHA 八列 → 2025）：生成器據此在表格標「已被取代」、數線不畫舊列；不填就是兩套一樣的分級並排當兩個現行機構。
- **interference 的 `direction` 只從原文明講的方向來**：「風險被低估」不是「數值偏低」，機轉句（抑制排泄）不推成 high；來源沒指方向就 `unspecified`。
- **generator 排序不靠檔序**：history 依 (year, id 數字) 排；`indicator_id` 不在頁面 ids 的列會印 ⚠️（曾靜默丟掉 whr 兩列）。
- 二審方法（可重跑）：`scripts/audit-rowctx.py <slug>` 把每列＋快照上下文 dump 成 `.audit/<slug>-rows.md`，五席分 slug 逐列問 C1–C8（category 語意／inclusive／unit／population／indicator_id／org／引句撐不撐得起／同 doc 矛盾），只回 findings 不改檔；主席裁決成 RULING.md 再派修正棒。找到引句 ≠ 列正確——收據 gate 只證前者。

## 2. 來源契約 — 三桶授權，抓法有雷

| `license_bucket` | 誰 | 快照 |
|---|---|---|
| `us-federal-pd` | MedlinePlus／NIH／CDC／USPSTF／PMC | 入版控 |
| `tw-gov` | 國健署／食藥署／衛福部 | 入版控 |
| `licensed-cite-only` | ADA／WHO／DAROC 學會指引／NGSP／期刊 | **只引不轉載：快照留本機、`.gitignore`、版控只有 sha256**（public repo，整段重製＝著作權問題）；CI 對這些列印 SKIP，合併前本機跑滿 |

- **`hpa.gov.tw` 對 curl 回 WAF 攔截頁、`diabetesjournals.org` 回 403**：兩者只能用瀏覽器抓文字快照（`retrieval: browser-text`）。`fetch-health-source.py` 偵測到攔截頁會拒絕落地——**拿到 HTTP 200 不等於拿到內容**，落地後先用「該頁必然存在的字串」探針。攔截頁不只一型：除了 WAF 與 403，還有 HTTP 200 的人機挑戰頁（reCAPTCHA／「Checking your browser」，body 可以有兩萬多 bytes 但可見文字只有一百多字元），這一型一律歸 `blocked`，不歸 `drift`。
- **LLM 網搜或模型記憶產出的事實不得進 `data/`**。事實只從快照來；二手媒體（含維基）是線索不是收據。
- 舊文件只能引「定義句」不能引判準（例：2003 國健局手冊可引「反映 2–3 個月平均血糖」，不可引它的診斷閾值）。

## 3. 內容契約 — 衛教，不是醫療廣告

- 定位＝醫療法 §87 第 2 項「醫學新知或研究報告之發表、病人衛生教育」；唯一殘餘風險是 §87 第 1 項「暗示或影射醫療業務」。
- **coverage window（不上線）**：治療建議、用藥、就醫科別／機構導引、保健品、任何商品名（試驗設計轉述除外）、民眾資料輸入。
- 禁詞 gate `scripts/check-health-terms.py`（資料 `config/banned-terms.json`，五類）；`absolute` 命中 exit 1。**gate 擋不住的**：語意升級（「相關」→「導致」、「建議考慮」→「應該」）、品牌名窮舉、119 例外句前面有沒有真的列急症徵象——這些只能人審，寫手 brief 的語意強度鎖表是人審的依據。
- 指標頁六段固定結構（是什麼／各機構判準並列／何時改過／何時失真／可以和醫師討論什麼／來源與版本）；判準表與來源段**由生成器從 `data/` 產出**，正文 md 內出現手寫表格＝build fail（防雙源）。
- 圖上的顏色語意＝**機構屬性**（`tw-gov`／`tw-society`／`intl`／`us`／`other`），不是逐個機構挑色票；名單外的機構一律 fallback 灰＋機構全名。圖例上的類別文字（「淡色帶＝…」）由該頁的資料推導，**不得寫死**——寫死「糖尿病前期」，血壓頁就會安靜地說錯話。
- 衛教句統一「可以和醫師討論」，不用「建議就診」。

## 4. 發布契約

- `config/site.json` `published:false`＝dormant：頁面照生，但不進 sitemap／llms.txt／導覽。翻開關前 build 必須 byte-identical，翻開關後才接線；兩態都有測試。
- **2026-08-28 起 `published:true`、站已公開**（health.twtools.cc）。**部署是手動的**：合 main 不會自動上線，要在對齊 `origin/main` 的 checkout 上跑 build 四步（`build-articles` → `gen-indicator` → `gen-indicators-index` → `build-sitemap`）再 `wrangler deploy -c wrangler-health.jsonc`；驗收＝線上與本機產物逐檔 byte 比對（`verify-deploy.py`，首次部署 DNS 未傳播時改 `curl --resolve`），不看 HTTP 200。sites-dashboard 的部署新鮮度會在「合了沒部署」6 小時後出聲。
- 觀測：GA4 `ga_id` 在 `config/site.json`（空字串＝不輸出 tag）；GSC sitemap 已提交；站群日報第 12 站。
- 生成器跑兩次 SHA-256 必須全同（禁時間戳）。
- **公開後改動要留痕**：頁面上的數字或說明文字改過，就在 `data/errata.json` 加一列（`was` 照舊頁抄、`now`、`reason`；有依據文件就附 `doc_id`＋`quote`，同樣受收據 gate）。有勘誤的指標頁在第⑥段之後多一段「勘誤紀錄」，站級清單在 `/errata/`。☠️ 不是「改完再寫一段話說明」——沒有那一列，頁面上就不會有痕跡。
- 個資：本站**不蒐集任何民眾健康資料**（個資法 §6 特種個資）。任何要民眾輸入數值的功能都是另一個產品決策，先過律師再動。

## 5. 交接條款

1. 動 `data/` 前先看該來源的 `license_bucket` 與 `retrieval`。
2. 收據 gate 紅了：不准改 `quote` 遷就快照、不准塞例外清單；回報主席裁決。
3. 「查不到」要先驗陽性對照（探針字串命中）才算查不到。
4. **gate 綠≠合規**：`check-health-terms.py` 抓字不抓語意。新增任何會讓讀者對自己數值下判斷的呈現（分級組名、「超標」類措辭、索引卡的統計），先想 §87①「暗示或影射」，不是只看 gate。
5. **來源會過期，但現在有人通知**：`manifest.json` 的 `fetched_at` 是抓取日不是有效期；ADA 每年 1 月改版、hpa 頁面隨時改。`scripts/check-source-drift.py`＋`.github/workflows/source-drift.yml` 每週一 01:00 UTC 重抓全部來源（2026-08-29 M6 後 52 份）、比對 `data/sources/drift-baseline.json`，驗的是「判準列引用的那句話還在不在」而不是任何一種 sha（理由見 README「來源改版監測」段）。**能監測到的只有 curl 抓得到的來源**——`blocked`／`unreachable` 的那幾份（本機首次 baseline：3 份，全是 diabetesjournals.org；2026-08-29 M6 重建後 7 份，多出的 4 份是瀏覽器抓的 ACC/AHA 2017／2025、JNC 8、Lancet 2004 摘要，本來就只能人工複查；hpa.gov.tw 當天抓得到，別從 `retrieval` 欄推名單，以每週報告為準）監測不到訊號，仍要靠人定期拿瀏覽器複查；監測全滅（exit 2）本身會開 issue，但不等於那幾份被顧到。☠️ **sha 類欄位（`remote_sha256`／`text_sha256`）只當資訊，drift 判定只看引句**：`remote_sha256` 不可信是因為同一份 PDF 連續下載會出現不同 raw bytes（EULAR 實測），`text_sha256` 也不可信——2026-08-28 CI 首次實跑（Ubuntu runner）在 5 份 PDF 上把「內容根本沒變」判成 drift，原因是 baseline 在本機 macOS 建、CI 在 Ubuntu 比，兩邊 `pdftotext`（poppler-utils）版本不保證一致，同一份 PDF 抽出來的文字本身就可能有斷行／空白差異。另：hpa.gov.tw 在 Ubuntu runner 上對 curl 回 `exit 60`（SSL 憑證鏈缺中繼憑證，本機 macOS 靠系統鑰匙圈矇混過去）——腳本已改成 exit 60 時自動 `-k` 重抓一次，成功則正常分類、報告標記 `tls_verified: false`，兩次都失敗才算 unreachable。第三種：PMC（pmc.ncbi.nlm.nih.gov）對 GitHub IP 偶爾回 HTTP 200 的替代頁（引句 4/4 全缺，下一次又全在）——所以報告對「全部引句同時消失」會標警語並附 `<title>`／摘錄，先確認回應是不是那份文件再判改版。CI 視角覆蓋（2026-08-28 第 3 次實跑）：可驗 40／blocked 5（diabetesjournals×3、endo-dm、bmj 擋 GitHub IP）／unreachable 1（health.hpa.gov.tw）。
5-1. **來源下架時的替代原則（2026-08-29 M6 立）**：官方頁被撤（實例：國健署「成人腰圍測量及判讀之方法」2005 公告頁 pid=1697，curl 與瀏覽器都導回首頁）時，不用 Wayback 快照當來源——監測會指到 archive、也不代表現行說法。改抓**同機構的現行頁**（新聞稿、主題頁）另立 id，manifest `note` 寫明「原頁已下架、此為替代」；舊頁若有判準列引用，列要改 doc_id 到替代頁並重驗引句。判準值若在替代頁找不到＝該列降回未落地，不得留著指向不存在的頁。
6. **勘誤機制存在，觸發點是每週的 drift issue**：CI 對 exit 1（drift）／exit 2（監測失效）用 label `source-drift` 開或更新 issue，接手看到就要開瀏覽器核對、真的變了才進 `data/errata.json`（流程見 README「來源改版監測」段第 3、4 步）。`data/errata.json` 目前仍是 `[]`——**這代表上線以來沒有一條判準列真的改版，不代表沒人在看**；改了公開頁的數字卻沒加列，或收到 issue 沒有人核對，才是違約。監測顧不到的 `blocked`／`unreachable` 來源，沒有自動觸發點，錯過就是錯過。
7. 別把站群其他站的譯名／fallback 政策搬過來：本站英文＝canonical、台灣官方用詞優先、**查無不用陸譯 fallback，留原文**。
8. ⭐ **修正輪不准新增——要用機械檢查，不能只靠叮嚀**（2026-08-31 basketball 判例 fan-out，與第 3 條同族）。agent 依查核意見改完判準列、引句或稿件後跑：
   `python3 ~/Library/CloudStorage/Dropbox/AI/CoWork/tools/conductor-newclaims.py 舊版 新版 --evidence <快照目錄>`
   它列出「新版有、舊版沒有」的**數字字面量／因果全稱句／引號內容**，每條都要指得出快照或來源檔才留。
   ☠️ 判例：basketball 一張事實表修三輪，每一輪的修正都**憑空長出**查無依據的說法（無證據的分類、未查證的比例、自己補的因果時序），三次都靠查核席事後攔——攔得住是運氣。
   派工單要明寫：**刪除與加限定是安全的；解釋、推算、加形容詞是危險的。**
   ⚠️ 本站特別高風險的位置：判準列的 `quote` 被「順手補完整」、`note` 欄新增沒有來源的換算或分級說明。
   ⚠️ 輸出是候選清單不是判決（同第 4 條「gate 綠≠合規」的精神）；合法的推導值也會被列，要求交代來源即可。

### ☠️ 本站與 racing 是同一套架構，那個「第二輸出根目錄」的洞在這裡同樣成立（2026-09-03/04）

racing 修「測試偷寫版控產物」時第一輪只導開**頁面**輸出，漏了 `write_sitemap_part()` 寫的
`data/sitemap-parts/`——它在 PUB 之外，所以「把 PUB 導到 tmp」導不走它。結果一個刻意用
`publish=True` 的測試每跑一次就往版控目錄寫四個 part，而它手動還原的清單只列了三個，
第四個（後來才加的 owner）於是每跑一次全套測試就被永久改寫一次。

**本站有完全相同的兩個輸出根目錄**：`data/sitemap-parts/articles.txt` ＋ `scripts/build-sitemap.py`。

⚠️ **實測目前乾淨**（70 tests／0.37 秒，哨兵存活、零改寫零新增），**但原因是測試沒在跑生成器**，
不是架構不同。加任何「跑 build-articles／build-sitemap 再驗輸出」的測試時，這個洞就會打開。

探針（可直接複用，本次就是用它實測的）：跑全套測試**前後**比對整棵工作樹每個檔的
content-hash 與 `st_mtime_ns`；並先在輸出檔植入哨兵（加一行）製造「已知過期」狀態
——因為「內容相同就跳過」的寫入端在產物是最新時完全隱形，mtime 探針會假綠。

⇒ 兩條可直接抄的做法：
1. **輸出根目錄收成一份註冊表**（racing 的 `OUTPUT_ROOTS`），重導與斷言都從它推導；
   斷言若自己列舉目錄，它就是第二份手寫清單，下一個輸出目標照樣會漏。
2. **測試不要用 save/restore 去碰真目錄**，即使會還原也不行——行程中途死掉就留髒，
   而且 mtime churn 會讓 mtime 型探針失去判別力。重導才是隔離，還原不是。
