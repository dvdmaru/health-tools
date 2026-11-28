#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build-articles.py — health.twtools.cc 文章／指標頁靜態產出引擎。

站群共通引擎，收斂成本站版本：
- 草稿 gate：config/draft-exclude.json 列出的 slug 不進 index／feed／sitemap／個別頁，
  且輸出目錄會被真的刪掉（只從索引拿掉不算下架，知道網址的人仍讀得到）。
- FAQ 鏡射：文章「## 常見問題」下的 ### 問答自動吐 FAQPage JSON-LD，schema 內容
  必定等於頁面可見文字。
- sitemap manifest：本腳本只寫自己擁有的 part（data/sitemap-parts/articles.txt），
  最終 sitemap.xml 由 scripts/build-sitemap.py 合併產生。
- 決定性輸出：全部內容由來源檔決定，不寫任何時間戳，連跑兩次全檔 SHA-256 相同。

M0 狀態：articles/ 為空是正常情形——本腳本在零文章時會產出站台骨架
（首頁殼、文章索引殼、feed、llms.txt、robots.txt、sitemap part），不生成任何內容頁。

用法：python3 scripts/build-articles.py
"""
import html as html_lib
import importlib.util
import pathlib
import shutil
import sys

try:
    import markdown as md_lib
except ImportError:  # pragma: no cover
    md_lib = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("healthlib", ROOT / "scripts" / "healthlib.py")
hl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hl)

import json  # noqa: E402  (放在 healthlib 載入之後，維持與姊妹站相同的載入順序)

SRC = ROOT / "articles"
PUB = hl.PUB
BASE = hl.BASE
SITE = hl.SITE
FEED_MAX = 20


def load_draft_excludes() -> set:
    p = ROOT / "config" / "draft-exclude.json"
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")).get("exclude", []))


INDEX_CSS = """
.idx-card { display:block; border:1px solid var(--line); border-radius: var(--radius);
  padding: 18px 20px; margin-bottom: 14px; text-decoration:none; background: var(--surface); }
.idx-card:hover { border-color: var(--accent-line); }
.idx-card h2 { font-size: 18px; margin: 0 0 6px; color: var(--fg); font-weight: 800; }
.idx-card p { font-size: 14px; color: var(--fg-soft); margin: 0; }
.idx-date { font-family: var(--font-mono); font-size: 11.5px; color: var(--dim); letter-spacing: 1.2px; }
.idx-empty { border:1px dashed var(--line-2); border-radius: var(--radius); padding: 26px 22px;
  color: var(--dim); font-size: 14.5px; background: var(--surface); }
.reader-links { margin:18px 0 8px; }
.reader-links a { display:inline-block; }
.report-entry { border:1px solid var(--accent-line); border-radius:var(--radius);
  background:var(--surface); padding:clamp(18px,4vw,32px); }
.reader-tools { display:flex; flex-wrap:wrap; align-items:flex-start; gap:18px 28px; margin-top:18px; }
#report-search { flex:1.25 1 19rem; min-width:0; }
.reader-symbols { flex:1 1 16rem; padding-inline-start:14px; border-inline-start:3px solid var(--accent-line); }
.reader-symbols h2 { margin:0; font-size:1.1rem; }
.reader-symbols p { margin:8px 0 0; }
.report-entry label { display:block; margin:0 0 6px; font-weight:700; }
.report-entry input { box-sizing:border-box; width:100%; padding:12px 14px; border:1px solid var(--line-2);
  border-radius:var(--radius-sm); background:var(--bg); color:var(--fg); font:inherit; }
.glucose-guide { margin:12px 0; padding:12px; border:1px solid var(--accent-line); border-radius:var(--radius-sm); }
.glucose-guide h2 { margin:0; font-size:1.1rem; }
.glucose-guide p { margin:8px 0; }
.glucose-guide details { border-top:1px solid var(--line); }
.glucose-guide details[open] { padding-bottom:10px; }
.glucose-guide summary { padding:10px 0; font-weight:700; cursor:pointer; }
.glucose-guide table { width:100%; border-collapse:collapse; font-size:.9rem; }
.glucose-guide caption { text-align:start; }
.glucose-guide th, .glucose-guide td { padding:5px; text-align:start; border-bottom:1px solid var(--line); }
#search-miss { padding:14px; margin:12px 0; border:1px solid var(--line); border-radius:var(--radius-sm); }
#search-miss h2 { margin:0; font-size:1.1rem; }
#search-miss summary { padding:8px 0; font-weight:700; cursor:pointer; }
.miss-example { display:flex; flex-wrap:wrap; gap:6px; margin:12px 0; }
.miss-example div { padding:6px 10px; background:var(--bg); border-radius:var(--radius-sm); }
.miss-example div:first-child { background:var(--accent-soft); border-inline-start:3px solid var(--accent); }
.miss-example dt { font-size:.85rem; }
.miss-example dd { margin:0; font-weight:700; }
#search-miss label { margin-top:12px; }
#search-miss textarea { display:block; width:100%; box-sizing:border-box; padding:10px; font:inherit;
  background:var(--bg); color:var(--fg); border:1px solid var(--line-2); border-radius:var(--radius-sm); }
#search-miss button { padding:9px 14px; margin-top:10px; font:inherit; cursor:pointer;
  border:0; border-radius:var(--radius-sm); background:var(--accent); color:var(--accent-ink); }
#report-line-help { margin:6px 0; font-size:.9em; color:var(--fg-soft); }
.report-line-preview { white-space:pre-wrap; overflow-wrap:anywhere; margin:8px 0; }
.report-line-preview mark { background:var(--accent-soft); color:var(--fg); font-weight:700;
  border-block-end:2px solid var(--accent); }
.reader-status:empty { margin:0; }
.reader-results { margin:8px 0; padding-left:1.25em; }
.reader-results li { padding:4px 0; }
"""

LIPID_GUIDE_CSS = """
.lipid-guide { padding:12px; margin:12px 0; border:1px solid var(--accent-line); border-radius:var(--radius-sm); }
.lipid-guide h2 { margin:0; font-size:1.1rem; }
.lipid-guide p { margin:8px 0; }
.lipid-guide details { border-top:1px solid var(--line); padding:0 8px; }
.lipid-guide summary { padding:12px 0; cursor:pointer; }
.lipid-guide summary span { display:inline-block; font-variant-numeric:tabular-nums; }
.lipid-guide details[open] { background:var(--accent-soft); box-shadow:inset 3px 0 var(--accent); padding-bottom:10px; }
.lipid-guide dl { display:flex; flex-wrap:wrap; gap:8px 18px; margin:0 0 10px; }
.lipid-guide dt { font-size:.85rem; color:var(--fg-soft); }
.lipid-guide dd { margin:0; font-weight:700; }
"""

# 首頁 FAQ（可見問答＝schema 鏡射源）。
# ⚠️ 這幾句要通過 scripts/check-health-terms.py：不得出現招徠、療效、自我標榜、gate 語言。
HOME_FAQ = [
    ("這個站整理的是什麼？",
     "健康檢查報告上常見的指標，逐項並列不同機構公布的判準值，每一列都標註機構、文件名稱、"
     "版本與頁碼。"),
    ("為什麼同一個指標會有好幾個判準？",
     "不同機構依據各自的文件訂定判準，數值本來就不一致。本站並列呈現，不代替讀者選邊。"),
    ("不同醫院或檢驗室的報告，同一個項目的數字背後做法會一樣嗎？",
     "不一定。各指標頁引用的來源寫到：美國胃腸病學院（American College of Gastroenterology，ACG）指出各檢驗室的 AST、ALT 正常上限範圍可能不同；"
     "腰圍的量測位置，WHO、美國 NIH 與國健署各有各的寫法；腎功能的 eGFR 計算公式也換過版本。"
     "報告上標示的參考範圍與計算方式，可以和您的醫師討論。"),
    ("這裡的內容可以當作診斷依據嗎？",
     "不行。本站整理的是公開文件寫了什麼，個人數值代表什麼意思，是要和您的醫師討論的事。"),
]


def _kicker(meta):
    return {"indicator": "指標整理", "reference": "判準對照", "changelog": "判準沿革",
            "feature": "專題"}.get(meta.get("type", "indicator"), "專題")


def _date_disp(s):
    import datetime
    try:
        d = datetime.date.fromisoformat(str(s))
        return f"{d.year} 年 {d.month} 月 {d.day} 日"
    except ValueError:
        return str(s)


def prune_stale_article_dirs(art_root: pathlib.Path, keep_slugs: set):
    """刪掉 public-health/articles/ 下不屬於本次產出的目錄（草稿回收／文章下架）。"""
    if not art_root.exists():
        return
    for child in sorted(art_root.iterdir()):
        if child.is_dir() and child.name not in keep_slugs:
            shutil.rmtree(child)
            print(f"🗑  removed stale article output: {child.name}（草稿或已下架）")


# ---------- 文章渲染 ----------

def render_article(meta, body_html, slug, excerpt, faq, prev_nav=None, next_nav=None):
    url = f"{BASE}/articles/{slug}/"
    title = meta.get("title", slug)
    desc = meta.get("subtitle", excerpt)[:300]
    cover = f"{url}cover.png" if (SRC / slug / "cover.png").exists() else ""
    lede = meta.get("lede", "")
    lede_html = f'<p class="art-lede">{html_lib.escape(lede)}</p>' if lede else ""
    cover_html = (f'<img class="art-cover" src="cover.png" alt="{html_lib.escape(title)}">'
                  if cover else "")

    nav_parts = []
    if prev_nav:
        nav_parts.append(
            f'<a href="/articles/{prev_nav["slug"]}/"><span class="lbl">← 前一篇</span>'
            f'{html_lib.escape(prev_nav["meta"].get("title", ""))[:40]}</a>')
    if next_nav:
        nav_parts.append(
            f'<a href="/articles/{next_nav["slug"]}/" style="text-align:right">'
            f'<span class="lbl">後一篇 →</span>'
            f'{html_lib.escape(next_nav["meta"].get("title", ""))[:40]}</a>')
    nav_html = f'<div class="art-nav">{"".join(nav_parts)}</div>' if nav_parts else ""

    art_node = {
        "@type": "Article", "@id": f"{url}#article",
        "headline": title, "description": desc,
        "datePublished": meta.get("date", ""),
        "dateModified": (meta.get("updated") or meta.get("date", "")),
        "inLanguage": "zh-Hant", "mainEntityOfPage": url,
        "author": {"@type": "Organization", "name": SITE["org_name"]},
        "publisher": {"@id": f"{BASE}/#org"},
        "isAccessibleForFree": True,
    }
    if cover:
        art_node["image"] = cover
    jsonld = hl.graph_ld([
        hl.org_node(), hl.website_node(), art_node,
        hl.breadcrumb_node([("首頁", f"{BASE}/"), ("文章", f"{BASE}/articles/"), (title, url)]),
        hl.faq_node(faq, url)])

    body = f"""  <main>
  <div class="art-kicker">{_kicker(meta)}</div>
  <h1 class="art-h1">{html_lib.escape(title)}</h1>
  <div class="art-meta"><span>{_date_disp(meta.get('date', ''))}</span><span>{SITE['org_name']}</span></div>
  {cover_html}
  {lede_html}
  <article class="prose">
{body_html}
  </article>
  {nav_html}
  </main>"""
    return hl.page_shell(title, desc, url, jsonld, body, "articles",
                         extra_css="", og_image=cover)


# ---------- 首頁／文章索引 ----------

def _idx_card(a):
    m = a["meta"]
    return (f'<a class="idx-card" href="/articles/{a["slug"]}/">'
            f'<div class="idx-date">{html_lib.escape(str(m.get("date", "")))}</div>'
            f'<h2>{html_lib.escape(m.get("title", a["slug"]))}</h2>'
            f'<p>{html_lib.escape(m.get("subtitle", a["excerpt"]))}</p></a>')


# ☠️ 這個空狀態代表的是「文章」列表為空，不是指標頁——指標頁 2026-08-28 就上線了。
# 舊文案寫「尚未發布任何指標頁」，在首頁與指標索引並存時會直接說錯話（2026-08-31 修）。
_EMPTY_HTML = ('<div class="idx-empty">尚未發布文章。'
               '指標判準的整理在<a href="/indicators/">指標索引</a>，'
               '每頁的判準值都標註機構、文件、版本與頁碼。</div>')


REPORT_PATH = "/adult-report/"
REPORT_TITLE = "成人健檢報告欄位導覽"
REPORT_CSS = """
.report-sheet { border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--surface); overflow: hidden; }
.report-sheet h2 { margin: 0; padding: 12px 18px; background: var(--accent-soft);
  color: var(--fg); font-size: 16px; }
.report-sheet details + details { border-top: 1px solid var(--line); }
.report-sheet summary { padding: 14px 18px; cursor: pointer; font-weight: 700; }
.report-sheet summary:hover, .report-sheet summary:focus-visible { color: var(--accent); }
.report-sheet p { margin: 0; padding: 0 18px 16px; line-height: 1.8; }
.report-source { margin: 0 0 20px; font-size: 14px; }
.report-guide { margin-top: 24px; }
.reading-examples { margin-top:34px; }
.reading-row { margin:16px 0; padding:18px; background:var(--surface); border:1px solid var(--line);
  border-radius:var(--radius); scroll-margin-top:6rem; }
.reading-row h3 { margin:0; }
#first-report, .report-practice { scroll-margin-top:6rem; }
#first-report > details { padding:10px 14px; border:1px solid var(--line); border-radius:var(--radius-sm); margin:6px 0; }
.guide-options a { display:inline-block; margin-inline-end:14px; padding-block:6px; }
#first-report > details summary { cursor:pointer; font-weight:600; }
.report-handoff textarea, #followup-form textarea { display:block; box-sizing:border-box; width:100%; max-width:42em; margin:6px 0 12px;
  border:1px solid var(--line-2); background:var(--surface); color:var(--fg); padding:10px; font:inherit; }
.report-handoff button, #followup-form button { border:0; border-radius:var(--radius-sm); background:var(--accent); color:var(--accent-ink);
  padding:10px 16px; cursor:pointer; font:inherit; }
#followup-advice { margin-block:12px; padding:12px; background:var(--surface); border-inline-start:3px solid var(--accent); }
#followup-form fieldset { margin:12px 0; min-width:0; border:1px solid var(--line); }
#followup-form legend { font-weight:600; }
#followup-form fieldset label { display:inline-block; padding:6px; }
#followup-form button { margin-block:4px; }
.report-handoff [role=status]:empty { display:none; }
.reading-cells { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:6px; }
.reading-cells a,.reading-cells button { padding:9px 8px; min-height:54px; text-align:start; cursor:pointer;
  background:var(--bg); border:1px solid var(--line-2); border-radius:var(--radius-sm); color:var(--fg);
  font:inherit; text-decoration:none; overflow-wrap:anywhere; }
.reading-cells span,.reading-cells strong { display:block; }
.reading-cells span { color:var(--fg-soft); font-size:.85em; }
.reading-cells button span::after { content:" ▾"; color:var(--accent); }
.reading-cells [aria-expanded=true],.reading-cells :focus-visible { border-color:var(--accent); background:var(--accent-soft); }
.reading-note { border-inline-start:3px solid var(--accent); padding:6px 12px; scroll-margin-top:6rem; }
.result-columns { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; }
.result-columns > * { padding:8px; text-align:start; overflow-wrap:anywhere; font:inherit; color:var(--fg); }
.result-columns span,.result-columns strong { display:block; }
.result-columns button { cursor:pointer; background:var(--surface); border:1px solid var(--line-2); border-radius:var(--radius-sm); }
.result-columns .correct { background:var(--accent-soft); outline:2px solid var(--accent); outline-offset:-2px; }
.result-feedback:empty { margin:0; }
.alt-result-guide details { margin-block:12px; }
.alt-result-guide summary { padding-block:6px; cursor:pointer; font-weight:600; }
@media(max-width:600px){ .result-columns { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.alt-result-guide h4,.alt-reference-guide h4 { margin:14px 0 6px; }
.alt-reference-guide details { margin-block:8px; }
.alt-reference-guide summary { padding:6px 0; cursor:pointer; font-weight:600; }
.alt-reference-guide li + li { margin-top:6px; }
.reading-source { margin-bottom:0; font-size:.9em; }
.report-sheet details[id] { scroll-margin-top:6rem; }
@media(max-width:600px){ .reading-cells { grid-template-columns:repeat(2,minmax(0,1fr)); } }
"""


def render_lipid_rows(entries):
    examples = json.loads((ROOT / "data/report-lipid-examples.json").read_text(encoding="utf-8"))
    sources = {s["id"]: s for s in json.loads((ROOT / "data/sources/manifest.json").read_text(encoding="utf-8"))}
    by_href = {entry["href"]: entry for entry in entries}
    esc = html_lib.escape
    rows = []
    for example in examples:
        href = "/indicators/lipids/#" + example["id"]
        entry = by_href[href]
        label = esc(entry["label"])
        names = [name for name in [entry["label"], *entry["aliases"]] if name != "血脂"]
        names.append(entry["label"].split("（")[0])
        source = sources[example["doc_id"]]
        unit = esc(example["unit"])
        page = example["page"]
        note = f'<p>{esc(example["note"])}</p>' if "note" in example else ""
        rows.append(
            f'<details name="lipid-row" data-names="{esc("|".join(names))}">'
            f'<summary><strong>{label}</strong> <span lang="en">{esc(example["english_name"])}</span> <span>{example["result"]} {unit}（虛構結果）</span></summary>'
            f'<dl><div><dt>檢驗結果</dt><dd>{example["result"]}</dd></div>'
            f'<div><dt>單位</dt><dd>{unit}</dd></div>'
            f'<div><dt>院所參考範圍</dt><dd>{esc(example["reference"])}</dd></div></dl>{note}'
            f'<a href="{esc(source["url"])}#page={page}">手冊第 {page} 頁</a> · '
            f'<a href="{esc(href)}">查看{label}的分級表</a></details>')
    return "".join(rows)


def render_report_search():
    entries = json.loads((ROOT / "data/report-search.json").read_text(encoding="utf-8"))
    items = []
    for entry in entries:
        names = "|".join([entry["label"], *entry["aliases"]])
        items.append(f'<li data-names="{html_lib.escape(names)}"><a href="{html_lib.escape(entry["href"])}">'
                     f'{html_lib.escape(entry["label"])}</a></li>')
    examples = json.loads((ROOT / "data/report-reading-examples.json").read_text(encoding="utf-8"))
    alt = next(row for row in examples if row["id"] == "read-alt")
    cells = []
    for label, value, _ in alt["fields"]:
        heading = {"檢查項目": "項目名稱（可搜尋）", "檢驗結果": "檢驗結果（虛構）",
                   "異常註記": "異常註記（虛構）"}.get(label, label)
        cells.append(f"<div><dt>{html_lib.escape(heading)}</dt><dd>{html_lib.escape(value)}</dd></div>")
    template = (ROOT / "templates/report-search.html").read_text(encoding="utf-8")
    return (template.replace("{{search_items}}", "".join(items))
            .replace("{{miss_example}}", "".join(cells))
            .replace("{{lipid_rows}}", render_lipid_rows(entries))
            .replace("{{home_title}}", html_lib.escape(SITE["home_title"])))


def render_reading_row(row, sources):
    esc = html_lib.escape
    row_id = esc(row["id"])
    cells, notes = [], []
    for index, (label, value, explanation) in enumerate(row["fields"]):
        field_id = f"{row_id}-field-{index + 1}"
        cells.append(f'<a href="#{field_id}"><span>{esc(label)}</span><strong>{esc(value)}</strong></a>')
        if row_id == "read-alt" and label == "檢驗結果":
            fields = {name: (f"{row_id}-field-{i}", esc(text))
                      for i, (name, text, _) in enumerate(row["fields"], 1)}
            reference_id, reference = fields["院所參考範圍"]
            guide = (ROOT / "templates/alt-current-result.html").read_text(encoding="utf-8")
            notes.append(guide.replace("{{field_id}}", field_id).replace("{{result}}", esc(value))
                         .replace("{{unit}}", fields["單位"][1]).replace("{{reference}}", reference)
                         .replace("{{reference_id}}", reference_id).replace("{{explanation}}", esc(explanation))
                         .replace("{{question}}", esc(hl.ALT_CURRENT_QUESTION)))
        elif row_id == "read-alt" and label == "院所參考範圍":
            guide = (ROOT / "templates/alt-reference-guide.html").read_text(encoding="utf-8")
            notes.append(guide.replace("{{field_id}}", field_id)
                         .replace("{{explanation}}", esc(explanation))
                         .replace("{{question}}", esc(hl.ALT_REFERENCE_QUESTION)))
        else:
            notes.append(f'<p class="reading-note" id="{field_id}"><strong>{esc(label)}</strong>　{esc(explanation)}</p>')
    url = sources[row["doc_id"]]["url"]
    if "page" in row:
        url += f'#page={row["page"]}'
    return (f'<section class="reading-row" id="{row_id}" aria-labelledby="{row_id}-title">'
            f'<h3 id="{row_id}-title">{esc(row["title"])}</h3><p>{esc(row["intro"])}</p>'
            f'<div class="reading-cells">{"".join(cells)}</div>{"".join(notes)}'
            f'<p class="reading-source"><a href="{esc(url)}">{esc(row["source_label"])}</a> · '
            f'<a href="{esc(row["more_url"])}">{esc(row["more_label"])}</a></p></section>')


def render_adult_report():
    body = (ROOT / "templates" / "adult-report.html").read_text(encoding="utf-8")
    rows = json.loads((ROOT / "data/report-reading-examples.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "data/sources/manifest.json").read_text(encoding="utf-8"))
    sources = {doc["id"]: doc for doc in manifest}
    instructions = {
        "alt": "點選「檢驗結果」，連同單位讀出數值。再點「院所參考範圍」和「異常註記」，看看這個虛構範例為什麼標 H。讀自己的報告時，對照同一列的範圍和院所的圖例。",
        "urine-protein": "這個虛構範例把加號填在「檢驗結果」。再點「異常註記」，看看這一列有沒有另外標記。若自己的報告印有其他符號，可對照院所的圖例。",
    }
    choices = ('<p>換成我報告上的項目</p><div class="guide-options">'
               '<a href="#practice-alt">GPT（ALT）</a>'
               '<a href="#read-urine-protein-field-2">尿蛋白（試紙）</a>'
               '<a href="/#report-query">回首頁查其他項目</a></div>')
    practice = (ROOT / "templates/report-practice.html").read_text(encoding="utf-8")
    by_id = {row["id"]: row for row in rows}
    rendered = []
    for key, item in hl.FIRST_REPORT_ITEMS.items():
        row = by_id.pop("read-" + key)
        rendered.append(practice.replace("{{key}}", key)
                        .replace("{{label}}", html_lib.escape(item["label"]))
                        .replace("{{question}}", html_lib.escape(item["question"]))
                        .replace("{{instruction}}", html_lib.escape(instructions[key]))
                        .replace("{{row}}", render_reading_row(row, sources)))
    checks = [
        ("item", "院所指的是哪些檢驗項目？"),
        ("action", "院所建議我接下來做什麼？"),
        ("time", "院所建議我什麼時候追蹤？"),
    ]
    fieldsets = []
    for key, prompt in checks:
        options = "".join(
            f'<label><input type="radio" name="advice-{key}" value="{value}" required> {label}</label>'
            for value, label in [("here", "這句原文寫清楚了"), ("elsewhere", "我在別處找到了"), ("missing", "我的報告也沒寫")]
        )
        fieldsets.append(f"<fieldset><legend>{prompt}</legend>{options}</fieldset>")
    body = (body.replace("{{item_choices}}", choices)
            .replace("{{followup_checks}}", "".join(fieldsets))
            .replace("{{practice_rows}}", "".join(rendered))
            .replace("{{other_reading_rows}}", "".join(render_reading_row(row, sources) for row in by_id.values())))
    script = (ROOT / "templates/report-fields.js").read_text(encoding="utf-8")
    body += f"<script>{script}</script>"
    url = BASE + REPORT_PATH
    jsonld = hl.graph_ld([hl.org_node(), hl.website_node(),
                          hl.breadcrumb_node([("首頁", BASE + "/"), (REPORT_TITLE, url)])])
    return hl.page_shell(REPORT_TITLE, "點選國健署表單節錄的欄位，對照名稱、單位與判準出處。",
                         url, jsonld, body, "adult-report", extra_css=REPORT_CSS)


def render_home(articles):
    cards = "\n".join(_idx_card(a) for a in articles[:8]) or _EMPTY_HTML
    faq_sec = hl.faq_html(HOME_FAQ)
    entry = render_report_search() if hl.PUBLISHED else (
        f'<h1 class="pg-h1">{html_lib.escape(SITE["home_title"])}</h1>'
        f'<p class="pg-sub">{html_lib.escape(SITE["website_desc"])}</p>')
    body = f"""  <main>
  {entry}
  <h2 class="sec-h">最新整理</h2>
{cards}
  {faq_sec}
  </main>"""
    jsonld = hl.graph_ld([hl.org_node(), hl.website_node(),
                          hl.faq_node(HOME_FAQ, f"{BASE}/")])
    return hl.page_shell(SITE["home_title"], SITE["website_desc"], f"{BASE}/",
                         jsonld, body, "home", extra_css=INDEX_CSS + LIPID_GUIDE_CSS)


def render_articles_index(articles):
    cards = "\n".join(_idx_card(a) for a in articles) or _EMPTY_HTML
    title = "健檢報告閱讀指南"
    desc = "從健檢表上的項目名稱與單位，對照原始文件的寫法。"
    body = f"""  <main>
  <h1 class="pg-h1">{html_lib.escape(title)}</h1>
  <p class="pg-sub">{html_lib.escape(desc)}</p>
{cards}
  </main>"""
    jsonld = hl.graph_ld([
        hl.org_node(), hl.website_node(),
        hl.breadcrumb_node([("首頁", f"{BASE}/"), (title, f"{BASE}/articles/")])])
    return hl.page_shell(title, desc, f"{BASE}/articles/", jsonld, body, "articles",
                         extra_css=INDEX_CSS)


# ---------- RSS ----------

def _rfc822(date_str):
    import datetime
    try:
        d = datetime.date.fromisoformat(str(date_str))
    except ValueError:
        return ""
    wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()]
    mo = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.month - 1]
    return f"{wd}, {d.day:02d} {mo} {d.year} 00:00:00 +0800"


def render_feed(articles):
    """RSS 2.0。刻意不輸出 lastBuildDate——那是時間戳，會讓同輸入的兩次 build 產出不同
    bytes，直接殺掉「連跑兩次 SHA-256 全同」這道最強驗收。"""
    items = []
    for a in articles[:FEED_MAX]:
        m = a["meta"]
        url = f"{BASE}/articles/{a['slug']}/"
        pub = _rfc822(m.get("date", ""))
        pub_line = f"      <pubDate>{pub}</pubDate>\n" if pub else ""
        items.append(
            "    <item>\n"
            f"      <title>{html_lib.escape(m.get('title', a['slug']))}</title>\n"
            f"      <link>{url}</link>\n"
            f"      <guid isPermaLink=\"true\">{url}</guid>\n"
            f"{pub_line}"
            f"      <description>{html_lib.escape(m.get('subtitle', a['excerpt']))}</description>\n"
            "    </item>\n")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
            "  <channel>\n"
            f"    <title>{html_lib.escape(SITE['feed_channel_title'])}</title>\n"
            f"    <link>{BASE}/</link>\n"
            f"    <description>{html_lib.escape(SITE['feed_channel_desc'])}</description>\n"
            "    <language>zh-tw</language>\n"
            f'    <atom:link href="{BASE}/feed.xml" rel="self" type="application/rss+xml"/>\n'
            f"{''.join(items)}"
            "  </channel>\n</rss>\n")


# ---------- llms.txt（build-time 生成，永不 stale） ----------

def render_llms_txt(articles):
    # 指標索引入口與導覽列同一條 published gate：/indicators/ 要到 M5 才生成，
    # 翻開關前列進 llms.txt 就是餵給 AI 一條死連結（llms.txt 沒人看，錯了不會有人叫）。
    indicators_line = (f"- [指標索引]({BASE}/indicators/)：各項指標的判準並列頁（陸續上線）。\n"
                       if hl.PUBLISHED else "")
    report_line = f"- [{REPORT_TITLE}]({BASE}{REPORT_PATH})\n" if hl.PUBLISHED else ""
    art_lines = "\n".join(
        f"- [{a['meta'].get('title', a['slug'])}]({BASE}/articles/{a['slug']}/)"
        + (f"（{a['meta']['date']}）" if a["meta"].get("date") else "")
        for a in articles[:10]) or "- （尚未發布內容頁）"
    return f"""# 健檢數據誌（health.twtools.cc）— 健康檢查指標判準整理

> {SITE['website_desc']}。整理健康檢查報告上常見指標的判準值，並列不同機構的數字，每一列標註機構、文件名稱、版本與頁碼，引句可回查原始文件。內容以繁體中文撰寫，面向台灣讀者。

本站為獨立經營的資訊站，與各判準發布機構均無關聯或授權關係。內容僅供資訊參考，不構成醫療建議、診斷或治療指示。

## 重點頁面

- [首頁]({BASE}/)：站台說明與最新整理。
{indicators_line}{report_line}- [所有整理]({BASE}/articles/)：長文與判準沿革。

## 最新內容

{art_lines}

## 引用說明

- 本站每一個判準值都綁定「機構＋文件＋版本＋頁碼」四項；四項不齊備的數字不會出現在頁面上。
- 引用時請一併帶上本站標註的原始文件出處，並以該機構的最新版本為準。
- 判準有版本沿革時，本站保留舊版並標明變更年份與依據文件，不覆寫歷史。
"""


# ---------- main build ----------


def write_indexnow_key(pub: pathlib.Path, key_file: pathlib.Path):
    """把 IndexNow 金鑰檔寫進 pub，回金鑰字串；沒設定金鑰回 None。

    ☠️ 金鑰是**設計上就要公開**的值——引擎會抓 https://<host>/<key>.txt 驗證擁有權，
    檔案內容就是金鑰本身。它不是密鑰，正本放 repo 是對的；但也因此**不能拿它當任何
    形式的憑證**。沒設定就回 None，由呼叫端說明，不要靜默產一個空檔或假檔。
    """
    if not key_file.exists():
        return None
    key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        return None
    pub.mkdir(parents=True, exist_ok=True)
    (pub / f"{key}.txt").write_text(key + "\n", encoding="utf-8")
    return key


def build():
    draft_excludes = load_draft_excludes()
    articles = []
    if SRC.exists():
        for d in sorted(SRC.iterdir()):
            article_path = d / "index.md"
            if not d.is_dir() or not article_path.exists():
                continue
            text = article_path.read_text(encoding="utf-8")
            meta, body = hl.parse_frontmatter(text)
            meta.setdefault("slug", d.name)
            slug = meta["slug"]
            if slug in draft_excludes:
                print(f"⏭  skip draft (pending review, excluded): {slug}")
                continue
            if md_lib is None:
                print("❌ 需要 markdown 套件才能渲染文章：pip install markdown", file=sys.stderr)
                sys.exit(1)
            body = hl.strip_h1(body)
            excerpt = hl.extract_excerpt(body)
            faq = hl.parse_faq(body)
            body_html = md_lib.markdown(body, extensions=["extra", "sane_lists"])
            body_html = (body_html.replace("<table>", '<div class="prose-tblwrap"><table>')
                                  .replace("</table>", "</table></div>"))
            out_dir = PUB / "articles" / slug
            out_dir.mkdir(parents=True, exist_ok=True)
            for asset in sorted(d.iterdir()):
                if asset.is_file() and asset.suffix != ".md":
                    shutil.copy2(asset, out_dir / asset.name)
            articles.append({"slug": slug, "meta": meta, "excerpt": excerpt,
                             "faq": faq, "body_html": body_html, "out_dir": out_dir})

    # 真下架：曾上線後改回草稿或整篇移除的文章，輸出目錄必須刪掉——
    # 只從 index／sitemap 拿掉不算下架，知道網址的人仍讀得到。
    prune_stale_article_dirs(PUB / "articles", {a["slug"] for a in articles})

    articles.sort(key=lambda a: (str(a["meta"].get("date", "")), a["slug"]), reverse=True)

    for i, a in enumerate(articles):
        prev_nav = articles[i + 1] if i + 1 < len(articles) else None   # 較舊
        next_nav = articles[i - 1] if i > 0 else None                   # 較新
        html_out = render_article(a["meta"], a["body_html"], a["slug"], a["excerpt"],
                                  a["faq"], prev_nav=prev_nav, next_nav=next_nav)
        (a["out_dir"] / "index.html").write_text(html_out, encoding="utf-8")
        print(f"✅ {a['slug']}")

    PUB.mkdir(parents=True, exist_ok=True)
    report_dir = PUB / REPORT_PATH.strip("/")
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "index.html").write_text(render_adult_report(), encoding="utf-8")
    (PUB / "index.html").write_text(render_home(articles), encoding="utf-8")
    (PUB / "articles").mkdir(parents=True, exist_ok=True)
    (PUB / "articles" / "index.html").write_text(render_articles_index(articles), encoding="utf-8")
    (PUB / "feed.xml").write_text(render_feed(articles), encoding="utf-8")
    (PUB / "llms.txt").write_text(render_llms_txt(articles), encoding="utf-8")
    (PUB / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")

    if write_indexnow_key(PUB, ROOT / "data" / "indexnow-key.txt"):
        print("🔑 IndexNow 金鑰檔已產出")
    else:
        print("ℹ️  未設定 IndexNow 金鑰（data/indexnow-key.txt 不存在），未產出金鑰檔")

    urls = ([f"{BASE}/", f"{BASE}/articles/"]
            + [f"{BASE}/articles/{a['slug']}/" for a in articles])
    if hl.PUBLISHED:
        urls.append(BASE + REPORT_PATH)
    hl.write_sitemap_part("articles", urls)
    print(f"🏠 index + articles index + feed + llms.txt + robots.txt + sitemap part "
          f"({len(articles)} 篇) → {PUB}/")


if __name__ == "__main__":
    build()
