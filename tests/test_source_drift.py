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
    （模擬 unreachable）。回傳是 (code, body, headers, tls_verified)——tls_verified
    預設 True，情境需要時用 entry["tls_verified"]=False 覆寫（見 fake_run_curl，
    exit-60 重抓那條真正的路徑則另外用它測，不靠這裡覆寫）。"""
    def _fn(url, timeout):
        if url not in url_map:
            raise OSError(f"fixture 沒有這個 url 的回應：{url}")
        entry = url_map[url]
        if "raise" in entry:
            raise OSError(entry["raise"])
        return (entry["code"], entry["body"], entry.get("headers", {}),
                entry.get("tls_verified", True))
    return _fn


def fake_run_curl(url_map: dict):
    """回一個取代 drift._run_curl 的函式，讓 drift.curl_with_headers 本尊的
    exit-60 重抓邏輯照跑，只是底層那次「真的打 curl」換成查表。
    url_map[url] = {"secure": (rc, stderr, code, body, headers),
                     "insecure": (...)}（沒給 insecure 就兩次都吃 secure 那組）。"""
    def _fn(url, timeout, insecure):
        entry = url_map[url]
        key = "insecure" if insecure and "insecure" in entry else "secure"
        return entry[key]
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

    def test_reachable_response_marks_tls_verified_true(self):
        """對照組：正常一次就成功的情境，tls_verified 該是 True（沒有繞過憑證）。"""
        url = "https://example.org/normal-tls"
        body = b"<p>fine</p>"
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})
        src = {"id": "normal-doc", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, set(), timeout=5)
        self.assertIs(True, result["tls_verified"])

    def test_body_bytes_and_text_chars_are_populated_on_every_reached_result(self):
        """2026-08-28 CI 第二輪教訓（iec-a1c-report-2009）：HTTP 200、引句全缺，
        但當時的結果完全沒有『這次到底抓到多少東西』這種基本診斷欄位。body_bytes／
        text_chars 現在應該在每一份『抓得到』的結果上都算出來，不只 drift 那份。"""
        body = "<p>The quick brown fox jumps over the lazy dog.</p>".encode("utf-8")
        url = "https://example.org/body-bytes-doc"
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})
        src = {"id": "body-bytes-doc", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, set(), timeout=5)

        self.assertEqual(len(body), result["body_bytes"])
        self.assertGreater(result["text_chars"], 0)
        # 正規化文字長度：全部空白吃光,一定 <= 原始去 tag 文字長度
        self.assertLessEqual(result["text_chars"], len(body))

    def test_body_bytes_is_none_when_unreachable(self):
        """沒抓到任何 body 時,body_bytes 老實留 None,不要假裝算出了 0。"""
        url = "https://example.org/never-connects"
        drift.curl_with_headers = fake_curl({url: {"raise": "curl exit 28: timeout"}})
        src = {"id": "never-connects", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, set(), timeout=5)
        self.assertIsNone(result["body_bytes"])
        self.assertIsNone(result["text_chars"])

    def test_page_title_extracted_from_raw_title_tag(self):
        """抽的是原始 body 的 <title>，不是 extract_text() 去 tag 後的版本——
        title 本身就含 tag 語意（例如攔截頁跟原文件的 <title> 通常不一樣）。"""
        body = ("<html><head><title>  Some Interstitial   Page  </title></head>"
                "<body><p>nothing here</p></body></html>").encode("utf-8")
        url = "https://example.org/titled-doc"
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})
        src = {"id": "titled-doc", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, set(), timeout=5)
        self.assertEqual("Some Interstitial Page", result["_page_title"])

    def test_page_title_is_empty_string_when_no_title_tag_or_pdf(self):
        body = b"<html><body><p>no title here</p></body></html>"
        url = "https://example.org/no-title-doc"
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})
        src = {"id": "no-title-doc", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, set(), timeout=5)
        self.assertEqual("", result["_page_title"])

        pdf_bytes = make_pdf_bytes(["irrelevant"])
        url2 = "https://example.org/no-title.pdf"
        drift.curl_with_headers = fake_curl({url2: {"code": "200", "body": pdf_bytes}})
        src2 = {"id": "no-title-pdf", "title": "t", "url": url2, "doc_type": "pdf"}
        result2 = drift.check_source(src2, set(), timeout=5)
        self.assertEqual("", result2["_page_title"])


class TestCurlExit60RetriesInsecure(unittest.TestCase):
    """2026-08-28 CI 實測：hpa.gov.tw 在 Ubuntu runner 上對 curl 回 exit 60
    （SSL certificate problem: unable to get local issuer certificate），本機
    macOS 靠系統鑰匙圈矇混過去、Ubuntu 沒有那個中繼憑證就不通。這裡直接 monkeypatch
    `drift._run_curl`（curl_with_headers 內部真正呼叫 curl 的那一層），讓
    curl_with_headers 本尊的重抓判斷邏輯照跑，不是繞過它。"""

    def setUp(self):
        self._orig_run_curl = drift._run_curl
        self.addCleanup(setattr, drift, "_run_curl", self._orig_run_curl)

    def test_exit_60_then_insecure_retry_succeeds_marks_tls_unverified(self):
        quote = "A1C threshold is 6.5%."
        body = f"<p>{quote}</p>".encode("utf-8")
        url = "https://hpa.example.gov.tw/page"
        drift._run_curl = fake_run_curl({
            url: {
                "secure": (60, b"SSL certificate problem: unable to get local "
                              b"issuer certificate", "", b"", {}),
                "insecure": (0, b"", "200", body, {}),
            }
        })
        src = {"id": "tls-doc", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, {quote}, timeout=5)

        self.assertEqual("reached", result["fetch_status"])
        self.assertIs(False, result["tls_verified"],
                      "exit 60 重抓成功後應該老實標記『沒驗證憑證』")
        self.assertEqual(1, result["quotes_found"])
        self.assertEqual("200", result["http_code"])

    def test_exit_60_then_insecure_retry_also_fails_is_unreachable(self):
        url = "https://hpa.example.gov.tw/still-broken"
        drift._run_curl = fake_run_curl({
            url: {
                "secure": (60, b"SSL certificate problem", "", b"", {}),
                "insecure": (35, b"SSL connect error", "", b"", {}),
            }
        })
        src = {"id": "tls-doc-2", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, set(), timeout=5)
        self.assertEqual("unreachable", result["fetch_status"])

    def test_non_60_curl_error_does_not_trigger_insecure_retry(self):
        """只有 exit 60 才重抓——其他錯誤（例如逾時 28）不該多打一次 -k。"""
        url = "https://example.org/timeout"
        calls = []

        def spy(url_, timeout, insecure):
            calls.append(insecure)
            return (28, b"Operation timed out", "", b"", {})

        drift._run_curl = spy
        src = {"id": "timeout-doc-2", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, set(), timeout=5)
        self.assertEqual("unreachable", result["fetch_status"])
        self.assertEqual([False], calls, "exit 28 不該觸發 -k 重抓")


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
        """PDF 的 raw sha 變了但抽出來的正文(text_sha256)沒變，只算
        changed-quotes-intact，不是 drift——實測 eular-gout-recommendations-2016
        這份 PDF 連續 curl 三次會出現兩種不同 raw sha256（size 相同），但三次的
        text_sha256 都一樣，證明 raw bytes 本身就不穩定，拿它當 drift 訊號只會
        天天假警報。"""
        c = cur(doc_type="pdf", remote_sha256="pdf-b", text_sha256="text-a")
        self.assertEqual("changed-quotes-intact",
                         drift.classify(c, baseline(remote_sha256="pdf-a"), building=False))

    def test_pdf_text_sha_change_alone_is_also_not_drift(self):
        """2026-08-28 CI 首次實跑推翻了『text_sha256 變＝PDF drift』：baseline 在
        本機 macOS 建、CI 在 Ubuntu 跑，兩邊 pdftotext(poppler-utils)版本不保證
        一致，同一份沒改版的 PDF 抽出來的文字本身就可能不同，5 份 PDF
        （jsgna／jnc7／atp3／who-trs894／who-waist）因此被本機規則誤判 drift。
        改成跟 HTML 同一條規則：sha（raw 或 text）變了只算 changed-quotes-intact，
        drift 只認『baseline 驗過在的引句現在找不到』。"""
        c = cur(doc_type="pdf", remote_sha256="pdf-a", text_sha256="text-b")
        self.assertEqual("changed-quotes-intact",
                         drift.classify(c, baseline(remote_sha256="pdf-a", text_sha256="text-a"),
                                        building=False))

    def test_pdf_quote_missing_is_still_drift_regardless_of_sha(self):
        """sha 不再是 PDF 的 drift 訊號，但『引句消失』這條 HTML／PDF 共用的規則
        對 PDF 一樣有效——不能因為拿掉 sha 規則就連這條也弱化了。"""
        c = cur(doc_type="pdf", _found=set(), _missing={"Q1"},
               remote_sha256="pdf-a", text_sha256="text-a")
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


class TestChallengePageIsBlockedNotDrift(unittest.TestCase):
    """人機挑戰頁（reCAPTCHA）＝blocked，不是 drift。

    2026-08-31 issue #22：PMC 對 GitHub runner IP 回一頁 HTTP 200 的
    「Checking your browser - reCAPTCHA」——body 兩萬多 bytes、可見文字只有一百多
    字元、四份來源的引句同時全消失，於是四份都被判成 drift＝每週一次假警報。
    攔截頁本來就該歸 blocked（「無法確認，需瀏覽器」，不是 ok 也不是改版），
    只是指紋漏收了這一型：標題沒有既有的 WAF 字樣，body 又超過
    _WAF_BODY 那條 <4096 的門檻。
    """

    def setUp(self):
        self._orig_curl = drift.curl_with_headers
        self.addCleanup(setattr, drift, "curl_with_headers", self._orig_curl)

    @staticmethod
    def _challenge_body(title):
        """照 issue #22 的形狀手刻：body 由 JS 撐到兩萬多 bytes，可見文字極短。"""
        padding = b"<script>" + b"var a=1;" * 2500 + b"</script>"
        return ((f"<html><head><title>{title}</title></head><body>"
                 "<p>Checking your browser before accessing pmc.example.org</p>"
                 "<p>Click here if you are not automatically redirected "
                 "after 5 seconds.</p></body>").encode("utf-8")
                + padding + b"</html>")

    def test_recaptcha_title_is_blocked_not_reached(self):
        url = "https://pmc.example.org/articles/PMC123456/"
        body = self._challenge_body("Checking your browser - reCAPTCHA")
        self.assertGreater(len(body), 4096,
                           "測資必須大於舊的 <4096 門檻，否則測不到這個洞")
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})
        src = {"id": "pmc-doc", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(
            src, {"For patients with asymptomatic hyperuricemia"}, timeout=5)
        self.assertEqual("blocked", result["fetch_status"])

    def test_challenge_body_is_blocked_even_when_title_looks_normal(self):
        """標題被換掉也要擋得住——指紋不能只靠 <title> 一個訊號。"""
        url = "https://pmc.example.org/articles/PMC654321/"
        body = self._challenge_body("PMC Article Viewer")
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})
        src = {"id": "pmc-doc-2", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, {"any quote"}, timeout=5)
        self.assertEqual("blocked", result["fetch_status"])

    def test_document_mentioning_recaptcha_in_prose_is_not_blocked(self):
        """陰性對照：指紋錨在 <title> 與挑戰頁那句文案，正文提到 reCAPTCHA 不算攔截。
        沒有這一條，指紋放寬到哪裡就沒人知道了。"""
        quote = "Stratified LDL-C goals have been reintroduced"
        url = "https://example.org/real-doc"
        body = ("<html><head><title>Management of Blood Cholesterol</title></head>"
                "<body><p>The publisher previously used a reCAPTCHA gate for "
                f"downloads.</p><p>{quote} for high-risk patients.</p>"
                "</body></html>").encode("utf-8")
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})
        src = {"id": "real-doc", "title": "t", "url": url, "doc_type": "html"}
        result = drift.check_source(src, {quote}, timeout=5)
        self.assertEqual("reached", result["fetch_status"])
        self.assertIn(quote, result["_found"])

    def test_blocked_challenge_never_reported_as_drift(self):
        """分類層的把關：fetch_status=blocked 時，引句全缺也不准變成 drift
        （blocked 仍會列進報告的 blocked 清單，不是靜默放行）。"""
        c = cur(fetch_status="blocked", _found=set(), _missing={"Q1"},
                remote_sha256="sha-challenge", text_sha256="text-challenge")
        self.assertEqual("blocked", drift.classify(c, baseline(), building=False))


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

    def test_ok_row_carries_body_bytes_and_text_chars_in_json(self):
        """body_bytes／text_chars 是『每份結果』的欄位，不是只有 drift 才有——
        隨便挑一份 ok 的來源，JSON 裡也該看得到。"""
        quote = "A1C threshold is 6.5%."
        body = f"<p>{quote}</p>".encode("utf-8")
        url = "https://example.org/diag-ok"
        self._write_manifest([{"id": "diag-ok", "title": "OK", "url": url, "doc_type": "html"}])
        self._write_criteria([{"doc_id": "diag-ok", "quote": quote}])
        self._write_baseline([{
            "id": "diag-ok", "url": url, "doc_type": "html",
            "checked_at": "2026-08-01T00:00:00Z", "http_code": "200", "status": "ok",
            "etag": None, "last_modified": None,
            "remote_sha256": "x", "text_sha256": "y",
            "quotes_total": 1, "quotes_verified": [quote], "quotes_never_verified": [],
        }])
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})

        code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        self.assertEqual(0, code, out)
        rows = json.loads((drift.DEFAULT_OUT_DIR / "report.json").read_text(encoding="utf-8"))
        row = next(r for r in rows if r["id"] == "diag-ok")
        self.assertEqual(len(body), row["body_bytes"])
        self.assertGreater(row["text_chars"], 0)
        self.assertNotIn("text_excerpt", row, "非 drift 列不該背 text_excerpt")
        self.assertNotIn("page_title", row, "非 drift 列不該背 page_title")

    def test_drift_row_carries_diagnostics_and_all_quotes_missing_warning_fires(self):
        """2026-08-28 CI 第二輪教訓：iec-a1c-report-2009 HTTP 200、4/4 引句全缺，
        baseline 4 句全驗過——這正是警語該觸發的情境。"""
        url = "https://example.org/interstitial"
        self._write_manifest([{"id": "doc-j", "title": "J", "url": url, "doc_type": "html"}])
        self._write_criteria([
            {"doc_id": "doc-j", "quote": "first threshold sentence"},
            {"doc_id": "doc-j", "quote": "second threshold sentence"},
        ])
        self._write_baseline([{
            "id": "doc-j", "url": url, "doc_type": "html",
            "checked_at": "2026-08-01T00:00:00Z", "http_code": "200", "status": "ok",
            "etag": None, "last_modified": None,
            "remote_sha256": "old", "text_sha256": "old-text",
            "quotes_total": 2,
            "quotes_verified": ["first threshold sentence", "second threshold sentence"],
            "quotes_never_verified": [],
        }])
        # 標題刻意不用「Just a moment」「Attention Required」這類已經被
        # blocked_reason() 認得的既有 WAF 指紋——這裡要測的是「連現有指紋都認不出
        # 來的陌生替代頁面」，那正是這批診斷欄位存在的理由（已知指紋早就被判
        # blocked，不會走到這裡）。
        interstitial = ("<html><head><title>PMC Article Viewer — Loading</title></head>"
                        "<body><p>This content requires a modern browser session.</p>"
                        "</body></html>").encode("utf-8")
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": interstitial}})

        code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        self.assertEqual(1, code, out)
        self.assertIn("PMC Article Viewer — Loading", out, "drift 明細該印出 <title>")
        self.assertIn("body_bytes", out)
        self.assertIn("text_chars", out)
        self.assertIn("This content requires a modern browser session", out,
                      "drift 明細該印出抽出文字前 300 字")
        self.assertIn("全部引句同時消失，較可能是攔截頁或替代頁面", out)

        rows = json.loads((drift.DEFAULT_OUT_DIR / "report.json").read_text(encoding="utf-8"))
        row = next(r for r in rows if r["id"] == "doc-j")
        self.assertEqual(len(interstitial), row["body_bytes"])
        self.assertEqual("PMC Article Viewer — Loading", row["page_title"])
        self.assertIn("This content requires a modern browser session", row["text_excerpt"])
        self.assertEqual(2, row["quotes_verified_at_baseline"])

    def test_warning_suppressed_when_some_quotes_still_found(self):
        """只有部分引句消失（quotes_found > 0）就不是『全部同時消失』，警語不該
        出現——即使整份仍然判 drift。"""
        url = "https://example.org/partial-drift"
        self._write_manifest([{"id": "doc-k", "title": "K", "url": url, "doc_type": "html"}])
        self._write_criteria([
            {"doc_id": "doc-k", "quote": "quote one stays"},
            {"doc_id": "doc-k", "quote": "quote two vanished"},
        ])
        self._write_baseline([{
            "id": "doc-k", "url": url, "doc_type": "html",
            "checked_at": "2026-08-01T00:00:00Z", "http_code": "200", "status": "ok",
            "etag": None, "last_modified": None,
            "remote_sha256": "old", "text_sha256": "old-text",
            "quotes_total": 2,
            "quotes_verified": ["quote one stays", "quote two vanished"],
            "quotes_never_verified": [],
        }])
        body = b"<p>quote one stays, but the other sentence is gone now.</p>"
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})

        code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        self.assertEqual(1, code, out)
        self.assertNotIn("全部引句同時消失", out)

    def test_warning_suppressed_when_only_one_quote_total(self):
        """只有 1 句判準的文件，就算那 1 句消失也不算『全部引句同時消失』這種
        多引句一致性訊號——quotes_total >= 2 才有意義，警語不該出現。"""
        url = "https://example.org/single-quote-drift"
        self._write_manifest([{"id": "doc-l", "title": "L", "url": url, "doc_type": "html"}])
        self._write_criteria([{"doc_id": "doc-l", "quote": "the only sentence"}])
        self._write_baseline([{
            "id": "doc-l", "url": url, "doc_type": "html",
            "checked_at": "2026-08-01T00:00:00Z", "http_code": "200", "status": "ok",
            "etag": None, "last_modified": None,
            "remote_sha256": "old", "text_sha256": "old-text",
            "quotes_total": 1, "quotes_verified": ["the only sentence"],
            "quotes_never_verified": [],
        }])
        body = b"<p>completely different content now.</p>"
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})

        code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        self.assertEqual(1, code, out)
        self.assertNotIn("全部引句同時消失", out)

    def test_warning_suppressed_when_baseline_did_not_verify_all_quotes(self):
        """baseline 當初就不是『全部驗過』（其中一句本來就是 never-verified）——
        就算這次全缺，也不能說『baseline 全找得到』，警語不該出現。"""
        url = "https://example.org/partial-baseline"
        self._write_manifest([{"id": "doc-m", "title": "M", "url": url, "doc_type": "html"}])
        self._write_criteria([
            {"doc_id": "doc-m", "quote": "verified quote"},
            {"doc_id": "doc-m", "quote": "never verified quote"},
        ])
        self._write_baseline([{
            "id": "doc-m", "url": url, "doc_type": "html",
            "checked_at": "2026-08-01T00:00:00Z", "http_code": "200", "status": "never-verified",
            "etag": None, "last_modified": None,
            "remote_sha256": "old", "text_sha256": "old-text",
            "quotes_total": 2,
            "quotes_verified": ["verified quote"],
            "quotes_never_verified": ["never verified quote"],
        }])
        body = b"<p>totally unrelated replacement content.</p>"
        drift.curl_with_headers = fake_curl({url: {"code": "200", "body": body}})

        code, out = self._run_main(["--workers", "1", "--timeout", "5"])
        self.assertEqual(1, code, out)
        self.assertNotIn("全部引句同時消失", out)

        rows = json.loads((drift.DEFAULT_OUT_DIR / "report.json").read_text(encoding="utf-8"))
        row = next(r for r in rows if r["id"] == "doc-m")
        self.assertEqual(1, row["quotes_verified_at_baseline"],
                         "baseline 只驗過 1 句，不是 2 句")


if __name__ == "__main__":
    unittest.main()
