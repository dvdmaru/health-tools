#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「頁面列了某個指標，但它沒有任何可上圖的判準列」的回歸測試。

情境：某指標在這頁收的文件裡只有 TABLE_CATEGORIES 以外的列（檢查單上有這一行、
這個數字量什麼），沒有任何分級／診斷／參考區間。
- 生成器：不畫數線、不呼叫 _axis_cfg，改放一句固定句；判準表不為它開組。
- 原本的保護不拿掉：criteria 檔裡連任何 category 都沒有這個 id（例：打錯）→ 仍中止。
- 工作表：略過這個指標的填空欄並印警告；索引頁：照常出卡。

夾具沿用 tests/test_gen_indicator.py 的 build_fixture_page／MULTI_MD（sbp＋dbp 兩指標頁）。
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_gen_indicator as tgi  # noqa: E402

ROOT = tgi.ROOT
gen = tgi.gen

FIXED = '<p class="nl-none">舒張壓：本頁收錄的文件沒有給它可以畫成數線的數值判準。</p>'

# sbp 有一列分級；dbp 只有一列 definition（不在 TABLE_CATEGORIES）。
ROWS = [
    tgi._fixture_row("sbp", "classification", 130, 139, "mmHg"),
    tgi._fixture_row("dbp", "definition", None, None, None),
]


def _build(tmp: pathlib.Path, rows: list, calls: list = None) -> str:
    orig = gen._axis_cfg

    def spy(indicator_id, rs):
        if calls is not None:
            calls.append(indicator_id)
        return orig(indicator_id, rs)

    gen._axis_cfg = spy
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return tgi.build_fixture_page(tmp, tgi.MULTI_MD, rows)
    finally:
        gen._axis_cfg = orig


class IndicatorWithOnlyNonTableRows(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.calls = []
        self.html = _build(self.tmp, ROWS, self.calls)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_succeeds_and_prints_the_fixed_sentence(self):
        self.assertIn(FIXED, self.html)
        self.assertEqual(1, self.html.count('class="nl-none"'))

    def test_fixed_sentence_is_the_module_constant(self):
        self.assertIn(f'<p class="nl-none">舒張壓{gen.NO_AXIS_SUFFIX}</p>', self.html)

    def test_no_number_line_for_it_and_the_other_indicator_keeps_its_line(self):
        self.assertEqual(1, self.html.count('<figure class="chart">'))
        self.assertIn('<figcaption class="ct">收縮壓（mmHg）</figcaption>', self.html)
        self.assertNotIn('<figcaption class="ct">舒張壓', self.html)

    def test_axis_config_is_never_asked_for_it(self):
        self.assertEqual(["sbp"], self.calls)

    def test_criteria_table_opens_no_group_and_adds_no_empty_row(self):
        names = [g[0] for g in tgi.crit_groups(self.html)]
        self.assertEqual(["收縮壓｜分級（1 列）"], names)
        self.assertEqual(1, len(tgi.table_cells(self.html)))
        self.assertNotIn("無資料", self.html)

    def test_fixed_sentence_carries_no_judgement_about_the_readers_value(self):
        for word in ("正常", "沒有標準", "不需要", "異常", "建議", "偏高", "偏低"):
            with self.subTest(word=word):
                self.assertNotIn(word, gen.NO_AXIS_SUFFIX)

    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.html, _build(pathlib.Path(d), ROWS))


class IndicatorWithNoRowsAtAllStillAborts(unittest.TestCase):
    """原本的保護：criteria 檔裡連任何 category 都沒有這個 id → 中止。"""

    def test_declared_id_absent_from_the_file_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                _build(pathlib.Path(d), ROWS[:1])

    def test_rows_filed_under_a_mistyped_id_do_not_rescue_it(self):
        rows = ROWS[:1] + [tgi._fixture_row("dbq", "definition", None, None, None)]
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                _build(pathlib.Path(d), rows)


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class WorksheetAndIndexOnSuchAPage(unittest.TestCase):
    """工作表略過該指標的填空欄並出聲；索引頁照常出卡（兩個短標籤、判準列只數 TABLE 列）。"""

    @classmethod
    def setUpClass(cls):
        cls.ws = _load("gen_worksheet_zero_table", "scripts/gen-worksheet.py")
        cls.idx = _load("gen_indicators_index_zero_table", "scripts/gen-indicators-index.py")

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.src = self.tmp / "articles"
        self.crit = self.tmp / "criteria"
        self.src.mkdir()
        self.crit.mkdir()
        (self.src / f"{tgi.MULTI_SLUG}.md").write_text(tgi.MULTI_MD, encoding="utf-8")
        (self.crit / f"{tgi.MULTI_SLUG}.json").write_text(
            json.dumps(ROWS, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_worksheet_skips_it_with_a_warning(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            blocks = self.ws.collect_blocks(src_dir=self.src, criteria_dir=self.crit)
        self.assertEqual(["sbp"], [i["id"] for i in blocks[0]["indicators"]])
        self.assertIn("dbp", out.getvalue())

    def test_index_card_still_lists_both_labels_and_counts_only_table_rows(self):
        card = self.idx.collect_cards(src_dir=self.src, criteria_dir=self.crit)[0]
        self.assertEqual(["收縮壓", "舒張壓"], card["labels"])
        self.assertEqual(1, card["n_rows"])


if __name__ == "__main__":
    unittest.main()
