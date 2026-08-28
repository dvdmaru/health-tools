#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""healthlib.py — health.twtools.cc（健檢數據誌）共用庫。

站群共通層（站身分／主題／頁面外殼／JSON-LD／frontmatter 與 FAQ 解析／sitemap
manifest），沿用姊妹站同一套慣例，收斂成單站版：

- 站身分單一資料源 config/site.json；ga_id 為空 → 不輸出 GA tag。
- published gate：site.json 的 published 為 false 時，帶 "requires": "published"
  的導覽／頁尾項目一律不輸出（dormant wiring，翻開關前不生成也不連結）。
- JSON-LD helpers（org / website / breadcrumb / FAQ）；FAQPage schema 永遠鏡射
  頁面上真實可見的問答，不放編輯評分、不杜撰。
- frontmatter / FAQ 解析器：FAQ 必須是「## 常見問題」下的 ### 問題 + 段落答案
  （### 才吐 schema）。
- 所有輸出必須是決定性的（禁時間戳）：同輸入連跑兩次全檔 SHA-256 必須相同。
"""
import hashlib
import html as html_lib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = json.loads((ROOT / "config" / "site.json").read_text(encoding="utf-8"))
BASE = SITE["base"]
PUB = ROOT / "public-health"

# 公開開關（M0 dormant wiring）：翻開關前，帶 requires 的入口一律不輸出。
PUBLISHED = SITE.get("published", False) is True


# ---------- GA4（config/site.json 的 ga_id 為空 → 不輸出 tag） ----------

def ga_snippet(site: dict = None) -> str:
    gid = (site or SITE).get("ga_id")
    if not gid:
        return "<!-- GA4: 待 property 開通後於 config/site.json 填 ga_id -->"
    return (
        "<!-- Google tag (gtag.js) -->\n"
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={gid}"></script>\n'
        "<script>\n"
        "  window.dataLayer = window.dataLayer || [];\n"
        "  function gtag(){dataLayer.push(arguments);}\n"
        "  gtag('js', new Date());\n"
        f"  gtag('config', '{gid}');\n"
        "</script>"
    )


# ---------- 主題家族（鍵 hl-theme；淺色重心，臨床報表質感） ----------
# 配色刻意避開紅綠燈式的「好／壞」暗示：本站並列各機構判準，不對讀者的數值下判斷，
# 顏色不得承載「這個數字有問題」的語意（一個視覺通道只承載一種語意）。
HL_THEMES = [
    ("paper", "paper 紙本報表", "#2f6f6b", "#f7f5f1", "#1b1f21"),
    ("slate", "slate 石板", "#3d6a8f", "#f2f4f7", "#171b20"),
    ("sage", "sage 灰綠", "#4f7350", "#f4f6f1", "#1a1e19"),
]
HL_THEME_KEYS = [t[0] for t in HL_THEMES]


def _theme_tokens_css() -> str:
    out = []
    for i, (key, _zh, accent, bg, ink) in enumerate(HL_THEMES):
        sel = ":root, " + f':root[data-theme="{key}"]' if i == 0 else f':root[data-theme="{key}"]'
        out.append(f"""
{sel} {{
  --accent: {accent};
  --accent-bright: color-mix(in srgb, {accent} 78%, #000 22%);
  --accent-ink: #ffffff;
  --accent-soft: color-mix(in srgb, {accent} 12%, transparent);
  --accent-line: color-mix(in srgb, {accent} 42%, transparent);
  --bg: {bg};
  --bg-glow: color-mix(in srgb, {accent} 8%, transparent);
  --ink: {ink};
  --surface: #ffffff;
  --fg: {ink};
  --fg-soft: color-mix(in srgb, {ink} 78%, #ffffff 22%);
  --dim: color-mix(in srgb, {ink} 55%, #ffffff 45%);
  --faint: color-mix(in srgb, {ink} 40%, #ffffff 60%);
  --line: color-mix(in srgb, {ink} 14%, transparent);
  --line-2: color-mix(in srgb, {ink} 26%, transparent);
}}""")
    return "\n".join(out) + "\n"


SHARED_TOKENS_CSS = """
:root {
  --radius: 12px;
  --radius-sm: 8px;
  --font-display: 'Noto Sans TC', -apple-system, BlinkMacSystemFont, 'PingFang TC', sans-serif;
  --font-ui: 'Noto Sans TC', -apple-system, BlinkMacSystemFont, 'PingFang TC', 'Microsoft JhengHei', sans-serif;
  --font-mono: ui-monospace, 'SF Mono', Menlo, monospace;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  background: var(--bg); color: var(--fg); font-family: var(--font-ui);
  line-height: 1.75; -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}
body { min-height: 100vh; padding: 0 16px 110px; position: relative; }
a { color: var(--accent); } a:hover { color: var(--accent-bright); }
.container { max-width: 900px; margin: 0 auto; position: relative; z-index: 1; }
""" + _theme_tokens_css()

THEME_SWITCH_CSS = """
.theme-switch {
  position: fixed; top: 14px; right: 16px; z-index: 150;
  display: flex; align-items: center; gap: 11px;
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  border: 1px solid var(--line); border-radius: 99px;
  padding: 7px 13px; box-shadow: 0 6px 22px rgba(0,0,0,0.08);
  backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
}
.ts-label { font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.5px; color: var(--dim); text-transform: uppercase; }
.ts-dots { display: flex; gap: 8px; }
.ts-dot {
  width: 19px; height: 19px; border-radius: 50%; padding: 0; cursor: pointer;
  background: var(--sw); border: 2px solid var(--surface);
  box-shadow: 0 0 0 1px var(--line-2); transition: transform 0.16s ease;
}
.ts-dot:hover { transform: scale(1.14); }
.ts-dot.active { box-shadow: 0 0 0 2px var(--sw); transform: scale(1.05); }
@media (max-width: 520px) { .theme-switch { top: 10px; right: 10px; padding: 6px 11px; gap: 9px; } .ts-label { display: none; } }
"""

THEME_SWITCH_HTML = (
    '\n<div class="theme-switch">\n  <span class="ts-label">配色</span>\n  <div class="ts-dots">\n'
    + "".join(
        f'    <button class="ts-dot" data-theme="{k}" onclick="setTheme(\'{k}\')" style="--sw:{acc}" aria-label="{zh}"></button>\n'
        for k, zh, acc, *_ in HL_THEMES)
    + '  </div>\n</div>\n')

THEME_SWITCH_JS = f"""
const THEMES = {HL_THEME_KEYS};
function setTheme(t) {{
  if (!THEMES.includes(t)) t = 'paper';
  document.documentElement.dataset.theme = t;
  try {{ localStorage.setItem('hl-theme', t); }} catch (e) {{}}
  document.querySelectorAll('.ts-dot').forEach(d => d.classList.toggle('active', d.dataset.theme === t));
}}
(function initTheme() {{
  let t = 'paper';
  try {{ t = localStorage.getItem('hl-theme') || 'paper'; }} catch (e) {{}}
  setTheme(t);
}})();
"""

THEME_PRELOAD_JS = (
    "<script>try{var t=localStorage.getItem('hl-theme');"
    "if(t)document.documentElement.dataset.theme=t}catch(e){}</script>")


# ---------- 站頭／站尾 ----------

SITE_HEADER_CSS = """
.site-header {
  position: sticky; top: 0; z-index: 30;
  display: flex; justify-content: space-between; align-items: center;
  gap: 14px 24px; flex-wrap: wrap;
  padding: 14px 0; margin-bottom: 34px;
  background: color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--line);
}
.brand-block { display: flex; flex-direction: column; gap: 5px; }
.brand-mark {
  font-family: var(--font-display); font-weight: 900; font-size: 24px; line-height: 1;
  color: var(--accent); letter-spacing: 1.5px; text-decoration: none;
  transition: color 0.15s ease;
}
.brand-mark:hover { color: var(--accent-bright); }
.brand-tag { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 2px; color: var(--dim); }
.site-nav { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.site-nav a { color: var(--dim); text-decoration: none; letter-spacing: 1px;
  padding: 6px 13px; border-radius: 999px; transition: color 0.15s ease, background 0.15s ease; }
.site-nav a:hover { color: var(--accent); background: var(--accent-soft); }
.site-nav a.active { color: var(--accent-ink); background: var(--accent); font-weight: 700; }
@media (max-width: 580px) { .brand-mark { font-size: 20px; } }
.site-disclaimer { font-size: 11.5px; color: var(--faint); line-height: 1.8; text-align: center;
  max-width: 660px; margin: 18px auto 0; }
.article-footer { margin-top: 64px; padding-top: 28px; border-top: 1px solid var(--line); text-align: center; }
.foot-links { display: flex; flex-wrap: wrap; gap: 10px 22px; justify-content: center; font-size: 13px; }
.foot-links a { color: var(--dim); text-decoration: none; }
.foot-links a:hover { color: var(--accent); }
"""

# 免責聲明（全站頁尾）。本站整理公開指引的判準值並標註出處，不做醫療判斷、不提供個人化建議。
# 這段是法規紅線的第一層防護（另兩層：禁詞 gate scripts/check-health-terms.py、
# 指標頁固定六段結構不得夾帶第七段治療建議）。
DISCLAIMER_HTML = (
    '<div class="site-disclaimer">本站整理公開發布的健康檢查指標判準，逐項標註機構、文件、版本與頁碼，'
    '與各發布機構均無關聯或授權關係。內容僅供資訊參考，不構成醫療建議、診斷或治療指示；'
    '個人數值的意義與後續處置，請與您的醫師討論。</div>'
)

# twtools 生態系姊妹站互連。這不是裝飾：站群實測過「全網域零連入」會讓新站被搜尋引擎
# 判為 URL 未知（三個月只被檢索 1 次），所以清單只增不減且掛在每一頁的頁尾。
# ⚠️ M0 只列與本站主題無關的通用站；體育線姊妹站等公開日（M5）連同 og/robots 一起補。
SISTER_SITES = [
    ("TWTools — 打工牛馬的線上工具箱", "https://twtools.cc/"),
    ("aire — AI Tool Atlas·AI 工具圖鑑", "https://aire.twtools.cc/"),
    ("樹洞21號 — 匿名 AI 心事平台", "https://tree.twtools.cc/"),
    ("Shhhh — 專業短網址管理平台", "https://shhhh.cc/"),
    ("dvdmaru — 把事實和敘事分開來看", "https://dvdmaru.com/"),
]


def sister_sites_html(site: dict = None) -> str:
    base = (site or SITE)["base"].rstrip("/") + "/"
    links = "　·　".join(
        f'<a href="{u}" style="color:var(--dim);text-decoration:none">{html_lib.escape(n)}</a>'
        for n, u in SISTER_SITES if u != base)
    return ('<div class="sister-sites" style="margin-top:12px;font-size:12px;'
            f'color:var(--dim);line-height:2;text-align:center">姊妹站　{links}</div>')


def nav_item_visible(item: dict) -> bool:
    """導覽列／頁尾連結的共用 published gate：帶 "requires": "published" 的項目只在
    site.json published 為 true 時輸出。

    ☠️ 為什麼抽成共用函式而不是兩處各寫一份 if：這條判定的失敗模式是單向的沉默——
    導覽列補了新入口、頁尾忘了補 gate，未公開時每一頁就多一條 404，站不會壞、測試不會紅。
    同一條規則只能有一份實作。
    """
    return not (item.get("requires") == "published" and not PUBLISHED)


def site_header_html(active: str, site: dict = None) -> str:
    site = site or SITE
    parts = []
    for n in site.get("nav", []):
        if not nav_item_visible(n):
            continue
        cls = ' class="active"' if n.get("key") == active else ""
        parts.append(f'<a href="{n["href"]}"{cls}>{n["label"]}</a>')
    links = "\n      ".join(parts)
    return f"""
  <header class="site-header">
    <div class="brand-block">
      <a href="/" class="brand-mark">{site["brand_mark"]}</a>
      <div class="brand-tag">{site["brand_tag"]}</div>
    </div>
    <nav class="site-nav">
      {links}
    </nav>
  </header>
"""


def site_footer_html(site: dict = None) -> str:
    site = site or SITE
    link_parts = []
    for l in site.get("footer_links", []):
        if not nav_item_visible(l):
            continue
        target = ' target="_blank" rel="noopener"' if l.get("external") else ""
        link_parts.append(f'<a href="{l["href"]}"{target}>{l["label"]}</a>')
    links = "\n      ".join(link_parts)
    return f"""  <div class="article-footer">
    <div class="foot-links">
      {links}
    </div>
    {DISCLAIMER_HTML}
    {sister_sites_html(site)}
  </div>"""


# ---------- JSON-LD helpers ----------

def _ld(obj: dict) -> str:
    payload = obj if "@context" in obj else {"@context": "https://schema.org", **obj}
    return ('<script type="application/ld+json">'
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + "</script>")


def graph_ld(nodes: list) -> str:
    nodes = [n for n in nodes if n]
    return _ld({"@context": "https://schema.org", "@graph": nodes}) if nodes else ""


def org_node(site: dict = None) -> dict:
    site = site or SITE
    base = site["base"]
    node = {"@type": "Organization", "@id": f"{base}/#org",
            "name": site["org_name"], "url": f"{base}/"}
    if site.get("org_same_as"):
        node["sameAs"] = site["org_same_as"]
    return node


def website_node(site: dict = None) -> dict:
    site = site or SITE
    base = site["base"]
    node = {"@type": "WebSite", "@id": f"{base}/#website",
            "name": site["website_name"], "url": f"{base}/",
            "inLanguage": "zh-Hant", "publisher": {"@id": f"{base}/#org"}}
    if site.get("website_desc"):
        node["description"] = site["website_desc"]
    return node


def breadcrumb_node(items: list) -> dict:
    elements = []
    for i, (name, url) in enumerate(items):
        el = {"@type": "ListItem", "position": i + 1, "name": name}
        if url:
            el["item"] = url
        elements.append(el)
    return {"@type": "BreadcrumbList", "itemListElement": elements}


def faq_node(pairs, page_url: str):
    """FAQPage schema——只鏡射頁面上真實可見的問答，不放編輯評分、不杜撰。"""
    if not pairs:
        return None
    return {"@type": "FAQPage", "@id": f"{page_url}#faq",
            "mainEntity": [
                {"@type": "Question", "name": q,
                 "acceptedAnswer": {"@type": "Answer", "text": a}}
                for q, a in pairs]}


# ---------- frontmatter / FAQ 解析（站群共通慣例） ----------

def parse_frontmatter(text: str):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if kv:
            k, v = kv.group(1), kv.group(2).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            meta[k] = v
    return meta, text[m.end():]


def strip_h1(body: str) -> str:
    return re.sub(r"^#\s+.*\n+", "", body, count=1)


def _strip_inline_md(s: str) -> str:
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return s.strip()


def parse_faq(body: str):
    """抽「## 常見問題」區塊的 ###-gated 問答（### 才吐 schema）。"""
    m = re.search(r"^##\s*常見問題.*?$(.*?)(?=^##\s|\Z)", body, re.S | re.M)
    if not m:
        return []
    section = m.group(1)
    pairs = []
    for qm in re.finditer(r"^###\s+(.+?)$\n(.*?)(?=^###\s|\Z)", section, re.S | re.M):
        q = _strip_inline_md(qm.group(1))
        a = _strip_inline_md(re.sub(r"\s+", " ", qm.group(2)))
        if q and a:
            pairs.append((q, a))
    return pairs


def extract_excerpt(body: str, length: int = 120) -> str:
    for para in body.split("\n\n"):
        p = _strip_inline_md(re.sub(r"\s+", " ", para)).strip()
        if p and not p.startswith("#") and not p.startswith("|") and not p.startswith("---"):
            return p[:length]
    return ""


# ---------- 頁面外殼 ----------

FONTS_HTML = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&display=swap" rel="stylesheet">'
)

# 資料頁通用 CSS（判準表／區塊標題／FAQ；與文章頁共用 tokens）
DATA_CSS = """
.pg-h1 { font-family: var(--font-display); font-size: clamp(26px,4.6vw,38px); line-height:1.2; margin: 4px 0 6px; font-weight: 900; }
.pg-sub { color: var(--fg-soft); font-size: 15px; margin: 12px 0 22px; }
.sec-h { font-family: var(--font-display); font-size: 20px; letter-spacing: .5px; margin: 40px 0 8px; font-weight: 800; }
.std-table { width:100%; border-collapse: collapse; margin: 10px 0 22px; font-size: 14px; }
.std-table th, .std-table td { padding: 9px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
.std-table thead th { background: var(--surface); color: var(--dim); font-weight: 600; font-size: 12.5px; }
.tbl-scroll { overflow-x: auto; }
/* 出處註記：判準值旁的「機構＋文件＋版本＋頁碼」四項，缺一即不得渲染該列 */
.src-note { font-family: var(--font-mono); font-size: 11.5px; color: var(--dim); line-height: 1.8; }
.pg-faq .qa { border-top: 1px solid var(--line); padding: 16px 0; }
.pg-faq h3 { font-size: 16px; margin: 0 0 8px; font-weight: 700; }
.pg-faq p { font-size: 14.5px; color: var(--fg-soft); margin: 0; }
.asof-note { font-size: 12px; color: var(--dim); border-top: 1px solid var(--line); padding-top: 10px; margin-top: 10px; }
"""

ARTICLE_CSS = """
.art-cover { width:100%; border-radius: var(--radius); margin: 8px 0 26px; display:block; }
.art-kicker { font-family: var(--font-mono); font-size: 12px; letter-spacing: 2.5px; color: var(--accent);
  text-transform: uppercase; margin-bottom: 10px; }
.art-h1 { font-family: var(--font-display); font-size: clamp(24px,4.4vw,36px); line-height: 1.28;
  margin: 0 0 14px; font-weight: 900; }
.art-meta { color: var(--dim); font-size: 13px; margin-bottom: 26px; display:flex; gap:14px; flex-wrap:wrap; }
.art-lede { font-size: 16.5px; color: var(--fg-soft); line-height: 1.9; border-left: 3px solid var(--accent);
  padding: 4px 0 4px 18px; margin: 0 0 30px; }
.prose { font-size: 16px; line-height: 1.95; }
.prose h2 { font-family: var(--font-display); font-size: 22px; margin: 44px 0 14px; line-height:1.4; font-weight: 800; }
.prose h3 { font-size: 17.5px; margin: 30px 0 10px; font-weight: 700; }
.prose p { margin: 0 0 18px; }
.prose strong { color: var(--fg); }
.prose a { color: var(--accent); }
.prose ul, .prose ol { margin: 0 0 18px 1.4em; }
.prose li { margin-bottom: 6px; }
.prose blockquote { border-left: 3px solid var(--line-2); color: var(--dim); padding-left: 16px; margin: 0 0 18px; }
.prose hr { border: none; border-top: 1px solid var(--line); margin: 34px 0; }
.prose table { width:100%; border-collapse: collapse; margin: 10px 0 22px; font-size: 14px; }
.prose th, .prose td { padding: 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
.prose th { color: var(--dim); font-weight: 600; font-size: 12.5px; }
.prose .tbl-scroll, .prose-tblwrap { overflow-x: auto; }
.art-nav { display:flex; gap:12px; margin-top: 44px; }
.art-nav a { flex:1; border:1px solid var(--line); border-radius: 12px; padding: 12px 16px;
  text-decoration:none; color: var(--fg-soft); font-size: 13.5px; background: var(--surface); }
.art-nav a:hover { border-color: var(--accent-line); }
.art-nav .lbl { display:block; color: var(--dim); font-size: 11px; font-family: var(--font-mono);
  letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 4px; }
"""

# 單一外部 CSS 檔（組裝順序＝原 inline <style> 順序）
SHARED_CSS_TEXT = (SHARED_TOKENS_CSS + THEME_SWITCH_CSS + SITE_HEADER_CSS
                   + DATA_CSS + ARTICLE_CSS)


def shared_css_href() -> str:
    """共用 CSS 落地到 public-health/assets/hl-<hash>.css，回傳 /assets/ 開頭的 href。
    檔名含內容 hash：同內容必同檔名，重跑天生 byte-stable。寫新 hash 檔時只保留
    「新版＋前一版」兩份，防部署中途切版時舊頁引用的檔案 404。"""
    assets_dir = PUB / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    content = SHARED_CSS_TEXT.encode("utf-8")
    fname = f"hl-{hashlib.sha256(content).hexdigest()[:10]}.css"
    fpath = assets_dir / fname
    if not fpath.exists():
        fpath.write_bytes(content)
        others = sorted(
            (p for p in assets_dir.glob("hl-*.css") if p.name != fname),
            key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in others[1:]:
            stale.unlink()
            print(f"🗑  removed stale shared css: {stale.name}")
    return f"/assets/{fname}"


def faq_html(pairs) -> str:
    qa = "".join(
        f'<div class="qa"><h3>{html_lib.escape(q)}</h3><p>{html_lib.escape(a)}</p></div>'
        for q, a in pairs)
    return f'<h2 class="sec-h">常見問題</h2><section class="pg-faq">{qa}</section>'


def page_shell(title: str, desc: str, canonical: str, jsonld: str, body: str,
               active: str, extra_css: str = "", og_image: str = "") -> str:
    """資料頁／列表頁共用外殼（文章頁另有 render；共用 tokens／站頭／站尾／主題）。"""
    og_img = ""
    if og_image:
        og_img = (f'<meta property="og:image" content="{og_image}">\n'
                  '<meta property="og:image:width" content="1200">\n'
                  '<meta property="og:image:height" content="630">\n'
                  '<meta name="twitter:card" content="summary_large_image">\n'
                  f'<meta name="twitter:image" content="{og_image}">\n')
    return f"""<!DOCTYPE html>
<html lang="zh-Hant" data-theme="{SITE['default_theme']}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_lib.escape(title)} | {SITE['title_suffix']}</title>
<meta name="description" content="{html_lib.escape(desc)}">
<meta property="og:title" content="{html_lib.escape(title)}">
<meta property="og:description" content="{html_lib.escape(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="{SITE['org_name']}">
<meta property="og:locale" content="zh_TW">
{og_img}<link rel="canonical" href="{canonical}">
{jsonld}
{FONTS_HTML}
{ga_snippet()}
<link rel="stylesheet" href="{shared_css_href()}">
{THEME_PRELOAD_JS}
{f"<style>{extra_css}</style>" if extra_css else ""}
</head>
<body>
{THEME_SWITCH_HTML}
<div class="container">{site_header_html(active)}
{body}
{site_footer_html()}
</div>
<script>{THEME_SWITCH_JS}</script>
</body>
</html>
"""


# ---------- sitemap manifest（各擁有者只寫自己的 part，build-sitemap.py 統一合併） ----------
# 不靠字串比對 read-modify-write 整個 sitemap.xml（跑序敏感、易踩踏）；各 owner 各寫
# data/sitemap-parts/<owner>.txt（append-only 擁有），build-sitemap.py 依固定順序讀取、
# 去重、產出最終 sitemap.xml。parts 檔進 git＝某 owner 這次沒跑時的保留機制。

def read_sitemap_part(owner: str) -> list:
    """讀 data/sitemap-parts/<owner>.txt，回 URL list；檔案不存在＝該線還沒接上 → 回 []。"""
    p = ROOT / "data" / "sitemap-parts" / f"{owner}.txt"
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_sitemap_part(owner: str, urls: list):
    """寫 data/sitemap-parts/<owner>.txt：一行一 URL，結尾換行；內容相同不重寫。"""
    parts_dir = ROOT / "data" / "sitemap-parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    p = parts_dir / f"{owner}.txt"
    content = "".join(f"{u}\n" for u in urls)
    if not p.exists() or p.read_text(encoding="utf-8") != content:
        p.write_text(content, encoding="utf-8")
    print(f"🗺️  sitemap part '{owner}' → {len(urls)} URL(s)")
