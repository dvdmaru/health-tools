#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""來源改版監測的回歸測試（scripts/check-source-drift.py）。

☠️ 不打網路：所有情境一律 monkeypatch `curl_with_headers`（drift 腳本自己包的
curl 呼叫函式）回假的 (code, body, headers)，不打真的 curl。pdftotext 是本機執行檔，
不是網路呼叫，PDF 情境照樣用真的 pdftotext 跑一份手刻的最小合法 PDF——這樣才真的
測到「PDF 抽字 → 正規化 → 比對」這條路徑，不是只測分類邏輯。

三層測試：
  1. TestExtraction　：check_source() 對假 HTML／PDF body 的抽字＋引句命中（不碰 classify）。
  2. TestClassify　　：classify() 純函式的狀態判定（不碰網路也不碰檔案，直接餵字典）。
  3. TestMainEndToEnd：整條 main() pipeline（manifest→baseline→報告→exit code），
     用暫存目錄當假 repo，把 drift 腳本與它 import 的 _receipts 模組的路徑常數
     一起指過去。

斷言一律從 fixture 資料自己算，不寫死列數／份數（M5 教訓）。
"""
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(modname: str, filename: str):
    spec = importlib.util.spec_from_file_location(modname, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


drift = _load("_check_source_drift_under_test", "check-source-drift.py")


# ---------------------------------------------------------------------------
# 共用小工具
# ---------------------------------------------------------------------------

def make_pdf_bytes(lines: list) -> bytes:
    """手刻一份最小合法 PDF（不壓縮、base14 字型），pdftotext 讀得懂。
    只用 ASCII——base14 Helvetica 對非 ASCII 符號的映射不可靠，這裡只是要驗證
    「PDF 位元組 → pdftotext -layout → 正規化比對」這條管線，不是測 pdftotext 本身。
    """
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = "BT /F1 12 Tf 72 720 Td " + " ".join(
        f"({esc(l)}) Tj 0 -14 Td" for l in lines) + " ET"
    content_bytes = content.encode("latin-1", "replace")
    objs = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n",
        (f"4 0 obj\n<< /Length {len(content_bytes)} >>\nstream\n".encode("latin-1")
         + content_bytes + b"\nendstream\nendobj\n"),
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for o in objs:
        offsets.append(len(pdf))
        pdf += o
    xref_at = len(pdf)
    pdf += f"xref\n0 {len(objs) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF").encode()
    return pdf


def fake_curl(url_map: dict):
    """回一個取代 drift.curl_with_headers 的函式：查表回假回應，查不到就丟 OSError
    （模擬 unreachable）。"""
    def _fn(url, timeout):
        if url not in url_map:
            raise OSError(f"fixture 沒有這個 url 的回應：{url}")
        entry = url_map[url]
        if "raise" in entry:
            raise OSError(entry["raise"])
        return entry["code"], entry["body"], entry.get("headers", {})
    return _fn


# ---------------------------------------------------------------------------
# 1. 抽字＋引句命中（check_source，不碰 baseline／classify）
# ---------------------------------------------------------------------------

class TestExtraction(unittest.TestCase):
    def setUp(self):
        self._orig_curl = drift.curl_with_headers
        self.addCleanup(setattr, drift, "curl_with_headers", self._orig_curl)

    def test_html_strips_script_style_and_unescapes_entities(self):
        quote = "The threshold is ≥6.5% for diagnosis."
        stripped_only_quote = "var x = 1"  # 只存在於 <script> 裡，抽字後不該出現
        body = (
            "<html><head><style>body{color:red}</style></head><body>"
            "<script>var x = 1;</script>"
            "<p>The threshold is &ge;6.5% for diagnosis.</p>"
            "</body></html>"
        ).encode("utf-8")
        url = "https://example.org/html-doc"
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})

        src = {"id": "html-doc", "title": "t", "url": url, "doc_type": "html"}
        required = {quote, stripped_only_quote}
        result = drift.check_source(src, required, timeout=5)

        self.assertEqual("reached", result["fetch_status"])
        self.assertEqual(1, result["quotes_found"],
                         "應該只驗到 1 句（script 裡的字不算數）")
        self.assertIn(quote, result["_found"])
        self.assertIn(stripped_only_quote, result["_missing"],
                      "script 內容沒被剝乾淨——那是抽字管線壞了，不是引句真的消失")
        self.assertEqual(hashlib.sha256(body).hexdigest(), result["remote_sha256"])

    def test_pdf_extraction_finds_quote_via_real_pdftotext(self):
        quote = "SUA >= 8.0 mg/dL is the diagnostic threshold."
        pdf_bytes = make_pdf_bytes([quote])
        url = "https://example.org/doc.pdf"
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": pdf_bytes}})

        src = {"id": "pdf-doc", "title": "t", "url": url, "doc_type": "pdf"}
        result = drift.check_source(src, {quote}, timeout=5)

        self.assertEqual("reached", result["fetch_status"])
        self.assertEqual(1, result["quotes_found"])
        self.assertEqual(hashlib.sha256(pdf_bytes).hexdigest(), result["remote_sha256"])

    def test_blocked_response_is_not_reached(self):
        url = "https://example.org/waf"
        body = b"forbidden"
        drift.curl_with_headers = fake_curl({url: {"code": "403", "body": body}})
        src = {"id": "blocked-doc", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, {"anything"}, timeout=5)
        self.assertEqual("blocked", result["fetch_status"])
        self.assertEqual("HTTP 403", result["error"])

    def test_unreachable_when_curl_raises(self):
        url = "https://example.org/timeout"
        drift.curl_with_headers = fake_curl({url: {"raise": "curl exit 28: timeout"}})
        src = {"id": "timeout-doc", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, {"anything"}, timeout=5)
        self.assertEqual("unreachable", result["fetch_status"])


# ---------------------------------------------------------------------------
# 2. classify() 純函式的狀態判定
# ---------------------------------------------------------------------------

def cur(**over):
    base = {
        "doc_type": "html", "quotes_total": 1,
        "_found": {"Q1"}, "_missing": set(),
        "fetch_status": "reached",
        "remote_sha256": "sha-a", "text_sha256": "text-a",
    }
    base.update(over)
    return base


def baseline(**over):
    base = {
        "remote_sha256": "sha-a", "text_sha256": "text-a",
        "quotes_verified": ["Q1"], "quotes_never_verified": [],
    }
    base.update(over)
    return base


class TestClassify(unittest.TestCase):
    def test_ok_when_everything_matches(self):
        self.assertEqual("ok", drift.classify(cur(), baseline(), building=False))

    def test_blocked_is_never_folded_into_ok(self):
        c = cur(fetch_status="blocked")
        self.assertEqual("blocked", drift.classify(c, baseline(), building=False))
        self.assertEqual("blocked", drift.classify(c, None, building=False))
        self.assertEqual("blocked", drift.classify(c, baseline(), building=True))

    def test_unreachable_is_never_folded_into_ok(self):
        c = cur(fetch_status="unreachable")
        self.assertEqual("unreachable", drift.classify(c, baseline(), building=False))

    def test_quote_verified_before_now_missing_is_drift(self):
        """baseline 裡驗過在的引句，現在找不到——這是核心 drift 情境。"""
        c = cur(_found=set(), _missing={"Q1"}, remote_sha256="sha-b", text_sha256="text-b")
        self.assertEqual("drift", drift.classify(c, baseline(), building=False))

    def test_never_verified_quote_missing_again_is_not_drift(self):
        """baseline 當初就沒驗到的引句，這次還是沒驗到——不算 drift。"""
        b = baseline(quotes_verified=["Q1"], quotes_never_verified=["Q2"])
        c = cur(quotes_total=2, _found={"Q1"}, _missing={"Q2"})
        self.assertEqual("never-verified", drift.classify(c, b, building=False))

    def test_never_verified_and_verified_missing_together_still_drift(self):
        """一份文件裡，一句是 never-verified、另一句是 verified-now-missing——
        只要有一句符合 drift 條件，整份就是 drift（不能被 never-verified 蓋過去）。"""
        b = baseline(quotes_verified=["Q1"], quotes_never_verified=["Q2"])
        c = cur(quotes_total=2, _found=set(), _missing={"Q1", "Q2"})
        self.assertEqual("drift", drift.classify(c, b, building=False))

    def test_pdf_raw_sha_change_with_same_text_is_not_drift(self):
        """2026-08-28 裁決：PDF 的 raw sha 變了但抽出來的正文(text_sha256)沒變，
        只算 changed-quotes-intact，不是 drift——實測 eular-gout-recommendations-2016
        這份 PDF 連續 curl 三次會出現兩種不同 raw sha256（size 相同），但三次的
        text_sha256 都一樣，證明 raw bytes 本身就不穩定，拿它當 drift 訊號只會
        天天假警報。"""
        c = cur(doc_type="pdf", remote_sha256="pdf-b", text_sha256="text-a")
        self.assertEqual("changed-quotes-intact",
                         drift.classify(c, baseline(remote_sha256="pdf-a"), building=False))

    def test_pdf_text_sha_change_is_drift(self):
        """跟上一條對照：raw sha 變不算數，但 text_sha256（pdftotext 抽出、正規化
        後的正文）真的變了——這才是『PDF 改版一定要人看』該抓的訊號。"""
        c = cur(doc_type="pdf", remote_sha256="pdf-a", text_sha256="text-b")
        self.assertEqual("drift",
                         drift.classify(c, baseline(remote_sha256="pdf-a", text_sha256="text-a"),
                                        building=False))

    def test_html_raw_sha_change_with_quotes_intact_is_only_informational(self):
        """html／html-text 的 raw sha 本來就會因 nonce／廣告位跳動，只要引句還在
        就只算 changed-quotes-intact，不是 drift。"""
        c = cur(doc_type="html", remote_sha256="html-b", text_sha256="text-a")
        self.assertEqual("changed-quotes-intact",
                         drift.classify(c, baseline(remote_sha256="html-a"), building=False))

    def test_no_baseline_change_no_quote_change_is_ok(self):
        self.assertEqual("ok", drift.classify(cur(), baseline(), building=False))

    def test_no_quotes_document_only_compares_sha(self):
        c = cur(quotes_total=0, _found=set(), _missing=set())
        self.assertEqual("no-quotes", drift.classify(c, baseline(), building=False))
        c2 = cur(quotes_total=0, _found=set(), _missing=set(), remote_sha256="sha-b")
        self.assertEqual("changed-quotes-intact",
                         drift.classify(c2, baseline(), building=False))

    def test_building_never_produces_drift_even_with_missing_quotes(self):
        """--update-baseline 那一輪沒有『上一版』可比，缺引句只能記
        never-verified，不能判 drift——不然第一次建 baseline 就會紅。"""
        c = cur(_found=set(), _missing={"Q1"})
        self.assertEqual("never-verified", drift.classify(c, None, building=True))
        self.assertEqual("never-verified", drift.classify(c, baseline(), building=True))

    def test_building_with_all_quotes_found_is_ok(self):
        self.assertEqual("ok", drift.classify(cur(), None, building=True))


# ---------------------------------------------------------------------------
# 3. main() 整條 pipeline
# ---------------------------------------------------------------------------

class TestMainEndToEnd(unittest.TestCase):
    def setUp(self):
        self._orig = dict(
            ROOT=drift.ROOT, SOURCES=drift.SOURCES, BASELINE=drift.BASELINE,
            DEFAULT_OUT_DIR=drift.DEFAULT_OUT_DIR,
            R_ROOT=drift._receipts.ROOT, R_CRIT=drift._receipts.CRITERIA_DIR,
            R_ERRATA=drift._receipts.ERRATA, curl=drift.curl_with_headers,
        )
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(self._restore)
        (self.tmp / "data" / "sources").mkdir(parents=True)
        (self.tmp / "data" / "criteria").mkdir(parents=True)
        drift.ROOT = self.tmp
        drift.SOURCES = self.tmp / "data" / "sources" / "manifest.json"
        drift.BASELINE = self.tmp / "data" / "sources" / "drift-baseline.json"
        drift.DEFAULT_OUT_DIR = self.tmp / ".drift"
        drift._receipts.ROOT = self.tmp
        drift._receipts.CRITERIA_DIR = self.tmp / "data" / "criteria"
        drift._receipts.ERRATA = self.tmp / "data" / "errata.json"

    def _restore(self):
        drift.ROOT = self._orig["ROOT"]
        drift.SOURCES = self._orig["SOURCES"]
        drift.BASELINE = self._orig["BASELINE"]
        drift.DEFAULT_OUT_DIR = self._orig["DEFAULT_OUT_DIR"]
        drift._receipts.ROOT = self._orig["R_ROOT"]
        drift._receipts.CRITERIA_DIR = self._orig["R_CRIT"]
        drift._receipts.ERRATA = self._orig["R_ERRATA"]
        drift.curl_with_headers = self._orig["curl"]
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_manifest(self, rows):
        drift.SOURCES.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    def _write_criteria(self, rows, name="fixture.json"):
        (drift._receipts.CRITERIA_DIR / name).write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    def _write_baseline(self, rows):
        drift.BASELINE.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                  encoding="utf-8")

    def _run_main(self, argv):
        old_argv = sys.argv
        sys.argv = ["check-source-drift.py"] + argv
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                code = drift.main()
        finally:
            sys.argv = old_argv
        return code, buf.getvalue()

    def test_exit_0_when_all_reachable_and_no_drift(self):
        quote = "A1C threshold is 6.5%."
        body = f"<p>{quote}</p>".encode("utf-8")
        url = "https://example.org/a"
        self._write_manifest([{"id": "doc-a", "title": "A", "url": url, "doc_type": "html"}])
        self._write_criteria([{"doc_id": "doc-a", "quote": quote}])
        sha = hashlib.sha256(body).hexdigest()
        self._write_baseline([{
            "id": "doc-a", "url": url, "doc_type": "html",
            "checked_at": "2026-08-01T00:00:00Z", "http_code": "200", "status": "ok",
            "etag": None, "last_modified": None,
            # sha 值本身對這個測試不重要——doc_type=html 時 sha 不同只會變成
            # changed-quotes-intact（仍是 exit 0），不會變成 drift；重點是引句要對得上。
            "remote_sha256": sha, "text_sha256": "irrelevant-for-html",
            "quotes_total": 1, "quotes_verified": [quote], "quotes_never_verified": [],
        }])
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})

        code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        self.assertEqual(0, code, out)
        self.assertIn("drift 0", out)

    def test_exit_1_when_a_verified_quote_goes_missing(self):
        quote = "A1C threshold is 6.5%."
        url = "https://example.org/b"
        self._write_manifest([{"id": "doc-b", "title": "B", "url": url, "doc_type": "html"}])
        self._write_criteria([{"doc_id": "doc-b", "quote": quote}])
        self._write_baseline([{
            "id": "doc-b", "url": url, "doc_type": "html",
            "checked_at": "2026-08-01T00:00:00Z", "http_code": "200", "status": "ok",
            "etag": None, "last_modified": None,
            "remote_sha256": "old-sha", "text_sha256": "old-text",
            "quotes_total": 1, "quotes_verified": [quote], "quotes_never_verified": [],
        }])
        # 這次線上版把那句話拿掉了
        new_body = b"<p>This page no longer states a numeric threshold.</p>"
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": new_body}})

        code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        self.assertEqual(1, code, out)
        self.assertIn("drift 1", out)
        self.assertIn("doc-b", out)

    def test_exit_2_when_everything_blocked_or_unreachable(self):
        url_a = "https://example.org/blocked"
        url_b = "https://example.org/down"
        self._write_manifest([
            {"id": "doc-c", "title": "C", "url": url_a, "doc_type": "html"},
            {"id": "doc-d", "title": "D", "url": url_b, "doc_type": "html"},
        ])
        self._write_criteria([{"doc_id": "doc-c", "quote": "irrelevant"}])
        self._write_baseline([
            {"id": "doc-c", "url": url_a, "doc_type": "html", "checked_at": "x",
             "http_code": "403", "status": "blocked", "etag": None, "last_modified": None,
             "remote_sha256": None, "text_sha256": None, "quotes_total": 1,
             "quotes_verified": [], "quotes_never_verified": ["irrelevant"]},
            {"id": "doc-d", "url": url_b, "doc_type": "html", "checked_at": "x",
             "http_code": None, "status": "unreachable", "etag": None, "last_modified": None,
             "remote_sha256": None, "text_sha256": None, "quotes_total": 0,
             "quotes_verified": [], "quotes_never_verified": []},
        ])
        drift.curl_with_headers = fake_curl({
            url_a: {"code": "403", "body": b"forbidden"},
            url_b: {"raise": "curl exit 28: timeout"},
        })

        code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        self.assertEqual(2, code, out)
        self.assertIn("blocked 1", out)
        self.assertIn("unreachable 1", out)

    def test_baseline_file_is_not_written_in_normal_mode(self):
        quote = "A1C threshold is 6.5%."
        body = f"<p>{quote}</p>".encode("utf-8")
        url = "https://example.org/e"
        self._write_manifest([{"id": "doc-e", "title": "E", "url": url, "doc_type": "html"}])
        self._write_criteria([{"doc_id": "doc-e", "quote": quote}])
        baseline_rows = [{
            "id": "doc-e", "url": url, "doc_type": "html",
            "checked_at": "2026-08-01T00:00:00Z", "http_code": "200", "status": "ok",
            "etag": None, "last_modified": None,
            "remote_sha256": "whatever", "text_sha256": "whatever-text",
            "quotes_total": 1, "quotes_verified": [quote], "quotes_never_verified": [],
        }]
        self._write_baseline(baseline_rows)
        before = drift.BASELINE.read_bytes()
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})

        code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        after = drift.BASELINE.read_bytes()
        self.assertEqual(before, after,
                         "平常執行(沒有 --update-baseline)不准動 baseline 檔")

    def test_update_baseline_writes_rows_sorted_by_id(self):
        urls = {"zzz-doc": "https://example.org/z", "aaa-doc": "https://example.org/a",
                "mmm-doc": "https://example.org/m"}
        self._write_manifest([
            {"id": doc_id, "title": doc_id, "url": url, "doc_type": "html"}
            for doc_id, url in urls.items()
        ])
        self._write_criteria([
            {"doc_id": doc_id, "quote": f"quote for {doc_id}"} for doc_id in urls
        ])
        drift.curl_with_headers = fake_curl({
            url: {"code": "200", "body": f"<p>quote for {doc_id}</p>".encode()}
            for doc_id, url in urls.items()
        })

        code, out = self._run_main(["--update-baseline", "--workers", "1", "--timeout", "5"])
        self.assertEqual(0, code, out)
        rows = json.loads(drift.BASELINE.read_text(encoding="utf-8"))
        ids = [r["id"] for r in rows]
        self.assertEqual(sorted(ids), ids, "baseline 必須依 id 排序寫出")
        self.assertEqual(set(urls), set(ids))
        for r in rows:
            self.assertEqual("ok", r["status"])

    def test_update_baseline_records_never_verified_not_drift_on_first_build(self):
        """第一次建 baseline 時,某份文件的引句就是驗不到(例如 JS 渲染)——
        這一輪不該是 drift(沒有『上一版』可比),要記 never-verified,而且
        quotes_never_verified 要把那句實際存下來(不是只存個數)。"""
        url = "https://example.org/js-rendered"
        self._write_manifest([{"id": "doc-f", "title": "F", "url": url, "doc_type": "html"}])
        quote = "This text only appears after JS runs."
        self._write_criteria([{"doc_id": "doc-f", "quote": quote}])
        drift.curl_with_headers = fake_curl({
            url: {"code": "200", "body": b"<p>empty shell, no content yet</p>"}
        })

        code, out = self._run_main(["--update-baseline", "--workers", "1", "--timeout", "5"])
        self.assertEqual(0, code, out)
        rows = {r["id"]: r for r in json.loads(drift.BASELINE.read_text(encoding="utf-8"))}
        self.assertEqual("never-verified", rows["doc-f"]["status"])
        self.assertEqual([quote], rows["doc-f"]["quotes_never_verified"])
        self.assertEqual([], rows["doc-f"]["quotes_verified"])

    def test_missing_baseline_in_normal_mode_is_config_error(self):
        self._write_manifest([{"id": "doc-g", "title": "G",
                               "url": "https://example.org/g", "doc_type": "html"}])
        self._write_criteria([{"doc_id": "doc-g", "quote": "q"}])
        # 沒寫 baseline
        code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        self.assertEqual(3, code)

    def test_unknown_only_id_is_config_error(self):
        self._write_manifest([{"id": "doc-h", "title": "H",
                               "url": "https://example.org/h", "doc_type": "html"}])
        self._write_criteria([{"doc_id": "doc-h", "quote": "q"}])
        self._write_baseline([])
        code, out = self._run_main(["--only", "no-such-id", "--workers", "1", "--timeout", "5"])
        self.assertEqual(3, code)

    def test_explicit_report_and_json_paths_resolve_against_cwd_not_root(self):
        """CI 用 `--report drift-report.md` 期望它落在執行當下的 CWD（checkout 出
        的 repo 根），不是腳本算出來的 ROOT。這裡刻意讓假 CWD 跟 drift.ROOT 是兩個
        不同的暫存目錄，才測得出兩者真的分開，不是剛好同一個路徑蒙混過關。"""
        quote = "A1C threshold is 6.5%."
        body = f"<p>{quote}</p>".encode("utf-8")
        url = "https://example.org/cwd-test"
        self._write_manifest([{"id": "doc-cwd", "title": "CWD", "url": url, "doc_type": "html"}])
        self._write_criteria([{"doc_id": "doc-cwd", "quote": quote}])
        self._write_baseline([{
            "id": "doc-cwd", "url": url, "doc_type": "html",
            "checked_at": "2026-08-01T00:00:00Z", "http_code": "200", "status": "ok",
            "etag": None, "last_modified": None,
            "remote_sha256": "x", "text_sha256": "y",
            "quotes_total": 1, "quotes_verified": [quote], "quotes_never_verified": [],
        }])
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})

        fake_cwd = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fake_cwd, True)
        self.assertNotEqual(fake_cwd, self.tmp,
                            "fixture 設計錯誤：假 CWD 得跟 drift.ROOT 是不同目錄，"
                            "不然測不出兩者有沒有分開")
        old_cwd = pathlib.Path.cwd()
        os.chdir(fake_cwd)
        try:
            code, out = self._run_main(
                ["--report", "drift-report.md", "--json", "drift-report.json",
                 "--workers", "1", "--timeout", "5"])
        finally:
            os.chdir(old_cwd)

        self.assertEqual(0, code, out)
        self.assertTrue((fake_cwd / "drift-report.md").exists(),
                        "給了相對路徑的 --report，應落在執行當下的 CWD")
        self.assertTrue((fake_cwd / "drift-report.json").exists(),
                        "給了相對路徑的 --json，應落在執行當下的 CWD")
        self.assertFalse((self.tmp / "drift-report.md").exists(),
                         "不該跑去腳本的 ROOT 底下找")
        self.assertFalse((self.tmp / ".drift" / "report.md").exists(),
                         "給了 --report 就不該再落到預設的 ROOT/.drift/ 位置")

    def test_default_report_and_json_paths_land_under_root_drift_dir(self):
        """跟上一條對照：完全不給 --report／--json 時，才落到 ROOT/.drift/ 這個
        預設位置（而不是 CWD）——兩條路徑分流由『有沒有給 --report/--json』決定，
        不是由 CWD 決定。"""
        quote = "A1C threshold is 6.5%."
        body = f"<p>{quote}</p>".encode("utf-8")
        url = "https://example.org/default-path-test"
        self._write_manifest([{"id": "doc-i", "title": "I", "url": url, "doc_type": "html"}])
        self._write_criteria([{"doc_id": "doc-i", "quote": quote}])
        self._write_baseline([{
            "id": "doc-i", "url": url, "doc_type": "html",
            "checked_at": "2026-08-01T00:00:00Z", "http_code": "200", "status": "ok",
            "etag": None, "last_modified": None,
            "remote_sha256": "x", "text_sha256": "y",
            "quotes_total": 1, "quotes_verified": [quote], "quotes_never_verified": [],
        }])
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})

        fake_cwd = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fake_cwd, True)
        old_cwd = pathlib.Path.cwd()
        os.chdir(fake_cwd)
        try:
            code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        finally:
            os.chdir(old_cwd)

        self.assertEqual(0, code, out)
        self.assertTrue((self.tmp / ".drift" / "report.md").exists(),
                        "沒給 --report 時應落在 ROOT/.drift/report.md")
        self.assertTrue((self.tmp / ".drift" / "report.json").exists())
        self.assertFalse((fake_cwd / "report.md").exists(),
                         "沒給 --report 時不該落到 CWD")


if __name__ == "__main__":
    unittest.main()
