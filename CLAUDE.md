# 這條線是誰

健檢數據誌（health.twtools.cc）：把健檢報告上常見指標的各機構判準並列整理、每個數字都附出處的靜態站。
這條線負責本 repo 的判準資料（`data/`）、來源快照登記、生成器與測試（`scripts/`、`tests/`）、指標頁正文（`articles/`），以及本站的部署。

## 這條線不碰什麼

- twtools 站群其他站（foootball、baseball、basketball、racing、blog）的內容、資料與部署；發現問題＝**回報給那條線**，不接手、不代為向 Charlie 請示。
- Charlie 的個人健檢數據（只留在他的本機，不進這個 repo）。
- 公司（Batmobile）的系統與資料。

模型層契約、紅線、不變量與部署程序都在 `MODEL.md`，專案脈絡在記憶檔 `project_health_data_site`。**本檔刻意不列規則清單**——規則只住一個地方，抄一份進自動載入的檔，漏改時是安靜的。
