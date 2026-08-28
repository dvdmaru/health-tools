#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收據 gate 的回歸測試（scripts/check-receipts.py）。

守兩件事：

1. **真資料是綠的**：data/criteria 的三個檔全部通過 schema，且每個 doc_id 指得到
   manifest。（引句能不能 grep 回快照由 gate 本身在 CI 跑，不在這裡重跑一次——
   licensed-cite-only 的快照不入版控，CI 上抓不到檔案，重跑只會得到一片 SKIP。）

2. **gate 真的會紅**：這才是重點。一道從來沒紅過的 gate 等於沒有 gate，
   所以下面用「刻意抄錯的引句」「指不到來源的 doc_id」「空引句」三個 fixture
   在暫存目錄裡跑真的腳本，逐個確認 exit code 是 1。
   還有一個 browser-needed fixture，確認快照沒到手時印的是 SKIP 而**不是** PASS——
   把「還沒驗」講成「驗過了」，比直接紅還危險。

☠️ 這裡沒有例外清單，也不准加。gate 紅了就是停下來給人裁決。
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "check-receipts.py"
SRC_DIR = ROOT / "data" / "sources"
CRIT_DIR = ROOT / "data" / "criteria"

MANIFEST = json.loads((SRC_DIR / "manifest.json").read_text(encoding="utf-8"))
SOURCE_IDS = {s["id"] for s in MANIFEST}

# 與 scripts/check-receipts.py 同規則：動態掃 data/criteria/*.json（schema 檔除外），
# 新指標落地不必回來改這裡，也不會出現「檔在、測試沒掃」的假綠。
def _data_files() -> dict:
    out = {}
    for f in sorted(CRIT_DIR.glob("*.json")):
        if f.name.endswith("schema.json"):
            continue
        if f.name.endswith("-history.json"):
            out[f.name] = "history-schema.json"
        elif f.name.endswith("-interference.json"):
            out[f.name] = "interference-schema.json"
        else:
            out[f.name] = "schema.json"
    return out


DATA_FILES = _data_files()

# 刻意未被引用的來源（每一份都要說得出為什麼）：
#   NGSP 兩份＝單位換算來源，尚未建換算列。
#   其餘＝M4 抓了快照但判準列落在別的 id 或該頁零判準（見 manifest note）；接上或移除時同步改這裡。
EXPECTED_ORPHANS = {"ngsp-convert-table", "ngsp-ifcc-standardization"}

# 一段確定會出現在 fixture 快照裡的原文，與一段確定不會出現的。
GOOD_QUOTE = "A1C ≥6.5% (≥48 mmol/mol)."
# ☠️ 刻意抄錯：把 6.5 寫成 6.4。這種錯不會被 schema 擋（型別、長度、白名單全都合法），
#    只有「回去 grep 原文」抓得到——這正是收據 gate 存在的理由。
BAD_QUOTE = "A1C ≥6.4% (≥48 mmol/mol)."
SNAPSHOT_BODY = (
    "Table 2.1 Criteria for the diagnosis of diabetes in nonpregnant individuals\n"
    "A1C ≥6.5%\n(≥48 mmol/mol). The test should be performed in a laboratory.\n"
)


def make_row(**over):
    row = {
        "indicator_id": "hba1c", "org": "American Diabetes Association",
        "doc_id": "fixture-doc", "version": "2026", "category": "diagnosis",
        "lower": 6.5, "upper": None, "unit": "%（NGSP）",
        "population": "非孕成人（一般）", "page_or_table": "Table 2.1",
        "quote": GOOD_QUOTE, "fetched_at": "2026-08-28",
    }
    row.update(over)
    return row


class TestRealData(unittest.TestCase):
    def test_each_data_file_validates_against_its_schema(self):
        for fname, sname in DATA_FILES.items():
            with self.subTest(file=fname):
                schema = json.loads((CRIT_DIR / sname).read_text(encoding="utf-8"))
                rows = json.loads((CRIT_DIR / fname).read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
                Draft202012Validator(schema).validate(rows)
                self.assertGreater(len(rows), 0, f"{fname} 是空的")

    def test_every_doc_id_resolves_to_a_source(self):
        """指不到來源的判準列不得渲染——所以先讓它在測試裡就爆。"""
        for fname in DATA_FILES:
            rows = json.loads((CRIT_DIR / fname).read_text(encoding="utf-8"))
            for i, row in enumerate(rows):
                ids = [row["doc_id"]] + [c["doc_id"] for c in row.get("corroboration", [])]
                for doc_id in ids:
                    with self.subTest(file=fname, row=i, doc_id=doc_id):
                        self.assertIn(doc_id, SOURCE_IDS,
                                      f"{fname} 第 {i + 1} 列的 doc_id 不在 manifest")

    def test_no_quote_is_empty(self):
        for fname in DATA_FILES:
            rows = json.loads((CRIT_DIR / fname).read_text(encoding="utf-8"))
            for i, row in enumerate(rows):
                with self.subTest(file=fname, row=i):
                    self.assertTrue(row["quote"].strip(), "空引句＝這一列沒有出處")
                    for q in row.get("quote_extra", []):
                        self.assertTrue(q.strip())

    def test_screening_thresholds_are_not_labelled_diagnosis(self):
        """☠️ 5.9%／<5.7%／<100 是篩檢分流門檻，標成 diagnosis 就會在頁面上
        把操作門檻講成診斷線。"""
        rows = json.loads((CRIT_DIR / "hba1c.json").read_text(encoding="utf-8"))
        triage = [r for r in rows if r["category"] == "screening_triage"]
        self.assertTrue(triage, "篩檢分流列不見了")
        for r in triage:
            with self.subTest(quote=r["quote"][:20]):
                self.assertEqual("daroc-t2dm-guideline-2022", r["doc_id"])
        for r in rows:
            if r["category"] == "diagnosis" and r["indicator_id"] == "hba1c":
                with self.subTest(quote=r["quote"][:20]):
                    self.assertEqual(6.5, r["lower"],
                                     "HbA1c 的 diagnosis 列下界只能是 6.5")

    def test_licensed_cite_only_snapshots_are_git_ignored(self):
        """licensed-cite-only＝不得落地公開快照。這個 repo 是 public 的，
        所以這些快照必須被 .gitignore 擋住；漏一份就是把整份文件重製上公開網路。"""
        for s in MANIFEST:
            if s["license_bucket"] != "licensed-cite-only" or not s.get("local_path"):
                continue
            with self.subTest(source=s["id"]):
                r = subprocess.run(["git", "check-ignore", "-q", s["local_path"]],
                                   cwd=ROOT)
                self.assertEqual(0, r.returncode,
                                 f"{s['local_path']} 是 licensed-cite-only，"
                                 f"必須加進 .gitignore")

    def test_source_ids_are_all_referenced_or_deliberately_unused(self):
        """manifest 裡的來源沒被任何列引用時要看得見——孤兒來源不是錯，
        但要是「我們知道它在那裡」，不是「忘了接上」。"""
        used = set()
        for fname in DATA_FILES:
            for row in json.loads((CRIT_DIR / fname).read_text(encoding="utf-8")):
                used.add(row["doc_id"])
                used.update(c["doc_id"] for c in row.get("corroboration", []))
        unused = SOURCE_IDS - used
        self.assertEqual(EXPECTED_ORPHANS, unused,
                         "manifest 裡出現了預期外的孤兒來源（或預期的孤兒被接上了）")


class GateFixtureCase(unittest.TestCase):
    """把 gate 腳本複製到暫存目錄，餵它假資料，看它紅不紅。"""

    def run_gate(self, criteria_rows, sources=None, snapshot=SNAPSHOT_BODY,
                 errata=None):
        tmp = pathlib.Path(tempfile.mkdtemp())
        try:
            (tmp / "scripts").mkdir()
            (tmp / "data" / "sources").mkdir(parents=True)
            (tmp / "data" / "criteria").mkdir(parents=True)
            shutil.copy(GATE, tmp / "scripts" / "check-receipts.py")
            if sources is None:
                sources = [{
                    "id": "fixture-doc", "title": "fixture", "org": "fixture",
                    "doc_type": "html", "url": "https://example.org/",
                    "version_or_date": "2026", "fetched_at": "2026-08-28",
                    "sha256": "0" * 64,
                    "local_path": "data/sources/fixture-doc.html",
                    "license_bucket": "us-federal-pd", "retrieval": "curl",
                }]
            for s in sources:
                if s.get("local_path") and snapshot is not None:
                    (tmp / s["local_path"]).write_text(snapshot, encoding="utf-8")
            (tmp / "data" / "sources" / "manifest.json").write_text(
                json.dumps(sources, ensure_ascii=False), encoding="utf-8")
            (tmp / "data" / "criteria" / "hba1c.json").write_text(
                json.dumps(criteria_rows, ensure_ascii=False), encoding="utf-8")
            for f in ("hba1c-history.json", "hba1c-interference.json"):
                (tmp / "data" / "criteria" / f).write_text("[]", encoding="utf-8")
            # errata=None＝這個 fixture 根目錄沒有 data/errata.json。gate 對「檔不在」
            # 是不掃也不報錯（其他所有 fixture 都走這條路，等於同時驗了那個分支）。
            if errata is not None:
                (tmp / "data" / "errata.json").write_text(
                    json.dumps(errata, ensure_ascii=False), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(tmp / "scripts" / "check-receipts.py")],
                capture_output=True, text=True, cwd=tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestGateGoesGreen(GateFixtureCase):
    def test_correct_quote_passes(self):
        """對照組：引句抄對就該過。沒有這一條，下面的紅可能是別的原因紅的。"""
        r = self.run_gate([make_row()])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("PASS 1", r.stdout)
        self.assertIn("FAIL 0", r.stdout)

    def test_whitespace_differences_still_pass(self):
        """快照裡的 6.5% 與 (≥48 之間有換行——比對前正規化空白，不得因此判不符。"""
        r = self.run_gate([make_row(quote="A1C ≥6.5% (≥48 mmol/mol).")])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)

    def test_halfwidth_is_not_folded_into_fullwidth(self):
        """全形半形不轉換：把 ≥ 寫成全形的 ≧ 就該紅。
        來源自己的 ≧／≥ 不一致是回查原文的指紋，正規化掉等於拆了『引句照抄』這條紅線。"""
        r = self.run_gate([make_row(quote="A1C ≧6.5% (≥48 mmol/mol).")])
        self.assertEqual(1, r.returncode,
                         "全形 ≧ 對半形 ≥ 的快照應該判不符，不得被正規化掉")


class TestGateGoesRed(GateFixtureCase):
    def test_wrong_quote_fails(self):
        """刻意抄錯的引句（6.5 寫成 6.4）必須讓 gate 紅。"""
        r = self.run_gate([make_row(quote=BAD_QUOTE)])
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("FAIL 1", r.stdout)
        self.assertIn("引句在快照中找不到", r.stdout)
        self.assertIn(BAD_QUOTE, r.stdout)

    def test_wrong_quote_in_quote_extra_fails(self):
        """quote_extra 不是備註欄——裡面的每一句同樣要 grep 得到。"""
        r = self.run_gate([make_row(quote_extra=[BAD_QUOTE])])
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("quote_extra[0]", r.stdout)

    def test_unknown_doc_id_fails(self):
        r = self.run_gate([make_row(doc_id="no-such-source")])
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("不在 manifest", r.stdout)

    def test_empty_quote_fails(self):
        r = self.run_gate([make_row(quote="   ")])
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("引句為空", r.stdout)

    def test_one_bad_row_among_good_ones_still_fails(self):
        """☠️ 通過率不是驗收標準：一列紅，整個 gate 就紅。"""
        r = self.run_gate([make_row(), make_row(quote=BAD_QUOTE), make_row()])
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("PASS 2", r.stdout)
        self.assertIn("FAIL 1", r.stdout)


def make_erratum(**over):
    """勘誤列的最小形狀（doc_id／quote 是選填，所以預設不給）。"""
    row = {"id": "E1", "date": "2026-09-15", "slug": "hba1c", "section": "table",
           "was": "篩檢分流：≥5.9%", "now": "篩檢分流（非診斷判準）：≥5.9%",
           "reason": "原標籤沒在表上寫明這不是診斷線。"}
    row.update(over)
    return row


class TestErrataReceipts(GateFixtureCase):
    """勘誤列也要收據：填了 doc_id 就得拿得出那份文件的原文。

    ☠️ 但沒填 doc_id 的列是「跳過」不是 FAIL——多數勘誤是我們自己的筆誤，本來就
    沒有外部依據。把它判 FAIL 會逼人編一個 doc_id 出來，那才是把出處變成事後編的。
    """

    def test_document_backed_erratum_with_the_right_quote_passes(self):
        r = self.run_gate([make_row()],
                          errata=[make_erratum(doc_id="fixture-doc", quote=GOOD_QUOTE)])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("PASS 2", r.stdout)
        self.assertIn("FAIL 0", r.stdout)

    def test_document_backed_erratum_with_a_wrong_quote_fails(self):
        r = self.run_gate([make_row()],
                          errata=[make_erratum(doc_id="fixture-doc", quote=BAD_QUOTE)])
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("errata:E1", r.stdout)
        self.assertIn("引句在快照中找不到", r.stdout)

    def test_erratum_without_a_document_is_skipped_not_failed(self):
        r = self.run_gate([make_row()], errata=[make_erratum()])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("PASS 1", r.stdout)
        self.assertIn("FAIL 0", r.stdout)
        self.assertNotIn("errata:E1", r.stdout)

    def test_an_empty_errata_file_is_fine(self):
        r = self.run_gate([make_row()], errata=[])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("FAIL 0", r.stdout)

    def test_erratum_pointing_at_an_unknown_source_fails(self):
        r = self.run_gate([make_row()],
                          errata=[make_erratum(doc_id="no-such-source",
                                               quote=GOOD_QUOTE)])
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("不在 manifest", r.stdout)


class TestGateSkipsHonestly(GateFixtureCase):
    def test_missing_snapshot_is_skip_not_pass(self):
        """快照還沒到手時，必須印 SKIP。印成 PASS 等於宣稱驗過了。"""
        sources = [{
            "id": "fixture-doc", "title": "fixture", "org": "fixture",
            "doc_type": "html", "url": "https://example.org/",
            "version_or_date": "2026", "fetched_at": "2026-08-28",
            "sha256": "", "local_path": "", "license_bucket": "licensed-cite-only",
            "retrieval": "browser-needed",
        }]
        r = self.run_gate([make_row()], sources=sources)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("SKIP", r.stdout)
        self.assertIn("PASS 0", r.stdout)
        self.assertIn("SKIP 1", r.stdout)
        self.assertIn("待補快照的來源", r.stdout)

    def test_gate_has_no_exception_list(self):
        """☠️ 驗證教義第 2 條：最大的風險是『gate 紅了就把錯誤塞進例外清單』。
        這道 gate 刻意不提供例外機制——出現這些字眼就是有人開始合法化失敗。"""
        src = GATE.read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        code = code.split('"""')[0] + '"""'.join(code.split('"""')[2:])
        for token in ("KNOWN_FAILURES", "ALLOWLIST", "ALLOWED_FAILURES",
                      "EXPECTED_FAILURES", "IGNORE_QUOTES", "WAIVER"):
            with self.subTest(token=token):
                self.assertNotIn(token, code,
                                 f"收據 gate 出現例外清單（{token}）——不准把驗不過的列合法化")


if __name__ == "__main__":
    unittest.main()
