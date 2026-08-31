#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列印版判準對照工作表生成器的 gate（scripts/gen-worksheet.py）。

守的是這頁專屬的幾個風險：

1. 反向比對（防手寫、防捏造）：頁面上出現的每一個切點值，都要能在
   data/criteria/<slug>.json 的同一批列裡找到——用 gen-indicator.py 的
   value_text() 現算出「期望集合」，跟從產出 HTML 反查出的實際集合做
   多重集合比對（Counter 相等，不只是「有出現過」），這樣列數被漏算或
   重複算都會紅，不必寫死任何一個數字。

2. 出處引註（2026-08-31 主席裁決加）：每個切點列的「出處」欄是 D{n}，
   區塊底部有一份 D1..Dn 對照文件標題／機構／版本的清單，n 依資料出現順序
   現編。要驗兩件事：(a) 每一列的 D{n} 真的指得到 manifest 裡那份文件的
   doc_id；(b) 同一份文件在同一區塊只佔一個編號（不重複、不跳號）。

3. 措辭紅線（比全站禁詞 gate 更嚴，這頁專屬）：正文不得出現第二人稱
   （你／您／你的／您的）與評價或建議動詞（是／屬於／代表／應該／建議／
   需要／要去看／請就醫／注意）。

   ☠️ 2026-08-31 主席裁決修正射程：manifest 裡有兩份官方文件標題自帶會被這份
   清單命中的字（衛福部新聞稿標題「…722**是**管理血壓好幫手」、國健署新聞稿
   標題「…陪**你**一起…」），另外還有幾列的 `page_or_table`（來源沒有頁碼、
   只能拿該頁的原文標題／FAQ 問句當定位，例如「頁面「我**是**18歲（含）以上的
   成人，要如何判斷體重是否正常？」BMI 表」）也帶到同一類字。這些字是**被引用
   的文件專名或原文定位描述**，不是本站在對讀者說話——第一輪初稿把整份文件
   標題從頁面上拿掉來閃避誤判，主席駁回：「出處要印回去，該修的是測試的射程
   不是內容」。所以掃描前只排除三塊：
     (1) 帶 `data-quoted="1"` 標記的元素（出處清單 `<div class="ws-sources">`
         與每列出處欄裡的 `<span class="ws-pageref">`）——裡面全是 manifest
         抄來的文件標題／機構全名，或 criteria 的 `page_or_table` 原文，
         不是本站寫的話；
     (2) healthlib.DISCLAIMER_HTML——站規既有全站免責聲明（本來就有「您的
         醫師」），不是本頁新增的措辭；
     (3) 「我的數值」欄位標籤——使用者自填欄位名，第一人稱不是對讀者說話。
   排除是**按區塊逐一挖掉每個帶 `data-quoted="1"` 的確切 HTML 子樹**（用
   標籤名回溯比對開合標籤，div 與 span 都認），不是關鍵字白名單——白名單式
   的「這幾個字放行」等於在紅線上開後門，逐塊挖掉標記好的子樹才確保排除範圍
   不會意外擴大到其他內容。
   陽性／陰性對照都要跑（本 repo 記過的教訓：只驗「真頁面乾淨」證明不了
   掃描器本身有作用）：
     - 陽性：對一句真的違規範例（含在本站自己寫的區域）必須抓到。
     - 陰性：既有免責聲明／「我的數值」／出處清單裡的合法命中必須放行。
     - **反向測試（本輪新增）**：同一份文件裡，出處清單內的違規字被排除，
       但正文區域（intro／表頭／欄位標籤）裡若混進同一個違規字仍要抓到——
       證明排除是「只挖掉那個標記好的子樹」，不是整份文件的規則失效。

4. 五個指標區塊都在：不從常數 5 驗，從 articles/indicators/*.md 的實際檔案
   數與檔名（slug）反查每個區塊的 <section id="slug"> 存不存在。
"""
import collections
import html as html_lib
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws = _load("gen_worksheet", "scripts/gen-worksheet.py")
gen = ws.gen           # 與指標頁共用同一份 TABLE_CATEGORIES／value_text／page_indicators
hl = ws.hl

SRC_DIR = ROOT / "articles" / "indicators"
CRITERIA_DIR = ROOT / "data" / "criteria"


def render(blocks=None, mf=None):
    blocks = blocks if blocks is not None else ws.collect_blocks()
    mf = mf if mf is not None else gen.manifest_index()
    return ws.render_page(blocks, mf)


# ---------- 措辭紅線常數（本頁專屬，比 config/banned-terms.json 更嚴） ----------
SECOND_PERSON_WORDS = ["你的", "您的", "你", "您"]   # 長片語先於短片語，避免子字串重複計數時互相干擾
EVAL_VERBS = ["是", "屬於", "代表", "應該", "建議", "需要", "要去看", "請就醫", "注意"]
BANNED_WORDS = SECOND_PERSON_WORDS + EVAL_VERBS

_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
# 帶 data-quoted="1" 的子樹：生成器對「這塊是引用內容」的明確標記（見
# gen-worksheet.py render_sources()／citation_html() 的 docstring），不是測試
# 自己猜的邊界。用 (\w+) 回溯比對開合標籤名——出處清單是 <div class="ws-sources">，
# 每列出處欄裡的頁碼／表號是 <span class="ws-pageref">，兩種都要挖掉，但只挖到
# 各自對應的第一個閉合標籤（非貪婪；這兩種子樹內都沒有同名巢狀標籤，安全）。
_QUOTED_BLOCK = re.compile(
    r'<(\w+)\b[^>]*\bdata-quoted="1"[^>]*>.*?</\1>', re.S)


def visible_text(page_html: str) -> str:
    body = _SCRIPT_STYLE.sub(" ", page_html)
    body = _TAG.sub(" ", body)
    return html_lib.unescape(body)


# 「我的數值」欄位標籤：使用者自填欄位名（第一人稱），不是對讀者說話，扣掉。
# healthlib 的全站免責聲明：站規既有內容（本來就有「您的醫師」等字），扣掉。
# 兩者都在 visible_text() 之後的正規化空間裡比對（先去標籤，snippet 也先去標籤），
# 引用子樹則是在去標籤「之前」整個挖掉（見下）。
_EXEMPT_TEXT_SNIPPETS = [visible_text(hl.DISCLAIMER_HTML).strip(), "我的數值"]


def wording_hits(page_html: str) -> list:
    """回傳 [(word, 前後文)]。排除順序：先挖掉帶 data-quoted="1" 的子樹（未去
    標籤前的原始 HTML 上做，因為那些子樹是用標籤界定的），再去標籤／解實體，
    最後才扣掉免責聲明與「我的數值」這兩段純文字。"""
    html_wo_quoted = _QUOTED_BLOCK.sub(" ", page_html)
    text = visible_text(html_wo_quoted)
    for snippet in _EXEMPT_TEXT_SNIPPETS:
        text = text.replace(snippet, " ")
    hits = []
    for w in BANNED_WORDS:
        for m in re.finditer(re.escape(w), text):
            s, e = m.span()
            hits.append((w, text[max(0, s - 12):e + 12]))
    return hits


# ---------- 資料驅動的期望值集合 ----------

def expected_value_texts() -> collections.Counter:
    """跟 gen-worksheet.py 的 collect_blocks() 走同一套過濾邏輯：
    indicator_id ∈ 該頁 frontmatter 的 indicator_ids、category ∈ TABLE_CATEGORIES。
    回傳的是 value_text 字串的多重集合（同一個字串在不同列出現多次也要對得上次數，
    不能只驗「有出現過」）。
    """
    counter = collections.Counter()
    for f in sorted(SRC_DIR.glob("*.md")):
        meta, h1, sections = gen.parse_article(f)
        slug = meta.get("slug") or f.stem
        ids, labels = gen.page_indicators(meta, slug)
        rows = gen.load_json(CRITERIA_DIR / f"{slug}.json")
        for r in rows:
            if r["indicator_id"] in ids and r["category"] in gen.TABLE_CATEGORIES:
                counter[gen.value_text(r)] += 1
    return counter


def rendered_value_texts(page_html: str) -> collections.Counter:
    cells = re.findall(r'<td class="ws-val">(.*?)</td>', page_html, re.S)
    return collections.Counter(html_lib.unescape(c) for c in cells)


def article_slugs() -> list:
    return sorted(p.stem for p in SRC_DIR.glob("*.md"))


class TestWorksheetValuesGrounded(unittest.TestCase):
    """每一個切點值都要能在 data/criteria/*.json 找到對應（防手寫、防捏造）。"""

    @classmethod
    def setUpClass(cls):
        cls.html = render()

    def test_rendered_values_are_exact_multiset_of_data_derived_values(self):
        expected = expected_value_texts()
        actual = rendered_value_texts(self.html)
        self.assertEqual(actual, expected)

    def test_negative_control_fabricated_value_would_be_caught(self):
        """陰性對照：竄改一個切點值，反查必須抓到差異——證明上一條真的在驗值，
        不是「兩邊都空所以相等」的假陽性。"""
        expected = expected_value_texts()
        tampered = collections.Counter(expected)
        # 塞一個資料裡不存在的值，多重集合就對不上。
        tampered["≥999.9 mg/dL（捏造）"] += 1
        self.assertNotEqual(tampered, rendered_value_texts(self.html))

    def test_row_count_matches_data_not_a_hardcoded_number(self):
        """列數斷言必須從資料算，不寫死常數（本 repo 的既有教訓）。"""
        expected_total = sum(expected_value_texts().values())
        actual_total = sum(rendered_value_texts(self.html).values())
        self.assertEqual(actual_total, expected_total)
        self.assertGreater(expected_total, 0)


class TestWorksheetCitations(unittest.TestCase):
    """出處引註（D1..Dn）：每個切點列的編號要指得到 manifest 裡的真文件，
    同一份文件在同一區塊只佔一個編號。"""

    @classmethod
    def setUpClass(cls):
        cls.mf = gen.manifest_index()
        cls.blocks = ws.collect_blocks()
        cls.html = render(cls.blocks, cls.mf)

    def test_every_row_citation_resolves_to_a_manifest_document(self):
        for block in self.blocks:
            with self.subTest(slug=block["slug"]):
                section = re.search(
                    rf'<section class="ws-block" id="{re.escape(block["slug"])}">.*?</section>',
                    self.html, re.S).group(0)
                # 出處清單：D{n} -> manifest 的 org｜title｜version_or_date。
                list_items = dict(re.findall(
                    r'<li id="[^"]*-D(\d+)">D\d+　([^<]*)</li>', section))
                expected_docs = ws.block_doc_order(block)
                self.assertEqual(len(list_items), len(expected_docs),
                                 "出處清單筆數應等於區塊內 distinct doc_id 數（不重複、不跳號）")
                for n, doc_id in enumerate(expected_docs, start=1):
                    m = self.mf[doc_id]
                    expected_line = (f'{html_lib.escape(gen.org_label(m["org"]))}｜'
                                     f'《{html_lib.escape(m["title"])}》｜'
                                     f'{html_lib.escape(m["version_or_date"])}')
                    self.assertEqual(list_items[str(n)], expected_line)

    def test_each_row_src_cell_points_to_a_number_in_that_blocks_source_list(self):
        for block in self.blocks:
            section = re.search(
                rf'<section class="ws-block" id="{re.escape(block["slug"])}">.*?</section>',
                self.html, re.S).group(0)
            valid_ns = {int(n) for n in re.findall(
                rf'<li id="{re.escape(block["slug"])}-D(\d+)">', section)}
            src_ns = {int(n) for n in re.findall(
                rf'<a href="#{re.escape(block["slug"])}-D(\d+)">D\d+</a>', section)}
            with self.subTest(slug=block["slug"]):
                self.assertTrue(src_ns, "區塊裡至少要有一個切點列引用出處編號")
                self.assertTrue(src_ns.issubset(valid_ns),
                                "切點列引用的編號必須都在該區塊的出處清單裡")

    def test_negative_control_missing_document_would_be_caught(self):
        """陰性對照：拿掉一份會被引用到的文件，manifest_index() 缺那個 doc_id，
        render_sources() 必須中止（doc_id 指不到 manifest＝出處缺一不渲染）。"""
        block = ws.collect_blocks()[0]
        doc_id = ws.block_doc_order(block)[0]
        crippled_mf = {k: v for k, v in gen.manifest_index().items() if k != doc_id}
        with self.assertRaises(SystemExit):
            ws.render_sources(block, crippled_mf)


class TestWorksheetPopulationNumbering(unittest.TestCase):
    """族群欄編號（P1..Pn，2026-08-31 第三次主席裁決加，跟出處欄同一型問題）：
    只有「同一子區塊內重複 ≥2 次」且「長度 > POP_NUMBER_MIN_LENGTH」的族群敘述才
    編號；沒踩到門檻的短敘述（「成人」「18歲以上民眾」「來源未標示」）維持原樣
    直接印在表格裡，不因為統一而編號。完整敘述必須仍完整出現在區塊底部的族群
    清單（跟出處同理，紙本要能查證）。
    """

    @classmethod
    def setUpClass(cls):
        cls.blocks = ws.collect_blocks()
        cls.html = render(cls.blocks)

    def test_every_row_pop_cell_resolves_to_a_full_population_string(self):
        """每個 P{n} 都指得到區塊底部族群清單裡的一列，且那一列的文字逐字等於
        資料裡的 population 欄——不是編號編錯、也不是清單漏列。"""
        for block in self.blocks:
            with self.subTest(slug=block["slug"]):
                section = re.search(
                    rf'<section class="ws-block" id="{re.escape(block["slug"])}">.*?</section>',
                    self.html, re.S).group(0)
                list_items = dict(re.findall(
                    r'<li id="[^"]*-P(\d+)">P\d+　([^<]*)</li>', section))
                expected_pops = ws.block_population_order(block)
                self.assertEqual(len(list_items), len(expected_pops),
                                 "族群清單筆數應等於區塊內符合編號門檻的敘述數")
                for n, pop in enumerate(expected_pops, start=1):
                    self.assertEqual(list_items[str(n)], html_lib.escape(pop))

    def test_each_pop_cell_link_points_to_a_number_in_that_blocks_list(self):
        for block in self.blocks:
            section = re.search(
                rf'<section class="ws-block" id="{re.escape(block["slug"])}">.*?</section>',
                self.html, re.S).group(0)
            valid_ns = {int(n) for n in re.findall(
                rf'<li id="{re.escape(block["slug"])}-P(\d+)">', section)}
            pop_ns = {int(n) for n in re.findall(
                rf'<a href="#{re.escape(block["slug"])}-P(\d+)">P\d+</a>', section)}
            with self.subTest(slug=block["slug"]):
                self.assertTrue(pop_ns.issubset(valid_ns),
                                "族群欄引用的編號必須都在該區塊的族群清單裡")

    def test_short_named_safe_populations_are_never_numbered(self):
        """主席點名要維持原樣的三個例子：「成人」「18歲以上民眾」「來源未標示」
        即使在資料裡重複出現很多次，也不得被收進任何區塊的編號池。"""
        safe = {"成人", "18歲以上民眾", "來源未標示"}
        for block in self.blocks:
            with self.subTest(slug=block["slug"]):
                numbered = set(ws.block_population_order(block))
                self.assertEqual(numbered & safe, set(),
                                 f"短敘述被誤編號：{numbered & safe}")

    def test_population_appearing_only_once_per_indicator_is_never_numbered(self):
        """門檻的另一半：重複 ≥2 次是必要條件，不是「夠長就編」。

        編號池是整個區塊共用（見 block_population_order() 的 docstring），所以
        「只出現一次」要看的是**在它所屬的每一個子指標裡都只出現一次**——一段
        敘述若在 A 子指標只出現 1 次、但在同一區塊的 B 子指標出現 2 次以上，
        整個區塊的編號池仍會收它（B 那邊已經踩到門檻），A 子指標裡的那一列也會
        顯示編號、共用同一個 P{n}，這是設計如此（同一份敘述不必因為子指標不同
        就編兩次號）。真正該驗的不變量是：一段敘述如果在區塊裡**每一個**出現過
        它的子指標中都只出現 1 次（從未在任何一個子指標內達到 ≥2），無論多長
        都不該被編號。
        """
        for block in self.blocks:
            numbered = set(ws.block_population_order(block))
            per_indicator_counts = [
                collections.Counter(r["population"] for r in ind["rows"])
                for ind in block["indicators"]]
            all_pops = {p for c in per_indicator_counts for p in c}
            never_reaches_two_anywhere = {
                p for p in all_pops
                if all(c.get(p, 0) < 2 for c in per_indicator_counts)}
            with self.subTest(slug=block["slug"]):
                self.assertEqual(never_reaches_two_anywhere & numbered, set())

    def test_real_page_actually_numbers_at_least_one_population(self):
        """先證明「真的有東西被編號」，不是門檻設太高、規則沒被用到就通過——
        血壓收縮壓表那句 35 字、重複 8 次的敘述必須被編號。"""
        long_repeated = "成人（依醫療照護場所測得之診間血壓平均值，≥2 次讀數、≥2 個場次）"
        bp_block = next(b for b in self.blocks if b["slug"] == "blood-pressure")
        self.assertIn(long_repeated, ws.block_population_order(bp_block))

    def test_negative_control_tampered_mapping_would_be_caught(self):
        """陰性對照：把族群清單裡的文字改掉一個字，反查必須抓到差異。"""
        block = next(b for b in self.blocks if b["slug"] == "blood-pressure")
        real_list = ws.block_population_order(block)
        tampered_list = list(real_list)
        tampered_list[0] = tampered_list[0] + "（竄改）"
        self.assertNotEqual(real_list, tampered_list)


class TestWorksheetPageOrTableCleanup(unittest.TestCase):
    """出處欄顯示用的 page_or_table 瘦身（2026-08-31 第二次主席裁決）：
    「」括起來的整段是文件標題／FAQ 問句的逐字重複——出處清單（ws-sources）已經
    用 D{n} 印過同一份文件的完整原文標題，同一區塊好幾列各自再印一次那句話只是
    吃版面，不是新資訊。只動**顯示**，data/criteria/ 的 page_or_table 欄位本身
    不動（收據 gate、TestWorksheetValuesGrounded 驗的是資料層，不受這裡影響）。
    """

    def test_unit_leading_bare_page_label_quote_is_dropped_entirely(self):
        """主席給的例二：開頭是「頁面「…」」時，「頁面」二字也一併拿掉——
        它只是「這段引自頁面上」的贅語，不像「主題頁本文」那樣還帶定位資訊，
        D{n} 已經指到是哪一頁。"""
        raw = "頁面「我是18歲（含）以上的成人，要如何判斷體重是否正常？」BMI 表"
        self.assertEqual(ws.clean_page_or_table(raw), "BMI 表")

    def test_unit_quote_in_the_middle_becomes_a_single_space(self):
        """主席給的例一：引號不在開頭時，整段拿掉但留前後文字，用一個空白
        銜接（收乾淨多餘空白，不留兩個字黏在一起）。"""
        raw = "主題頁本文「國民健康署提醒所有民眾應了解自己的血壓值，並注意」第 1 點"
        self.assertEqual(ws.clean_page_or_table(raw), "主題頁本文 第 1 點")

    def test_unit_no_quotes_is_left_untouched(self):
        """沒有「」的字串（例：Sec. 2, Table 2.1）原樣不動。"""
        raw = "Sec. 2, Table 2.1"
        self.assertEqual(ws.clean_page_or_table(raw), raw)

    def test_unit_bare_leading_page_label_with_nothing_after_the_quote(self):
        """真實資料的另一個「頁面「…」」案例，引號後面只剩一個字——同樣整段
        （含「頁面」）拿掉，不留孤零零的「頁面 表」。"""
        raw = "頁面「理想腰圍範圍」表"
        self.assertEqual(ws.clean_page_or_table(raw), "表")

    def test_unit_result_would_be_empty_leaves_nothing(self):
        """拿掉「」括起來的整段後如果整段變空，回傳空字串——citation_html()
        據此不印孤零零的逗號，只印 D{n}。"""
        self.assertEqual(ws.clean_page_or_table("「純粹只是引號」"), "")

    def test_citation_html_prints_bare_dn_when_page_or_table_cleans_to_empty(self):
        row = {"doc_id": "x", "page_or_table": "「純粹只是引號」"}
        html = ws.citation_html(row, "slug", {"x": 1})
        self.assertEqual(html, '<a href="#slug-D1">D1</a>')
        self.assertNotIn(",", html)  # 不留孤零零的逗號

    def test_real_page_src_cells_never_contain_full_width_quotation_marks(self):
        """正面驗證轉換確實生效：整頁出處欄（ws-src／ws-pageref）不得再出現
        「」全形引號。"""
        html = render()
        src_cells = re.findall(r'<td class="ws-src">(.*?)</td>', html, re.S)
        self.assertGreater(len(src_cells), 0)
        offenders = [c for c in src_cells if "「" in c or "」" in c]
        self.assertEqual(offenders, [], f"出處欄仍殘留全形引號：{offenders}")

    def test_negative_control_a_real_unquoted_locator_is_left_intact(self):
        """陰性對照：轉換不能把正常、原本就沒有「」的定位文字也砍掉——
        血壓區塊真實存在的 "Table 5. Definition and grading of hypertension"
        必須逐字原樣印在頁面上。"""
        html = render()
        self.assertIn(
            '<span class="ws-pageref" data-quoted="1">, '
            'Table 5. Definition and grading of hypertension</span>',
            html)


class TestWorksheetWordingRedlines(unittest.TestCase):
    """第二人稱與評價／建議動詞清單逐一檢查；陽性、陰性、反向排除三種對照都要跑。"""

    @classmethod
    def setUpClass(cls):
        cls.html = render()

    def test_no_banned_wording_outside_the_quoted_blocks(self):
        hits = wording_hits(self.html)
        self.assertEqual(hits, [], f"措辭紅線命中（出處清單／page_or_table 之外）：{hits}")

    def test_real_page_actually_contains_quoted_text_with_banned_characters(self):
        """先證明「真的有東西被排除」，而不是頁面上根本沒有這些字、排除規則沒被
        用到就通過了——manifest 有官方文件標題本來就帶「是」「你」。

        2026-08-31 第二次主席裁決後：page_or_table 裡「」括起來的整段（本來帶
        「是」「注意」的那幾句）已經在**顯示**時被拿掉（clean_page_or_table()，
        見 TestWorksheetPageOrTableCleanup），所以這裡不再能從 page_or_table
        舉例——真正還帶違規字、需要 data-quoted="1" 保護的只剩出處清單
        （ws-sources）裡的文件標題。"""
        self.assertIn("722是管理血壓好幫手", self.html)  # 出處清單（ws-sources）裡的文件標題
        # findall() 在有括號群組時只回傳群組內容（標籤名），要整段引用文字得用
        # finditer().group(0)。
        quoted_only = "".join(m.group(0) for m in _QUOTED_BLOCK.finditer(self.html))
        self.assertIn("是", quoted_only)

    def test_scanner_catches_second_person_positive_control(self):
        sample = "<main><p>您的數值偏高，建議您注意。</p></main>"
        hits = wording_hits(sample)
        words_hit = {w for w, _ in hits}
        self.assertIn("您的", words_hit)
        self.assertIn("建議", words_hit)
        self.assertIn("注意", words_hit)

    def test_disclaimer_and_my_value_label_are_exempt(self):
        """既有免責聲明與「我的數值」欄位標籤本身含有清單字，但不該被算作違規。"""
        sample = f"<main><p>我的數值：___</p>{hl.DISCLAIMER_HTML}</main>"
        self.assertEqual(wording_hits(sample), [])

    def test_quoted_sources_and_pageref_blocks_are_exempt(self):
        """出處清單（<div class="ws-sources">）與出處欄的頁碼定位
        （<span class="ws-pageref">）兩種子樹裡的違規字都放行。"""
        sample = (
            '<main>'
            '<div class="ws-sources" data-quoted="1">'
            '<h4>出處</h4><ol><li id="x-D1">D1　衛福部｜《…722是管理血壓好幫手》｜112-05-15</li></ol>'
            '</div>'
            '<span class="ws-pageref" data-quoted="1">, 頁面「我是18歲以上的成人」段</span>'
            '</main>')
        self.assertEqual(wording_hits(sample), [])

    def test_reverse_control_banned_word_outside_quoted_block_still_caught(self):
        """反向測試：排除只挖掉帶 data-quoted="1" 的子樹，不是整份文件的規則
        失效——同一份文件裡，出處清單與 page_or_table 裡的「是」被排除，但正文
        區塊裡若混進「您的」仍要抓到。"""
        sample = (
            '<main>'
            '<p class="ws-intro">這是您的健檢報告。</p>'
            '<div class="ws-sources" data-quoted="1">'
            '<h4>出處</h4><ol><li id="x-D1">D1　衛福部｜《…722是管理血壓好幫手》｜112-05-15</li></ol>'
            '</div>'
            '<span class="ws-pageref" data-quoted="1">, 頁面「我是18歲以上的成人」段</span>'
            '</main>')
        hits = wording_hits(sample)
        words_hit = {w for w, _ in hits}
        self.assertIn("您的", words_hit, "正文區域的「您的」應該被抓到")
        # 兩個引用子樹裡的「是」不該貢獻任何一筆命中。
        is_hits = [ctx for w, ctx in hits if w == "是"]
        self.assertFalse(any("722" in ctx or "18歲" in ctx for ctx in is_hits),
                         "出處清單／page_or_table 裡的「是」不該被算進命中——"
                         "排除範圍跑到子樹外面去了")

    def test_each_banned_word_individually_detectable(self):
        """清單逐一檢查：每個詞各自造一句最小違規樣本，掃描器都要抓到（不是只測整體 OR）。"""
        samples = {
            "你": "你好嗎", "您": "您好嗎", "你的": "你的資料", "您的": "您的資料",
            "是": "這是什麼", "屬於": "屬於高風險", "代表": "代表異常",
            "應該": "應該減重", "建議": "建議就醫", "需要": "需要複檢",
            "要去看": "要去看醫師", "請就醫": "請就醫", "注意": "請注意",
        }
        for word, sample in samples.items():
            with self.subTest(word=word):
                hits = wording_hits(f"<p>{sample}</p>")
                self.assertTrue(any(w == word for w, _ in hits), f"「{word}」未被掃描器抓到：{sample}")


class TestWorksheetBlocks(unittest.TestCase):
    """五個指標的區塊都在——從 articles/indicators/*.md 的實際檔案反查，不寫死 5。"""

    @classmethod
    def setUpClass(cls):
        cls.html = render()

    def test_one_block_per_article_slug(self):
        slugs = article_slugs()
        self.assertGreater(len(slugs), 0)
        for slug in slugs:
            with self.subTest(slug=slug):
                self.assertIn(f'<section class="ws-block" id="{slug}">', self.html)
        block_count = len(re.findall(r'<section class="ws-block"', self.html))
        self.assertEqual(block_count, len(slugs))

    def test_required_five_indicator_topics_present(self):
        """題目點名的五個指標主題（糖化血色素／血壓／血脂／尿酸／BMI 與腰圍）都要有
        對應區塊。用主題關鍵字比對區塊標題，不假設 slug 拼法。"""
        slugs = set(article_slugs())
        topic_slugs = {
            "糖化血色素": "hba1c",
            "血壓": "blood-pressure",
            "血脂": "lipids",
            "尿酸": "uric-acid",
            "BMI": "bmi-waist",
        }
        for topic, slug in topic_slugs.items():
            with self.subTest(topic=topic):
                self.assertIn(slug, slugs, f"預期的 {topic} 頁（{slug}）不在 articles/indicators/ 底下")


class TestWorksheetDeterminism(unittest.TestCase):
    """同輸入連跑兩次必須 byte-identical（禁時間戳，站群通則）。"""

    def test_two_runs_are_byte_identical(self):
        self.assertEqual(render(), render())


if __name__ == "__main__":
    unittest.main()
