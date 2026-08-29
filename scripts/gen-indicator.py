#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen-indicator.py — 指標頁生成器（/indicators/<slug>/）。

輸入＝正文 md（articles/indicators/<slug>.md）＋三個資料檔（判準／變更史／已知限制）
＋來源 manifest；輸出＝public-health/indicators/<slug>/index.html。

為什麼要有這支：M3 定調頁是手寫 HTML，判準值在正文裡各寫一份、在圖裡再寫一份——
資料改了頁面不會叫。這支把「頁面上出現的每個判準數字」的唯一來源收斂回
data/criteria/，md 只留敘事。所以：

- 第②段的判準表**不從 md 讀**，從 data/criteria/<slug>.json 生成
  （category ∈ TABLE_CATEGORIES 且 indicator_id ∈ frontmatter 的 indicator_ids 者，
  資料順序即列序）。☠️ md 裡再出現任何表格一律 exit 1：雙源就是遲早對不起來。
- **一頁多指標**：frontmatter 的 `indicator_ids: [sbp, dbp]` 決定這頁收哪些指標
  （舊的單數 `indicator_id` 仍支援＝單元素 list；兩者都沒有＝用 slug）。三個資料檔
  一律以**頁面 slug** 定位（<slug>.json／<slug>-history.json／<slug>-interference.json）。
  多指標時判準表最前面多一欄「指標」，每個 indicator_id 各畫一條數線；欄裡與數線
  標題的中文短標籤只能來自 frontmatter 的 `indicator_labels`，缺了就中止不猜。
- 三張圖同源：判準數線畫 criteria、時間軸畫 *-history、失真卡畫 *-interference。
  每張圖旁保留 table view（圖看趨勢、表看出處），圖下「依據」行列出用到的資料列
  id／索引與 doc_id。
- 第⑥段「來源與版本」從 data/sources/manifest.json 生成，順序＝ frontmatter 的
  sources；md 裡不寫（寫了就是第二份會過期的清單）。
- direction／inclusive 這類旗標一律照資料渲染，生成器不做二次判斷、不猜方向；
  資料沒給數值區間就在頁面上說「原文未給數值區間」，不留空白也不腦補。
- **勘誤紀錄**（data/errata.json，站級一個檔）：公開後改過的數字或說明留痕給讀者看。
  有勘誤的指標頁在第⑥段之後多一段「勘誤紀錄」（零列＝整段不存在，連 CSS 都不多）；
  站級頁 /errata/ 列全站，最新在前，只在全量 build 生成。

dormant（config/site.json 的 published 為 false）：
    頁面照生（要能看、能審），但不寫 sitemap part、不進 llms.txt、導覽不連。
    翻成 true 才接線。兩個方向都有測試（tests/test_gen_indicator.py）。

決定性：全部內容由來源檔決定，不寫任何時間戳；同輸入連跑兩次 byte-identical。

跑序：build-articles.py → **本腳本** → build-sitemap.py
用法：python3 scripts/gen-indicator.py [slug ...]     # 預設全部
"""
import argparse
import html as html_lib
import importlib.util
import json
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("healthlib", ROOT / "scripts" / "healthlib.py")
hl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hl)

SRC_DIR = ROOT / "articles" / "indicators"
CRITERIA_DIR = ROOT / "data" / "criteria"
MANIFEST_PATH = ROOT / "data" / "sources" / "manifest.json"
SITEMAP_OWNER = "indicators"

# 第②段判準表要收哪些 category。☠️ 篩檢分流與未訂判準**不得**併進診斷列——
# 5.9% 是要不要轉介做 OGTT 的門檻，WHO 的「未訂」是一個明確的空缺，兩者都不是診斷線。
# classification 與 risk_threshold 同理：分級是把連續數值切成命名等級（高血壓第一期、
# BMI 過重），風險門檻是「超過此值風險升高」但來源沒說它構成診斷（腰圍 ≥90 cm）。
# 分類就是判準的一部分。
TABLE_CATEGORIES = ["diagnosis", "prediabetes", "screening_triage",
                    "classification", "risk_threshold", "no_criterion_stated"]

CATEGORY_LABEL = {
    "diagnosis": "診斷",
    "prediabetes": "糖尿病前期",
    "screening_triage": "篩檢分流（非診斷判準）",
    "classification": "分級",
    "risk_threshold": "風險門檻",
    "no_criterion_stated": "未訂判準",
}

# ---------- 勘誤紀錄（公開後改過什麼，留給讀者看的痕跡） ----------
# 資料在 data/errata.json（站級，一個檔管全站；不在 data/criteria/ 底下——它不屬於
# 任何一個指標）。☠️ 上線前的修改不是勘誤：初始值 []，不得把 M4 的內部修正補記進來。
ERRATA_PATH = ROOT / "data" / "errata.json"
ERRATA_TITLE = "勘誤紀錄"
ERRATA_URL = f"{hl.BASE}/errata/"
# 這頁的用途說明（站級頁的第一句）。零列時另外加一句「目前沒有勘誤紀錄。」——
# 「沒有勘誤」與「還沒有這個機制」是兩件事，頁面要說得出是前者。
ERRATA_LEDE = "這頁列出本站公開後改過的判準數字或說明文字，逐筆記下原本寫什麼、改成什麼、為什麼改。"
ERRATA_EMPTY = "目前沒有勘誤紀錄。"
ERRATA_LLMS_DESC = "本站公開後的更正明細，最新在前。"

# section → 中文標籤。1–6 是指標頁固定六段（每頁的實際標題各自不同，所以這裡用
# MODEL.md §3 登記的那六個段落角色當簡稱，不抄任何一頁的標題）；其餘是元件。
ERRATA_SECTION_LABEL = {
    "1": "第①段（是什麼）",
    "2": "第②段（各機構判準並列）",
    "3": "第③段（判準何時改過）",
    "4": "第④段（何時失真）",
    "5": "第⑤段（可以和醫師討論什麼）",
    "6": "第⑥段（來源與版本）",
    "table": "判準表",
    "chart": "判準數線",
    "history": "判準沿革時間軸",
    "interference": "失真卡",
    "sources": "來源與版本清單",
}

# ---------- 呈現層設定（不是資料；資料一律在 data/ 下） ----------
# 顏色在這幾張圖承載的語意是「這條判準是誰發布的」，一個視覺通道只能承載一種語意。
# ☠️ 語意的單位是**機構屬性**（family），不是機構本身：新指標會帶進新機構
# （心臟學會、國際高血壓學會…），逐一挑色票遲早撞色或輪替，讀者就得重學一次圖例。
# family → 色票；機構全名 → (頁面短標籤, family)。名單外的機構走 fallback 灰＋全名。
ORG_FAMILY_COLOR = {
    "tw-gov": "--c-hpa",        # 台灣官方（國健署／食藥署／衛福部）
    "tw-society": "--c-daroc",  # 台灣專科學會
    "intl": "--c-who",          # 國際組織（WHO 等）
    "us": "--c-ada",            # 美國學會／其專家委員會
    "other": "--c-other",       # 其他（標準化計畫、跨國專家委員會、衛教資料庫…）
}
ORG_DISPLAY = {
    "American Diabetes Association": ("ADA", "us"),
    "World Health Organization": ("WHO", "intl"),
    "衛生福利部國民健康署": ("國健署", "tw-gov"),
    "行政院衛生署國民健康局": ("國健局（2003）", "tw-gov"),
    "社團法人中華民國糖尿病學會／中華民國內分泌暨糖尿病學會": ("糖尿病學會", "tw-society"),
    "The Expert Committee on the Diagnosis and Classification of Diabetes Mellitus"
    "（American Diabetes Association）": ("ADA 專家委員會", "us"),
    "International Expert Committee": ("國際專家委員會", "other"),
    "MedlinePlus（美國國家醫學圖書館 NLM，NIH 旗下）": ("MedlinePlus", "other"),
    "National Glycohemoglobin Standardization Program": ("NGSP", "other"),
    # ---- M4 新增（血壓／血脂／尿酸／BMI 腰圍）----
    "World Health Organization Regional Office for the Western Pacific／International Association for the Study of Obesity／International Obesity Task Force": ("WHO 西太平洋辦公室／IASO／IOTF", "intl"),
    "衛生福利部": ("衛福部", "tw-gov"),
    "American College of Cardiology／American Heart Association": ("ACC/AHA", "us"),
    "American Heart Association／American College of Cardiology": ("AHA/ACC", "us"),
    "American Heart Association／American College of Cardiology 等多學會聯合（AHA/ACC/AACVPR/AAPA/ABC/ACPM/ADA/AGS/APhA/ASPC/NLA/PCNA）": ("AHA/ACC 等多學會", "us"),
    "American College of Rheumatology": ("ACR", "us"),
    "European League Against Rheumatism": ("EULAR", "intl"),
    "International Diabetes Federation": ("IDF", "intl"),
    "Japanese Society of Gout and Uric & Nucleic Acids": ("日本痛風・尿酸核酸學會", "intl"),
    "MedlinePlus（U.S. National Library of Medicine）": ("MedlinePlus", "other"),
    "National Cholesterol Education Program（National Heart, Lung, and Blood Institute, National Institutes of Health）": ("NCEP（NHLBI）", "us"),
    "National Heart, Lung, and Blood Institute（National Institutes of Health）": ("NHLBI", "us"),
    "National High Blood Pressure Education Program（National Heart, Lung, and Blood Institute, National Institutes of Health）": ("NHBPEP（NHLBI）", "us"),
    "National Institutes of Health／National Heart, Lung, and Blood Institute": ("NIH/NHLBI", "us"),
    "National Institutes of Health／National Heart, Lung, and Blood Institute（National Cholesterol Education Program）": ("NIH/NHLBI（NCEP）", "us"),
    "Taiwan Society of Cardiology／Taiwan Hypertension Society": ("心臟學會／高血壓學會", "tw-society"),
    "中華民國風濕病醫學會": ("風濕病醫學會", "tw-society"),
    "台灣血脂及動脈硬化學會（Taiwan Society of Lipids and Atherosclerosis）等八學會": ("血脂學會等八學會", "tw-society"),
    "WHO expert consultation": ("WHO 專家諮詢會", "intl"),
}
# 名單外的機構＝去強調灰，不配系列色（系列色是已具名機構屬性的識別，不能被稀釋）。
ORG_FALLBACK_FAMILY = "other"

# 失真卡的欄序。五種 direction 各自有欄，來源沒指方向就進 unspecified 欄，不猜。
DIRECTION_ORDER = ["high", "both", "low", "unsuitable", "unspecified"]
DIRECTION_LABEL = {
    "high": "使數值偏高",
    "both": "同一機轉兩側都有",
    "low": "使數值偏低",
    "unsuitable": "來源說此時不適合用於診斷",
    "unspecified": "來源只說會影響，未指方向",
}

# 判準數線的座標軸，**鍵＝indicator_id**（不是頁面 slug）：一頁多指標時每個
# indicator_id 各畫一條數線，各自吃自己的視窗。未列名者由該指標的資料 min/max 推導。
AXIS = {
    "hba1c": {"min": 4.5, "max": 8.0,
              "ticks": [4.5, 5.0, 6.0, 6.5, 7.0, 8.0],
              "label": "HbA1c（%）"},
    "sbp": {"min": 100, "max": 160, "ticks": [100, 120, 130, 140, 160], "label": "收縮壓（mmHg）"},
    "dbp": {"min": 60, "max": 100, "ticks": [60, 80, 85, 90, 100], "label": "舒張壓（mmHg）"},
    "total-chol": {"min": 150, "max": 260, "ticks": [150, 200, 240, 260], "label": "總膽固醇（mg/dL）"},
    "ldl-c": {"min": 80, "max": 200, "ticks": [80, 100, 130, 160, 190], "label": "LDL-C（mg/dL）"},
    "hdl-c": {"min": 30, "max": 70, "ticks": [30, 40, 50, 60, 70], "label": "HDL-C（mg/dL）"},
    "tg": {"min": 100, "max": 550, "ticks": [100, 150, 200, 500], "label": "三酸甘油酯（mg/dL）"},
    "uric-acid": {"min": 6.0, "max": 10.0, "ticks": [6.0, 6.8, 7.0, 8.0, 9.0, 10.0], "label": "尿酸（mg/dL）"},
    "bmi": {"min": 15, "max": 42, "ticks": [15, 18.5, 23, 24, 25, 27, 30, 35, 40], "label": "BMI（kg/m²）"},
    "waist": {"min": 70, "max": 110, "ticks": [70, 80, 88, 90, 94, 102, 110], "label": "腰圍（cm）"},
}


# ---------- 小工具 ----------

def esc(s) -> str:
    return html_lib.escape(str(s if s is not None else ""))


def num(v) -> str:
    """數值轉字串：6.5→「6.5」、30.0→「30」。頁面上的數字只能長這樣。"""
    return f"{v:g}"


def load_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_index() -> dict:
    return {m["id"]: m for m in load_json(MANIFEST_PATH)}


def source_ref(doc_id: str, mf: dict, page_or_table: str = "") -> str:
    """依據欄：manifest 的 title＋version_or_date（＋該列的頁碼／表號）。

    doc_id 指不到 manifest＝這一列沒有出處，直接中止：四項出處缺一即不渲染。
    """
    m = mf.get(doc_id)
    if not m:
        raise SystemExit(f"❌ doc_id 指不到 manifest：{doc_id}（四項出處缺一，不渲染）")
    out = f"《{m['title']}》{m['version_or_date']}"
    if page_or_table:
        out += f"，{page_or_table}"
    return out


def superseded_label(doc_id: str, mf: dict) -> str:
    """P5：判準表依據欄「已被 X 取代」的短標——機構短標＋年份，不是完整 source_ref
    （完整出處已在來源段），只給讀者夠短的線索去找取代它的那一份文件。

    doc_id 指不到 manifest＝取代關係本身沒有出處，直接中止（與 source_ref 同紅線）。
    """
    m = mf.get(doc_id)
    if not m:
        raise SystemExit(f"❌ superseded_by 指不到 manifest：{doc_id}（取代關係缺出處，不渲染）")
    label = ORG_DISPLAY.get(m["org"], (m["org"], ORG_FALLBACK_FAMILY))[0]
    year = re.search(r"\d{4}", m.get("version_or_date", ""))
    return f"{label} {year.group(0)}" if year else label


def source_cell(row: dict, mf: dict) -> str:
    """判準表／時間軸「依據」欄的完整文字：source_ref＋（若被取代）取代註記。

    ☠️ 只有判準表這一欄要標「已被誰取代」（P5）；來源段照常列出這份文件本身，
    不因為它被取代就從清單移除或改寫。
    """
    out = source_ref(row["doc_id"], mf, row["page_or_table"])
    sup = row.get("superseded_by")
    if sup:
        out += f"（已被 {superseded_label(sup, mf)} 取代）"
    return out


def org_label(org: str) -> str:
    return ORG_DISPLAY.get(org, (org, ORG_FALLBACK_FAMILY))[0]


def org_family(org: str) -> str:
    """機構屬性（tw-gov／tw-society／intl／us／other）。名單外一律 other。"""
    return ORG_DISPLAY.get(org, (org, ORG_FALLBACK_FAMILY))[1]


def org_color(org: str) -> str:
    return f"var({ORG_FAMILY_COLOR[org_family(org)]})"


def wrap_cjk(text: str, width: int) -> list:
    """SVG 沒有自動換行，只能自己斷行。

    ☠️ 斷行不得吃掉原文的空白：中文與英數之間的空格（盤古之白）與 mg/dL 這種
    單位前的空格都是正文的一部分，重組時要照原樣還原，不能因為換行演算法方便
    就把「≥140 mg/dL 下修為」黏成「≥140 mg/dL下修為」。
    """
    # tokens=[(字串, 前面原本有沒有空白)]；中日韓字元一字一 token，拉丁字母整串不切。
    tokens, buf, pending_space = [], "", False
    for ch in text:
        if ch == " ":
            if buf:
                tokens.append((buf, pending_space))
                buf, pending_space = "", False
            pending_space = True
            continue
        if ord(ch) > 0x2E7F:
            if buf:
                tokens.append((buf, pending_space))
                buf, pending_space = "", False
            tokens.append((ch, pending_space))
            pending_space = False
        else:
            if not buf:
                pass
            buf += ch
    if buf:
        tokens.append((buf, pending_space))

    # 避頭尾：起始括號不落在行尾、收尾標點不落在行首（黏進相鄰 token 一起搬）。
    OPEN, CLOSE = "（「《〈［【", "）」》〉］】。，、；：？！%"
    merged = []
    for t, sp in tokens:
        if merged and t in CLOSE:
            merged[-1] = (merged[-1][0] + (" " if sp else "") + t, merged[-1][1])
        elif merged and merged[-1][0][-1] in OPEN:
            merged[-1] = (merged[-1][0] + (" " if sp else "") + t, merged[-1][1])
        else:
            merged.append((t, sp))
    tokens = merged

    def w_of(t):
        return sum(1.0 if ord(c) > 0x2E7F else 0.55 for c in t)

    lines, cur, cur_w = [], "", 0.0
    for t, sp in tokens:
        gap = 0.55 if (sp and cur) else 0.0
        if cur and cur_w + gap + w_of(t) > width:
            lines.append(cur)
            cur, cur_w = t, w_of(t)
        else:
            cur += (" " if gap else "") + t
            cur_w += gap + w_of(t)
    if cur:
        lines.append(cur)
    return lines or [""]


# ---------- 正文 md ----------

_TABLE_LINE = re.compile(r"(?m)^\s*\|")

SECTION_COUNT = 6


def parse_list(raw: str) -> list:
    """frontmatter 的 `[a, b, c]`（healthlib 的解析器只回原字串）→ list。"""
    return [s.strip() for s in (raw or "").strip().lstrip("[").rstrip("]").split(",")
            if s.strip()]


def parse_map(raw: str) -> dict:
    """frontmatter 的 `{sbp: 收縮壓, dbp: 舒張壓}` → dict。冒號後的值照抄不改。"""
    out = {}
    for item in (raw or "").strip().lstrip("{").rstrip("}").split(","):
        k, sep, v = item.partition(":")
        if sep and k.strip() and v.strip():
            out[k.strip()] = v.strip()
    return out


def parse_article(path: pathlib.Path):
    """回 (meta, h1, sections)；sections＝[(標題, [段落…])]，固定六段。

    ☠️ md 內出現表格一律中止：第②段的判準表是資料生成的，md 再寫一份就是雙源。
    """
    text = path.read_text(encoding="utf-8")
    meta, body = hl.parse_frontmatter(text)
    if _TABLE_LINE.search(body):
        raise SystemExit(
            f"❌ {path.name} 正文含手寫表格。指標頁的判準表由 data/criteria/ 生成，"
            "md 不得再寫一份（雙源＝資料改了頁面不會叫）。請把表格刪掉。")

    m = re.match(r"\s*#\s+(.+?)\s*\n", body)
    h1 = m.group(1) if m else meta.get("title", "")
    body = body[m.end():] if m else body

    parts = re.split(r"(?m)^##\s+", body)[1:]
    sections = []
    for p in parts:
        head, _, rest = p.partition("\n")
        paras = [re.sub(r"\s*\n\s*", "", b).strip()
                 for b in re.split(r"\n\s*\n", rest) if b.strip()]
        sections.append((head.strip(), paras))
    if len(sections) != SECTION_COUNT:
        raise SystemExit(f"❌ {path.name} 有 {len(sections)} 段，固定結構是 "
                         f"{SECTION_COUNT} 段且順序不可調換（Style Spec §4）。")

    meta["sources"] = parse_list(meta.get("sources", ""))
    return meta, h1, sections


def page_indicators(meta: dict, slug: str) -> tuple:
    """(indicator_ids, indicator_labels)。

    一頁多指標（blood-pressure＝sbp＋dbp、lipids＝四項…）靠 `indicator_ids`；
    舊的單數 `indicator_id` 仍支援（＝單元素 list）；兩者都沒有就用 slug。

    多指標頁的短標籤（判準表的「指標」欄、每條數線的標題）必須由 frontmatter 的
    `indicator_labels` 給——☠️ 生成器不從 indicator_id 造中文，也不從 unit 猜，
    缺一個就中止：猜出來的「SBP」不會有人發現它不是來源的用詞。
    """
    ids = parse_list(meta.get("indicator_ids", ""))
    if not ids:
        ids = [meta["indicator_id"]] if meta.get("indicator_id") else [slug]
    labels = parse_map(meta.get("indicator_labels", ""))
    if len(ids) > 1:
        missing = [i for i in ids if i not in labels]
        if missing:
            raise SystemExit(
                f"❌ {slug}：indicator_labels 缺 {missing} 的中文短標籤。"
                "多指標頁的「指標」欄與各數線標題只能由 frontmatter 指定，生成器不猜。")
    return ids, labels


# ---------- 判準值組字（唯一的數字來源） ----------

def _glyph(row: dict, full: str, plain: str) -> str:
    """不等號字形照原文：來源自己寫 ≧ 就不改成 ≥（那是回查原文的指紋）。"""
    quotes = " ".join([row.get("quote", "")] + list(row.get("quote_extra") or []))
    return full if full in quotes else plain


NO_RANGE = "（原文未給數值區間）"


def unit_suffix(unit) -> str:
    if not unit:
        return ""
    return unit if unit.startswith("%") else f" {unit}"


def value_text(row: dict, short: bool = False) -> str:
    """判準值＝lower／upper／unit ＋ inclusive 旗標組出來的字，不從正文抄。

    short=True 給圖上的標籤用（單位只留 %／原單位主體，不帶括號補述）。
    兩端都是 null＝來源沒給數值區間，照實說，不留空、不腦補。
    """
    lo, up = row.get("lower"), row.get("upper")
    unit = row.get("unit") or ""
    if short and unit.startswith("%"):
        unit = "%"
    u = unit_suffix(unit)
    ge = _glyph(row, "≧", "≥")
    le = _glyph(row, "≦", "≤")
    if lo is None and up is None:
        return NO_RANGE
    if up is None:
        return f"{ge if row.get('lower_inclusive') is not False else '>'}{num(lo)}{u}"
    if lo is None:
        return f"{le if row.get('upper_inclusive') is not False else '<'}{num(up)}{u}"
    if row.get("upper_inclusive") is False or row.get("lower_inclusive") is False:
        lo_s = f"{ge}{num(lo)}{u}" if row.get("lower_inclusive") is not False else f">{num(lo)}{u}"
        up_s = f"{le}{num(up)}{u}" if row.get("upper_inclusive") is not False else f"<{num(up)}{u}"
        return f"{lo_s} 且 {up_s}"
    if lo == up:
        return f"{num(lo)}{u}"
    return f"{num(lo)}–{num(up)}{u}"


def criteria_cell(row: dict) -> str:
    v = value_text(row)
    label = CATEGORY_LABEL[row["category"]]
    return f"{label}{v}" if v == NO_RANGE else f"{label}：{v}"


# ---------- 圖表 CSS（色票＝M3 定調頁；深淺色兩套，不載外部函式庫） ----------

CHART_CSS = """
:root{
  --c-ada:#2a78d6; --c-who:#eb6834; --c-hpa:#1baf7a; --c-daroc:#eda100;
  --c-other:#8c8c8c; --ink-on-fill:#101418; --wash:.22;
}
@media (prefers-color-scheme: dark){
  :root{ --c-ada:#3987e5; --c-who:#d95926; --c-hpa:#199e70; --c-daroc:#c98500;
         --c-other:#8f8f8f; --wash:.3; }
}
figure.chart{ margin:1.6rem 0 2rem; padding:0; }
figure.chart .ct{ font-size:15.5px; font-weight:700; line-height:1.55; margin:0 0 2px; color:var(--fg); }
figure.chart svg{ display:block; width:100%; height:auto; overflow:visible; }
figure.chart .src{ font-size:12.5px; color:var(--dim); margin:8px 0 0; line-height:1.7; }
.lg{ display:flex; flex-wrap:wrap; gap:5px 15px; margin:8px 0 11px; font-size:12.5px;
     color:var(--dim); line-height:1.5; }
.lg span{ display:inline-flex; align-items:center; gap:6px; white-space:nowrap; }
.lg i{ display:inline-block; width:16px; height:11px; border-radius:2px; flex:none; }
.lg i.dot{ width:11px; height:11px; border-radius:50%; }
.lg i.dash{ background:none; border:1.5px dashed var(--c-daroc); }
.lg i.rule{ width:16px; height:0; border-top:2px solid var(--dim); border-radius:0; }
.cs .lb{ font-size:13px; } .cs .sm{ font-size:11.5px; } .cs .bd{ font-size:13.5px; font-weight:600; }
@media (max-width:620px){ .cs .lb{ font-size:19px; } .cs .sm{ font-size:17px; } .cs .bd{ font-size:19.5px; } }
@media (max-width:430px){ .cs .lb{ font-size:20px; } .cs .sm{ font-size:20.5px; } .cs .bd{ font-size:22px; } }
.cs text{ fill:var(--fg); font-family:var(--font-ui); }
.cs text.mu{ fill:var(--dim); }
.cs text.on{ fill:var(--ink-on-fill); }
.cs .grid{ stroke:var(--line); stroke-width:1; }
.cs .axis{ stroke:var(--line-2); stroke-width:1; }
.cs .ref{ stroke:var(--dim); stroke-width:1.5; }
figure.chart svg.wide-only{ display:block; }
figure.chart svg.narrow-only{ display:none; }
@media (max-width:620px){
  figure.chart svg.wide-only{ display:none; }
  figure.chart svg.narrow-only{ display:block; }
}
.fx{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; margin:2px 0 0; }
.fx .col{ border:1px solid var(--line); border-radius:var(--radius-sm); padding:11px 13px;
          background:var(--surface); border-top:3px solid var(--line-2); }
.fx .col h3{ margin:0 0 7px; font-size:14px; font-weight:700; }
.fx .col h3 b{ display:block; font-size:11.5px; font-weight:400; color:var(--dim); margin-top:2px; }
.fx ul{ margin:0; padding-left:0; list-style:none; }
.fx li{ display:flex; align-items:flex-start; gap:7px; font-size:13.5px; line-height:1.65; margin:5px 0; }
.fx li i{ display:inline-block; width:9px; height:9px; border-radius:50%; flex:none; margin-top:7px; }
.fx .tag{ display:block; font-size:11.5px; color:var(--dim); }
/* 窄螢幕：表格橫向捲動而不是把欄位擠成一字一行（五欄表擠到 390px 等於沒得讀）。
   .tbl-scroll 本身是 overflow-x:auto，給表格一個 min-width 就會在容器內捲。 */
@media (max-width:620px){ .tbl-scroll > .std-table{ min-width:600px; } }
/* 判準表分組折疊：原生 details 元素（無 JS）。組的外框與組名用外殼的
   --line／--surface／--dim／--accent（跟著配色切換走）；☠️ 不用 --c-* 系列色——
   那組色票在這幾張圖承載的語意是「這條判準是誰發布的」，拿來當組框會讓同一個
   視覺通道多背一種意思。 */
.crit-sum{ font-size:13px; color:var(--dim); margin:10px 0 8px; }
details.crit-grp{ border:1px solid var(--line); border-radius:var(--radius-sm);
                  background:var(--surface); margin:0 0 8px; }
details.crit-grp > summary{ cursor:pointer; font-weight:700; font-size:14px;
                            padding:10px 12px; line-height:1.6; }
details.crit-grp > summary:hover{ color:var(--accent); }
details.crit-grp[open] > summary{ border-bottom:1px solid var(--line); }
details.crit-grp > .tbl-scroll{ padding:0 12px; }
details.crit-grp .std-table{ margin:10px 0 12px; }
.ind-note{ font-size:13px; color:var(--dim); margin:6px 0 0; }
.ind-foot{ font-size:12.5px; color:var(--dim); border-top:1px solid var(--line);
           padding-top:10px; margin-top:34px; }
.src-list{ margin:10px 0 0 1.3em; font-size:14px; line-height:1.9; }
.src-list li{ margin-bottom:4px; }
"""


# ---------- ② 判準表（唯一數字來源） ----------

# 一頁進表列數 ≤ 這個數就全部展開：組數本來就少的時候（hba1c 10 列 4 組），
# 折疊只是多一次點擊才看得到全貌，省不到捲動。
CRIT_OPEN_ALL_MAX = 12
# 預設展開的類別：診斷、分級、風險門檻是讀者翻到這頁要找的數字（腰圍頁只有風險門檻
# 一種，不開就整段看不到腰圍的值——M5 拍板加進來）。其餘（篩檢分流、未訂判準）
# 預設收合——但收合的內容仍在 DOM 裡（原生 <details>，無 JS），爬蟲與 RAG 讀得到。
CRIT_OPEN_CATEGORIES = ("diagnosis", "classification", "risk_threshold")


def group_criteria_rows(rows: list, multi: bool = False, labels: dict = None) -> list:
    """分組：回 [(indicator_id 或 None, category, 該組的列)]。

    多指標頁＝先 indicator_id 再 category；單指標頁＝只 category（一頁只有一個
    指標，再分一層等於每組的指標欄只有一個值）。

    indicator_id 的順序取 labels 的鍵序——frontmatter 的 `indicator_labels`
    與 `indicator_ids` 是同一份清單的兩種寫法，render_page 畫數線走 ids，這裡走
    labels，兩邊要對齊。☠️ 若有人只改其中一個的順序，表的組序會與數線順序不同；
    rows 裡出現但 labels 沒列到的 indicator_id 補在最後（不靜默丟列）。
    category 順序照 TABLE_CATEGORIES；組內維持原始 json 行序，不重排。沒列的組不出現。
    """
    labels = labels or {}
    if multi:
        present = list(dict.fromkeys(r["indicator_id"] for r in rows))
        order = [i for i in labels if i in present]
        order += [i for i in present if i not in order]
    else:
        order = [None]
    out = []
    for iid in order:
        for cat in TABLE_CATEGORIES:
            grp = [r for r in rows if r["category"] == cat
                   and (iid is None or r["indicator_id"] == iid)]
            if grp:
                out.append((iid, cat, grp))
    return out


def render_criteria_table(rows: list, mf: dict, multi: bool = False,
                          labels: dict = None) -> str:
    """一組一張表，各包在一個原生 <details> 裡（無 JS）。

    為什麼不是一張平表：血脂 51 列、BMI 腰圍 58 列，讀者要找「我這個指標的分級」
    得在同一張表裡捲過別的指標。分組後組名就是路標。

    多指標頁**不再有「指標」欄**——指標已經寫在組名上，每列再重複一次是白佔一欄寬。
    """
    labels = labels or {}
    groups = group_criteria_rows(rows, multi, labels)
    open_all = len(rows) <= CRIT_OPEN_ALL_MAX
    head = ("<thead><tr><th>機構</th><th>判準值</th><th>族群</th>"
            "<th>依據文件與版本（含頁碼或表號）</th></tr></thead>")
    out = [f'<p class="crit-sum">共 {len(rows)} 列，分 {len(groups)} 組；'
           "點組名可展開或收合。</p>"]
    for iid, cat, grp in groups:
        body = "".join(
            "<tr>"
            f"<td>{esc(org_label(r['org']))}</td>"
            f"<td>{esc(criteria_cell(r))}</td>"
            f"<td>{esc(r['population'])}</td>"
            f"<td>{esc(source_cell(r, mf))}</td>"
            "</tr>" for r in grp)
        name = (f"{esc(labels.get(iid, iid))}｜" if iid else "") + esc(CATEGORY_LABEL[cat])
        op = " open" if (open_all or cat in CRIT_OPEN_CATEGORIES) else ""
        out.append(
            f'<details class="crit-grp"{op}>'
            f'<summary>{name}（{len(grp)} 列）</summary>'
            '<div class="tbl-scroll"><table class="std-table">'
            + head + "<tbody>" + body + "</tbody></table></div></details>")
    return "".join(out)


# ---------- 圖一：判準數線 ----------

X0, X1, TOP = 118, 704, 32
ROW_H, ROW_PITCH, FIRST_ROW_Y = 26, 58, 42
SUB_DY, SUB_H = 34, 12


def _axis_cfg(indicator_id: str, rows: list) -> dict:
    if indicator_id in AXIS:
        return AXIS[indicator_id]
    vals = [v for r in rows for v in (r.get("lower"), r.get("upper")) if v is not None]
    lo, hi = (min(vals), max(vals)) if vals else (0.0, 1.0)
    pad = (hi - lo) * 0.25 or 1.0
    return {"min": lo - pad, "max": hi + pad, "ticks": [lo - pad, lo, hi, hi + pad], "label": ""}


def line_title(indicator_id: str, rows: list, labels: dict) -> str:
    """多指標頁每條數線的標題＝短標籤＋單位（單位照資料抄，沒有就只放短標籤）。"""
    units = [r["unit"] for r in rows if r.get("unit")]
    return f"{labels[indicator_id]}（{units[0]}）" if units else labels[indicator_id]


def render_number_line(rows: list, indicator_id: str, mf: dict, slug: str,
                       caption: str) -> str:
    """各機構判準數線：同一批 criteria 列，畫的與表上的是同一份數字。

    一頁多指標時每個 indicator_id 各一條，rows 已先按 indicator_id 篩過。

    兩端都沒有數值的列畫不出來（例：流程圖型的篩檢分流），不硬畫也不靜默丟掉——
    在圖下明說有幾列只在表上。
    """
    cfg = _axis_cfg(indicator_id, rows)
    vmin, vmax = cfg["min"], cfg["max"]

    def X(v):
        return f"{round(X0 + (v - vmin) / (vmax - vmin) * (X1 - X0), 1):g}"

    # P5：已被取代的列不畫上數線——它的數字已經不是現行判準，繼續畫出來會讓
    # 讀者以為新舊兩條線同時有效。表上仍完整保留這一列（依據欄標「已被 X 取代」），
    # 只有這張圖不畫；被排除的機構若因此沒有任何可畫的列，也整條標籤一起消失
    # （不留一個沒有內容的機構列）。
    superseded = [r for r in rows if r.get("superseded_by")]
    draw_rows = [r for r in rows if not r.get("superseded_by")]

    orgs = list(dict.fromkeys(r["org"] for r in draw_rows))
    by_org = {o: [r for r in draw_rows if r["org"] == o] for o in orgs}

    diag_units = [r for r in draw_rows if r["category"] == "diagnosis" and r.get("lower") is not None]
    refs = sorted({r["lower"] for r in diag_units})
    ref_unit = "%"
    if diag_units:
        u = diag_units[0].get("unit") or ""
        ref_unit = "%" if u.startswith("%") else unit_suffix(u)

    undrawable, parts = [], []
    bottom = FIRST_ROW_Y + ROW_H
    for i, org in enumerate(orgs):
        y = FIRST_ROW_Y + ROW_PITCH * i
        mid = y + ROW_H / 2
        color = org_color(org)
        parts.append(f'<text class="lb" x="106" y="{mid:g}" text-anchor="end" '
                     f'dominant-baseline="central">{esc(org_label(org))}</text>')
        for r in by_org[org]:
            tip = (f"{org_label(org)}｜{criteria_cell(r)}｜族群：{r['population']}"
                   f"｜依據：{source_ref(r['doc_id'], mf, r['page_or_table'])}")
            title = f"<title>{esc(tip)}</title>"
            lo, up = r.get("lower"), r.get("upper")
            label = value_text(r, short=True)
            if lo is None and up is None:
                if r["category"] == "no_criterion_stated":
                    cx = (X0 + float(X(refs[0]))) / 2 if refs else (X0 + X1) / 2
                    parts.append(
                        f'<g class="seg">{title}<text class="sm mu" x="{cx:g}" y="{mid:g}" '
                        f'text-anchor="middle" dominant-baseline="central">'
                        f'{esc(CATEGORY_LABEL[r["category"]])}</text></g>')
                else:
                    undrawable.append(r)
                continue
            if r["category"] == "screening_triage":
                sy = y + SUB_DY
                x_a = X(lo) if lo is not None else X(vmin)
                x_b = X(up) if up is not None else X(vmax)
                w = float(x_b) - float(x_a)
                parts.append(
                    f'<g class="seg">{title}'
                    f'<rect x="{x_a}" y="{sy:g}" width="{w:g}" height="{SUB_H}" rx="2" '
                    f'fill="{color}" fill-opacity=".1" stroke="{color}" stroke-width="1.5" '
                    f'stroke-dasharray="5 3"/>'
                    # 標籤只放數值：類別由虛線框＋圖例承載，再加一次「篩檢分流」四個字，
                    # 在窄螢幕的放大字級下會頂出 viewBox 右緣。
                    f'<text class="sm mu" x="{float(x_b) + 7:g}" y="{sy + SUB_H / 2:g}" '
                    f'dominant-baseline="central">{esc(label)}</text></g>')
                bottom = max(bottom, sy + SUB_H)
                continue
            x_a = X(lo) if lo is not None else X(vmin)
            x_b = X(up) if up is not None else X(vmax)
            w = float(x_b) - float(x_a)
            solid = r["category"] == "diagnosis"
            fill_op = "" if solid else ' fill-opacity="var(--wash)"'
            cls = "sm on" if solid else "sm"
            parts.append(
                f'<g class="seg">{title}'
                f'<rect x="{x_a}" y="{y:g}" width="{w:g}" height="{ROW_H}" rx="3" '
                f'fill="{color}"{fill_op}/>'
                f'<text class="{cls}" x="{(float(x_a) + float(x_b)) / 2:g}" y="{mid:g}" '
                f'text-anchor="middle" dominant-baseline="central">{esc(label)}</text></g>')
            bottom = max(bottom, y + ROW_H)

    axis_y = bottom + 26
    vb_h = axis_y + 56

    grid = "".join(f'<line x1="{X(t)}" y1="{TOP}" x2="{X(t)}" y2="{axis_y:g}"/>'
                   for t in cfg["ticks"] if t not in refs)
    ref_lines = "".join(
        f'<line class="ref" x1="{X(v)}" y1="{TOP}" x2="{X(v)}" y2="{axis_y:g}"/>'
        f'<text class="bd" x="{X(v)}" y="24" text-anchor="middle">{num(v)}{ref_unit}</text>'
        for v in refs)
    all_ticks = sorted(set(cfg["ticks"]) | set(refs))
    # 刻度標籤的小數位取整組最長者：混成「4.5／5／6」會讓讀者以為刻度不等距。
    dec = max((len(f"{t:g}".partition(".")[2]) for t in all_ticks), default=0)
    ticks = "".join(f'<line x1="{X(t)}" y1="{axis_y:g}" x2="{X(t)}" y2="{axis_y + 6:g}"/>'
                    for t in all_ticks)
    tick_labels = "".join(
        f'<text class="sm mu" x="{X(t)}" y="{axis_y + 20:g}" text-anchor="middle">'
        f'{t:.{dec}f}</text>' for t in all_ticks)
    axis_label = (f'<text class="sm mu" x="{X1}" y="{axis_y + 46:g}" text-anchor="end">'
                  f'{esc(cfg["label"])}</text>' if cfg.get("label") else "")

    aria = "、".join(org_label(o) for o in orgs)
    legend = "".join(
        f'<span><i style="background:{org_color(o)}"></i>{esc(org_label(o))}</span>'
        for o in orgs)
    # ☠️ 圖例的類別文字由資料推導，不寫死：淡色帶承載的是「畫得出來、但不是診斷線也
    # 不是篩檢分流」的那些類別，血壓頁是分級、腰圍頁是風險門檻，寫死「糖尿病前期」
    # 就會在別的指標頁上安靜地說錯話。
    wash_cats = [c for c in TABLE_CATEGORIES
                 if c not in ("diagnosis", "screening_triage")
                 and any(r["category"] == c
                         and (r.get("lower") is not None or r.get("upper") is not None)
                         for r in draw_rows)]
    # 多個類別共用同一個淡色帶時併成一個圖例項：同一個色塊給兩行圖例，等於讓一個
    # 視覺通道承載兩種語意，讀者會以為深淺之外還有別的差別。
    if wash_cats:
        legend += ('<span><i style="background:var(--c-ada);opacity:.32"></i>淡色帶＝'
                   + esc("／".join(CATEGORY_LABEL[c] for c in wash_cats)) + '</span>')
    if any(r["category"] == "screening_triage" and r.get("lower") is not None for r in draw_rows):
        legend += ('<span><i class="dash"></i>虛線框＝'
                   f'{esc(CATEGORY_LABEL["screening_triage"])}</span>')
    for v in refs:
        legend += f'<span><i class="rule"></i>{num(v)}{ref_unit} 參考線</span>'

    note_parts = []
    if undrawable:
        note_parts.append("另有 " + str(len(undrawable))
                          + " 列的來源未給數值區間（流程圖型判準），畫不到數線上，只列於上表。")
    if superseded:
        note_parts.append("另有 " + str(len(superseded))
                          + " 列已被新版取代，不畫在數線上，只列於上表（依據欄標示取代關係）。")
    note = ("　" + "".join(note_parts)) if note_parts else ""
    # criteria 列沒有 id 欄，用「原始檔案內的第幾列」當索引（_row_no 在 build() 標上，
    # 不用 list.index——相同內容的兩列會讓 index() 都指回第一列，那是靜默的錯指）。
    basis = "、".join(f"第 {r['_row_no']} 列（{r['doc_id']}）" for r in rows)

    return f"""<figure class="chart">
<figcaption class="ct">{esc(caption)}</figcaption>
<div class="lg">{legend}</div>
<svg class="cs" viewBox="0 0 720 {vb_h:g}" role="img" aria-label="{esc(aria)}的{esc(cfg.get('label', ''))}判準數線">
<g class="grid">{grid}</g>
{ref_lines}
{"".join(parts)}
<g class="axis"><line x1="{X0}" y1="{axis_y:g}" x2="{X1}" y2="{axis_y:g}"/>{ticks}</g>
{tick_labels}
{axis_label}
</svg>
<p class="src">依據：data/criteria/{esc(slug)}.json {esc(basis)}。判準值與完整出處見上表。{esc(note)}</p>
</figure>"""


# ---------- 圖二：判準沿革時間軸 ----------

def _timeline_svg(rows: list, vb_w: int, wrap: int, dot_x: int, text_x: int, cls: str) -> str:
    f_year, f_org, f_body, line_h = 17, 13.5, 15.5, 22
    y, entries = 40, []
    for r in rows:
        lines = wrap_cjk(r["change"], wrap)
        tip = (f"{r['id']}｜{r['year']}｜{org_label(r['org'])}｜{r['change']}"
               f"｜依據：{r['doc_id']} {r['page_or_table']}")
        block = [f'<g class="seg"><title>{esc(tip)}</title>',
                 f'<circle cx="{dot_x}" cy="{y}" r="7" fill="{org_color(r["org"])}" '
                 f'stroke="var(--bg)" stroke-width="2.5"/>',
                 f'<text x="{text_x}" y="{y - 8}" font-size="{f_year:g}" font-weight="600">'
                 f'{esc(r["year"])}</text>',
                 f'<text class="mu" x="{text_x}" y="{y + 12}" font-size="{f_org:g}">'
                 f'{esc(org_label(r["org"]))}</text>']
        for i, ln in enumerate(lines):
            block.append(f'<text x="{text_x}" y="{y + 34 + line_h * i}" '
                         f'font-size="{f_body:g}">{esc(ln)}</text>')
        block.append("</g>")
        entries.append("".join(block))
        y += 34 + line_h * len(lines) + 26
    last = y - 26
    axis = f'<line class="axis" x1="{dot_x}" y1="24" x2="{dot_x}" y2="{last - 10}"/>'
    return (f'<svg class="cs {cls}" viewBox="0 0 {vb_w} {last + 8}" role="img" '
            f'aria-label="判準沿革時間軸，共 {len(rows)} 次具名變更">'
            f'{axis}{"".join(entries)}</svg>')


def history_sort_key(r: dict) -> tuple:
    """P7：(year, id 數字) 遞增——純資料鍵，不含檔案順序，重跑仍 byte-identical。

    ☠️ id 不能照字串排（H10 會排在 H2 前面），取數字部分，同 errata_order() 的作法。"""
    return (r["year"], int(r["id"][1:]))


def render_history(rows: list, mf: dict, slug: str) -> str:
    """判準沿革時間軸。history 檔以頁面 slug 定位，多指標頁共用一條時間軸。

    ☠️ 資料檔內的順序不再重要：這裡先依 (year, id 數字) 排過，時間軸與下表兩處
    渲染都吃排序後的結果，資料檔要怎麼擺（可讀性）與頁面要怎麼畫（時序）分開。"""
    rows = sorted(rows, key=history_sort_key)
    orgs = list(dict.fromkeys(r["org"] for r in rows))
    legend = "".join(
        f'<span><i class="dot" style="background:{org_color(o)}"></i>{esc(org_label(o))}</span>'
        for o in orgs)
    head = ("<thead><tr><th>年份</th><th>機構</th><th>變更內容</th>"
            "<th>依據文件與版本（含頁碼或表號）</th><th>列號</th></tr></thead>")
    body = "".join(
        "<tr>"
        f"<td>{esc(r['year'])}</td>"
        f"<td>{esc(org_label(r['org']))}</td>"
        f"<td>{esc(r['change'])}</td>"
        f"<td>{esc(source_ref(r['doc_id'], mf, r['page_or_table']))}</td>"
        f"<td>{esc(r['id'])}</td>"
        "</tr>" for r in rows)
    table = ('<div class="tbl-scroll"><table class="std-table">'
             + head + "<tbody>" + body + "</tbody></table></div>")
    basis = "、".join(f"{r['id']}（{r['doc_id']}）" for r in rows)
    return f"""<figure class="chart">
<figcaption class="ct">同一個指標，判準被改過幾次、誰改的</figcaption>
<div class="lg">{legend}</div>
{_timeline_svg(rows, 720, 30, 26, 48, "wide-only")}
{_timeline_svg(rows, 340, 15, 22, 42, "narrow-only")}
<p class="src">依據：data/criteria/{esc(slug)}-history.json {esc(basis)}。事件點依序排列，縱軸不等距於實際年數；完整出處見下表。</p>
</figure>
{table}"""


# ---------- 圖三：失真卡 ----------

def render_interference(rows: list, mf: dict, slug: str) -> str:
    """五種 direction 各自成欄；來源沒指方向的收在「未指方向」欄，不併也不猜。

    interference 檔同樣以頁面 slug 定位，多指標頁共用一張失真卡。
    """
    by_dir = {d: [r for r in rows if r["direction"] == d] for d in DIRECTION_ORDER}
    unknown = sorted({r["direction"] for r in rows} - set(DIRECTION_ORDER))
    if unknown:
        raise SystemExit(f"❌ 未知的 direction：{unknown}（生成器不替來源決定方向）")

    cols = []
    for d in DIRECTION_ORDER:
        group = by_dir[d]
        if not group:
            continue
        items = "".join(
            f'<li><i style="background:{org_color(r["org"])}"></i>'
            f'<span>{esc(r["factor"])}'
            f'<span class="tag">{esc(org_label(r["org"]))}　{esc(r["id"])}</span></span></li>'
            for r in group)
        cols.append(f'<div class="col"><h3>{esc(DIRECTION_LABEL[d])}'
                    f'<b>{len(group)} 列</b></h3><ul>{items}</ul></div>')

    orgs = list(dict.fromkeys(r["org"] for r in rows))
    legend = "".join(
        f'<span><i class="dot" style="background:{org_color(o)}"></i>{esc(org_label(o))}</span>'
        for o in orgs)
    head = ("<thead><tr><th>方向</th><th>情況</th><th>機構</th>"
            "<th>依據文件與版本（含頁碼或表號）</th><th>列號</th></tr></thead>")
    body = "".join(
        "<tr>"
        f"<td>{esc(DIRECTION_LABEL[r['direction']])}</td>"
        f"<td>{esc(r['factor'])}</td>"
        f"<td>{esc(org_label(r['org']))}</td>"
        f"<td>{esc(source_ref(r['doc_id'], mf, r['page_or_table']))}</td>"
        f"<td>{esc(r['id'])}</td>"
        "</tr>" for r in rows)
    table = ('<div class="tbl-scroll"><table class="std-table">'
             + head + "<tbody>" + body + "</tbody></table></div>")
    basis = "、".join(f"{r['id']}（{r['doc_id']}）" for r in rows)
    return f"""<figure class="chart">
<figcaption class="ct">同一批狀況，各機構標的方向不一樣，也有只說會影響而未指方向的</figcaption>
<div class="lg">{legend}</div>
<div class="fx">{"".join(cols)}</div>
<p class="src">依據：data/criteria/{esc(slug)}-interference.json {esc(basis)}。方向一律照來源原文標示，來源未指方向者不推論。</p>
</figure>
{table}"""


# ---------- ⑥ 來源與版本（從 manifest 生成） ----------

def render_sources(source_ids: list, mf: dict) -> str:
    items = []
    for sid in source_ids:
        m = mf.get(sid)
        if not m:
            raise SystemExit(f"❌ frontmatter 的 sources 指不到 manifest：{sid}")
        title = esc(m["title"])
        link = (f'<a href="{esc(m["url"])}" rel="nofollow noopener" target="_blank">{title}</a>'
                if m.get("url") else title)
        items.append(f'<li>{esc(m["org"])}《{link}》{esc(m["version_or_date"])}</li>')
    return f'<ol class="src-list">{"".join(items)}</ol>'


# ---------- 勘誤紀錄（指標頁的段落＋站級頁） ----------

# 只在真的有勘誤列時才注入（零列的頁面連 CSS 都不多一個 byte——加了就是全站
# 每一頁都因為「有這個功能」而改變，公開後那是一次沒有內容變化的全站 diff）。
ERRATA_CSS = """
ol.errata{ margin:10px 0 0; padding-left:1.4em; }
ol.errata li{ font-size:14.5px; line-height:1.85; margin:0 0 10px; }
ol.errata .er-src{ display:block; font-size:12.5px; color:var(--dim); line-height:1.7; }
"""

# 站級勘誤頁沒有圖表，不載 CHART_CSS，但共用同一句免責聲明，樣式要一致。
# ☠️ 下面的 .ind-foot 是 CHART_CSS 裡那條規則的副本：抽成共用常數會改到指標頁的
# CSS bytes（M5 的驗收條件是既有頁面 byte-identical），所以刻意留兩份——
# 兩份會不會偷偷長歪，由測試盯（test_errata_page_reuses_the_indicator_foot_rule）。
ERRATA_FOOT_CSS = """
.ind-foot{ font-size:12.5px; color:var(--dim); border-top:1px solid var(--line);
           padding-top:10px; margin-top:34px; }
.lede{ font-size:15px; line-height:1.9; margin:0 0 14px; }
"""


def load_errata(path=None) -> list:
    """讀 data/errata.json。檔案不存在＝這站還沒有勘誤層，回 []（不是錯）。"""
    p = pathlib.Path(path) if path else ERRATA_PATH
    return load_json(p) if p.exists() else []


def errata_order(rows: list) -> list:
    """最新在前：date 由新到舊，同一天由 id 的數字由大到小（id 遞增＝越後面越新）。

    ☠️ id 不能照字串排（E10 會排在 E2 前面），取數字部分。排序鍵完全來自資料，
    不含檔案順序也不含時間，所以重跑仍 byte-identical。
    """
    return sorted(rows, key=lambda r: (r["date"], int(r["id"][1:])), reverse=True)


def errata_line(r: dict, mf: dict) -> str:
    """一列勘誤的文字。有 doc_id 才有「依據」，沒有就不編一個出來。"""
    out = (f"{esc(r['date'])}｜{esc(ERRATA_SECTION_LABEL[r['section']])}："
           f"原寫「{esc(r['was'])}」，改為「{esc(r['now'])}」。{esc(r['reason'])}")
    if r.get("doc_id"):
        out += f'<span class="er-src">依據：{esc(source_ref(r["doc_id"], mf, ""))}</span>'
    return out


def render_errata_list(rows: list, mf: dict, titles: dict = None) -> str:
    """勘誤清單。titles 有給（站級頁）就在每列前面加該頁標題連結；指標頁不加
    （讀者已經在那一頁上了，再連一次是繞回原地）。"""
    items = []
    for r in errata_order(rows):
        prefix = ""
        if titles is not None:
            prefix = (f'<a href="/indicators/{esc(r["slug"])}/">'
                      f'{esc(titles[r["slug"]])}</a>｜')
        items.append(f"<li>{prefix}{errata_line(r, mf)}</li>")
    return f'<ol class="errata">{"".join(items)}</ol>'


def render_errata_page(rows: list, mf: dict, titles: dict, published: bool) -> str:
    """站級勘誤頁 /errata/：列出全站所有勘誤，最新在前。零列也照生（頁面要能說出
    「目前沒有勘誤」，那與「還沒有這個機制」是兩件事）。"""
    body_parts = [f'<p class="lede">{esc(ERRATA_LEDE)}</p>']
    if rows:
        body_parts.append(render_errata_list(rows, mf, titles))
    else:
        body_parts.append(f"<p>{esc(ERRATA_EMPTY)}</p>")
    body = ('  <main>\n'
            f'  <h1 class="pg-h1">{esc(ERRATA_TITLE)}</h1>\n'
            + "\n".join(body_parts)
            + f'\n  <p class="ind-foot">{esc(FOOT_LINE)}</p>\n  </main>')

    # ☠️ 這裡不放 dateModified／勘誤筆數：那是彙總欄，資料層明令不存，頁面層也不生。
    page_node = {
        "@type": "WebPage", "@id": f"{ERRATA_URL}#page",
        "name": ERRATA_TITLE, "description": ERRATA_LEDE, "url": ERRATA_URL,
        "inLanguage": "zh-Hant", "isAccessibleForFree": True,
        "mainEntityOfPage": ERRATA_URL,
        "publisher": {"@id": f"{hl.BASE}/#org"},
    }
    jsonld = hl.graph_ld([
        hl.org_node(), hl.website_node(), page_node,
        hl.breadcrumb_node([("首頁", f"{hl.BASE}/"), (ERRATA_TITLE, ERRATA_URL)])])
    return hl.page_shell(ERRATA_TITLE, ERRATA_LEDE, ERRATA_URL, jsonld, body,
                         "errata", extra_css=ERRATA_CSS + ERRATA_FOOT_CSS)


# ---------- 頁面組裝 ----------

FOOT_LINE = "本站不提供診斷或治療建議。頁面整理的是各機構公開文件寫了什麼，個人數值的意義請與您的醫師討論。"


def render_page(meta: dict, h1: str, sections: list, crit: list, hist: list,
                intf: list, errata: list, mf: dict, ids: list, labels: dict,
                slug: str, published: bool) -> str:
    url = f"{hl.BASE}/indicators/{slug}/"
    title = meta.get("title", h1)
    desc = (sections[0][1][0] if sections[0][1] else "")[:120]
    multi = len(ids) > 1

    blocks = []
    for i, (head, paras) in enumerate(sections):
        blocks.append(f'<h2 class="sec-h">{esc(head)}</h2>')
        if i == 1:                                   # ② 各機構判準並列
            if paras:
                blocks.append(f"<p>{esc(paras[0])}</p>")
            blocks.append(render_criteria_table(crit, mf, multi, labels))
            blocks.extend(f"<p>{esc(p)}</p>" for p in paras[1:])
            # 一個 indicator_id 一條數線；多指標頁的標題＝短標籤＋單位，單指標頁
            # 的標題是編輯下的判斷（「分歧全在門檻以下」不是資料推得出來的），
            # 所以走 frontmatter 的 criteria_chart_caption，缺了就中止不猜。
            for iid in ids:
                rows = [r for r in crit if r["indicator_id"] == iid]
                if not rows:
                    raise SystemExit(
                        f"❌ {slug}：indicator_ids 列了 {iid}，但 data/criteria/{slug}.json "
                        "沒有它可渲染的判準列（頁面不得宣稱一個沒有資料的指標）。")
                caption = line_title(iid, rows, labels) if multi else meta.get(
                    "criteria_chart_caption", "")
                if not caption:
                    raise SystemExit(
                        f"❌ {slug}：frontmatter 缺 criteria_chart_caption（判準數線的標題）。")
                blocks.append(render_number_line(rows, iid, mf, slug, caption))
        else:
            blocks.extend(f"<p>{esc(p)}</p>" for p in paras)
            if i == 2 and hist:                      # ③ 判準什麼時候改過
                blocks.append(render_history(hist, mf, slug))
            elif i == 3 and intf:                    # ④ 哪些情況這個數字會失真
                blocks.append(render_interference(intf, mf, slug))
            elif i == 5:                             # ⑥ 來源與版本
                blocks.append(render_sources(meta["sources"], mf))

    # 勘誤紀錄：這一頁有被改過才出現。零列時整段不存在（連 CSS 都不多一個 byte）——
    # 空的「勘誤紀錄（0 筆）」看起來像功能沒接好，而且會讓每一頁都因為別頁的更正而變。
    if errata:
        blocks.append(f'<h2 class="sec-h">{esc(ERRATA_TITLE)}</h2>')
        blocks.append(render_errata_list(errata, mf))

    body = ('  <main>\n'
            f'  <h1 class="pg-h1">{esc(h1)}</h1>\n'
            + "\n".join(blocks)
            + f'\n  <p class="ind-foot">{esc(FOOT_LINE)}</p>\n  </main>')

    page_node = {
        "@type": "MedicalWebPage", "@id": f"{url}#page",
        "name": title, "description": desc, "url": url,
        "inLanguage": "zh-Hant", "isAccessibleForFree": True,
        "dateModified": meta.get("updated", ""),
        "mainEntityOfPage": url,
        "publisher": {"@id": f"{hl.BASE}/#org"},
        # citation＝頁面上每個數字的來源文件（順序＝frontmatter sources）。
        # ☠️ 這裡永遠不放任何評分／aggregateRating：本站不評價文件，只列它寫了什麼。
        "citation": [
            {"@type": "CreativeWork", "name": mf[s]["title"],
             "url": mf[s].get("url", ""), "version": mf[s]["version_or_date"],
             "publisher": {"@type": "Organization", "name": mf[s]["org"]}}
            for s in meta["sources"] if s in mf],
    }
    jsonld = hl.graph_ld([
        hl.org_node(), hl.website_node(), page_node,
        hl.breadcrumb_node([("首頁", f"{hl.BASE}/"),
                            ("指標", f"{hl.BASE}/indicators/" if published else None),
                            (title, url)])])

    return hl.page_shell(title, desc, url, jsonld, body, "indicators",
                         extra_css=CHART_CSS + (ERRATA_CSS if errata else ""))


# ---------- dormant 接線 ----------

LLMS_HEAD = "## 指標頁"


def wire_llms(pages: list, llms_path: pathlib.Path, published: bool,
              extra: list = None):
    """llms.txt 的指標頁區塊：dormant 時整塊不存在，翻開關才出現。

    做法是「先移除既有區塊再視情況重寫」，所以重跑幾次都一樣（build-articles.py
    每次重寫 llms.txt，本函式跑在它之後）。翻回 false 也會把區塊收乾淨。

    extra＝[(標題, URL, 說明)]，接在區塊最後（站級的 /errata/ 走這裡）。☠️ 不把它
    併進 pages：那份清單的說明句是「各機構判準並列、判準沿革與已知限制」，勘誤頁
    不是那種頁，共用會讓 llms.txt 對它說錯話。
    """
    if not llms_path.exists():
        return
    text = llms_path.read_text(encoding="utf-8")
    if f"\n{LLMS_HEAD}\n" in text:
        head, _, tail = text.partition(f"\n{LLMS_HEAD}\n")
        nxt = tail.find("\n## ")
        text = head + (tail[nxt:] if nxt >= 0 else "\n")
    if published and pages:
        rows = [(t, u, "各機構判準並列、判準沿革與已知限制。") for t, u in pages]
        rows += list(extra or [])
        lines = "\n".join(f"- [{t}]({u})：{d}" for t, u, d in rows)
        text = text.rstrip("\n") + f"\n\n{LLMS_HEAD}\n\n{lines}\n"
    if text != llms_path.read_text(encoding="utf-8"):
        llms_path.write_text(text, encoding="utf-8")


def wire_sitemap(pages: list, parts_dir: pathlib.Path, published: bool):
    """sitemap part：dormant 時不寫，且既有的 part 檔要收掉（不留死 URL）。

    沒有直接用 healthlib.write_sitemap_part()：那支固定寫 repo 內的目錄，
    這裡多兩件它沒有的事——目錄可注入（測試不弄髒 repo）、翻回 dormant 要刪檔。
    寫出來的格式與它相同（一行一 URL、結尾換行），build-sitemap.py 照樣讀得到。
    """
    part = parts_dir / f"{SITEMAP_OWNER}.txt"
    if not published:
        if part.exists():
            part.unlink()
            print(f"🗺️  dormant：移除 sitemap part '{SITEMAP_OWNER}'（未公開不進 sitemap）")
        return
    parts_dir.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{u}\n" for _, u in pages)
    if not part.exists() or part.read_text(encoding="utf-8") != content:
        part.write_text(content, encoding="utf-8")
    print(f"🗺️  sitemap part '{SITEMAP_OWNER}' → {len(pages)} URL(s)")


def prune_stale(out_root: pathlib.Path, keep: set):
    root = out_root / "indicators"
    if not root.exists():
        return
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name not in keep:
            shutil.rmtree(child)
            print(f"🗑  removed stale indicator output: {child.name}")


# ---------- build ----------

def build(slugs=None, out_root=None, parts_dir=None, llms_path=None, published=None) -> list:
    out_root = pathlib.Path(out_root) if out_root else hl.PUB
    parts_dir = pathlib.Path(parts_dir) if parts_dir else ROOT / "data" / "sitemap-parts"
    llms_path = pathlib.Path(llms_path) if llms_path else out_root / "llms.txt"
    if published is None:
        published = json.loads((ROOT / "config" / "site.json").read_text(
            encoding="utf-8")).get("published", False) is True

    # 一次 build 內 published 只有一個值：導覽／頁尾的 gate（healthlib.PUBLISHED）
    # 與 sitemap／llms 接線吃同一個旗標，不會出現「頁面連了但 sitemap 沒有」的半開狀態。
    hl.PUBLISHED = published

    mf = manifest_index()
    errata_all = load_errata()
    files = sorted(SRC_DIR.glob("*.md")) if SRC_DIR.exists() else []
    if slugs:
        files = [f for f in files if f.stem in set(slugs)]
    if not files:
        print("ℹ️  articles/indicators/ 沒有正文檔，未生成任何指標頁。")
        return []

    pages, titles = [], {}
    for f in files:
        meta, h1, sections = parse_article(f)
        slug = meta.get("slug") or f.stem
        ids, labels = page_indicators(meta, slug)

        # 三個資料檔一律以**頁面 slug** 定位（不是 indicator_id）：一頁多指標時
        # 「哪些 indicator_id 進這頁」是 frontmatter 的事，檔名只認頁面。
        crit_path = CRITERIA_DIR / f"{slug}.json"
        if not crit_path.exists():
            raise SystemExit(f"❌ 找不到判準明細：{crit_path}（沒有資料就不生成頁面）")
        # P10：indicator_id 不在這頁 frontmatter ids 內的列，過去是靜默丟掉（例：
        # bmi-waist.json 混了 whr 兩列，頁面只收 bmi／waist）。改成印警告不 fail——
        # 資料層允許一個檔混放屬於別頁的列，但丟列這件事不能無聲：可能是真的不屬於
        # 這頁，也可能是打錯 indicator_id。索引＝JSON 陣列位置（0 起算，與稽核 findings
        # 的列號口徑一致），與下面 _row_no（1 起算、只用於圖下依據行）是兩套不同的數。
        crit_raw = load_json(crit_path)
        off_page = [(i, r) for i, r in enumerate(crit_raw) if r["indicator_id"] not in ids]
        for i, r in off_page:
            print(f"⚠️  {slug}：第 {i} 列（JSON 索引）的 indicator_id="
                 f"「{r['indicator_id']}」不在這頁的 indicator_ids {ids} 內，已略過。")

        # _row_no＝該列在原始 json 檔裡的行序（1 起算），只用於圖下「依據」行的回指，
        # 不寫回資料檔（判準層只存明細，不存衍生欄位）。
        crit = [dict(r, _row_no=i) for i, r in enumerate(crit_raw, start=1)
                if r["indicator_id"] in ids and r["category"] in TABLE_CATEGORIES]
        if not crit:
            raise SystemExit(f"❌ {slug}（{'、'.join(ids)}）沒有可渲染的判準列"
                             "（TABLE_CATEGORIES 皆空）。")

        hp = CRITERIA_DIR / f"{slug}-history.json"
        # status 為「未證實」的列不得渲染（history schema 的宣告）。
        hist = [r for r in load_json(hp) if r.get("status") != "未證實"] if hp.exists() else []
        ip = CRITERIA_DIR / f"{slug}-interference.json"
        intf = load_json(ip) if ip.exists() else []

        errata = [e for e in errata_all if e["slug"] == slug]
        html_out = render_page(meta, h1, sections, crit, hist, intf, errata, mf,
                               ids, labels, slug, published)
        out_dir = out_root / "indicators" / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(html_out, encoding="utf-8")
        titles[slug] = meta.get("title", h1)
        pages.append((titles[slug], f"{hl.BASE}/indicators/{slug}/"))
        print(f"✅ /indicators/{slug}/　判準 {len(crit)} 列／沿革 {len(hist)} 列／"
              f"限制 {len(intf)} 列／勘誤 {len(errata)} 列")

    extra = []
    if not slugs:  # 只跑部分 slug 時不清別人的輸出（平行寫手互刪頁的坑）
        prune_stale(out_root, {u.rstrip("/").rsplit("/", 1)[-1] for _, u in pages})
        # 站級勘誤頁只在全量 build 生成：它列的是全站，只跑一個 slug 時手上沒有
        # 別頁的標題，生出來會是一份殘缺的清單。也不刪它（上一次全量 build 的仍有效）。
        missing = sorted({e["slug"] for e in errata_all} - set(titles))
        if missing:
            raise SystemExit(
                f"❌ data/errata.json 的 slug 指不到任何指標頁：{missing}"
                "（勘誤要有落點；改錯 slug 的那一列會在站級頁上連到 404）。")
        errata_dir = out_root / "errata"
        errata_dir.mkdir(parents=True, exist_ok=True)
        (errata_dir / "index.html").write_text(
            render_errata_page(errata_all, mf, titles, published), encoding="utf-8")
        print(f"✅ /errata/　勘誤 {len(errata_all)} 列")
        extra = [(ERRATA_TITLE, ERRATA_URL, ERRATA_LLMS_DESC)]

    # 勘誤頁排在最後一行：sitemap 與 llms 的指標頁區塊都以指標頁為主，站級頁墊底。
    wire_sitemap(pages + [(t, u) for t, u, _ in extra], parts_dir, published)
    wire_llms(pages, llms_path, published, extra)
    if not published:
        print("🔒 dormant（config/site.json published=false）：頁面已生成，"
              "但不進 sitemap／llms.txt，導覽不連。")
    return pages


def main() -> int:
    ap = argparse.ArgumentParser(description="指標頁生成器（資料驅動，dormant 感知）")
    ap.add_argument("slugs", nargs="*", help="要生成的 slug（預設全部）")
    args = ap.parse_args()
    build(slugs=args.slugs or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
