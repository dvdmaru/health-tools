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
"""

# 首頁 FAQ（可見問答＝schema 鏡射源）。
# ⚠️ 這幾句要通過 scripts/check-health-terms.py：不得出現招徠、療效、自我標榜、gate 語言。
HOME_FAQ = [
    ("這個站整理的是什麼？",
     "健康檢查報告上常見的指標，逐項並列不同機構公布的判準值，每一列都標註機構、文件名稱、"
     "版本與頁碼。"),
    ("為什麼同一個指標會有好幾個判準？",
     "不同機構依據各自的文件訂定判準，數值本來就不一致。本站並列呈現，不代替讀者選邊。"),
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
    return hl.page_shell(title, desc, url, jsonld, body, "indicators",
                         extra_css="", og_image=cover)


# ---------- 首頁／文章索引 ----------

def _idx_card(a):
    m = a["meta"]
    return (f'<a class="idx-card" href="/articles/{a["slug"]}/">'
            f'<div class="idx-date">{html_lib.escape(str(m.get("date", "")))}</div>'
            f'<h2>{html_lib.escape(m.get("title", a["slug"]))}</h2>'
            f'<p>{html_lib.escape(m.get("subtitle", a["excerpt"]))}</p></a>')


_EMPTY_HTML = ('<div class="idx-empty">地基已就緒，尚未發布任何指標頁。'
               '每個指標頁上線前，判準值必須齊備機構、文件、版本與頁碼四項出處。</div>')


def render_home(articles):
    cards = "\n".join(_idx_card(a) for a in articles[:8]) or _EMPTY_HTML
    faq_sec = hl.faq_html(HOME_FAQ)
    body = f"""  <main>
  <h1 class="pg-h1">{html_lib.escape(SITE['home_title'])}</h1>
  <p class="pg-sub">{html_lib.escape(SITE['website_desc'])}</p>
  <h2 class="sec-h">最新整理</h2>
{cards}
  {faq_sec}
  </main>"""
    jsonld = hl.graph_ld([hl.org_node(), hl.website_node(),
                          hl.faq_node(HOME_FAQ, f"{BASE}/")])
    return hl.page_shell(SITE["home_title"], SITE["website_desc"], f"{BASE}/",
                         jsonld, body, "home", extra_css=INDEX_CSS)


def render_articles_index(articles):
    cards = "\n".join(_idx_card(a) for a in articles) or _EMPTY_HTML
    title = "所有指標整理"
    desc = SITE["website_desc"]
    body = f"""  <main>
  <h1 class="pg-h1">{html_lib.escape(title)}</h1>
  <p class="pg-sub">{html_lib.escape(desc)}</p>
{cards}
  </main>"""
    jsonld = hl.graph_ld([
        hl.org_node(), hl.website_node(),
        hl.breadcrumb_node([("首頁", f"{BASE}/"), (title, f"{BASE}/articles/")])])
    return hl.page_shell(title, desc, f"{BASE}/articles/", jsonld, body, "indicators",
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
    art_lines = "\n".join(
        f"- [{a['meta'].get('title', a['slug'])}]({BASE}/articles/{a['slug']}/)"
        + (f"（{a['meta']['date']}）" if a["meta"].get("date") else "")
        for a in articles[:10]) or "- （尚未發布內容頁）"
    return f"""# 健檢數據誌（health.twtools.cc）— 健康檢查指標判準整理

> {SITE['website_desc']}。整理健康檢查報告上常見指標的判準值，並列不同機構的數字，每一列標註機構、文件名稱、版本與頁碼，引句可回查原始文件。內容以繁體中文撰寫，面向台灣讀者。

本站為獨立經營的資訊站，與各判準發布機構均無關聯或授權關係。內容僅供資訊參考，不構成醫療建議、診斷或治療指示。

## 重點頁面

- [首頁]({BASE}/)：站台說明與最新整理。
- [指標索引]({BASE}/indicators/)：各項指標的判準並列頁（陸續上線）。
- [所有整理]({BASE}/articles/)：長文與判準沿革。

## 最新內容

{art_lines}

## 引用說明

- 本站每一個判準值都綁定「機構＋文件＋版本＋頁碼」四項；四項不齊備的數字不會出現在頁面上。
- 引用時請一併帶上本站標註的原始文件出處，並以該機構的最新版本為準。
- 判準有版本沿革時，本站保留舊版並標明變更年份與依據文件，不覆寫歷史。
"""


# ---------- main build ----------

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
    (PUB / "index.html").write_text(render_home(articles), encoding="utf-8")
    (PUB / "articles").mkdir(parents=True, exist_ok=True)
    (PUB / "articles" / "index.html").write_text(render_articles_index(articles), encoding="utf-8")
    (PUB / "feed.xml").write_text(render_feed(articles), encoding="utf-8")
    (PUB / "llms.txt").write_text(render_llms_txt(articles), encoding="utf-8")
    (PUB / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")

    urls = ([f"{BASE}/", f"{BASE}/articles/"]
            + [f"{BASE}/articles/{a['slug']}/" for a in articles])
    hl.write_sitemap_part("articles", urls)
    print(f"🏠 index + articles index + feed + llms.txt + robots.txt + sitemap part "
          f"({len(articles)} 篇) → {PUB}/")


if __name__ == "__main__":
    build()
