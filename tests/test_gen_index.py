#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""/indicators/ 索引頁生成器的 gate（scripts/gen-indicators-index.py）。

索引頁的失敗模式和指標頁不一樣：它上面沒有判準值，只有**跨頁的計數**，而計數錯了
畫面上看起來完全正常。所以這裡守的是：

1. 卡片＝來源檔的鏡子：一張卡對一篇 md，順序是 slug 序，不多不少。
2. 「判準 N 列」必須等於那一頁判準表的實際列數——用真的生成出來的指標頁 HTML 反查，
   不是拿同一段程式碼自己驗自己（那只證明兩邊都用了同一個 bug）。
3. 缺判準檔＝中止，不生成半頁（一張卡＝宣稱那個頁面存在且有資料）。
4. dormant 雙向：published 兩個值都要驗；接線是讀 gen-indicator.py 寫的 part／
   llms 區塊再改寫回，所以測試照真實跑序先跑它再跑索引。
5. 決定性：同輸入兩次 byte-identical；接線重跑不重複插入。
"""
import importlib.util
import json
import pathlib
import re
import shutil
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


idx = _load("gen_indicators_index", "scripts/gen-indicators-index.py")
gen = idx.gen                      # 索引頁與指標頁必須吃同一份過濾規則與同一份 healthlib
terms = _load("check_health_terms", "scripts/check-health-terms.py")

SRC_DIR = ROOT / "articles" / "indicators"
CRITERIA_DIR = ROOT / "data" / "criteria"
LLMS_SEED = "# 健檢數據誌\n\n## 引用說明\n\n- 一行。\n"


def build_into(tmp: pathlib.Path, published: bool):
    """照真實跑序：gen-indicator.py 先寫 part／llms 區塊，索引再讀它改寫回。

    全部落在暫存目錄，不動 repo 的 data/sitemap-parts 與 public-health/indicators。
    """
    out = tmp / "public-health"
    parts = tmp / "sitemap-parts"
    llms = out / "llms.txt"
    out.mkdir(parents=True, exist_ok=True)
    llms.write_text(LLMS_SEED, encoding="utf-8")
    gen.build(out_root=out, parts_dir=parts, llms_path=llms, published=published)
    html = idx.build(out_root=out, parts_dir=parts, llms_path=llms, published=published)
    return html, out, parts, llms


def article_slugs() -> list:
    return sorted(p.stem for p in SRC_DIR.glob("*.md"))


def criteria_table_row_count(page_html: str) -> int:
    """指標頁上第②段判準表的實際資料列數。

    ☠️ 認的是表頭語意（判準表才有「判準值」欄），不是「第幾張表」也不是外面包了
    什麼容器：判準表可能被拆成多張（依類別分組摺疊），沿革表與失真卡表用的是同一個
    .std-table class。位置式的抓法會在版面一改就靜默少算，而少算不會讓畫面壞掉。
    """
    n = 0
    for table in re.findall(r'<table class="std-table">.*?</table>', page_html, re.S):
        if "<th>判準值</th>" not in table:
            continue
        n += len([tr for tr in re.findall(r"<tr>(.*?)</tr>", table, re.S) if "<td>" in tr])
    return n


def card_hrefs(page_html: str) -> list:
    return re.findall(r'<li class="ix-card"><h2 class="ix-h"><a href="([^"]+)"', page_html)


def llms_block(text: str) -> list:
    """llms.txt 的「## 指標頁」區塊裡的連結行（沒有這個區塊＝空 list）。"""
    marker = f"\n{idx.LLMS_HEAD}\n"
    if marker not in text:
        return []
    _, _, tail = text.partition(marker)
    nxt = tail.find("\n## ")
    block = tail[:nxt] if nxt >= 0 else tail
    return [l for l in block.split("\n") if l.startswith("- ")]


class CardsMirrorTheSourceCorpus(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.html, self.out, *_ = build_into(self.tmp, published=False)
        self.cards = idx.collect_cards()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_one_card_per_article_md(self):
        slugs = article_slugs()
        self.assertGreater(len(slugs), 0)
        self.assertEqual(len(slugs), len(self.cards))
        self.assertEqual(len(slugs), self.html.count('<li class="ix-card">'))

    def test_cards_are_ordered_by_slug(self):
        self.assertEqual(article_slugs(), [c["slug"] for c in self.cards])
        self.assertEqual([f"/indicators/{s}/" for s in article_slugs()],
                         card_hrefs(self.html))

    def test_row_count_on_each_card_equals_that_pages_criteria_table(self):
        """☠️ 這條要拿生成出來的指標頁反查，不能兩邊都用同一段過濾自證。"""
        for c in self.cards:
            with self.subTest(slug=c["slug"]):
                page = (self.out / "indicators" / c["slug"] / "index.html").read_text(
                    encoding="utf-8")
                self.assertEqual(criteria_table_row_count(page), c["n_rows"])
                self.assertIn(f"判準 {c['n_rows']} 列", self.html)

    def test_the_row_counter_itself_reacts_to_a_missing_row(self):
        """陰性對照：上一條若靠一個常數也會綠。刪掉一列，計數器必須跟著少一。"""
        page = (self.out / "indicators" / self.cards[0]["slug"] / "index.html").read_text(
            encoding="utf-8")
        before = criteria_table_row_count(page)
        one_row = re.search(r"<tr><td>.*?</tr>", page, re.S).group(0)
        self.assertEqual(before - 1, criteria_table_row_count(page.replace(one_row, "", 1)))

    def test_org_and_source_counts_come_from_the_same_rows(self):
        for c in self.cards:
            with self.subTest(slug=c["slug"]):
                meta, h1, _ = gen.parse_article(SRC_DIR / f"{c['slug']}.md")
                ids, _ = gen.page_indicators(meta, c["slug"])
                rows = [r for r in gen.load_json(CRITERIA_DIR / f"{c['slug']}.json")
                        if r["indicator_id"] in ids
                        and r["category"] in gen.TABLE_CATEGORIES]
                self.assertEqual(len({r["org"] for r in rows}), c["n_orgs"])
                self.assertEqual(len(meta["sources"]), c["n_sources"])
                self.assertIn(f"機構 {c['n_orgs']} 家・來源 {c['n_sources']} 份", self.html)

    def test_latest_history_year_ignores_unverified_rows(self):
        for c in self.cards:
            hp = CRITERIA_DIR / f"{c['slug']}-history.json"
            if not hp.exists():
                continue
            rows = json.loads(hp.read_text(encoding="utf-8"))
            years = [r["year"] for r in rows if r.get("status") != "未證實"]
            with self.subTest(slug=c["slug"]):
                self.assertEqual(max(years), c["last_year"])
                self.assertIn(f"沿革最近一次：{c['last_year']}", self.html)
                for r in rows:
                    if r.get("status") == "未證實" and r["year"] > max(years):
                        self.fail("未證實的列的年份被算進最近一次")

    def test_labels_come_from_frontmatter_for_multi_indicator_pages(self):
        multi = next(c for c in self.cards if len(c["labels"]) > 1)
        meta, _, _ = gen.parse_article(SRC_DIR / f"{multi['slug']}.md")
        ids, labels = gen.page_indicators(meta, multi["slug"])
        self.assertEqual([labels[i] for i in ids], multi["labels"])

    def test_single_indicator_card_uses_its_page_title_as_the_label(self):
        single = next(c for c in self.cards if len(c["labels"]) == 1)
        self.assertEqual([single["title"]], single["labels"])

    def test_description_comes_from_the_first_section_first_paragraph(self):
        for c in self.cards:
            _, _, sections = gen.parse_article(SRC_DIR / f"{c['slug']}.md")
            with self.subTest(slug=c["slug"]):
                self.assertTrue(sections[0][1][0].startswith(c["desc"][:60]))

    def test_every_card_links_to_a_page_that_was_actually_generated(self):
        for c in self.cards:
            with self.subTest(slug=c["slug"]):
                self.assertTrue(
                    (self.out / "indicators" / c["slug"] / "index.html").exists())


class MissingDataAborts(unittest.TestCase):
    """一張卡＝宣稱那一頁存在且有資料。資料不在就中止，不生成半頁索引。"""

    def _corpus(self, tmp: pathlib.Path, with_criteria: bool, with_history: bool = True):
        src, crit = tmp / "articles", tmp / "criteria"
        src.mkdir(parents=True, exist_ok=True)
        crit.mkdir(parents=True, exist_ok=True)
        shutil.copy(SRC_DIR / "hba1c.md", src / "hba1c.md")
        if with_criteria:
            shutil.copy(CRITERIA_DIR / "hba1c.json", crit / "hba1c.json")
        if with_history:
            shutil.copy(CRITERIA_DIR / "hba1c-history.json", crit / "hba1c-history.json")
        return src, crit

    def _build(self, tmp, src, crit):
        out = tmp / "public-health"
        out.mkdir(parents=True, exist_ok=True)
        return idx.build(out_root=out, parts_dir=tmp / "parts",
                         llms_path=out / "llms.txt", published=False,
                         src_dir=src, criteria_dir=crit)

    def test_missing_criteria_file_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            src, crit = self._corpus(tmp, with_criteria=False)
            with self.assertRaises(SystemExit):
                self._build(tmp, src, crit)
            self.assertFalse((tmp / "public-health" / "indicators" / "index.html").exists(),
                             "中止時不得留下一份半頁索引")

    def test_criteria_file_present_does_not_abort(self):
        """陽性對照：補回判準檔就要過，否則上面那條可能是別的原因紅的。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            src, crit = self._corpus(tmp, with_criteria=True)
            self.assertIn("/indicators/hba1c/", self._build(tmp, src, crit))

    def test_no_history_file_means_no_history_line(self):
        """沒有沿革資料就不顯示這一行，不寫「無」也不補 0。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            src, crit = self._corpus(tmp, with_criteria=True, with_history=False)
            html = self._build(tmp, src, crit)
            self.assertNotIn("沿革最近一次", html)
            self.assertIn("判準 ", html)

    def test_criteria_file_with_no_renderable_row_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            src, crit = self._corpus(tmp, with_criteria=True)
            rows = json.loads((crit / "hba1c.json").read_text(encoding="utf-8"))
            for r in rows:
                r["category"] = "method_requirement"
            (crit / "hba1c.json").write_text(
                json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(SystemExit):
                self._build(tmp, src, crit)


class DormantWiring(unittest.TestCase):
    def test_dormant_writes_no_part_no_llms_entry_and_does_not_link_the_nav(self):
        with tempfile.TemporaryDirectory() as d:
            html, out, parts, llms = build_into(pathlib.Path(d), published=False)
            self.assertTrue((out / "indicators" / "index.html").exists(),
                            "dormant 仍要生成索引頁（要能審），只是不接線")
            self.assertFalse((parts / "indicators.txt").exists())
            self.assertEqual([], llms_block(llms.read_text(encoding="utf-8")))
            self.assertNotIn(idx.INDEX_URL, llms.read_text(encoding="utf-8"))
            self.assertNotIn('<a href="/indicators/"', html)

    def test_published_puts_the_index_url_first_in_the_part(self):
        with tempfile.TemporaryDirectory() as d:
            html, out, parts, llms = build_into(pathlib.Path(d), published=True)
            urls = (parts / "indicators.txt").read_text(
                encoding="utf-8").splitlines()
            self.assertEqual(idx.INDEX_URL, urls[0])
            self.assertEqual(1, urls.count(idx.INDEX_URL))
            for slug in article_slugs():
                self.assertIn(f"https://health.twtools.cc/indicators/{slug}/", urls,
                              "索引 URL 不得擠掉 gen-indicator.py 寫的指標頁 URL")
            self.assertIn('<a href="/indicators/"', html)

    def test_published_links_the_index_first_in_the_llms_block(self):
        with tempfile.TemporaryDirectory() as d:
            _, out, parts, llms = build_into(pathlib.Path(d), published=True)
            bullets = llms_block(llms.read_text(encoding="utf-8"))
            self.assertEqual(idx.LLMS_LINE, bullets[0])
            # 索引頁在第一行、勘誤頁（M5 棒 C）在最後一行：指標頁數＋2
            self.assertEqual(len(article_slugs()) + 2, len(bullets))

    def test_rerunning_the_wiring_does_not_duplicate_anything(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            _, out, parts, llms = build_into(tmp, published=True)
            part_once = (parts / "indicators.txt").read_text(encoding="utf-8")
            llms_once = llms.read_text(encoding="utf-8")
            idx.build(out_root=out, parts_dir=parts, llms_path=llms, published=True)
            idx.build(out_root=out, parts_dir=parts, llms_path=llms, published=True)
            self.assertEqual(part_once, (parts / "indicators.txt").read_text(encoding="utf-8"))
            self.assertEqual(llms_once, llms.read_text(encoding="utf-8"))

    def test_flipping_back_to_dormant_leaves_no_index_url_behind(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            _, out, parts, llms = build_into(tmp, published=True)
            gen.build(out_root=out, parts_dir=parts, llms_path=llms, published=False)
            idx.build(out_root=out, parts_dir=parts, llms_path=llms, published=False)
            self.assertFalse((parts / "indicators.txt").exists())
            self.assertNotIn(idx.INDEX_URL, llms.read_text(encoding="utf-8"))

    def test_published_but_no_part_file_does_not_invent_one(self):
        """跑序被打破時不自己造 part：那會生出「有索引、沒有指標頁」的 sitemap。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            out, parts = tmp / "public-health", tmp / "parts"
            out.mkdir(parents=True)
            parts.mkdir(parents=True)
            (out / "llms.txt").write_text(LLMS_SEED, encoding="utf-8")
            idx.build(out_root=out, parts_dir=parts, llms_path=out / "llms.txt",
                      published=True)
            self.assertFalse((parts / "indicators.txt").exists())


class DeterministicOutput(unittest.TestCase):
    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            h1, *_ = build_into(pathlib.Path(a), published=False)
            h2, *_ = build_into(pathlib.Path(b), published=False)
            self.assertEqual(h1, h2, "同輸入兩次產出不同 bytes（混進時間戳／集合迭代？）")

    def test_published_and_dormant_differ_only_in_the_wiring_entrances(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            dormant, *_ = build_into(pathlib.Path(a), published=False)
            live, *_ = build_into(pathlib.Path(b), published=True)

            def strip(s):
                s = re.sub(r'<a href="/(?:indicators|errata)/"[^>]*>.*?</a>', "", s)
                return "\n".join(l for l in s.splitlines() if l.strip())
            self.assertEqual(strip(dormant), strip(live))


class GeneratedPagePassesGates(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.html, self.out, *_ = build_into(self.tmp, published=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banned_terms_gate_is_clean_on_the_generated_html(self):
        rules = terms.load_rules()
        page = self.out / "indicators" / "index.html"
        hits = [h for h in terms.scan(terms.extract_text(page), rules)
                if h["level"] == "absolute" and not h["exempt"]]
        self.assertEqual([], hits, f"生成後的 HTML 命中絕對禁詞：{hits}")

    def test_jsonld_has_collectionpage_and_a_matching_itemlist(self):
        graph = json.loads(re.findall(
            r'<script type="application/ld\+json">(.*?)</script>',
            self.html, re.S)[0])["@graph"]
        page = next(n for n in graph if n["@type"] == "CollectionPage")
        self.assertEqual(f"{idx.INDEX_URL}#page", page["@id"])
        self.assertTrue(page["isAccessibleForFree"])
        self.assertEqual("zh-Hant", page["inLanguage"])
        self.assertEqual({"@id": "https://health.twtools.cc/#org"}, page["publisher"])

        items = next(n for n in graph if n["@type"] == "ItemList")["itemListElement"]
        self.assertEqual(list(range(1, len(article_slugs()) + 1)),
                         [i["position"] for i in items])
        self.assertEqual([f"https://health.twtools.cc/indicators/{s}/"
                          for s in article_slugs()], [i["url"] for i in items])

    def test_breadcrumb_is_home_then_indicators(self):
        graph = json.loads(re.findall(
            r'<script type="application/ld\+json">(.*?)</script>',
            self.html, re.S)[0])["@graph"]
        crumbs = next(n for n in graph if n["@type"] == "BreadcrumbList")["itemListElement"]
        self.assertEqual(["首頁", "指標"], [c["name"] for c in crumbs])
        self.assertEqual(idx.INDEX_URL, crumbs[-1]["item"])

    def test_jsonld_carries_no_rating(self):
        raw = re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                         self.html, re.S)[0]
        for banned in ("aggregateRating", "ratingValue", "reviewRating", "Review"):
            self.assertNotIn(banned, raw, "JSON-LD 不放任何評分：本站不評價文件")

    def test_head_has_canonical_and_og(self):
        self.assertIn(f'<link rel="canonical" href="{idx.INDEX_URL}">', self.html)
        self.assertIn(f'<meta property="og:url" content="{idx.INDEX_URL}">', self.html)
        self.assertIn('<meta property="og:title"', self.html)

    def test_footer_states_the_site_gives_no_diagnosis(self):
        self.assertIn(gen.FOOT_LINE, self.html)

    def test_no_external_script_beyond_the_site_shell(self):
        srcs = re.findall(r'<script[^>]*\ssrc="([^"]+)"', self.html)
        self.assertEqual([], [s for s in srcs if "googletagmanager" not in s])

    def test_intro_is_short_enough_to_read_at_a_glance(self):
        self.assertLessEqual(len(idx.INTRO), 80)
        self.assertIn(idx.INTRO, self.html)


if __name__ == "__main__":
    unittest.main()
