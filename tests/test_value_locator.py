#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指標頁「數值定位」互動的 gate（SPEC-compare-feature.md 2026-08-31＋
2026-09-01 主席裁決：查驗席「改壞實作看測試會不會紅」挖出的三個洞）。

守的是規格與裁決裡明講「靠寫的人自律會壞」的那幾條：

1. data-* 屬性逐列與 criteria 相符（不是抽樣）。
2. server-rendered HTML 不含 <input>。
3. 邊界含不含等於（≥/> 之分、≤/< 之分）——查驗席變異：把
   `lowerExclusive ? v > lower : v >= lower` 改成永遠 `v >= lower`，290 個既有測試
   全綠，但尿酸 7.0（>7.0 的診斷列）、BMI 24.0（<24 的列）會被標錯。這條用
   subprocess 呼叫 node，把 withinBounds() 從 VALUE_LOCATOR_JS 抽出來單獨餵
   邊界案例表，不透過完整頁面（頁面級測試看不到這個洞——這正是查驗席的發現）。
4. 零儲存零請求——查驗席變異：插一行 localStorage.setItem(...) 全綠，因為沒有
   測試掃過 JS 原始碼本身。這條直接掃 VALUE_LOCATOR_JS／VALUE_LOCATOR_CSS 的
   原始碼字串（只掃定位器自己的常數，不掃整頁——頁面上既有的配色切換器本來就用
   localStorage，掃整頁永遠紅）。
5. 文案：CSS 的 content: 屬性是唯一能從 style 洩字到畫面上的路徑，查驗席變異
   `.vloc-badge::after{content:"（您的數值偏高，建議就醫）"}` 全綠、連站級
   check-health-terms.py 都 FAIL 0（因為它不掃 script/style，這是對的，站級 gate
   不改）。這裡把措辭檢查的範圍擴大到 VALUE_LOCATOR_CSS，禁詞表補招徠類
   （掛號／預約／線上諮詢／推薦醫師／名醫／門診／就醫／優惠／購買）。
6. 標記位置：2026-09-01 三方獨立收斂——縫進第四欄（依據文件）會讓「這句話是誰
   說的」出處欄與執行期輸出黏在一起，對 AI／RAG 抓取代價最高。移到「判準值」欄
   並加分隔字元；用 DOM shim（不依賴 jsdom，repo 沒有 node 依賴管理）跑真正的
   VALUE_LOCATOR_JS 驗證實際輸出的一行字。
7. 折疊造成的可見性偏差：CRIT_OPEN_CATEGORIES 讓「篩檢分流」預設收合，命中列
   若剛好落在收合組，畫面上完全看不到。裁決：有命中的組自動展開，預設收合規則
   本身不改。同一個 DOM shim 驗「命中在收合組」的實例。
8. 無命中：裁決要補「沒有列包含 X」，主詞是表格不是讀者，同樣受禁詞檢查。
9. REQUIRED_NOTE 的豁免射程釘死在剛好出現一次。

每一條「改壞會紅」的證明都用同一支 DOM shim／node harness 對「正確版」與
「被我在測試裡動態注入的壞版 JS」各跑一次，斷言正確版通過、壞版失敗——不必
真的改 gen-indicator.py 本體，測試自己模擬變異。

☠️ 規格第 7 條要求的固定說明句本身含「代表」（「不判斷這代表什麼」）——這個字也在
第 2 條的禁詞清單裡。這不是漏檢：規則 2 禁的是「對輸入值的評語」，這句話是工具對
自己功能的免責聲明，不是評語，且規格第 7 條逐字要求輸出這句話。處理方式比照全域
規則既有的先例（工作表「我的數值」欄位標籤、site_footer_html 既有免責聲明都是
明文例外）：掃描禁詞前先把這句規格要求的固定句挖掉，其餘 JS／CSS 原始碼一個字
都不放過。
"""
import html as html_lib
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("gen_indicator_vloc_test", "scripts/gen-indicator.py")

ARTICLES = sorted((ROOT / "articles" / "indicators").glob("*.md"))

NODE = shutil.which("node")

# 規格規定的固定字面（硬規則 #7），與說明句/標記模板要逐字相符的來源。
REQUIRED_NOTE = "只標出數值落在哪些列，不判斷這代表什麼。"
# 2026-09-01 裁決要補的無命中句，字面與「此列包含 X」對稱（主詞是表格不是讀者）。
REQUIRED_NO_HIT = "沒有列包含 "

# ---------- 禁詞清單（SPEC 硬規則 #1、#2 逐字抄＋2026-09-01 裁決補的招徠類）----------
SECOND_PERSON_WORDS = ["你的", "您的", "你", "您"]
EVAL_WORDS = ["是", "屬於", "代表", "應該", "建議", "需要",
              "要去看", "請就醫", "注意", "小心", "偏高", "偏低", "異常", "正常"]
SOLICITATION_WORDS = ["掛號", "預約", "線上諮詢", "推薦醫師", "名醫",
                      "門診", "就醫", "優惠", "購買"]
BANNED_WORDS = SECOND_PERSON_WORDS + EVAL_WORDS + SOLICITATION_WORDS

# 零儲存／零請求：只掃定位器自己的產出（VALUE_LOCATOR_JS／CSS），不掃整頁——
# 頁面上既有的配色切換器（healthlib.THEME_SWITCH_JS）本來就用 localStorage，
# 掃整頁會把站上既有、規格管不到的元件也算進來，變成永遠紅。
STORAGE_NETWORK_PATTERNS = [
    "localStorage", "sessionStorage", "document.cookie",
    "fetch(", "XMLHttpRequest", "sendBeacon",
]


def scan_banned(text: str) -> list:
    """回傳文字裡命中的禁詞（有序、可重複，方便除錯）。零命中回空 list。"""
    return [w for w in BANNED_WORDS if w in text]


def scan_storage_network(text: str) -> list:
    return [p for p in STORAGE_NETWORK_PATTERNS if p in text]


TR_RE = re.compile(r"<tr([^>]*)>")
ATTR_RE = re.compile(r'(data-[a-z-]+)="([^"]*)"')


def parse_data_trs(html_text: str) -> Counter:
    """抓出所有帶 data-indicator 的 <tr> 標籤，回傳 attrs（frozenset）的 multiset。

    用 Counter 而不是照順序比對：同一批列裡本來就可能有兩列的 lower/upper/unit/
    indicator 剛好相同（機構不同），順序不是這條測試要驗的（gen-indicator 既有的
    test_gen_indicator.py 已經驗過組序），這裡只驗「這些屬性值真的和資料逐列對得上」。
    """
    out = []
    for m in TR_RE.finditer(html_text):
        seg = m.group(1)
        if "data-indicator=" not in seg:
            continue
        attrs = {k: html_lib.unescape(v) for k, v in ATTR_RE.findall(seg)}
        out.append(frozenset(attrs.items()))
    return Counter(out)


def expected_attrs(r: dict) -> frozenset:
    """獨立重算一次「這一列應該長出的 data-* 屬性」——刻意不呼叫
    gen.row_data_attrs()（受測函式），避免測試只是在照鏡子。"""
    out = {"data-indicator": r["indicator_id"]}
    lo, up, unit = r.get("lower"), r.get("upper"), r.get("unit")
    if lo is not None:
        out["data-lower"] = json.dumps(lo)
        if r.get("lower_inclusive") is False:
            out["data-lower-inclusive"] = "false"
    if up is not None:
        out["data-upper"] = json.dumps(up)
        if r.get("upper_inclusive") is False:
            out["data-upper-inclusive"] = "false"
    if unit:
        out["data-unit"] = unit
    return frozenset(out.items())


def build_all() -> dict:
    """把五個指標頁全部生到暫存目錄，回傳 {slug: html}。不動 repo 內的產物。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        out = tmp / "public-health"
        out.mkdir()
        (out / "llms.txt").write_text(
            "# 健檢數據誌\n\n## 引用說明\n\n- 一行。\n", encoding="utf-8")
        gen.build(out_root=out, parts_dir=tmp / "parts",
                  llms_path=out / "llms.txt", published=True)
        return {
            f.parent.name: f.read_text(encoding="utf-8")
            for f in sorted((out / "indicators").glob("*/index.html"))
        }


class DataAttrsMatchCriteriaExactly(unittest.TestCase):
    """規格技術決策①：data-* 值必須逐列與 criteria 相符，不是抽樣。"""

    @classmethod
    def setUpClass(cls):
        cls.pages = build_all()

    def test_every_qualifying_row_in_every_indicator_page(self):
        checked_pages = 0
        for article in ARTICLES:
            meta, h1, sections = gen.parse_article(article)
            slug = meta.get("slug") or article.stem
            ids, labels = gen.page_indicators(meta, slug)
            crit_raw = json.loads(
                (gen.CRITERIA_DIR / f"{slug}.json").read_text(encoding="utf-8"))
            qualifying = [r for r in crit_raw
                         if r["indicator_id"] in ids and r["category"] in gen.TABLE_CATEGORIES]
            self.assertTrue(qualifying, f"{slug}：沒有可比對的判準列，測試設計有誤")

            expected = Counter(expected_attrs(r) for r in qualifying)
            actual = parse_data_trs(self.pages[slug])
            self.assertEqual(
                expected, actual,
                f"{slug}：<tr> 上的 data-* 屬性與 data/criteria/{slug}.json 逐列不符\n"
                f"only in expected: {expected - actual}\nonly in actual: {actual - expected}")
            checked_pages += 1
        # 不寫死「應該有幾頁」——用 ARTICLES 本身的長度反過來確認迴圈真的跑過每一頁。
        self.assertEqual(checked_pages, len(ARTICLES))

    def test_no_criterion_row_carries_only_the_indicator_attribute(self):
        """兩端皆 null 的列（如 no_criterion_stated）不得輸出 data-lower／data-upper／
        data-unit——這條專門盯「null 就不輸出該屬性」這條規則，用真實資料裡找得到
        的列驗證，不是自己編一列。"""
        found = False
        for article in ARTICLES:
            meta, h1, sections = gen.parse_article(article)
            slug = meta.get("slug") or article.stem
            ids, labels = gen.page_indicators(meta, slug)
            crit_raw = json.loads(
                (gen.CRITERIA_DIR / f"{slug}.json").read_text(encoding="utf-8"))
            for r in crit_raw:
                if (r["indicator_id"] in ids and r["category"] in gen.TABLE_CATEGORIES
                        and r.get("lower") is None and r.get("upper") is None):
                    attrs = dict(expected_attrs(r))
                    self.assertEqual(set(attrs), {"data-indicator"},
                                     f"{slug}：兩端皆 null 的列不該有 lower/upper/unit 屬性")
                    found = True
        self.assertTrue(found, "資料裡應該至少有一列兩端皆 null，測試才驗得到這條規則")


class ServerRenderedHtmlHasNoInput(unittest.TestCase):
    """規格技術決策②：輸入框由 JS 動態插入，server-rendered HTML 不含 <input>。"""

    @classmethod
    def setUpClass(cls):
        cls.pages = build_all()

    def test_no_input_tag_on_any_indicator_page(self):
        for slug, html_text in self.pages.items():
            self.assertNotIn("<input", html_text.lower(),
                             f"{slug}：server-rendered HTML 不得含 <input>（互動要由 JS 插入）")

    def test_script_and_data_attrs_are_present_so_the_no_input_check_is_not_vacuous(self):
        """陰性對照的另一面：先確認頁面真的有數值定位的料（script／data-indicator），
        排除「沒有 <input> 只是因為整個功能沒生出來」這種假綠燈。"""
        for slug, html_text in self.pages.items():
            self.assertIn("數值定位", html_text, f"{slug}：頁面沒有數值定位的 JS")
            self.assertIn("data-indicator=", html_text, f"{slug}：頁面沒有 data-indicator")


class CopyConstantsAreClean(unittest.TestCase):
    """規格硬規則 #1／#2／#7＋2026-09-01 裁決：JS／CSS 文案常數不得含第二人稱、
    評價／建議動詞、招徠類詞彙；標記模板、說明句、無命中句字面要逐字相符；
    REQUIRED_NOTE 的豁免射程只能是「剛好出現一次」。配陰性對照，證明掃描器
    不是永遠綠。"""

    def test_note_constant_matches_spec_verbatim(self):
        m = re.search(r"NOTE = '([^']*)'", gen.VALUE_LOCATOR_JS)
        self.assertIsNotNone(m, "找不到 NOTE 常數")
        self.assertEqual(m.group(1), REQUIRED_NOTE)

    def test_note_appears_exactly_once_so_the_exemption_scope_is_pinned(self):
        """2026-09-01 裁決：豁免用 replace() 移除所有出現處，射程要釘死在
        「剛好一次」——如果哪天多了第二處固定句，這條測試要先紅，逼人回頭想
        豁免範圍還對不對，而不是讓 replace() 默默吃掉一個不該被吃掉的命中。"""
        self.assertEqual(gen.VALUE_LOCATOR_JS.count(REQUIRED_NOTE), 1)

    def test_mark_prefix_produces_the_required_shape(self):
        """規則 3 的形狀：「此列包含 6.0」——前綴＋使用者輸入原樣，不多加字。"""
        m = re.search(r"MARK_PREFIX = '([^']*)'", gen.VALUE_LOCATOR_JS)
        self.assertIsNotNone(m, "找不到 MARK_PREFIX 常數")
        prefix = m.group(1)
        self.assertEqual(prefix + "6.0", "此列包含 6.0")

    def test_no_hit_prefix_matches_the_2026_09_01_ruling_verbatim(self):
        """裁決要補的無命中句：「沒有列包含 4.0」，數值照輸入原樣。"""
        m = re.search(r"NO_HIT_PREFIX = '([^']*)'", gen.VALUE_LOCATOR_JS)
        self.assertIsNotNone(m, "找不到 NO_HIT_PREFIX 常數")
        prefix = m.group(1)
        self.assertEqual(prefix, REQUIRED_NO_HIT)
        self.assertEqual(prefix + "4.0", "沒有列包含 4.0")

    def test_js_source_is_free_of_banned_words_outside_the_mandated_note_sentence(self):
        """把規格第 7 條要求的固定句挖掉之後，其餘 JS 原始碼（含 LABEL／MARK_PREFIX／
        NO_HIT_PREFIX／SEP／變數名／字面）一個禁詞都不該有（含 2026-09-01 補的招徠類）。"""
        js_minus_note = gen.VALUE_LOCATOR_JS.replace(REQUIRED_NOTE, "")
        hits = scan_banned(js_minus_note)
        self.assertEqual(hits, [], f"JS 原始碼命中禁詞：{hits}")

    def test_css_source_is_free_of_banned_words(self):
        """2026-09-01 裁決：措辭檢查的範圍加上 CSS——content: 是唯一能從 style
        洩字到畫面上的路徑，這裡不特別只挑 content:，整份 VALUE_LOCATOR_CSS 一起
        掃（CSS 本來就不該有中文文案，掃全部比只挑 content: 更不會漏）。"""
        hits = scan_banned(gen.VALUE_LOCATOR_CSS)
        self.assertEqual(hits, [], f"CSS 原始碼命中禁詞：{hits}")

    def test_negative_control_scanner_catches_a_planted_bad_string_in_js_style_text(self):
        """陰性對照：塞一句含「您的數值偏高」的假字串進同一支掃描器，必須被抓到，
        證明上一條測試不是因為掃描器本身永遠綠。"""
        fake = "var WARN = '您的數值偏高，建議就醫。';"
        hits = scan_banned(fake)
        self.assertIn("您的", hits)
        self.assertIn("建議", hits)
        self.assertIn("偏高", hits)
        self.assertIn("就醫", hits)

    def test_negative_control_scanner_catches_a_planted_css_content_property(self):
        """2026-09-01 查驗席的原始變異：CSS 加 ::after{content:"（您的數值偏高，
        建議就醫）"}。掃描器要能在 CSS 文字裡抓到，不是只對 JS 有效。"""
        fake_css = '.vloc-badge::after{content:"（您的數值偏高，建議掛號）";}'
        hits = scan_banned(fake_css)
        self.assertIn("您的", hits)
        self.assertIn("建議", hits)
        self.assertIn("偏高", hits)
        self.assertIn("掛號", hits)

    def test_negative_control_scanner_catches_solicitation_words(self):
        """2026-09-01 裁決補的招徠類禁詞——單獨驗證每一個新詞都真的會被抓到，
        不是加進清單卻拼錯或漏接。"""
        for word in SOLICITATION_WORDS:
            with self.subTest(word=word):
                self.assertIn(word, scan_banned(f"標籤改成「數值定位（{word}）」"))

    def test_negative_control_scanner_is_not_fooled_by_clean_text(self):
        """陰性對照的另一半：乾淨的文字不該被誤抓，否則前面幾條測試等於沒在測。"""
        clean = ("var LABEL = '數值定位'; var PREFIX = '此列包含 '; "
                "var NO_HIT = '沒有列包含 '; var SEP = '｜';")
        self.assertEqual(scan_banned(clean), [])


class ZeroStorageAndNoNetworkRequests(unittest.TestCase):
    """2026-09-01 裁決洞二：查驗席變異插一行 localStorage.setItem(...) 全綠——
    因為沒有測試掃過 JS 原始碼本身（只驗行為，沒驗「有沒有多打一通電話」）。
    這裡直接掃定位器自己的產出，不掃整頁（頁面既有配色切換器用 localStorage
    是站上既有、規格管不到的元件，掃整頁會讓這條測試永遠紅）。"""

    def test_locator_js_has_no_storage_or_network_calls(self):
        hits = scan_storage_network(gen.VALUE_LOCATOR_JS)
        self.assertEqual(hits, [], f"VALUE_LOCATOR_JS 命中零儲存／零請求禁令：{hits}")

    def test_locator_css_has_no_storage_or_network_calls(self):
        hits = scan_storage_network(gen.VALUE_LOCATOR_CSS)
        self.assertEqual(hits, [])

    def test_negative_control_catches_a_planted_localstorage_call(self):
        """陰性對照：查驗席原始變異的重現——塞一行 localStorage.setItem(...)
        進去，掃描器必須抓到，證明上一條測試不是因為掃描器永遠綠。"""
        mutated = gen.VALUE_LOCATOR_JS + "\n  localStorage.setItem('vloc-last', raw);\n"
        hits = scan_storage_network(mutated)
        self.assertIn("localStorage", hits)

    def test_negative_control_catches_fetch_sendbeacon_and_xhr(self):
        for snippet, needle in [
            ("fetch('/log?v=' + raw);", "fetch("),
            ("navigator.sendBeacon('/log', raw);", "sendBeacon"),
            ("new XMLHttpRequest();", "XMLHttpRequest"),
            ("document.cookie = 'vloc=' + raw;", "document.cookie"),
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(needle, scan_storage_network(snippet))


class NoLeftoverSubstitutionLanguage(unittest.TestCase):
    """收尾驗收條件：代入語殘留掃描（SPEC 附的四個詞＋規則 2 全部詞）在新產出的
    互動文案（JS 常數，不含正文既有的 site_footer_html 免責聲明）零命中。"""

    LEFTOVER_PHRASES = ["你的", "您的", "報告落在", "這次", "這個組合", "屬於", "代表"]

    def test_leftover_phrases_absent_outside_the_mandated_note_sentence(self):
        js_minus_note = gen.VALUE_LOCATOR_JS.replace(REQUIRED_NOTE, "")
        hits = [w for w in self.LEFTOVER_PHRASES if w in js_minus_note]
        self.assertEqual(hits, [])


class RowCountsAreDerivedNotHardcoded(unittest.TestCase):
    """守則 #5：斷言不寫死列數常數，從資料算。"""

    def test_qualifying_row_count_per_page_matches_data_on_disk(self):
        for article in ARTICLES:
            meta, h1, sections = gen.parse_article(article)
            slug = meta.get("slug") or article.stem
            ids, labels = gen.page_indicators(meta, slug)
            crit_raw = json.loads(
                (gen.CRITERIA_DIR / f"{slug}.json").read_text(encoding="utf-8"))
            qualifying = [r for r in crit_raw
                         if r["indicator_id"] in ids and r["category"] in gen.TABLE_CATEGORIES]
            # 直接對資料算 len()，不寫死任何數字；這條本身也順便證明
            # DataAttrsMatchCriteriaExactly 用的 qualifying 清單不是空的巧合。
            self.assertGreater(len(qualifying), 0)


# =====================================================================
# 2026-09-01 裁決洞一：邊界語意——用 node 把 withinBounds() 從 VALUE_LOCATOR_JS
# 抽出來單獨測，餵一張邊界案例表。不透過完整頁面：查驗席的發現正是「頁面級測試
# 看不到這個洞」（290 個既有測試全綠，實際後果要 node 重測才看得到）。
# =====================================================================

WITHIN_BOUNDS_RE = re.compile(
    r"function withinBounds\([^)]*\) \{.*?\n  \}", re.S)


def extract_within_bounds(js_source: str) -> str:
    m = WITHIN_BOUNDS_RE.search(js_source)
    if not m:
        raise AssertionError("找不到 withinBounds() 函式——抽取用的正規表示式可能跟實作脫節了")
    return m.group(0)


# 邊界案例表：每案例 = (名稱, lower, upper, lowerExclusive, upperExclusive, 輸入值, 期望結果)。
# 覆蓋四種 inclusive 組合（II／IE／EI／EE，both-bound 案例）＋單邊界（inclusive／exclusive
# 各自成組）。必測四條在註解標「★必測」。
BOUNDARY_CASES = [
    ("只有下界·含等於·剛好等於下界(★必測 ≥6.5 對 6.5 要 true)",
     6.5, None, False, False, 6.5, True),
    ("只有下界·含等於·略低於下界", 6.5, None, False, False, 6.4, False),
    ("只有下界·不含等於·剛好等於下界(★必測 尿酸 >7.0 對 7.0 要 false)",
     7.0, None, True, False, 7.0, False),
    ("只有下界·不含等於·略高於下界", 7.0, None, True, False, 7.1, True),
    ("只有下界·不含等於·略低於下界", 7.0, None, True, False, 6.9, False),
    ("只有上界·含等於·剛好等於上界", None, 6.4, False, False, 6.4, True),
    ("只有上界·含等於·略高於上界", None, 6.4, False, False, 6.5, False),
    ("只有上界·不含等於·剛好等於上界(★必測 BMI <24 對 24 要 false)",
     None, 24, False, True, 24, False),
    ("只有上界·不含等於·略低於上界", None, 24, False, True, 23.9, True),
    ("只有上界·不含等於·略高於上界", None, 24, False, True, 24.1, False),
    ("雙界·含·含(II)·剛好等於上界(★必測 5.7–6.4 對 6.4 要 true)",
     5.7, 6.4, False, False, 6.4, True),
    ("雙界·含·含(II)·超過上界(★必測 5.7–6.4 對 6.5 要 false)",
     5.7, 6.4, False, False, 6.5, False),
    ("雙界·含·含(II)·剛好等於下界", 5.7, 6.4, False, False, 5.7, True),
    ("雙界·含·含(II)·低於下界", 5.7, 6.4, False, False, 5.6, False),
    ("雙界·下含·上不含(IE)·剛好等於下界", 130, 140, False, True, 130, True),
    ("雙界·下含·上不含(IE)·上界前一格", 130, 140, False, True, 139.9, True),
    ("雙界·下含·上不含(IE)·剛好等於上界", 130, 140, False, True, 140, False),
    ("雙界·下不含·上含(EI)·剛好等於下界", 90, 99, True, False, 90, False),
    ("雙界·下不含·上含(EI)·下界後一格", 90, 99, True, False, 90.1, True),
    ("雙界·下不含·上含(EI)·剛好等於上界", 90, 99, True, False, 99, True),
    ("雙界·不含·不含(EE)·剛好等於下界", 5, 10, True, True, 5, False),
    ("雙界·不含·不含(EE)·剛好等於上界", 5, 10, True, True, 10, False),
    ("雙界·不含·不含(EE)·中間值", 5, 10, True, True, 7, True),
]


def run_node(script: str, timeout: int = 20) -> tuple:
    """跑一段 node 腳本，回傳 (stdout, returncode)。腳本自己負責印 JSON 到 stdout。"""
    result = subprocess.run([NODE, "-e", script], capture_output=True,
                            text=True, timeout=timeout)
    return result.stdout, result.returncode, result.stderr


def build_boundary_driver(within_bounds_js: str, cases: list) -> str:
    cases_json = json.dumps([
        {"lower": lo, "upper": up, "lowerExclusive": le, "upperExclusive": ue, "v": v}
        for _, lo, up, le, ue, v, _exp in cases
    ])
    return within_bounds_js + f"""
var CASES = {cases_json};
var out = CASES.map(function (c) {{
  return withinBounds(c.lower, c.upper, c.lowerExclusive, c.upperExclusive, c.v);
}});
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node 不在 PATH 上，邊界語意測試需要 node")
class BoundarySemanticsViaNode(unittest.TestCase):
    """洞一：把 withinBounds() 從實際 JS 原始碼抽出來，用 node 跑真正的邏輯
    （不是在 Python 重新實作一份比較邏輯——那樣兩邊同時錯就會假綠）。"""

    def test_current_implementation_matches_every_boundary_case(self):
        within_bounds_js = extract_within_bounds(gen.VALUE_LOCATOR_JS)
        script = build_boundary_driver(within_bounds_js, BOUNDARY_CASES)
        stdout, code, stderr = run_node(script)
        self.assertEqual(code, 0, stderr)
        actual = json.loads(stdout)
        expected = [exp for *_, exp in BOUNDARY_CASES]
        self.assertEqual(len(actual), len(BOUNDARY_CASES))
        self.assertGreaterEqual(len(BOUNDARY_CASES), 12, "案例表不得少於 12 條")
        mismatches = [
            (name, exp, act) for (name, *_r, exp), act in zip(BOUNDARY_CASES, actual)
            if act != exp
        ]
        self.assertEqual(mismatches, [], f"邊界案例不符：{mismatches}")

    def test_mutation_always_inclusive_lower_bound_is_caught(self):
        """改壞會紅的證明：把查驗席的原始變異（下界永遠當含等於，忽略
        lowerExclusive）套進抽出來的函式，重跑同一張案例表，確認「尿酸 >7.0
        對 7.0」這條會從 false 變成 true——證明上一條測試不是配飾。"""
        within_bounds_js = extract_within_bounds(gen.VALUE_LOCATOR_JS)
        mutated = within_bounds_js.replace(
            "ok = ok && (lowerExclusive ? v > lower : v >= lower);",
            "ok = ok && (v >= lower);")
        self.assertNotEqual(mutated, within_bounds_js, "替換沒有命中，變異腳本本身壞了")
        script = build_boundary_driver(mutated, BOUNDARY_CASES)
        stdout, code, stderr = run_node(script)
        self.assertEqual(code, 0, stderr)
        actual = json.loads(stdout)
        idx = next(i for i, c in enumerate(BOUNDARY_CASES) if c[0].startswith("只有下界·不含等於·剛好等於下界"))
        self.assertEqual(BOUNDARY_CASES[idx][-1], False, "案例表本身的期望值設反了")
        self.assertTrue(actual[idx], "變異後 7.0 對 >7.0 應該被錯誤標成 true，"
                                     "沒有變成 true 代表變異沒有生效或函式已經改了寫法")

    def test_mutation_always_inclusive_upper_bound_is_caught(self):
        """對稱的上界變異（BMI <24 對 24.0 的情境）。"""
        within_bounds_js = extract_within_bounds(gen.VALUE_LOCATOR_JS)
        mutated = within_bounds_js.replace(
            "ok = ok && (upperExclusive ? v < upper : v <= upper);",
            "ok = ok && (v <= upper);")
        self.assertNotEqual(mutated, within_bounds_js, "替換沒有命中，變異腳本本身壞了")
        script = build_boundary_driver(mutated, BOUNDARY_CASES)
        stdout, code, stderr = run_node(script)
        self.assertEqual(code, 0, stderr)
        actual = json.loads(stdout)
        idx = next(i for i, c in enumerate(BOUNDARY_CASES) if c[0].startswith("只有上界·不含等於·剛好等於上界"))
        self.assertEqual(BOUNDARY_CASES[idx][-1], False, "案例表本身的期望值設反了")
        self.assertTrue(actual[idx], "變異後 24.0 對 <24 應該被錯誤標成 true")


# =====================================================================
# DOM shim：repo 沒有 node 依賴管理（無 package.json），不引入 jsdom。
# 只實作 VALUE_LOCATOR_JS 實際用到的 DOM 子集（見類別內註解），拿真正的
# VALUE_LOCATOR_JS 原始碼在這個 shim 上完整跑一次 IIFE，藉此驗證：
# 標記位置（②）、命中組自動展開（③）、無命中訊息（④）、aria-live 屬性存在。
# =====================================================================

DOM_SHIM_JS = r"""
function camelToKebab(s) { return s.replace(/[A-Z]/g, function (m) { return '-' + m.toLowerCase(); }); }

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.attrs = {};
    this.classes = new Set();
    this.children = [];
    this.parentNode = null;
    this._text = '';
    this.listeners = {};
    this.open = false;
  }
  get classList() {
    var self = this;
    return {
      add: function (c) { self.classes.add(c); },
      remove: function (c) { self.classes.delete(c); },
      contains: function (c) { return self.classes.has(c); }
    };
  }
  get className() { return Array.from(this.classes).join(' '); }
  set className(v) { this.classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get dataset() {
    var self = this;
    return new Proxy({}, {
      get: function (_, key) {
        var attr = 'data-' + camelToKebab(String(key));
        return Object.prototype.hasOwnProperty.call(self.attrs, attr) ? self.attrs[attr] : undefined;
      },
      set: function (_, key, value) {
        self.attrs['data-' + camelToKebab(String(key))] = String(value);
        return true;
      }
    });
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  insertBefore(node, ref) {
    node.parentNode = this;
    var i = this.children.indexOf(ref);
    if (i === -1) this.children.push(node); else this.children.splice(i, 0, node);
    return node;
  }
  get lastElementChild() { return this.children.length ? this.children[this.children.length - 1] : null; }
  get textContent() {
    if (!this.children.length) return this._text;
    return this._text + this.children.map(function (c) { return c.textContent; }).join('');
  }
  set textContent(v) { this._text = v; this.children = []; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  dispatch(type) { (this.listeners[type] || []).forEach(function (fn) { fn(); }); }
  matches(sel) {
    var m = /^([a-z0-9]+)?(\.[a-zA-Z0-9_-]+)?(\[[a-zA-Z0-9_-]+\])?$/.exec(sel);
    if (!m) throw new Error('unsupported selector: ' + sel);
    var tag = m[1], cls = m[2], attr = m[3];
    if (tag && this.tagName !== tag.toUpperCase()) return false;
    if (cls && !this.classes.has(cls.slice(1))) return false;
    if (attr) {
      var name = attr.slice(1, -1);
      if (!Object.prototype.hasOwnProperty.call(this.attrs, name)) return false;
    }
    return true;
  }
  closest(sel) {
    var node = this;
    while (node) { if (node.matches(sel)) return node; node = node.parentNode; }
    return null;
  }
  querySelectorAll(sel) {
    var out = [];
    (function walk(node) {
      node.children.forEach(function (c) {
        if (c.matches(sel)) out.push(c);
        walk(c);
      });
    })(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  remove() {
    if (!this.parentNode) return;
    var i = this.parentNode.children.indexOf(this);
    if (i !== -1) this.parentNode.children.splice(i, 1);
    this.parentNode = null;
  }
}

var __root = new El('root');
var document = {
  createElement: function (tag) { return new El(tag); },
  querySelectorAll: function (sel) { return __root.querySelectorAll(sel); },
  querySelector: function (sel) { return __root.querySelector(sel); }
};
"""


def build_fixture_and_driver() -> str:
    """兩組 <details class="crit-grp" data-indicator="testind">：
    組 A（open=true，模擬「診斷」預設展開）放一個單點列 lower=upper=6.5（含等於）；
    組 B（open=false，模擬「篩檢分流」預設收合）放一個雙界列 120–130（皆含等於）。
    輸入 125 只命中組 B——刻意讓兩組的判準值範圍不重疊，這樣「只有收合組被打開」
    才是乾淨的證據，不會被「兩組剛好都命中」混淆。
    """
    return r"""
var container = document.createElement('div');
__root.appendChild(container);

function makeGroup(indicator, initialOpen, lower, upper, lowerExcl, upperExcl, unit, cellText) {
  var details = document.createElement('details');
  details.className = 'crit-grp';
  details.setAttribute('data-indicator', indicator);
  details.open = initialOpen;
  var table = document.createElement('table');
  var tbody = document.createElement('tbody');
  var tr = document.createElement('tr');
  tr.setAttribute('data-indicator', indicator);
  if (lower !== null) {
    tr.setAttribute('data-lower', String(lower));
    if (lowerExcl) tr.setAttribute('data-lower-inclusive', 'false');
  }
  if (upper !== null) {
    tr.setAttribute('data-upper', String(upper));
    if (upperExcl) tr.setAttribute('data-upper-inclusive', 'false');
  }
  if (unit) tr.setAttribute('data-unit', unit);
  var tdOrg = document.createElement('td'); tdOrg.textContent = '機構';
  var tdCell = document.createElement('td'); tdCell.textContent = cellText;
  var tdPop = document.createElement('td'); tdPop.textContent = '族群';
  var tdSrc = document.createElement('td'); tdSrc.textContent = '第四章 表三';
  [tdOrg, tdCell, tdPop, tdSrc].forEach(function (td) { tr.appendChild(td); });
  tbody.appendChild(tr);
  table.appendChild(tbody);
  details.appendChild(table);
  return { details: details, tr: tr };
}

var groupA = makeGroup('testind', true, 6.5, 6.5, false, false, '%', '診斷：6.5%');
var groupB = makeGroup('testind', false, 120, 130, false, false, 'mmHg', '分級：120-130 mmHg');
container.appendChild(groupA.details);
container.appendChild(groupB.details);
"""


def build_scenario_script(js_source: str) -> str:
    """DOM shim ＋ fixture ＋ 實際的 VALUE_LOCATOR_JS ＋ 操作序列 ＋ 結果輸出。

    操作序列：輸入 125（只命中組 B）→ 讀狀態 → 清空 → 讀狀態 → 輸入 999（零命中）
    → 讀狀態。全部結果印成一個 JSON 物件，Python 端逐項斷言。
    """
    return DOM_SHIM_JS + build_fixture_and_driver() + js_source + r"""
var input = document.querySelector('.vloc-input');
var status = document.querySelector('.vloc-status');

function snapshot() {
  return {
    groupAOpen: groupA.details.open,
    groupBOpen: groupB.details.open,
    trAClass: groupA.tr.classes.has('vloc-hit'),
    trBClass: groupB.tr.classes.has('vloc-hit'),
    trBCellText: groupB.tr.children[1].textContent,
    trBLastCellText: groupB.tr.children[3].textContent,
    statusText: status.textContent
  };
}

input.value = '125';
input.dispatch('input');
var afterHit = snapshot();

input.value = '';
input.dispatch('input');
var afterClear = snapshot();

input.value = '999';
input.dispatch('input');
var afterMiss = snapshot();

console.log(JSON.stringify({
  ariaLive: status.getAttribute('aria-live'),
  role: status.getAttribute('role'),
  afterHit: afterHit,
  afterClear: afterClear,
  afterMiss: afterMiss
}));
"""


@unittest.skipUnless(NODE, "node 不在 PATH 上，DOM shim 測試需要 node")
class WidgetRuntimeBehavior(unittest.TestCase):
    """洞二／三方收斂的標記位置／自動展開／無命中訊息，用 DOM shim 跑真正的
    VALUE_LOCATOR_JS（不是重新描述邏輯）。"""

    @classmethod
    def setUpClass(cls):
        script = build_scenario_script(gen.VALUE_LOCATOR_JS)
        stdout, code, stderr = run_node(script)
        if code != 0:
            raise AssertionError(f"DOM shim 執行失敗：{stderr}\n---script---\n{script}")
        cls.result = json.loads(stdout)

    def test_badge_lands_in_the_criteria_value_column_not_the_source_column(self):
        """②：標記要在「判準值」欄（children[1]），不是「依據文件與版本」欄
        （children[3]）——這正是三方收斂要修的那個位置。"""
        hit = self.result["afterHit"]
        self.assertEqual(hit["trBCellText"], "分級：120-130 mmHg｜此列包含 125")
        self.assertEqual(hit["trBLastCellText"], "第四章 表三",
                         "依據欄不該被動態插入的文字改到")

    def test_hit_in_a_collapsed_group_auto_opens_it(self):
        """③：組 B 一開始是收合（open=false），輸入 125 命中組 B 的列之後
        必須自動展開；沒有命中的組 A（本來就是展開）維持原狀。"""
        hit = self.result["afterHit"]
        self.assertTrue(hit["groupBOpen"], "命中的收合組沒有被自動展開")
        self.assertTrue(hit["trBClass"])
        self.assertFalse(hit["trAClass"], "組 A 的列不該被標記（範圍設計上不重疊）")

    def test_clearing_input_restores_original_collapsed_state(self):
        """展開只在有命中時才生效，不是永久改變預設收合規則——清空後組 B
        要回到原本的收合狀態。"""
        cleared = self.result["afterClear"]
        self.assertFalse(cleared["groupBOpen"], "清空輸入後收合組沒有回到原始狀態")
        self.assertFalse(cleared["trBClass"])
        self.assertEqual(cleared["statusText"], "")

    def test_no_hit_value_shows_the_ruled_message_and_group_reverts(self):
        """④：999 命中零列 → 狀態文字＝「沒有列包含 999」；組 B 不該因為上一次
        （125）留下的展開狀態而繼續開著。"""
        miss = self.result["afterMiss"]
        self.assertEqual(miss["statusText"], "沒有列包含 999")
        self.assertFalse(miss["groupBOpen"])
        self.assertFalse(miss["trBClass"])

    def test_status_region_is_a_polite_live_region(self):
        """螢幕報讀器回饋：狀態元素要有 aria-live="polite"（role="status" 是
        額外的語意加強，不是規格硬性要求，但無害且是常見寫法）。"""
        self.assertEqual(self.result["ariaLive"], "polite")
        self.assertEqual(self.result["role"], "status")

    def test_mutation_reverting_badge_to_the_source_column_is_caught(self):
        """改壞會紅：把 markRow 的 cell 選擇改回舊行為（永遠 lastElementChild，
        也就是三方收斂前的「縫進依據欄」），同一個情境重跑，判準值欄應該不再
        出現標記——證明上面的欄位斷言不是配飾。"""
        mutated = gen.VALUE_LOCATOR_JS.replace(
            "    var cell = tr.children[1];\n    if (!cell) return;",
            "    var cell = tr.lastElementChild;")
        self.assertNotEqual(mutated, gen.VALUE_LOCATOR_JS, "替換沒有命中，變異腳本本身壞了")
        script = build_scenario_script(mutated)
        stdout, code, stderr = run_node(script)
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        hit = result["afterHit"]
        self.assertEqual(hit["trBCellText"], "分級：120-130 mmHg",
                         "變異後判準值欄不該再被標記")
        self.assertIn("此列包含 125", hit["trBLastCellText"],
                      "變異後標記應該退回依據欄——沒退回代表變異沒生效")

    def test_mutation_removing_auto_open_is_caught(self):
        """改壞會紅：拿掉「命中就展開收合組」那一行，組 B 命中後應該仍然收合——
        證明自動展開的斷言不是配飾。"""
        mutated = gen.VALUE_LOCATOR_JS.replace(
            "if (d) d.open = true;\n",
            "")
        self.assertNotEqual(mutated, gen.VALUE_LOCATOR_JS, "替換沒有命中，變異腳本本身壞了")
        script = build_scenario_script(mutated)
        stdout, code, stderr = run_node(script)
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertFalse(result["afterHit"]["groupBOpen"],
                         "變異後收合組不該再被自動展開——沒有維持收合代表變異沒生效")


if __name__ == "__main__":
    unittest.main()
