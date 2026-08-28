#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指標頁生成器的 gate（scripts/gen-indicator.py）。

守的是「壞了不會在畫面上立刻看見」的那幾種：

1. 決定性：同輸入連跑兩次，產物 byte-identical（禁時間戳；重構驗收靠這條）。
2. 反向比對：HTML 判準表裡出現的每一個數字，都要在 data/criteria 的同一列找得回去。
   ☠️ 這條要配陰性對照一起跑——只驗「真資料會過」證明不了 gate 有作用，
   所以同一支檢查器也拿被竄改的數字跑一次，必須紅。
3. 雙源即斷：md 正文再寫一份手寫表格 → 生成器中止（資料改了頁面不會叫的典型病灶）。
4. dormant 雙向：published 兩個值都要驗。翻開關前後只有接線差別，頁面本身不變。
5. 禁詞 gate 對生成後的 HTML 為 FAIL 0（掃的是產物，不是原稿）。
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


gen = _load("gen_indicator", "scripts/gen-indicator.py")
terms = _load("check_health_terms", "scripts/check-health-terms.py")

SLUG = "hba1c"
ARTICLE = ROOT / "articles" / "indicators" / f"{SLUG}.md"
CRITERIA = ROOT / "data" / "criteria" / f"{SLUG}.json"

_NUM = re.compile(r"\d+(?:\.\d+)?")


def build_into(tmp: pathlib.Path, published: bool):
    """把整頁生成到暫存目錄，回傳 (html, pages, tmp)。不動 repo 內的產物。"""
    out = tmp / "public-health"
    parts = tmp / "sitemap-parts"
    llms = out / "llms.txt"
    out.mkdir(parents=True, exist_ok=True)
    llms.write_text("# 健檢數據誌\n\n## 引用說明\n\n- 一行。\n", encoding="utf-8")
    pages = gen.build(out_root=out, parts_dir=parts, llms_path=llms, published=published)
    html = (out / "indicators" / SLUG / "index.html").read_text(encoding="utf-8")
    return html, pages, out, parts, llms


def expected_group_order(rows: list, ids: list):
    """把資料列排成「頁面上應該長的組序」：多指標＝先 indicator 再 category。

    ☠️ 這裡故意不呼叫 gen.group_criteria_rows()：測試要有自己獨立的一份順序，
    借生成器的分組來當期望值，分組排錯時兩邊會一起錯（假綠）。
    """
    order = ids if len(ids) > 1 else [None]
    out = []
    for iid in order:
        for cat in gen.TABLE_CATEGORIES:
            out += [r for r in rows if r["category"] == cat
                    and (iid is None or r["indicator_id"] == iid)]
    return out


def criteria_rows():
    rows = [r for r in json.loads(CRITERIA.read_text(encoding="utf-8"))
            if r["indicator_id"] == SLUG and r["category"] in gen.TABLE_CATEGORIES]
    return expected_group_order(rows, [SLUG])


def crit_groups(html: str):
    """回傳判準表的每一組：[(summary 純文字, 有沒有 open, [資料列…])]。"""
    import html as html_lib

    def text(s):
        return html_lib.unescape(re.sub(r"<[^>]+>", "", s))

    out = []
    for attrs, block in re.findall(r'<details class="crit-grp"([^>]*)>(.*?)</details>',
                                   html, re.S):
        summary = text(re.search(r"<summary>(.*?)</summary>", block, re.S).group(1))
        cells = []
        for tr in re.findall(r"<tr>(.*?)</tr>", block, re.S):
            tds = re.findall(r"<td>(.*?)</td>", tr, re.S)
            if tds:
                cells.append([text(c) for c in tds])
        out.append((summary, "open" in attrs, cells))
    return out


def table_cells(html: str):
    """回傳判準表的資料列（每列＝各欄純文字），依組在頁面上出現的順序串起來。"""
    return [row for _, _, cells in crit_groups(html) for row in cells]


def unbacked_numbers(cell: str, row: dict) -> list:
    """回傳這個儲存格裡「在該資料列找不到出處」的數字。空 list＝全部有據。

    允許的來源只有三個欄位：lower、upper、unit（單位字串本身帶的數字，
    例如「%（48 mmol/mol）」）。分類標籤不含數字，所以任何多出來的數字
    都代表頁面上有一個資料層沒有的數字。
    """
    allowed = {gen.num(row[k]) for k in ("lower", "upper") if row.get(k) is not None}
    allowed |= set(_NUM.findall(row.get("unit") or ""))
    return [n for n in _NUM.findall(cell) if n not in allowed]


class DeterministicOutput(unittest.TestCase):
    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            h1, *_ = build_into(pathlib.Path(a), published=False)
            h2, *_ = build_into(pathlib.Path(b), published=False)
            self.assertEqual(h1, h2, "同輸入兩次產出不同 bytes（是不是混進時間戳／集合迭代？）")

    def test_published_page_body_is_identical_to_dormant(self):
        """翻開關只改接線，不改頁面內容——唯一容許的差是導覽與麵包屑的入口。"""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            dormant, *_ = build_into(pathlib.Path(a), published=False)
            live, *_ = build_into(pathlib.Path(b), published=True)
            def strip(s):
                # 拿掉 published 才有的入口（導覽、頁尾、麵包屑的 item），
                # 再把因此空掉的行收乾淨；剩下的必須逐字相同。
                # /errata/ 是 M5 加的頁尾連結，與 /indicators/ 同樣帶 requires:published。
                s = re.sub(r'<a href="/(?:indicators|errata)/"[^>]*>.*?</a>', "", s)
                s = s.replace(',"item":"https://health.twtools.cc/indicators/"', "")
                return "\n".join(l for l in s.splitlines() if l.strip())
            self.assertEqual(strip(dormant), strip(live))


class NumbersTraceBackToData(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.html, *_ = build_into(self.tmp, published=False)
        self.rows = criteria_rows()
        self.cells = table_cells(self.html)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_table_has_one_row_per_criteria_row(self):
        self.assertEqual(len(self.cells), len(self.rows))
        self.assertGreater(len(self.rows), 0)

    def test_every_number_in_the_table_is_backed_by_its_data_row(self):
        for cell_row, data_row in zip(self.cells, self.rows):
            with self.subTest(org=data_row["org"], cat=data_row["category"]):
                self.assertEqual([], unbacked_numbers(cell_row[1], data_row),
                                 f"判準值欄有資料層沒有的數字：{cell_row[1]}")

    def test_checker_catches_a_fabricated_number(self):
        """陰性對照：檢查器對被竄改的數字必須紅，否則上面那條是假綠。"""
        row = next(r for r in self.rows if r.get("lower") is not None)
        self.assertNotEqual([], unbacked_numbers("糖尿病診斷：≥6.7%", row))

    def test_summary_line_counts_match_the_data(self):
        """表前那行「共 N 列，分 K 組」的兩個數字都由資料算，不是寫死的。"""
        self.assertIn(
            f'<p class="crit-sum">共 {len(self.rows)} 列，'
            f"分 {len(crit_groups(self.html))} 組；", self.html)

    def test_population_and_source_columns_come_from_data(self):
        mf = gen.manifest_index()
        for cell_row, data_row in zip(self.cells, self.rows):
            self.assertEqual(data_row["population"], cell_row[2])
            self.assertIn(mf[data_row["doc_id"]]["title"], cell_row[3])
            self.assertIn(data_row["page_or_table"], cell_row[3])

    def test_screening_threshold_is_not_rendered_as_diagnosis(self):
        """5.9% 是轉介做 OGTT 的門檻。頁面上把它寫成診斷線是這頁最貴的錯。"""
        for cell_row, data_row in zip(self.cells, self.rows):
            if data_row["category"] == "screening_triage":
                self.assertIn("篩檢分流", cell_row[1])
                self.assertNotIn("糖尿病診斷", cell_row[1])

    def test_chart_rows_without_bounds_are_declared_not_dropped(self):
        """畫不出來的列要在圖下說有幾列只在表上，不能靜默消失。"""
        n = len([r for r in self.rows
                 if r.get("lower") is None and r.get("upper") is None
                 and r["category"] != "no_criterion_stated"])
        if n:
            self.assertIn(f"另有 {n} 列", self.html)


class DoubleSourceIsRejected(unittest.TestCase):
    def test_handwritten_table_in_md_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            bad = pathlib.Path(d) / "bad.md"
            text = ARTICLE.read_text(encoding="utf-8")
            text = text.replace("同一個數字，不同機構的門檻不一樣，以下並列，不選邊。",
                                "同一個數字，不同機構的門檻不一樣，以下並列，不選邊。\n\n"
                                "| 機構 | 判準值 |\n|---|---|\n| ADA | ≥6.5% |")
            bad.write_text(text, encoding="utf-8")
            with self.assertRaises(SystemExit):
                gen.parse_article(bad)

    def test_clean_md_parses(self):
        meta, h1, sections = gen.parse_article(ARTICLE)
        self.assertEqual(len(sections), gen.SECTION_COUNT)
        self.assertEqual(meta["indicator_id"], SLUG)
        self.assertTrue(meta["sources"])

    def test_section_count_is_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            bad = pathlib.Path(d) / "bad.md"
            bad.write_text(ARTICLE.read_text(encoding="utf-8") + "\n\n## 第七段\n\n多的。\n",
                           encoding="utf-8")
            with self.assertRaises(SystemExit):
                gen.parse_article(bad)


class DormantWiring(unittest.TestCase):
    def test_dormant_writes_no_sitemap_part_and_no_llms_entry(self):
        with tempfile.TemporaryDirectory() as d:
            html, pages, out, parts, llms = build_into(pathlib.Path(d), published=False)
            self.assertTrue((out / "indicators" / SLUG / "index.html").exists(),
                            "dormant 仍要生成頁面（要能審），只是不接線")
            self.assertFalse((parts / "indicators.txt").exists())
            self.assertNotIn("/indicators/", llms.read_text(encoding="utf-8"))
            self.assertNotIn('<a href="/indicators/"', html)

    def test_published_writes_sitemap_part_and_llms_entry(self):
        with tempfile.TemporaryDirectory() as d:
            html, pages, out, parts, llms = build_into(pathlib.Path(d), published=True)
            self.assertIn(f"https://health.twtools.cc/indicators/{SLUG}/\n",
                          (parts / "indicators.txt").read_text(encoding="utf-8"))
            self.assertIn(f"/indicators/{SLUG}/", llms.read_text(encoding="utf-8"))
            self.assertIn('<a href="/indicators/"', html)

    def test_flipping_back_to_dormant_cleans_the_wiring(self):
        """翻回 false 要把 part 與 llms 區塊收乾淨，不留指向未公開頁的 URL。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            _, _, out, parts, llms = build_into(tmp, published=True)
            gen.build(out_root=out, parts_dir=parts, llms_path=llms, published=False)
            self.assertFalse((parts / "indicators.txt").exists())
            self.assertNotIn("/indicators/", llms.read_text(encoding="utf-8"))

    def test_llms_wiring_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            _, _, out, parts, llms = build_into(tmp, published=True)
            once = llms.read_text(encoding="utf-8")
            gen.build(out_root=out, parts_dir=parts, llms_path=llms, published=True)
            self.assertEqual(once, llms.read_text(encoding="utf-8"))


class GeneratedPagePassesGates(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.html, *_ = build_into(self.tmp, published=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_banned_terms_gate_is_clean_on_the_generated_html(self):
        rules = terms.load_rules()
        page = self.tmp / "public-health" / "indicators" / SLUG / "index.html"
        hits = [h for h in terms.scan(terms.extract_text(page), rules)
                if h["level"] == "absolute" and not h["exempt"]]
        self.assertEqual([], hits, f"生成後的 HTML 命中絕對禁詞：{hits}")

    def test_jsonld_has_no_rating_and_is_free_to_read(self):
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                            self.html, re.S)
        self.assertTrue(blocks)
        graph = json.loads(blocks[0])["@graph"]
        page = next(n for n in graph if n["@type"] == "MedicalWebPage")
        self.assertTrue(page["isAccessibleForFree"])
        raw = blocks[0]
        for banned in ("aggregateRating", "ratingValue", "reviewRating", "Review"):
            self.assertNotIn(banned, raw, "JSON-LD 不放任何評分：本站不評價文件")

    def test_page_head_has_canonical_and_og(self):
        url = f"https://health.twtools.cc/indicators/{SLUG}/"
        self.assertIn(f'<link rel="canonical" href="{url}">', self.html)
        self.assertIn(f'<meta property="og:url" content="{url}">', self.html)
        self.assertIn('<meta property="og:title"', self.html)

    def test_footer_states_the_site_gives_no_diagnosis(self):
        self.assertIn("本站不提供診斷或治療建議", self.html)

    def test_no_external_script_or_stylesheet_beyond_site_shell(self):
        """圖表不得載外部函式庫：SVG 是 inline 的，頁面上不該多出第三方 script。"""
        srcs = re.findall(r'<script[^>]*\ssrc="([^"]+)"', self.html)
        self.assertEqual([], [s for s in srcs if "googletagmanager" not in s])

    def test_every_direction_bucket_is_rendered_or_absent_by_data(self):
        data = json.loads((ROOT / "data" / "criteria"
                           / f"{SLUG}-interference.json").read_text(encoding="utf-8"))
        present = {r["direction"] for r in data}
        for d in gen.DIRECTION_ORDER:
            label = gen.DIRECTION_LABEL[d]
            self.assertEqual(d in present, label in self.html,
                             f"direction {d} 的欄位有無與資料不符（不得猜方向、也不得漏欄）")

    def test_unverified_history_rows_are_not_rendered(self):
        hist = json.loads((ROOT / "data" / "criteria"
                           / f"{SLUG}-history.json").read_text(encoding="utf-8"))
        for r in hist:
            if r.get("status") == "未證實":
                self.assertNotIn(r["change"], self.html)
            else:
                self.assertIn(r["id"], self.html)


class ValueComposition(unittest.TestCase):
    """判準值組字：只吃 lower／upper／unit／inclusive，不吃正文。"""

    def test_open_ended_lower_bound(self):
        self.assertEqual(
            "≥6.5%（NGSP）",
            gen.value_text({"lower": 6.5, "upper": None, "lower_inclusive": True,
                            "unit": "%（NGSP）", "quote": "A1C ≥6.5%"}))

    def test_glyph_follows_the_source(self):
        """來源寫 ≧ 就渲染 ≧——全形半形不折疊，那是回查原文的指紋。"""
        self.assertEqual(
            "≧6.5%",
            gen.value_text({"lower": 6.5, "upper": None, "lower_inclusive": True,
                            "unit": "%", "quote": "糖化血色素≧6.5%"}))

    def test_closed_range(self):
        self.assertEqual(
            "5.7–6.4%",
            gen.value_text({"lower": 5.7, "upper": 6.4, "unit": "%", "quote": "5.7-6.4%"}))

    def test_exclusive_upper_keeps_the_strict_less_than(self):
        self.assertEqual(
            "≥5.9% 且 <6.5%",
            gen.value_text({"lower": 5.9, "upper": 6.5, "lower_inclusive": True,
                            "upper_inclusive": False, "unit": "%",
                            "quote": "大於等於 5.9 但小於 6.5%"}))

    def test_no_bounds_says_so_instead_of_guessing(self):
        self.assertEqual(
            gen.NO_RANGE,
            gen.value_text({"lower": None, "upper": None, "unit": None, "quote": "x"}))

    def test_non_percent_unit_keeps_a_space(self):
        self.assertEqual(
            "≥126 mg/dL",
            gen.value_text({"lower": 126, "upper": None, "lower_inclusive": True,
                            "unit": "mg/dL", "quote": "FPG ≥126 mg/dL"}))


class TextWrapping(unittest.TestCase):
    def test_wrapping_preserves_original_spacing(self):
        """SVG 斷行不得吃掉盤古之白：拼回去要與原文逐字相同（只少換行處的空白）。"""
        src = "糖尿病診斷的空腹血糖切點由 ≥140 mg/dL 下修為 ≥126 mg/dL（7.0 mmol/L）"
        for width in (12, 20, 30, 200):
            joined = " ".join(gen.wrap_cjk(src, width))
            self.assertEqual(src.replace(" ", ""), joined.replace(" ", ""))
            self.assertIn("≥140 mg/dL", " ".join(gen.wrap_cjk(src, 200)))

    def test_no_line_ends_with_an_opening_bracket(self):
        src = "採納 HbA1c 6.5% 為診斷切點，但明言證據不足以對 <6.5% 做任何正式建議（＝不設前期判準）"
        for width in (10, 15, 22, 30):
            for line in gen.wrap_cjk(src, width):
                self.assertNotIn(line[-1], "（「《")


# ---------- 一頁多指標（M4：blood-pressure／lipids／bmi-waist） ----------

# fixture 用真的 doc_id（manifest 裡有）與真的 category 白名單值，只有指標與數值是造的：
# 造一份「剛好符合生成器」的假資料，驗不到 source_ref 與 category 這兩條會炸的路。
MULTI_SLUG = "bp-fixture"
MULTI_DOC = "ada-standards-of-care-2026"

MULTI_MD = """---
title: 血壓（收縮壓／舒張壓）
indicator_ids: [sbp, dbp]
indicator_labels: {sbp: 收縮壓, dbp: 舒張壓}
slug: bp-fixture
status: draft
updated: 2026-08-28
sources: [ada-standards-of-care-2026]
---

# 血壓（收縮壓／舒張壓）

## 一段

第一段。

## 二段

第二段。

## 三段

第三段。

## 四段

第四段。

## 五段

第五段。

## 六段

第六段。
"""


def _fixture_row(iid, category, lower, upper, unit):
    return {
        "indicator_id": iid, "org": "American Diabetes Association",
        "doc_id": MULTI_DOC, "version": "2026", "category": category,
        "lower": lower, "upper": upper, "unit": unit, "population": "成人",
        "page_or_table": "Sec. 10", "quote": "fixture quote",
        "fetched_at": "2026-08-28",
    }


MULTI_ROWS = [
    _fixture_row("sbp", "classification", 130, 139, "mmHg"),
    _fixture_row("sbp", "risk_threshold", 140, None, "mmHg"),
    _fixture_row("dbp", "classification", 80, 89, "mmHg"),
    # 不在 TABLE_CATEGORIES 的列：不得進表，也不得畫上數線。
    _fixture_row("sbp", "method_requirement", None, None, None),
    # 這頁沒宣告的 indicator_id：同一個檔可以放別的指標，但不屬於這一頁。
    _fixture_row("map", "classification", 90, 99, "mmHg"),
]


def build_fixture_page(tmp: pathlib.Path, md: str, rows: list, slug: str = MULTI_SLUG):
    """把 fixture 的 md 與 criteria 餵給 build()，回傳生成的 HTML。不動 repo 內的檔。"""
    src = tmp / "articles"
    src.mkdir(parents=True, exist_ok=True)
    (src / f"{slug}.md").write_text(md, encoding="utf-8")
    crit = tmp / "criteria"
    crit.mkdir(parents=True, exist_ok=True)
    (crit / f"{slug}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    out = tmp / "public-health"
    out.mkdir(parents=True, exist_ok=True)
    llms = out / "llms.txt"
    llms.write_text("# 健檢數據誌\n\n## 引用說明\n\n- 一行。\n", encoding="utf-8")

    # 勘誤層也一起注入成空的：fixture 的 SRC_DIR 只有這一頁，repo 的 data/errata.json
    # 哪天真的多一列（slug 是別的頁），全量 build 會判定「勘誤指不到任何指標頁」而中止，
    # 這些與勘誤無關的 fixture 就會集體紅。勘誤本身有自己的測試（ErrataOnTheIndicatorPage）。
    (tmp / "errata.json").write_text("[]", encoding="utf-8")

    keep = (gen.SRC_DIR, gen.CRITERIA_DIR, gen.ERRATA_PATH)
    gen.SRC_DIR, gen.CRITERIA_DIR, gen.ERRATA_PATH = src, crit, tmp / "errata.json"
    try:
        gen.build(out_root=out, parts_dir=tmp / "parts", llms_path=llms, published=False)
    finally:
        gen.SRC_DIR, gen.CRITERIA_DIR, gen.ERRATA_PATH = keep
    return (out / "indicators" / slug / "index.html").read_text(encoding="utf-8")


class MultiIndicatorPage(unittest.TestCase):
    """一頁多指標：判準表多一欄「指標」，每個 indicator_id 各一條數線。"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.html = build_fixture_page(self.tmp, MULTI_MD, MULTI_ROWS)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_indicator_label_from_the_frontmatter_names_each_group(self):
        """M5：短標籤從「指標」欄搬到組名上（意圖不變＝短標籤只能來自 frontmatter，
        頁面上看得到每一列屬於哪個指標；改的只是它出現在哪裡）。"""
        self.assertNotIn("<th>指標</th>", self.html)
        groups = crit_groups(self.html)
        self.assertEqual(["收縮壓｜分級（1 列）", "收縮壓｜風險門檻（1 列）",
                          "舒張壓｜分級（1 列）"], [g[0] for g in groups])
        for row in table_cells(self.html):
            self.assertEqual(4, len(row), "指標搬到組名後，表回到四欄")

    def test_only_declared_indicators_and_table_categories_are_rendered(self):
        cells = table_cells(self.html)
        self.assertEqual(3, len(cells), "只收 indicator_ids 內、category 在白名單的列")
        self.assertNotIn("90–99", self.html, "未宣告的 indicator_id 不得進這一頁")

    def test_one_number_line_per_indicator_titled_by_label_and_unit(self):
        self.assertEqual(2, self.html.count('<figure class="chart">'))
        self.assertIn('<figcaption class="ct">收縮壓（mmHg）</figcaption>', self.html)
        self.assertIn('<figcaption class="ct">舒張壓（mmHg）</figcaption>', self.html)

    def test_axis_is_derived_per_indicator_when_not_named_in_AXIS(self):
        """AXIS 沒列名的指標由該指標自己的 min／max 推導，不借用別的指標的視窗。"""
        saved = {k: gen.AXIS.pop(k) for k in ("sbp", "dbp") if k in gen.AXIS}
        try:
            with tempfile.TemporaryDirectory() as d:
                html = build_fixture_page(pathlib.Path(d), MULTI_MD, MULTI_ROWS)
        finally:
            gen.AXIS.update(saved)
        self.assertIn("130", html)
        self.assertIn("80", html)

    def test_legend_category_text_comes_from_data_not_a_hardcoded_string(self):
        """血壓頁不得出現「糖尿病前期」：圖例的類別字是從這頁的資料推導出來的。"""
        self.assertIn("淡色帶＝分級／風險門檻", self.html)
        self.assertIn("淡色帶＝分級<", self.html)
        self.assertNotIn("糖尿病", self.html)

    def test_new_categories_render_with_their_own_labels(self):
        self.assertIn("分級：130–139 mmHg", self.html)
        self.assertIn("風險門檻：≥140 mmHg", self.html)

    def test_data_files_are_located_by_slug_not_indicator_id(self):
        self.assertIn(f"data/criteria/{MULTI_SLUG}.json", self.html)

    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                self.html, build_fixture_page(pathlib.Path(d), MULTI_MD, MULTI_ROWS))


class MissingIndicatorLabelsAborts(unittest.TestCase):
    """短標籤缺一個就中止：生成器不從 indicator_id 造中文，也不從單位猜。"""

    def _build(self, md, rows=None):
        with tempfile.TemporaryDirectory() as d:
            return build_fixture_page(pathlib.Path(d), md, rows or MULTI_ROWS)

    def test_no_indicator_labels_at_all_aborts(self):
        md = MULTI_MD.replace("indicator_labels: {sbp: 收縮壓, dbp: 舒張壓}\n", "")
        with self.assertRaises(SystemExit):
            self._build(md)

    def test_partial_indicator_labels_abort(self):
        md = MULTI_MD.replace("{sbp: 收縮壓, dbp: 舒張壓}", "{sbp: 收縮壓}")
        with self.assertRaises(SystemExit):
            self._build(md)

    def test_declared_indicator_without_any_criteria_row_aborts(self):
        """宣告了卻沒有資料列＝頁面在宣稱一個空指標，中止而不是靜默少畫一條數線。"""
        with self.assertRaises(SystemExit):
            self._build(MULTI_MD,
                        [r for r in MULTI_ROWS if r["indicator_id"] != "dbp"])

    def test_complete_labels_do_not_abort(self):
        """陽性對照：補齊就要過，否則上面三條可能是別的原因紅的。"""
        self.assertIn("<summary>收縮壓｜", self._build(MULTI_MD))


class SingleIndicatorPageKeepsItsShape(unittest.TestCase):
    """hba1c 是單指標頁：不加「指標」欄、只有一條數線、標題走 frontmatter。"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.html, *_ = build_into(self.tmp, published=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_indicator_column(self):
        self.assertNotIn("<th>指標</th>", self.html)
        for row in table_cells(self.html):
            self.assertEqual(4, len(row), "單指標頁的判準表維持四欄")

    def test_exactly_one_number_line(self):
        meta, _, _ = gen.parse_article(ARTICLE)
        self.assertEqual([SLUG], gen.page_indicators(meta, SLUG)[0])
        self.assertEqual(1, self.html.count(f"data/criteria/{SLUG}.json"))

    def test_chart_caption_comes_from_frontmatter(self):
        meta, _, _ = gen.parse_article(ARTICLE)
        self.assertIn(
            f'<figcaption class="ct">{meta["criteria_chart_caption"]}</figcaption>',
            self.html)

    def test_missing_caption_aborts_instead_of_rendering_an_empty_title(self):
        md = ARTICLE.read_text(encoding="utf-8")
        md = re.sub(r"(?m)^criteria_chart_caption:.*\n", "", md)
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            (tmp / "criteria").mkdir(parents=True)
            shutil.copy(CRITERIA, tmp / "criteria" / f"{SLUG}.json")
            with self.assertRaises(SystemExit):
                build_fixture_page(tmp, md, json.loads(
                    CRITERIA.read_text(encoding="utf-8")), slug=SLUG)


class FrontmatterIndicatorFields(unittest.TestCase):
    def test_plural_list_and_label_map_parse(self):
        self.assertEqual(
            (["sbp", "dbp"], {"sbp": "收縮壓", "dbp": "舒張壓"}),
            gen.page_indicators({"indicator_ids": "[sbp, dbp]",
                                 "indicator_labels": "{sbp: 收縮壓, dbp: 舒張壓}"}, "bp"))

    def test_singular_indicator_id_is_still_supported(self):
        self.assertEqual(["hba1c"], gen.page_indicators({"indicator_id": "hba1c"}, "x")[0])

    def test_neither_field_falls_back_to_slug(self):
        self.assertEqual(["uric-acid"], gen.page_indicators({}, "uric-acid")[0])


class OrgColourIsKeyedByFamily(unittest.TestCase):
    """配色語意＝機構屬性（tw-gov／tw-society／intl／us／other），不是逐一挑色票。"""

    EXPECTED = {
        "American Diabetes Association": ("us", "--c-ada"),
        "World Health Organization": ("intl", "--c-who"),
        "衛生福利部國民健康署": ("tw-gov", "--c-hpa"),
        "行政院衛生署國民健康局": ("tw-gov", "--c-hpa"),
        "社團法人中華民國糖尿病學會／中華民國內分泌暨糖尿病學會": ("tw-society", "--c-daroc"),
        "International Expert Committee": ("other", "--c-other"),
        "MedlinePlus（美國國家醫學圖書館 NLM，NIH 旗下）": ("other", "--c-other"),
        "National Glycohemoglobin Standardization Program": ("other", "--c-other"),
    }

    def test_every_named_org_keeps_its_family_and_colour(self):
        for org, (family, var) in self.EXPECTED.items():
            with self.subTest(org=org):
                self.assertEqual(family, gen.org_family(org))
                self.assertEqual(f"var({var})", gen.org_color(org))

    def test_every_family_in_the_roster_maps_to_a_declared_colour(self):
        for _, family in gen.ORG_DISPLAY.values():
            with self.subTest(family=family):
                self.assertIn(family, gen.ORG_FAMILY_COLOR)

    def test_unlisted_org_falls_back_to_grey_and_keeps_its_full_name(self):
        unknown = "某個還沒登記的學會"
        self.assertEqual(gen.ORG_FALLBACK_FAMILY, gen.org_family(unknown))
        self.assertEqual("var(--c-other)", gen.org_color(unknown))
        self.assertEqual(unknown, gen.org_label(unknown))


class NewTableCategories(unittest.TestCase):
    def test_classification_and_risk_threshold_are_table_categories(self):
        for c in ("classification", "risk_threshold"):
            with self.subTest(category=c):
                self.assertIn(c, gen.TABLE_CATEGORIES)
        self.assertEqual("分級", gen.CATEGORY_LABEL["classification"])
        self.assertEqual("風險門檻", gen.CATEGORY_LABEL["risk_threshold"])

    def test_every_table_category_has_a_label(self):
        for c in gen.TABLE_CATEGORIES:
            with self.subTest(category=c):
                self.assertIn(c, gen.CATEGORY_LABEL)

    def test_table_categories_are_a_subset_of_the_schema_whitelist(self):
        schema = json.loads(
            (ROOT / "data" / "criteria" / "schema.json").read_text(encoding="utf-8"))
        enum = schema["$defs"]["criterion"]["properties"]["category"]["enum"]
        for c in gen.TABLE_CATEGORIES:
            with self.subTest(category=c):
                self.assertIn(c, enum, "生成器收的類別不在 schema 白名單裡（兩邊各長各的）")


# ---------- M5：判準表分組折疊 ----------

SINGLE_MD = MULTI_MD.replace(
    "indicator_ids: [sbp, dbp]\nindicator_labels: {sbp: 收縮壓, dbp: 舒張壓}\n",
    "indicator_id: sbp\ncriteria_chart_caption: 收縮壓的各機構判準\n")

# 14 列（> CRIT_OPEN_ALL_MAX）：要驗的是「只有診斷與分級預設展開」，所以這份
# fixture 必須超過全展開的門檻，否則測到的是 ≤12 那條規則。
BIG_ROWS = [
    _fixture_row("sbp", "diagnosis", 140, None, "mmHg"),
    _fixture_row("sbp", "diagnosis", 130, None, "mmHg"),
    _fixture_row("sbp", "classification", 120, 129, "mmHg"),
    _fixture_row("sbp", "classification", 130, 139, "mmHg"),
    _fixture_row("sbp", "classification", 140, 159, "mmHg"),
    _fixture_row("sbp", "screening_triage", 135, None, "mmHg"),
    _fixture_row("sbp", "screening_triage", 125, None, "mmHg"),
    _fixture_row("sbp", "risk_threshold", 150, None, "mmHg"),
    _fixture_row("dbp", "diagnosis", 90, None, "mmHg"),
    _fixture_row("dbp", "diagnosis", 85, None, "mmHg"),
    _fixture_row("dbp", "classification", 80, 89, "mmHg"),
    _fixture_row("dbp", "screening_triage", 84, None, "mmHg"),
    _fixture_row("dbp", "risk_threshold", 95, None, "mmHg"),
    _fixture_row("dbp", "no_criterion_stated", None, None, None),
]


def _cat_of(summary: str) -> str:
    return re.sub(r"（\d+ 列）$", "", summary).rpartition("｜")[2]


class CriteriaTableGrouping(unittest.TestCase):
    """判準表改成一組一表的原生 <details>：分組鍵、組序、預設展開、沒有列被吃掉。"""

    def _build(self, md, rows):
        with tempfile.TemporaryDirectory() as d:
            return build_fixture_page(pathlib.Path(d), md, rows)

    def setUp(self):
        self.html = self._build(MULTI_MD, BIG_ROWS)
        self.groups = crit_groups(self.html)

    def test_one_group_per_indicator_and_category_pair(self):
        pairs = list(dict.fromkeys((r["indicator_id"], r["category"]) for r in BIG_ROWS))
        self.assertEqual(len(pairs), len(self.groups))
        self.assertEqual(9, len(self.groups))

    def test_group_order_is_indicator_ids_then_table_categories(self):
        self.assertEqual(
            ["收縮壓｜診斷", "收縮壓｜篩檢分流（非診斷判準）", "收縮壓｜分級",
             "收縮壓｜風險門檻", "舒張壓｜診斷", "舒張壓｜篩檢分流（非診斷判準）",
             "舒張壓｜分級", "舒張壓｜風險門檻", "舒張壓｜未訂判準"],
            [re.sub(r"（\d+ 列）$", "", s) for s, _, _ in self.groups])

    def test_summary_carries_the_short_label_and_the_row_count(self):
        for summary, _, cells in self.groups:
            with self.subTest(summary=summary):
                self.assertRegex(summary, r"^(收縮壓|舒張壓)｜")
                self.assertTrue(summary.endswith(f"（{len(cells)} 列）"), summary)

    def test_only_diagnosis_classification_and_risk_groups_are_open(self):
        for summary, is_open, _ in self.groups:
            with self.subTest(summary=summary):
                self.assertEqual(_cat_of(summary) in ("診斷", "分級", "風險門檻"), is_open)
        self.assertEqual(6, sum(1 for _, o, _ in self.groups if o))

    def test_a_short_page_opens_every_group(self):
        """≤12 列的頁面全部展開：組本來就少的時候，折疊只是多一次點擊。"""
        groups = crit_groups(self._build(MULTI_MD, MULTI_ROWS))
        self.assertEqual(3, len(groups))
        self.assertLessEqual(sum(len(g[2]) for g in groups), gen.CRIT_OPEN_ALL_MAX)
        self.assertTrue(all(o for _, o, _ in groups),
                        "≤12 列時連風險門檻組也要展開（門檻規則蓋過類別規則）")

    def test_no_row_disappears_into_a_fold(self):
        self.assertEqual(len(BIG_ROWS), sum(len(g[2]) for g in self.groups))
        self.assertIn(f'<p class="crit-sum">共 {len(BIG_ROWS)} 列，'
                      f"分 {len(self.groups)} 組；", self.html)

    def test_rows_inside_a_group_keep_the_original_json_order(self):
        """組內不重排：分級組的三列要照 json 裡的行序出現。"""
        cells = next(c for s, _, c in self.groups
                     if s.startswith("收縮壓｜分級"))
        self.assertEqual(["分級：120–129 mmHg", "分級：130–139 mmHg",
                          "分級：140–159 mmHg"], [c[1] for c in cells])

    def test_single_indicator_groups_drop_the_indicator_segment(self):
        html = self._build(SINGLE_MD, [r for r in BIG_ROWS if r["indicator_id"] == "sbp"])
        groups = crit_groups(html)
        self.assertEqual(["診斷（2 列）", "篩檢分流（非診斷判準）（2 列）",
                          "分級（3 列）", "風險門檻（1 列）"], [s for s, _, _ in groups])
        for summary, _, _ in groups:
            self.assertNotIn("｜", summary)
        self.assertNotIn("<th>指標</th>", html)
        for row in table_cells(html):
            self.assertEqual(4, len(row), "單指標頁的判準表維持四欄")

    def test_folding_uses_native_details_and_no_script(self):
        """折疊只能用原生 <details>：內容全在 DOM，爬蟲與 RAG 讀得到。"""
        self.assertEqual(len(self.groups), self.html.count('<details class="crit-grp"'))
        self.assertEqual(len(self.groups), self.html.count("<summary>"))
        self.assertEqual([], [s for s in re.findall(r'<script[^>]*\ssrc="([^"]+)"', self.html)
                              if "googletagmanager" not in s])
        self.assertNotIn("onclick", self.html.split("<main>")[1])

    def test_two_runs_are_byte_identical(self):
        self.assertEqual(self.html, self._build(MULTI_MD, BIG_ROWS))


# ---------- M5：勘誤紀錄（data/errata.json → 指標頁段落＋站級 /errata/） ----------

# 三列刻意造成「同一天兩列」「id 兩位數」：排序要是 date 由新到舊、同日 id 由大到小，
# 而且 id 不能照字串排（E10 照字串會排到 E2 前面就綠得莫名其妙，照字串排 E2 會贏）。
ERRATA_ROWS = [
    {"id": "E1", "date": "2026-09-01", "slug": SLUG, "section": "table",
     "was": "篩檢分流：≥5.9%", "now": "篩檢分流（非診斷判準）：≥5.9%",
     "reason": "原標籤沒在表上寫明這不是診斷線。"},
    {"id": "E2", "date": "2026-09-10", "slug": "blood-pressure", "section": "3",
     "was": "140/90 已作廢", "now": "140/90 被降成第 2 級",
     "reason": "原句把「降級」寫成「作廢」。"},
    {"id": "E10", "date": "2026-09-10", "slug": SLUG, "section": "2",
     "was": "ADA 把糖尿病前期畫在 6.5%", "now": "ADA 把糖尿病診斷畫在 6.5%",
     "reason": "原句把兩條線寫反了。",
     "doc_id": MULTI_DOC, "quote": "A1C ≥6.5% (≥48 mmol/mol)."},
]


def build_with_errata(tmp: pathlib.Path, rows: list, published: bool = False):
    """把 errata fixture 餵給 build()：patch gen.ERRATA_PATH（與 SRC_DIR／CRITERIA_DIR
    同一套注入法），不動 repo 內的 data/errata.json。"""
    path = tmp / "errata.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    keep = gen.ERRATA_PATH
    gen.ERRATA_PATH = path
    try:
        return build_into(tmp, published)
    finally:
        gen.ERRATA_PATH = keep


def errata_items(html: str):
    """回傳 <ol class="errata"> 裡每一項的純文字。"""
    import html as html_lib
    m = re.search(r'<ol class="errata">(.*?)</ol>', html, re.S)
    if not m:
        return []
    return [html_lib.unescape(re.sub(r"<[^>]+>", "", li))
            for li in re.findall(r"<li>(.*?)</li>", m.group(1), re.S)]


class ErrataOnTheIndicatorPage(unittest.TestCase):
    """有勘誤才有那一段。零列時整段不存在——空的「勘誤紀錄」看起來像功能沒接好。"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.html, *_ = build_with_errata(self.tmp, ERRATA_ROWS)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_page_shows_only_its_own_errata(self):
        items = errata_items(self.html)
        self.assertEqual(2, len(items), "hba1c 有兩列；血壓那列不屬於這一頁")
        self.assertIn("勘誤紀錄", self.html)
        self.assertNotIn("140/90 被降成第 2 級", self.html)

    def test_each_item_says_what_it_was_and_what_it_is_now(self):
        row = ERRATA_ROWS[0]
        self.assertIn(
            f"{row['date']}｜{gen.ERRATA_SECTION_LABEL[row['section']]}："
            f"原寫「{row['was']}」，改為「{row['now']}」。{row['reason']}",
            errata_items(self.html))

    def test_a_document_backed_row_cites_the_document(self):
        mf = gen.manifest_index()
        item = next(i for i in errata_items(self.html) if "診斷畫在 6.5%" in i)
        self.assertIn(f"依據：{gen.source_ref(MULTI_DOC, mf, '')}", item)

    def test_a_row_without_a_document_cites_nothing(self):
        item = next(i for i in errata_items(self.html) if "篩檢分流" in i)
        self.assertNotIn("依據：", item, "沒有 doc_id 就不編一份依據出來")

    def test_no_errata_means_no_section_and_no_extra_css(self):
        """☠️ 這條是既有頁面 byte-identical 的守門：零列時連 CSS 都不能多一個 byte。"""
        with tempfile.TemporaryDirectory() as d:
            html, *_ = build_with_errata(pathlib.Path(d), [])
            self.assertNotIn("勘誤紀錄", html)
            self.assertNotIn("ol.errata", html)
            self.assertEqual([], errata_items(html))

    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            other, *_ = build_with_errata(pathlib.Path(d), ERRATA_ROWS)
            self.assertEqual(self.html, other)


class ErrataSitePage(unittest.TestCase):
    """站級 /errata/：全站的勘誤都在這裡，最新在前。"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        _, _, self.out, self.parts, self.llms = build_with_errata(
            self.tmp, ERRATA_ROWS)
        self.html = (self.out / "errata" / "index.html").read_text(encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_lists_every_erratum_newest_first(self):
        items = errata_items(self.html)
        self.assertEqual(len(ERRATA_ROWS), len(items))
        self.assertEqual(["ADA 把糖尿病診斷畫在 6.5%", "140/90 被降成第 2 級",
                          "篩檢分流（非診斷判準）：≥5.9%"],
                         [re.search(r"改為「(.*?)」", i).group(1) for i in items])

    def test_id_ordering_is_numeric_not_lexical(self):
        """同一天的 E10 要排在 E2 前面——照字串排會反過來。"""
        self.assertEqual(["E10", "E2", "E1"],
                         [r["id"] for r in gen.errata_order(ERRATA_ROWS)])

    def test_each_item_links_to_the_page_it_corrects(self):
        self.assertIn(f'<a href="/indicators/{SLUG}/">糖化血色素（HbA1c）</a>｜',
                      self.html)
        self.assertIn('<a href="/indicators/blood-pressure/">', self.html)

    def test_empty_state_says_there_is_nothing_yet(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, out, _, _ = build_with_errata(pathlib.Path(d), [])
            html = (out / "errata" / "index.html").read_text(encoding="utf-8")
            self.assertIn(gen.ERRATA_EMPTY, html)
            self.assertIn(gen.ERRATA_LEDE, html)
            self.assertNotIn('<ol class="errata">', html)
            self.assertLessEqual(len(gen.ERRATA_LEDE), 60)

    def test_head_and_jsonld(self):
        url = f"{gen.hl.BASE}/errata/"
        self.assertIn(f'<link rel="canonical" href="{url}">', self.html)
        graph = json.loads(re.findall(
            r'<script type="application/ld\+json">(.*?)</script>',
            self.html, re.S)[0])["@graph"]
        types = [n["@type"] for n in graph]
        self.assertEqual(["Organization", "WebSite", "WebPage", "BreadcrumbList"],
                         types)
        crumbs = next(n for n in graph if n["@type"] == "BreadcrumbList")
        self.assertEqual(["首頁", "勘誤紀錄"],
                         [i["name"] for i in crumbs["itemListElement"]])
        for banned in ("aggregateRating", "dateModified", "errataCount"):
            self.assertNotIn(banned, self.html.split("</head>")[0],
                             "勘誤頁不放評分，也不放彙總（最後勘誤日／筆數）")

    def test_banned_terms_gate_is_clean(self):
        rules = terms.load_rules()
        page = self.out / "errata" / "index.html"
        hits = [h for h in terms.scan(terms.extract_text(page), rules)
                if h["level"] == "absolute" and not h["exempt"]]
        self.assertEqual([], hits, f"勘誤頁命中絕對禁詞：{hits}")

    def test_errata_page_reuses_the_indicator_foot_rule(self):
        """☠️ ERRATA_FOOT_CSS 的 .ind-foot 是 CHART_CSS 那條規則的副本（抽成共用會改到
        指標頁的 bytes）。兩份必須逐字相同，否則頁尾樣式會安靜地長歪。"""
        rule = re.search(r"\.ind-foot\{.*?\}", gen.ERRATA_FOOT_CSS, re.S).group(0)
        self.assertIn(rule, gen.CHART_CSS)

    def test_a_slug_without_a_page_aborts_instead_of_linking_to_a_404(self):
        bad = [{**ERRATA_ROWS[0], "slug": "no-such-indicator"}]
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                build_with_errata(pathlib.Path(d), bad)

    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, out, _, _ = build_with_errata(pathlib.Path(d), ERRATA_ROWS)
            self.assertEqual(
                self.html, (out / "errata" / "index.html").read_text(encoding="utf-8"))

    def test_a_partial_build_neither_writes_nor_deletes_the_site_page(self):
        """只跑一個 slug 時手上沒有別頁的標題，生出來會是一份殘缺的清單；
        也不刪它——上一次全量 build 產出的那份仍然有效。"""
        before = (self.out / "errata" / "index.html").read_text(encoding="utf-8")
        keep = gen.ERRATA_PATH
        gen.ERRATA_PATH = self.tmp / "errata.json"
        try:
            gen.build(slugs=[SLUG], out_root=self.out, parts_dir=self.parts,
                      llms_path=self.llms, published=False)
        finally:
            gen.ERRATA_PATH = keep
        self.assertEqual(
            before, (self.out / "errata" / "index.html").read_text(encoding="utf-8"))


class ErrataDormantWiring(unittest.TestCase):
    """dormant 雙向：published 才接線，且勘誤頁排在指標頁後面（最後一行）。"""

    def test_published_puts_errata_last_in_the_sitemap_part_and_llms(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, out, parts, llms = build_with_errata(
                pathlib.Path(d), ERRATA_ROWS, published=True)
            urls = (parts / "indicators.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(f"{gen.hl.BASE}/errata/", urls[-1])
            self.assertEqual(1, urls.count(f"{gen.hl.BASE}/errata/"))
            block = llms.read_text(encoding="utf-8").split(gen.LLMS_HEAD)[1]
            lines = [l for l in block.strip().splitlines() if l.strip()]
            self.assertTrue(lines[-1].startswith(
                f"- [{gen.ERRATA_TITLE}]({gen.hl.BASE}/errata/)："), lines[-1])
            self.assertIn(gen.ERRATA_LLMS_DESC, lines[-1])
            self.assertNotIn("各機構判準並列、判準沿革與已知限制", lines[-1],
                             "勘誤頁不是指標頁，說明句不能共用")

    def test_dormant_generates_the_page_but_wires_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, out, parts, llms = build_with_errata(
                pathlib.Path(d), ERRATA_ROWS, published=False)
            self.assertTrue((out / "errata" / "index.html").exists(),
                            "dormant 仍要生成（要能審），只是不接線")
            self.assertFalse((parts / "indicators.txt").exists())
            self.assertNotIn("/errata/", llms.read_text(encoding="utf-8"))

    def test_the_footer_link_follows_the_same_published_gate(self):
        entry = next(l for l in gen.hl.SITE["footer_links"]
                     if l["href"] == "/errata/")
        self.assertEqual("published", entry.get("requires"))
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            dormant, *_ = build_with_errata(pathlib.Path(a), ERRATA_ROWS, False)
            live, *_ = build_with_errata(pathlib.Path(b), ERRATA_ROWS, True)
        self.assertNotIn('<a href="/errata/">', dormant)
        self.assertIn('<a href="/errata/">勘誤紀錄</a>', live)


if __name__ == "__main__":
    unittest.main()
