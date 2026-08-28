#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""禁詞 gate 回歸測試（scripts/check-health-terms.py ＋ config/banned-terms.json）。

兩組都要跑，只跑一組不准信（掃描器出過「陽性抓得到、陰性也全抓」的假陽性事故）：
- 陽性：五類禁詞各至少一個違規樣本必須被抓成 FAIL。
- 陰性：合法句子不得被誤殺——119／急診例外句型放行、「成人預防保健」的「預防」不誤殺。

☠️ 這裡直接 import scan()，不走命令列的 stdin：驗掃描器要驗它的判定函式本身，
繞一層 CLI 只會多一個自己也可能壞掉的環節。
"""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_health_terms", ROOT / "scripts" / "check-health-terms.py")
cht = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cht)

RULES = cht.load_rules()


def hits(text, level=None, include_exempt=False):
    out = cht.scan(text, RULES)
    if not include_exempt:
        out = [h for h in out if not h["exempt"]]
    if level:
        out = [h for h in out if h["level"] == level]
    return out


def fails(text):
    return hits(text, level="absolute")


def warns(text):
    return hits(text, level="conditional")


class TestBannedTermsPositive(unittest.TestCase):
    """五類各至少一個違規樣本必須被抓到（absolute → FAIL）。"""

    CASES = {
        "solicitation": [
            "數值偏高的話，這裡推薦醫院給你參考。",
            "報告拿到之後，建議找新陳代謝科。",
            "可以先線上掛號。",
            "數值超標，建議您做進一步檢查。",
        ],
        "efficacy": [
            "照著做可以逆轉糖尿病。",
            "這個方法能治癒。",
            "三個月就能根治。",
            "這份研究顯示它很有效。",
        ],
        "product": [
            "看完立即購買。",
            "點下面的導購連結。",
        ],
        "self_promotion": [
            "老實說，這個門檻本來就有爭議。",
            "我們查證了三份指引。",
            "本站查核後才寫這一段。",
            "本文查到的條文裡沒有這一項。",
        ],
        "gate_language": [
            "準確的說法是這樣。",
            "本文不做推測。",
            "本文一律採用官方版本。",
            "只能寫與較低風險有關，不可以寫成預防。",
        ],
    }

    def test_every_category_has_a_caught_sample(self):
        for category, samples in self.CASES.items():
            with self.subTest(category=category):
                caught = [s for s in samples
                          if any(h["category"] == category for h in fails(s))]
                self.assertTrue(
                    caught,
                    f"{category} 類沒有任何樣本被抓到，這一類的 gate 等於沒接")

    def test_each_positive_sample_is_caught(self):
        for category, samples in self.CASES.items():
            for s in samples:
                with self.subTest(category=category, sample=s):
                    got = fails(s)
                    self.assertTrue(got, f"漏抓：{s}")
                    self.assertIn(category, {h["category"] for h in got})

    def test_conditional_terms_warn_but_do_not_fail(self):
        for s in ["建議就診並追蹤。", "與改善血糖控制有關。"]:
            with self.subTest(sample=s):
                self.assertEqual([], fails(s), f"需附條件的詞不該判 FAIL：{s}")
                self.assertTrue(warns(s), f"需附條件的詞應該要 WARN：{s}")


class TestBannedTermsNegative(unittest.TestCase):
    """合法句子不得被誤殺。"""

    EMERGENCY = ("若出現意識不清、呼吸急促、冒冷汗等立即危險徵象，請立即就醫，"
                 "撥打 119 或前往急診。")

    def test_emergency_exception_sentence_passes(self):
        self.assertEqual([], fails(self.EMERGENCY))
        self.assertEqual([], warns(self.EMERGENCY),
                         "119／急診例外句型內的導引就醫用語應被放行")

    def test_emergency_exception_is_actually_exercised(self):
        """放行必須來自 exceptions，而不是「這句話本來就沒命中任何詞」。

        沒有這條，例外句型的正規表示式整條寫錯也不會有人發現。
        """
        exempted = [h for h in cht.scan(self.EMERGENCY, RULES) if h["exempt"]]
        self.assertTrue(exempted, "例外句型測試沒有真的觸發任何放行，等於沒在測 exception")
        self.assertIn("emergency-119", {h["exempt_by"] for h in exempted})

    def test_same_wording_outside_exception_still_warns(self):
        """同一組字眼離開例外句型就必須恢復告警——否則放行等於全域關掉。"""
        s = "如果覺得數字不好看，請立即就醫。"
        self.assertTrue(warns(s), "例外句型外的「立即就醫」應該要 WARN")

    def test_adult_preventive_care_program_name_not_killed(self):
        s = "成人預防保健的血液生化檢查項目包含血糖與血脂。"
        self.assertEqual([], fails(s))
        self.assertEqual([], warns(s), "「成人預防保健」是服務名稱，其中的「預防」不得誤殺")

    def test_preventive_care_exemption_is_actually_exercised(self):
        s = "成人預防保健的血液生化檢查項目包含血糖與血脂。"
        exempted = [h for h in cht.scan(s, RULES) if h["exempt"]]
        self.assertTrue(exempted, "白名單語境測試沒有真的觸發放行，等於沒在測 allow_context")
        self.assertIn("allow_context", {h["exempt_by"] for h in exempted})

    def test_downgraded_phrasing_is_clean(self):
        for s in ["多份指引把它列進心血管風險評估的其中一項。",
                  "規律運動與較低風險有關。",
                  "要不要處理，可以和醫師討論。"]:
            with self.subTest(sample=s):
                self.assertEqual([], fails(s))
                self.assertEqual([], warns(s))

    def test_repo_content_passes_the_gate(self):
        """repo 目前的 md/html 產物本身必須是乾淨的（gate 對自己也生效）。"""
        for f in cht.collect_files([]):
            with self.subTest(file=str(f)):
                self.assertEqual([], fails(cht.extract_text(f)))


class TestRulesFile(unittest.TestCase):
    def test_all_five_categories_declared_and_used(self):
        declared = set(RULES["categories"])
        used = {t["category"] for t in RULES["terms"]}
        self.assertEqual(declared, used, "categories 宣告與 terms 實際使用必須一致")
        self.assertEqual(5, len(declared), "Style Spec §3 是五類，多一類少一類都要先改規格")

    def test_levels_are_known(self):
        for t in RULES["terms"]:
            with self.subTest(term=t["term"]):
                self.assertIn(t["level"], ("absolute", "conditional"))


if __name__ == "__main__":
    unittest.main()
