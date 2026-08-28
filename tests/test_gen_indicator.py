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


def criteria_rows():
    rows = json.loads(CRITERIA.read_text(encoding="utf-8"))
    return [r for r in rows
            if r["indicator_id"] == SLUG and r["category"] in gen.TABLE_CATEGORIES]


def table_cells(html: str):
    """回傳判準表的資料列（每列＝四欄純文字）。"""
    import html as html_lib
    table = re.search(r'<table class="std-table">.*?</table>', html, re.S).group(0)
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", table, re.S):
        cells = re.findall(r"<td>(.*?)</td>", tr, re.S)
        if cells:
            out.append([html_lib.unescape(re.sub(r"<[^>]+>", "", c)) for c in cells])
    return out


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
                s = re.sub(r'<a href="/indicators/"[^>]*>.*?</a>', "", s)
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
            self.assertEqual((parts / "indicators.txt").read_text(encoding="utf-8"),
                             f"https://health.twtools.cc/indicators/{SLUG}/\n")
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


if __name__ == "__main__":
    unittest.main()
