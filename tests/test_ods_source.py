#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ODS 來源格式（doc_type=ods）的回歸測試。

有些國健署資料集只以 ODS（OpenDocument 試算表）發布。快照存原檔，抽字在 gate 端做，
規則固定（與來源席的探針一致，見 scripts/check-receipts.py 的 ods_text()）。

守四件事：
1. 抽字結果逐字元釘住：被合併蓋住的格當空字串、一格多段用換行、段內 span 的字要在、
   重複格不展開。
2. 收據 gate、drift 監測、抓取工具吃**同一支**抽字，不是三份各自長歪的實作。
3. 收據 gate 對 ods 引句：抄對 PASS；改一個字、全形改半形都 FAIL（陰性對照）。
4. 回應讀不出 ODS（攔截頁）＝blocked／中止不落地，不是 drift。
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
GATE = SCRIPTS / "check-receipts.py"


def _load(modname: str, filename: str):
    spec = importlib.util.spec_from_file_location(modname, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


receipts = _load("_check_receipts_under_ods_test", "check-receipts.py")
drift = _load("_check_source_drift_under_ods_test", "check-source-drift.py")
fetch = _load("_fetch_health_source_under_ods_test", "fetch-health-source.py")

# 最小 ODS 的 content.xml：
#   第 1 列：一格橫跨兩欄（後面跟一個被蓋住的格，裡面刻意留字——規則說當空字串）＋一般格。
#   第 2 列：一格兩個 text:p，第二段內有 text:span；全形 ≧ 原樣保留。
#   第 3 列：試算表尾端常見的「重複上百萬列、每列重複上千格」空白列——不展開。
CONTENT_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<office:document-content'
    ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
    ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
    ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
    ' office:version="1.2">\n'
    '<office:body><office:spreadsheet>\n'
    '<table:table table:name="工作表1">\n'
    '<table:table-column table:number-columns-repeated="3"/>\n'
    '<table:table-row>\n'
    '  <table:table-cell table:number-columns-spanned="2" office:value-type="string">'
    '<text:p>分期</text:p></table:table-cell>\n'
    '  <table:covered-table-cell><text:p>不該出現</text:p></table:covered-table-cell>\n'
    '  <table:table-cell office:value-type="string"><text:p>腎絲球過濾率</text:p>'
    '</table:table-cell>\n'
    '</table:table-row>\n'
    '<table:table-row>\n'
    '  <table:table-cell office:value-type="string"><text:p>第一期</text:p></table:table-cell>\n'
    '  <table:table-cell office:value-type="string"><text:p>腎功能正常，</text:p>'
    '<text:p>但出現<text:span>蛋白尿</text:span>、血尿</text:p></table:table-cell>\n'
    '  <table:table-cell office:value-type="string"><text:p>≧ 90</text:p></table:table-cell>\n'
    '</table:table-row>\n'
    '<table:table-row table:number-rows-repeated="1048573">'
    '<table:table-cell table:number-columns-repeated="1024"/></table:table-row>\n'
    '</table:table>\n'
    '</office:spreadsheet></office:body>\n'
    '</office:document-content>\n'
)

EXPECTED = ("分期\t\t腎絲球過濾率\n"
            "第一期\t腎功能正常，\n但出現蛋白尿、血尿\t≧ 90\n")

GOOD_QUOTE = "腎功能正常，但出現蛋白尿、血尿"      # 橫跨一格裡的兩個 text:p
BAD_QUOTE = "腎功能正常，但出現蛋白尿、血糖"       # ☠️ 改一個字（尿→糖）
FULLWIDTH_QUOTE = "≧ 90"
HALFWIDTH_QUOTE = "≥ 90"                          # ☠️ 全形 ≧ 寫成半形 ≥

HTML_BODY = ("<html><head><title>首頁</title></head>"
             "<body><p>這不是試算表</p></body></html>").encode("utf-8")


def make_ods(content_xml: str = CONTENT_XML, with_content: bool = True) -> bytes:
    """現場組一個最小 ODS（mimetype 不壓縮放第一個，同 ODF 規格）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"),
                   "application/vnd.oasis.opendocument.spreadsheet")
        if with_content:
            z.writestr("content.xml", content_xml, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. 抽字規則
# ---------------------------------------------------------------------------

class OdsExtraction(unittest.TestCase):
    def test_extracted_text_is_pinned_character_by_character(self):
        self.assertEqual(EXPECTED, receipts.ods_text(make_ods()))

    def test_covered_cell_is_an_empty_string_even_if_it_holds_text(self):
        text = receipts.ods_text(make_ods())
        self.assertEqual("分期\t\t腎絲球過濾率", text.split("\n")[0])
        self.assertNotIn("不該出現", text)

    def test_several_paragraphs_in_one_cell_are_joined_by_newline(self):
        self.assertIn("腎功能正常，\n但出現蛋白尿、血尿", receipts.ods_text(make_ods()))

    def test_repeated_blank_cells_and_rows_are_not_expanded(self):
        """一個 table-row 元素＝一行，一個 table-cell 元素＝一格；重複屬性不展開。"""
        text = receipts.ods_text(make_ods())
        # 第 3 列（重複 1048573 列 × 1024 格）只貢獻結尾一個空行，沒有展開出的 \t 或 \n。
        self.assertTrue(text.endswith("\t≧ 90\n"))
        self.assertNotIn("\t\t\t", text)
        self.assertNotIn("\n\n", text)

    def test_fullwidth_symbols_are_kept_as_is(self):
        self.assertIn("≧ 90", receipts.ods_text(make_ods()))

    def test_not_a_zip_raises_value_error(self):
        with self.assertRaises(ValueError):
            receipts.ods_text(HTML_BODY)

    def test_zip_without_content_xml_raises_value_error(self):
        with self.assertRaises(ValueError):
            receipts.ods_text(make_ods(with_content=False))

    def test_broken_xml_raises_value_error(self):
        with self.assertRaises(ValueError):
            receipts.ods_text(make_ods(content_xml="<office:document-content>"))


# ---------------------------------------------------------------------------
# 2. 三支工具同一支抽字
# ---------------------------------------------------------------------------

class OneExtractorForAllTools(unittest.TestCase):
    def test_drift_extract_text_equals_the_gate_extractor(self):
        data = make_ods()
        self.assertEqual(receipts.ods_text(data), drift.extract_text("ods", data))

    def test_drift_and_fetch_borrow_the_function_defined_in_check_receipts(self):
        for fn in (drift._receipts.ods_text, fetch._receipts().ods_text):
            with self.subTest(fn=fn):
                self.assertTrue(fn.__code__.co_filename.endswith("check-receipts.py"))

    def test_ods_has_no_page_title_like_pdf(self):
        self.assertEqual("", drift.extract_page_title("ods", make_ods()))

    def test_unreadable_ods_extracts_to_empty_string_in_drift(self):
        self.assertEqual("", drift.extract_text("ods", HTML_BODY))


# ---------------------------------------------------------------------------
# 3. 收據 gate 對 ods 引句
# ---------------------------------------------------------------------------

class ReceiptsGateOnOds(unittest.TestCase):
    """把 gate 腳本複製到暫存目錄，餵它 ODS 快照與一列判準，看它紅不紅。"""

    def run_gate(self, quote: str, snapshot: bytes = None):
        tmp = pathlib.Path(tempfile.mkdtemp())
        try:
            (tmp / "scripts").mkdir()
            (tmp / "data" / "sources").mkdir(parents=True)
            (tmp / "data" / "criteria").mkdir(parents=True)
            shutil.copy(GATE, tmp / "scripts" / "check-receipts.py")
            src = {
                "id": "ods-fixture", "title": "fixture", "org": "fixture",
                "doc_type": "ods", "url": "https://example.org/fixture.ods",
                "version_or_date": "文件未標示", "fetched_at": "2026-09-10",
                "sha256": "0" * 64, "local_path": "data/sources/ods-fixture.ods",
                "license_bucket": "tw-gov", "retrieval": "manual",
            }
            (tmp / src["local_path"]).write_bytes(
                make_ods() if snapshot is None else snapshot)
            (tmp / "data" / "sources" / "manifest.json").write_text(
                json.dumps([src], ensure_ascii=False), encoding="utf-8")
            row = {"indicator_id": "egfr", "org": "fixture", "doc_id": "ods-fixture",
                   "category": "classification", "quote": quote}
            (tmp / "data" / "criteria" / "ckd-fixture.json").write_text(
                json.dumps([row], ensure_ascii=False), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(tmp / "scripts" / "check-receipts.py")],
                capture_output=True, text=True, cwd=tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_correct_quote_passes(self):
        """對照組：引句抄對（橫跨一格裡的兩段）就該過。"""
        r = self.run_gate(GOOD_QUOTE)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("PASS 1", r.stdout)
        self.assertIn("FAIL 0", r.stdout)

    def test_one_character_changed_fails(self):
        r = self.run_gate(BAD_QUOTE)
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("FAIL 1", r.stdout)
        self.assertIn("引句在快照中找不到", r.stdout)

    def test_fullwidth_passes_and_halfwidth_fails(self):
        """全形半形不轉換：來源的 ≧ 抄成 ≥ 就該紅。"""
        self.assertEqual(0, self.run_gate(FULLWIDTH_QUOTE).returncode)
        self.assertEqual(1, self.run_gate(HALFWIDTH_QUOTE).returncode)

    def test_snapshot_that_is_not_an_ods_fails_not_skips(self):
        """快照檔在但讀不出 ODS＝快照不是那份文件：FAIL，不是 SKIP 也不是 PASS。"""
        r = self.run_gate(GOOD_QUOTE, snapshot=HTML_BODY)
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("ODS 抽字失敗", r.stdout)
        self.assertIn("SKIP 0", r.stdout)


# ---------------------------------------------------------------------------
# 4. drift 與抓取工具：讀不出 ODS＝攔截頁
# ---------------------------------------------------------------------------

def _fake_curl(body: bytes, code: str = "200"):
    def _fn(url, timeout):
        return code, body, {}, True
    return _fn


class DriftOnOds(unittest.TestCase):
    def setUp(self):
        orig = drift.curl_with_headers
        self.addCleanup(setattr, drift, "curl_with_headers", orig)

    def _check(self, body: bytes, quotes: set) -> dict:
        drift.curl_with_headers = _fake_curl(body)
        src = {"id": "ods-doc", "title": "t", "url": "https://example.org/x.ods",
               "doc_type": "ods"}
        return drift.check_source(src, quotes, timeout=5)

    def test_quotes_are_found_in_a_reached_ods(self):
        result = self._check(make_ods(), {GOOD_QUOTE, FULLWIDTH_QUOTE})
        self.assertEqual("reached", result["fetch_status"])
        self.assertEqual(2, result["quotes_found"])
        self.assertEqual("", result["_page_title"])

    def test_a_changed_quote_is_missing(self):
        result = self._check(make_ods(), {GOOD_QUOTE, BAD_QUOTE})
        self.assertEqual({BAD_QUOTE}, result["_missing"])

    def test_html_answer_to_an_ods_url_is_blocked_not_drift(self):
        result = self._check(HTML_BODY, {GOOD_QUOTE})
        self.assertEqual("blocked", result["fetch_status"])
        self.assertIn("不是 ODS", result["error"])
        self.assertEqual("blocked", drift.classify(result, {"quotes_verified": [GOOD_QUOTE]},
                                                   building=False))


class FetchToolOnOds(unittest.TestCase):
    ARGS = ["fetch-health-source.py", "--id", "ods-probe-fixture",
            "--url", "https://example.org/x.ods", "--title", "t", "--org", "o",
            "--doc-type", "ods", "--version", "v", "--license-bucket", "tw-gov",
            "--probe-only"]

    def test_doc_type_choices_include_ods(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "fetch-health-source.py"), "--help"],
                           capture_output=True, text=True)
        self.assertEqual(0, r.returncode)
        self.assertIn("ods", r.stdout)

    def test_ods_blocked_reason(self):
        self.assertEqual("", fetch.ods_blocked_reason(make_ods()))
        self.assertIn("不是 ODS", fetch.ods_blocked_reason(HTML_BODY))

    def _probe(self, body: bytes):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", self.ARGS), \
                mock.patch.object(fetch, "curl", lambda url: ("200", body)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = fetch.main()
        return rc, out.getvalue(), err.getvalue()

    def test_probe_passes_for_a_real_ods(self):
        rc, out, _ = self._probe(make_ods())
        self.assertEqual(0, rc)
        self.assertIn("探測通過", out)

    def test_probe_refuses_an_html_answer_and_lands_nothing(self):
        rc, _, err = self._probe(HTML_BODY)
        self.assertEqual(1, rc)
        self.assertIn("不是 ODS", err)
        self.assertFalse((ROOT / "data" / "sources" / "ods-probe-fixture.ods").exists())


if __name__ == "__main__":
    unittest.main()
