#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen-worksheet.py — 列印版判準對照工作表（public-health/worksheet/index.html）。

輸入＝與 gen-indicator.py 完全相同的那批來源（articles/indicators/*.md ＋
data/criteria/<slug>.json，篩選條件也完全相同：indicator_id ∈ 該頁 frontmatter
的 indicator_ids、category ∈ gen-indicator.py 的 TABLE_CATEGORIES——直接 import
那份常數，不在這裡重列一份）。輸出＝一張可以列印、拿著紙本自己對照的表：
每個指標一區塊，區塊裡每個 indicator_id 各留一組「我的數值」／「檢測日期」空格
（列印後用筆寫），旁邊列出同一批資料在各機構、各判定類別下的切點，維持資料
原始行序（不排序成「哪個比較準」）。

為什麼是獨立一支而不是塞進 gen-indicator.py：那支的職責是「一頁一指標（群）」，
這支是「全部指標濃縮進一張可列印的表」——輸出形狀（單頁、無圖、無折疊、
四欄簡表）與既有指標頁完全不同，硬塞只會讓兩種讀者（線上瀏覽 vs. 列印帶去對照）
共用一份會互相牽制的版面邏輯。

☠️ 資料契約：本頁不得手寫任何判準數字。頁面上出現的每一個切點值都是
`gen.value_text(row)` 依 data/criteria/<slug>.json 的 lower／upper／unit／
inclusive 現算出來的，機構標籤走 `gen.org_label`、判定類別走
`gen.CATEGORY_LABEL`——與指標頁判準表用的是同一份實作，不是另抄一份格式化邏輯。
族群一樣照 `population` 欄原文抄。

**出處採編號引註（2026-08-31 主席裁決，駁回 M4 初稿「只連回指標頁」的做法）**：
紙本會離開網站，只印機構、不印文件與版本，拿到紙的人無從查證——這正是本站
存在要防止的事（「某機構說 X」）。所以每個切點列右邊多一欄「出處」，只印
`D{n}`（＋若有頁碼／表號則接在後面，如 `D1, Table 6`）；`n` 在該區塊內從資料
出現順序現編（同一份文件在同一區塊只佔一個編號，不手寫對照）。區塊底部有一個
`<div class="ws-sources" data-quoted="1">` 出處清單，逐號列出
`D{n}　{機構}｜《{文件標題}》｜{版本}`（機構與文件標題來自
`data/sources/manifest.json`，同一份文件的正式標題原文照抄）。

☠️ 措辭紅線（比禁詞 gate 更嚴，這頁專屬，見 tests/test_worksheet.py）：
不出現第二人稱（你／您／你的／您的）、不出現評價或建議動詞（是／屬於／代表／
應該／建議／需要／要去看／請就醫／注意）。三種東西不在此限：
（1）「我的數值」是使用者自填欄位的標籤（第一人稱，不是對讀者說話）；
（2）`healthlib.site_footer_html()` 的既有全站免責聲明（含「您的醫師」）是
站規既有內容，不是本頁新增的措辭；
（3）**帶 `data-quoted="1"` 標記的區塊**（出處清單 `<div class="ws-sources">`、
每列出處欄裡的 page_or_table `<span class="ws-pageref">`）裡的文字——
manifest 裡有些官方文件標題自帶會被本頁規則命中的字（例："…722是管理血壓
好幫手"、"…陪你一起…"），但那是**被引用的文件專名**，不是本站在對讀者說話；
本站自己寫的說明文字、欄位標籤、表頭仍全部受檢，`data-quoted="1"` 只框住
這一塊引用區。本頁的說明文字只描述「這張表是什麼」，不暗示填完之後會得到
任何結論。

dormant（config/site.json 的 published 為 false）：頁面照生（要能看、能審），
但不寫 sitemap part、導覽不連（本頁未掛進 site.json 的 nav，任何時候都要靠
網址或站內連結直接抵達；是否掛進導覽是另一個產品決策，留給主席）。

決定性：全部內容由來源檔決定，不寫任何時間戳；同輸入連跑兩次 byte-identical。

跑序：要能獨立跑（只讀 articles/indicators/*.md ＋ data/criteria/），
且必須在 scripts/build-sitemap.py 之前。
用法：python3 scripts/gen-worksheet.py
"""
import argparse
import collections
import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 帶連字號的檔名不能 import，照 tests/ 與 gen-indicators-index.py 的載法。沿用同一份
# gen-indicator.py 實例＝同一份 TABLE_CATEGORIES／org_label／CATEGORY_LABEL／
# value_text／page_indicators／parse_article，不在本檔重新實作或重列白名單。
gen = _load("gen_indicator", "scripts/gen-indicator.py")
hl = gen.hl
esc = gen.esc

SRC_DIR = gen.SRC_DIR
CRITERIA_DIR = gen.CRITERIA_DIR
SITEMAP_OWNER = "worksheet"

PAGE_TITLE = "列印版判準對照工作表"
WORKSHEET_URL = f"{hl.BASE}/worksheet/"

# 說明文字只描述這張表是什麼，不暗示填完之後會得到什麼結論（措辭紅線見上）。
INTRO = ("這張表把各指標頁上，各機構公布的判準切點，整理成同一頁、附「我的數值」與"
         "「檢測日期」空格的版面，方便列印後手寫比對，逐項仍標明機構、判定類別與族群。")
PRINT_HELP = "螢幕上可以直接閱讀；列印時，站頭、導覽與姊妹站連結會自動隱藏，只留內容本身。"
BLOCK_REF_LABEL = "完整判準表與出處："


# ---------- 資料收集（全部由既有來源推導，不手寫任何數值） ----------

def collect_blocks(src_dir=None, criteria_dir=None) -> list:
    """回傳區塊 list（依 slug 字母序，與 /indicators/ 索引頁同序）。

    一個區塊＝一篇 articles/indicators/*.md（＝一個 slug）；區塊裡再依該頁
    frontmatter 的 indicator_ids 拆成多個「我的數值」子欄位（單指標頁只有一個）。
    這與 gen-indicator.py 的頁面切法完全一致——五篇正文對五個區塊，就是題目要的
    「糖化血色素／血壓／血脂／尿酸／BMI 與腰圍」五塊。
    """
    src_dir = pathlib.Path(src_dir) if src_dir else SRC_DIR
    criteria_dir = pathlib.Path(criteria_dir) if criteria_dir else CRITERIA_DIR

    files = sorted(src_dir.glob("*.md")) if src_dir.exists() else []
    if not files:
        raise SystemExit("❌ 工作表：articles/indicators/ 沒有正文檔，無法生成任何區塊。")

    blocks = []
    for f in files:
        meta, h1, sections = gen.parse_article(f)
        slug = meta.get("slug") or f.stem
        ids, labels = gen.page_indicators(meta, slug)

        crit_path = criteria_dir / f"{slug}.json"
        if not crit_path.exists():
            raise SystemExit(
                f"❌ 工作表：找不到判準明細 {crit_path}。工作表上的一個區塊等於宣稱"
                f"「{slug} 這個指標有可對照的資料」，資料不在就不生成這個區塊。")
        all_rows = gen.load_json(crit_path)

        multi = len(ids) > 1
        indicators = []
        for iid in ids:
            irows = [r for r in all_rows
                     if r["indicator_id"] == iid and r["category"] in gen.TABLE_CATEGORIES]
            if not irows:
                # 資料層允許同一個 slug 檔混放不屬於這頁的 indicator_id（P10 的坑，
                # 見 gen-indicator.py），但一個 frontmatter 明講要收的 id 卻一列
                # 判準都湊不出來，不能無聲跳過——印警告，不是 fail（跟 gen-indicator.py
                # 的「總表非空即可」門檻不同：這裡多一層是為了不讓某個指標的填空欄
                # 憑空出現在區塊裡卻沒有對照資料）。
                print(f"⚠️  工作表：{slug} 的指標 {iid} 沒有 TABLE_CATEGORIES 判準列，"
                      "已略過這一個「我的數值」子欄位。")
                continue
            label = labels[iid] if multi else meta.get("title", h1)
            unit = next((r["unit"] for r in irows if r.get("unit")), "")
            indicators.append({"id": iid, "label": label, "unit": unit, "rows": irows})

        if not indicators:
            raise SystemExit(
                f"❌ 工作表：{slug}（{'、'.join(ids)}）沒有任何可渲染的判準列"
                "（TABLE_CATEGORIES 皆空），這個區塊生不出來。")

        blocks.append({
            "slug": slug,
            "title": meta.get("title", h1),
            "href": f"/indicators/{slug}/",
            "indicators": indicators,
        })
    return blocks


# ---------- 版面 ----------

WORKSHEET_CSS = """
.ws-intro{ font-size:15px; color:var(--fg-soft); margin:10px 0 4px; line-height:1.9; }
.ws-blocks{ margin:22px 0 0; }
.ws-block{ border:1px solid var(--line); border-radius:var(--radius); background:var(--surface);
           padding:18px 20px 16px; margin:0 0 20px; }
.ws-h2{ font-family:var(--font-display); font-size:20px; font-weight:800; margin:0 0 6px; }
.ws-ref{ font-size:12.5px; color:var(--dim); margin:0 0 14px; }
.ws-ref a{ color:var(--dim); }
.ws-indicator{ margin:16px 0 4px; }
.ws-indicator + .ws-indicator{ border-top:1px dashed var(--line); padding-top:14px; }
.ws-h3{ font-size:15.5px; font-weight:700; margin:0 0 8px; }
.ws-fields{ display:flex; flex-wrap:wrap; gap:10px 28px; margin:0 0 10px; font-size:14px; }
.ws-field{ display:inline-flex; align-items:baseline; gap:6px; white-space:nowrap; }
.ws-blank{ display:inline-block; min-width:130px; border-bottom:1px solid var(--line-2); height:1.3em; }
.ws-unit{ color:var(--dim); font-size:12.5px; }
.ws-table th, .ws-table td{ font-size:13.5px; }
.ws-val{ white-space:nowrap; }
.ws-src{ min-width:110px; }
.ws-src a{ color:var(--accent); text-decoration:none; font-weight:600; }
.ws-src a:hover{ text-decoration:underline; }
.ws-pageref{ color:var(--dim); }
.ws-pop a{ color:var(--accent); text-decoration:none; font-weight:600; }
.ws-pop a:hover{ text-decoration:underline; }
.ws-sources, .ws-population-refs{ margin-top:14px; font-size:12.5px; color:var(--dim); }
.ws-h4{ font-size:12.5px; font-weight:700; margin:0 0 6px; color:var(--fg-soft);
        text-transform:uppercase; letter-spacing:.5px; }
.ws-source-list{ margin:0 0 0 1.2em; padding:0; line-height:1.85; }
.ws-source-list li{ margin-bottom:2px; }
.ws-foot{ font-size:12.5px; color:var(--dim); border-top:1px solid var(--line);
          padding-top:10px; margin-top:14px; }
@media (max-width:560px){ .ws-fields{ flex-direction:column; align-items:flex-start; gap:8px; } }
@media print{
  /* .theme-switch 的隱藏規則已搬進 healthlib.py 的共用 CSS（全站每一頁列印都受益，
     不是本頁局部蓋掉——見 2026-08-31 第三次主席裁決）。本頁的 site-header 仍是
     本頁專屬的隱藏（判準對照表不需要導覽列跟著印出來），留在這裡。 */
  .site-header, .foot-links, .sister-sites, .ws-noprint{ display:none !important; }
  body{ padding:0 !important; background:#fff !important; color:#000 !important; }
  a{ color:#000 !important; text-decoration:none !important; }
  .container{ max-width:100% !important; }
  .pg-h1, .ws-h2, .ws-h3, .ws-h4, .ws-intro, .ws-ref, .ws-unit, .ws-foot,
  .ws-sources, .ws-population-refs, .ws-source-list, .ws-pageref, .site-disclaimer{
    color:#000 !important; }
  .ws-block{ border-color:#000 !important; box-shadow:none !important; background:#fff !important; }
  .ws-blank{ border-color:#000 !important; }
  .std-table th, .std-table td{ border-color:#000 !important; color:#000 !important; }

  /* ① 大量空白頁的根因：break-inside:avoid 之前套在 .ws-block／.ws-indicator 這種
     大容器上——一個 32 列的表放不進剩餘頁面高度就整塊被推到下一頁，前一頁下半段
     留白、標題落單在新頁頂端。改法：容器不設 break-inside（讓表格本身可以跨頁），
     只在「列」這個最小單位上擋（tr 不被從中間腰斬），標題用 break-after 跟它後面
     的內容黏住（不會有 h2/h3 自己落在頁尾、內容被推到下一頁）。 */
  .ws-table tbody tr{ break-inside:avoid; page-break-inside:avoid; }
  .ws-h2, .ws-h3{ break-after:avoid; page-break-after:avoid; }

  /* ② 表頭跨頁不重複，根因不是缺了 display:table-header-group（那本來就是 thead
     的預設值）——是 .tbl-scroll 的 overflow-x:auto 把表格包進一個會建立新格式化
     上下文的容器，Chrome 的分頁引擎因此不把它當一般表格跨頁重複表頭。列印時關掉
     這層 overflow，thead 的 table-header-group 才吃得到。 */
  .tbl-scroll{ overflow-x:visible; }
  thead{ display:table-header-group; }

  /* ⑥ 列印字級與間距收緊（螢幕版不動，只在這個 media block 裡）。 */
  .ws-block{ padding:9px 12px 6px; margin:0 0 8px; }
  .ws-h2{ font-size:14px; margin:0 0 3px; }
  .ws-h3{ font-size:11.5px; margin:7px 0 3px; }
  .ws-ref{ font-size:9.5px; margin:0 0 6px; }
  .ws-intro{ font-size:10px; margin:2px 0; line-height:1.5; }
  .ws-fields{ font-size:10px; gap:4px 14px; margin:0 0 5px; }
  .ws-blank{ min-width:70px; height:1em; }
  .ws-table th, .ws-table td{ font-size:9.5px; padding:2.5px 4px; }
  .ws-foot{ font-size:9.5px; margin-top:6px; padding-top:5px; }
  .ws-sources, .ws-population-refs{ font-size:9px; margin-top:6px; }
  .ws-h4{ font-size:9px; margin:0 0 3px; }
  .ws-source-list{ line-height:1.35; }
}
"""


def block_doc_order(block: dict) -> list:
    """區塊內 distinct doc_id 的出現順序（同一份文件在同一區塊只算一次）：
    依 indicators 的順序、每個 indicator 內部的原始 json 行序掃過去，第一次見到
    的 doc_id 依序收進來——編號完全由資料出現順序推出，不是手寫對照表。"""
    order, seen = [], set()
    for ind in block["indicators"]:
        for r in ind["rows"]:
            d = r["doc_id"]
            if d not in seen:
                seen.add(d)
                order.append(d)
    return order


# ⑤ 族群欄編號（P{n}）：2026-08-31 第三次主席裁決加，跟出處欄同一型問題——同一個
# 子區塊內，好幾列重複印同一段長族群敘述（例：血壓收縮壓表有 8 列都印「成人（依
# 醫療照護場所測得之診間血壓平均值，≥2 次讀數、≥2 個場次）」），紙本白白多佔版面。
#
# 門檻＝「同一子區塊內重複 ≥2 次」且「長度 > POP_NUMBER_MIN_LENGTH」兩個條件同時
# 成立才編號。長度門檻定在 15 字：
#   - 主席點名要維持原樣的三個例子——「成人」(2 字)、「18歲以上民眾」(7 字)、
#     「來源未標示」(5 字)——連同其餘常見短族群（「男性（men）」7 字、「篩檢對象」
#     4 字、「18歲（含）以上的成人」11 字）全部落在 15 字以下，門檻抓在它們與
#     真正的長敘述（22 字以上，如「初級預防對象（無臨床顯著 ASCVD 之成人）」23 字、
#     「成人（依 722 協定量得的家用血壓...）」34 字）之間，留了足夠餘裕不會抓錯邊。
#   - 短字串就算重複 10 次也不編號：短字串本來就不佔版面，編號後讀者還要往下翻
#     清單才看得懂 P3 是什麼，對 4～11 字的字串是負優化。
POP_NUMBER_MIN_REPEAT = 2
POP_NUMBER_MIN_LENGTH = 15


def block_population_order(block: dict) -> list:
    """族群編號池：跟 block_doc_order() 同一種做法（依子指標順序、原始 json 行序
    找出第一次出現、且符合編號門檻的敘述），編號在整個區塊內共用（同一份敘述若
    在血壓的收縮壓與舒張壓兩個子表都重複出現，共用同一個 P{n}，不必各自編一次）。
    門檻判定的分母是**各子指標自己的列**（同一子區塊內重複 ≥2 次），不是跨子指標
    合併計數——這樣才是主席說的「同一子區塊內」重複。
    """
    order, seen = [], set()
    for ind in block["indicators"]:
        counts = collections.Counter(r["population"] for r in ind["rows"])
        for r in ind["rows"]:
            p = r["population"]
            if (p not in seen and counts[p] >= POP_NUMBER_MIN_REPEAT
                    and len(p) > POP_NUMBER_MIN_LENGTH):
                seen.add(p)
                order.append(p)
    return order


def source_line(doc_id: str, n: int, mf: dict) -> str:
    """出處清單一行：D{n}　機構｜《文件標題》｜版本。

    doc_id 指不到 manifest＝這一列沒有出處，直接中止（與 gen-indicator.py 的
    source_ref／superseded_label 同一條紅線：四項出處缺一即不渲染）。
    """
    m = mf.get(doc_id)
    if not m:
        raise SystemExit(f"❌ 工作表：doc_id 指不到 manifest：{doc_id}（出處缺一，不渲染）")
    return (f'D{n}　{esc(gen.org_label(m["org"]))}｜'
            f'《{esc(m["title"])}》｜{esc(m["version_or_date"])}')


# 出處欄要印的 page_or_table 是「顯示用瘦身版」，不是資料本身：data/criteria/
# 的 page_or_table 逐字照抄來源（MODEL.md「引句照抄」），部分列沒有頁碼只能拿
# 該頁的原文標題／FAQ 問句當定位（例：「頁面「我是18歲（含）以上的成人，要如何
# 判斷體重是否正常？」BMI 表」）。這段引號內文字在出處清單（ws-sources）裡，
# 同一份文件已經用 D{n} 完整印過一次原文標題——同一區塊裡好幾列各自重複印一次
# 那句話，紙上只是白佔版面，不是新資訊。所以「「」括起來的整段」只在**顯示**時
# 拿掉，只留前後的定位文字；data/criteria/ 的 page_or_table 欄位本身完全不動
# （2026-08-31 第二次主席裁決：「只動顯示，不動資料」）。
_QUOTE_SPAN = re.compile(r"「[^」]*」")
# 特例：字串開頭就是「頁面「…」」——這裡的「頁面」只是「這段引自頁面上」的贅語
# （不是像「主題頁本文」「頁面內文」「新聞稿本文」那樣還帶著「是頁面的哪個部分」
# 的定位資訊），D{n} 已經指到是哪一頁，整段（連「頁面」兩字）一併拿掉，不留
# 「頁面 BMI 表」這種贅語+定位文字並排的殘餘。只鎖定字串開頭這個確切樣式，
# 不擴大成「頁面」這個詞出現在任何位置都砍——「頁面內文」「頁面服務內容表」這類
# 複合詞不受影響（判斷式是 `^頁面「`，中間夾了字就不比對）。
_LEADING_BARE_PAGE_LABEL_QUOTE = re.compile(r"^頁面「[^」]*」\s*")
_TRIM_PUNCT = "，,、；;／/　 "


def clean_page_or_table(text: str) -> str:
    """出處欄顯示用：拿掉「」括起來的整段，只留前後的定位文字，收乾淨多餘空白
    與標點。沒有「」的字串（如 "Sec. 2, Table 2.1"）原樣不動。拿掉後整段變空，
    回傳空字串——呼叫端據此不印孤零零的逗號。"""
    if "「" not in text:
        return text
    cleaned = _LEADING_BARE_PAGE_LABEL_QUOTE.sub("", text, count=1)
    cleaned = _QUOTE_SPAN.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split())          # 收乾淨多餘（含全形）空白
    cleaned = cleaned.strip(_TRIM_PUNCT)
    return cleaned


def citation_html(row: dict, slug: str, num_of: dict) -> str:
    """出處欄一格：D{n}（連到區塊底部的出處清單）＋（若有）page_or_table 的
    顯示瘦身版（見 clean_page_or_table()）。

    page_or_table 跟出處清單裡的文件標題是同一類東西——不是本站在對讀者說話，
    同樣包在 `data-quoted="1"`，掃描器對「出處」相關內容用同一條規則，不是只顧到
    清單漏了這一格（見 tests/test_worksheet.py 的措辭紅線 docstring）。
    """
    n = num_of[row["doc_id"]]
    page = row.get("page_or_table")
    cleaned = clean_page_or_table(page) if page else ""
    suffix = (f'<span class="ws-pageref" data-quoted="1">, {esc(cleaned)}</span>'
              if cleaned else "")
    return f'<a href="#{esc(slug)}-D{n}">D{n}</a>{suffix}'


def render_sources(block: dict, mf: dict) -> str:
    order = block_doc_order(block)
    items = "".join(
        f'<li id="{esc(block["slug"])}-D{n}">{source_line(d, n, mf)}</li>'
        for n, d in enumerate(order, start=1))
    # data-quoted="1"：措辭紅線的豁免區——裡面是 manifest 的文件標題原文（見上方
    # docstring），本站自己寫的字（「出處」這個標題本身）仍受檢，不在豁免範圍內。
    return (f'<div class="ws-sources" data-quoted="1"><h4 class="ws-h4">出處</h4>'
            f'<ol class="ws-source-list">{items}</ol></div>')


def render_population_refs(block: dict) -> str:
    """族群清單：跟 render_sources() 同一種結構，只在有東西可列時才輸出——多數
    區塊裡沒有任何族群敘述踩到編號門檻，這種情況不生一個空的 <div>。population
    欄一樣是逐字照抄來源（MODEL.md「引句照抄」），不是本站的話，同樣包
    data-quoted="1"（「族群」這個標題本身仍受檢）。"""
    order = block_population_order(block)
    if not order:
        return ""
    items = "".join(
        f'<li id="{esc(block["slug"])}-P{n}">P{n}　{esc(p)}</li>'
        for n, p in enumerate(order, start=1))
    return (f'<div class="ws-population-refs" data-quoted="1"><h4 class="ws-h4">族群</h4>'
            f'<ol class="ws-source-list">{items}</ol></div>')


def population_cell(row: dict, slug: str, pop_num_of: dict) -> str:
    """族群欄一格：踩到編號門檻（block_population_order()）的敘述印 P{n}（連到
    區塊底部的族群清單）；沒踩到的短敘述照舊直接印原文，不因為統一而編號
    （見 block_population_order() 上方門檻理由）。"""
    p = row["population"]
    n = pop_num_of.get(p)
    if n is None:
        return esc(p)
    return f'<a href="#{esc(slug)}-P{n}">P{n}</a>'


def render_indicator(ind: dict, slug: str, num_of: dict, pop_num_of: dict) -> str:
    unit_note = f'<span class="ws-unit">（{esc(ind["unit"])}）</span>' if ind["unit"] else ""
    fields = (
        '<div class="ws-fields">'
        f'<label class="ws-field">我的數值：<span class="ws-blank"></span>{unit_note}</label>'
        '<label class="ws-field">檢測日期：<span class="ws-blank"></span></label>'
        '</div>')
    rows_html = "".join(
        "<tr>"
        f'<td>{esc(gen.org_label(r["org"]))}</td>'
        f'<td>{esc(gen.CATEGORY_LABEL[r["category"]])}</td>'
        f'<td class="ws-val">{esc(gen.value_text(r))}</td>'
        f'<td class="ws-pop">{population_cell(r, slug, pop_num_of)}</td>'
        f'<td class="ws-src">{citation_html(r, slug, num_of)}</td>'
        "</tr>" for r in ind["rows"])
    table = (
        '<div class="tbl-scroll"><table class="std-table ws-table">'
        '<thead><tr><th>機構</th><th>判定類別</th><th>切點</th><th>族群</th>'
        '<th>出處</th></tr></thead>'
        f'<tbody>{rows_html}</tbody></table></div>')
    return f'<div class="ws-indicator">{fields}{table}</div>'


def render_block(block: dict, mf: dict) -> str:
    multi = len(block["indicators"]) > 1
    num_of = {d: i for i, d in enumerate(block_doc_order(block), start=1)}
    pop_num_of = {p: i for i, p in enumerate(block_population_order(block), start=1)}
    heads = "".join(
        (f'<h3 class="ws-h3">{esc(ind["label"])}</h3>' if multi else "")
        + render_indicator(ind, block["slug"], num_of, pop_num_of)
        for ind in block["indicators"])
    return (
        f'<section class="ws-block" id="{esc(block["slug"])}">'
        f'<h2 class="ws-h2">{esc(block["title"])}</h2>'
        f'<p class="ws-ref">{esc(BLOCK_REF_LABEL)}'
        f'<a href="{esc(block["href"])}">{esc(block["href"])}</a></p>'
        f'{heads}{render_sources(block, mf)}{render_population_refs(block)}</section>')


def render_page(blocks: list, mf: dict) -> str:
    n_rows = sum(len(ind["rows"]) for b in blocks for ind in b["indicators"])
    body = (
        '  <main>\n'
        f'  <h1 class="pg-h1">{esc(PAGE_TITLE)}</h1>\n'
        f'  <p class="ws-intro">{esc(INTRO)}</p>\n'
        f'  <p class="ws-intro ws-noprint">{esc(PRINT_HELP)}</p>\n'
        f'  <div class="ws-blocks">{"".join(render_block(b, mf) for b in blocks)}</div>\n'
        f'  <p class="ws-foot">共 {len(blocks)} 個指標區塊、{n_rows} 個切點。</p>\n'
        '  </main>')

    page_node = {
        "@type": "WebPage", "@id": f"{WORKSHEET_URL}#page",
        "name": PAGE_TITLE, "description": INTRO, "url": WORKSHEET_URL,
        "inLanguage": "zh-Hant", "isAccessibleForFree": True,
        "mainEntityOfPage": WORKSHEET_URL,
        "publisher": {"@id": f"{hl.BASE}/#org"},
    }
    jsonld = hl.graph_ld([
        hl.org_node(), hl.website_node(), page_node,
        hl.breadcrumb_node([("首頁", f"{hl.BASE}/"), (PAGE_TITLE, WORKSHEET_URL)])])

    return hl.page_shell(PAGE_TITLE, INTRO, WORKSHEET_URL, jsonld, body,
                         "worksheet", extra_css=WORKSHEET_CSS)


# ---------- dormant 接線 ----------

def wire_sitemap(published: bool, parts_dir: pathlib.Path = None):
    """未公開時不進 sitemap，且要把上一次公開時留下的 part 檔收乾淨（不留死 URL）。

    照 gen-indicators-index.py／gen-indicator.py 的 dormant 處理方式：public 時用
    healthlib.write_sitemap_part 寫一行；dormant 時直接刪掉那個 part 檔。
    """
    parts_dir = pathlib.Path(parts_dir) if parts_dir else (ROOT / "data" / "sitemap-parts")
    if published:
        if parts_dir == ROOT / "data" / "sitemap-parts":
            hl.write_sitemap_part(SITEMAP_OWNER, [WORKSHEET_URL])
        else:
            parts_dir.mkdir(parents=True, exist_ok=True)
            p = parts_dir / f"{SITEMAP_OWNER}.txt"
            content = f"{WORKSHEET_URL}\n"
            if not p.exists() or p.read_text(encoding="utf-8") != content:
                p.write_text(content, encoding="utf-8")
            print(f"🗺️  sitemap part '{SITEMAP_OWNER}' → 1 URL(s)")
        return
    part = parts_dir / f"{SITEMAP_OWNER}.txt"
    if part.exists():
        part.unlink()
        print(f"🗺️  dormant：移除 sitemap part '{SITEMAP_OWNER}'（未公開不進 sitemap）")


# ---------- build ----------

def build(out_root=None, published=None, src_dir=None, criteria_dir=None,
         parts_dir=None) -> str:
    out_root = pathlib.Path(out_root) if out_root else hl.PUB
    if published is None:
        published = json.loads((ROOT / "config" / "site.json").read_text(
            encoding="utf-8")).get("published", False) is True

    # 導覽／頁尾的 published gate 與 sitemap 接線吃同一個旗標（見 gen-indicator.build()）。
    hl.PUBLISHED = published

    blocks = collect_blocks(src_dir, criteria_dir)
    mf = gen.manifest_index()
    html_out = render_page(blocks, mf)
    out_dir = out_root / "worksheet"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html_out, encoding="utf-8")

    n_rows = sum(len(ind["rows"]) for b in blocks for ind in b["indicators"])
    print(f"✅ /worksheet/　{len(blocks)} 區塊・{n_rows} 個切點"
          f"（{'、'.join(b['slug'] for b in blocks)}）")

    wire_sitemap(published, parts_dir)
    if not published:
        print("🔒 dormant（config/site.json published=false）：工作表已生成，"
              "但不進 sitemap，導覽不連。")
    return html_out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="/worksheet/ 列印版判準對照工作表生成器（資料驅動，dormant 感知；"
                    "可獨立跑，須在 build-sitemap.py 之前）")
    ap.parse_args()
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
