#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事實包產生器：把一個指標頁會碰到的每一列資料，照 schema 全欄印成查核用的 Markdown。

用法：
  python3 scripts/gen-factpack.py <slug> [--ids ast,alt] [--out 路徑]

  --ids 只在正文檔還不存在時需要（新頁寫稿前先審事實表）；正文檔在，就以
  frontmatter 的 indicator_ids 為準。

為什麼要有這支（2026-09-10 血糖併頁那輪）：
  事實包原本是指揮位用一次性腳本、手選欄位印的，同一天漏了三次
  （*_inclusive、quote_extra、confirmation_procedure 那列的 category），
  每漏一欄，查核席就憑空生出一條假 finding，還會稀釋掉真的那幾條。
  三次的共同根因是「手選欄位」。
  ⇒ 這支不選欄：走 schema 的 properties 全欄印，選填欄沒填也印「（未填）」；
    印完再把輸出**讀回來**數欄位，與 schema 的欄位集合比對，缺一欄就 exit 1。
    （只比對迴圈本身證明不了什麼——要驗的是產物。）
  ⇒ 也不選列：印整個 <slug>.json，含不進判準表的列、indicator_id 不在這頁的列，
    因為稿子會碰到的列不只本輪動到的那幾列。

產物給查核桌讀，不進 build、不上站；決定性（無時間戳）。
"""
import argparse
import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CRITERIA_DIR = ROOT / "data" / "criteria"
MANIFEST = ROOT / "data" / "sources" / "manifest.json"
ARTICLES = ROOT / "articles" / "indicators"

sys.path.insert(0, str(ROOT / "scripts"))
import healthlib as hl  # noqa: E402


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_indicator", ROOT / "scripts" / "gen-indicator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def item_properties(schema_path: pathlib.Path) -> dict:
    """schema 的「一列」有哪些欄位（保留 schema 內的順序）。

    兩種寫法都收：頂層 items 直接給 properties，或 items 用 $ref 指到 $defs。
    """
    s = json.loads(schema_path.read_text(encoding="utf-8"))
    node = s.get("items", s)
    ref = node.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        node = s["$defs"][name]
    if "properties" not in node and "$defs" in s and len(s["$defs"]) == 1:
        node = next(iter(s["$defs"].values()))
    if "properties" not in node:
        raise SystemExit(f"❌ 讀不出 {schema_path} 的列欄位（找不到 properties）")
    return node["properties"]


def manifest_properties() -> dict:
    s = json.loads((ROOT / "data" / "sources" / "schema.json").read_text(encoding="utf-8"))
    if "$defs" in s and "source" in s["$defs"]:
        return s["$defs"]["source"]["properties"]
    return item_properties(ROOT / "data" / "sources" / "schema.json")


def load_manifest() -> dict:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    docs = m if isinstance(m, list) else (m.get("documents") or m.get("sources") or [])
    return {d["id"]: d for d in docs}


def fmt(v) -> str:
    # 一律 JSON 字面值：字串帶引號、null 就是 null、布林是 true/false，
    # 讀的人不必猜「空白」是空字串還是沒填。
    return json.dumps(v, ensure_ascii=False)


FIELD_LINE = re.compile(r"^- `([^`]+)`：")


def render_record(rec: dict, props: dict, where: str) -> list:
    extra = sorted(set(rec) - set(props))
    if extra:
        raise SystemExit(f"❌ {where} 有 schema 沒有的欄位：{extra}")
    out = []
    for field, spec in props.items():
        if field in rec:
            out.append(f"- `{field}`：{fmt(rec[field])}")
        elif "default" in spec:
            out.append(f"- `{field}`：（未填；schema 預設 {fmt(spec['default'])}）")
        else:
            out.append(f"- `{field}`：（未填）")
    return out


def missing_fields(block_lines: list, props: dict) -> list:
    """把一列的產出讀回來，回傳 schema 有、產出卻沒印的欄位。"""
    seen = {m.group(1) for line in block_lines for m in [FIELD_LINE.match(line)] if m}
    return [f for f in props if f not in seen]


def build(slug: str, ids_override=None) -> str:
    gen = _load_gen()
    art = ARTICLES / f"{slug}.md"
    meta, text = {}, None
    if art.exists():
        text = art.read_text(encoding="utf-8")
        meta, _ = hl.parse_frontmatter(text)
    if ids_override:
        ids = list(ids_override)
    elif text is not None:
        ids = list(gen.page_indicators(meta, slug)[0])
    else:
        raise SystemExit(f"❌ {art} 不存在：新頁請用 --ids 指定這頁收哪些 indicator_id")

    crit_props = item_properties(CRITERIA_DIR / "schema.json")
    hist_props = item_properties(CRITERIA_DIR / "history-schema.json")
    intf_props = item_properties(CRITERIA_DIR / "interference-schema.json")
    man_props = manifest_properties()
    manifest = load_manifest()

    def load(name):
        p = CRITERIA_DIR / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    crit = load(f"{slug}.json")
    if crit is None:
        raise SystemExit(f"❌ 找不到 data/criteria/{slug}.json")
    hist = load(f"{slug}-history.json")
    intf = load(f"{slug}-interference.json")

    L = [f"# 事實包｜{slug}",
         "",
         "> 本檔由 `scripts/gen-factpack.py` 從 repo 資料機械生成，**每一列照 schema 全欄印出**，",
         "> 選填欄沒填也印「（未填）」。欄位值是 JSON 字面值（字串帶引號、`null`＝空值）。",
         "> 引句已受收據 gate 檢查，**逐字、勿改**。",
         "",
         f"- 這頁收的 indicator_id：{fmt(ids)}",
         f"- 判準表收的 category（生成器 TABLE_CATEGORIES）：{fmt(list(gen.TABLE_CATEGORIES))}",
         ""]
    problems = []

    def section(title, rows, props, tag_fn):
        L.append(f"## {title}")
        L.append("")
        if rows is None:
            L.append("（無此檔）")
            L.append("")
            return
        L.append(f"共 {len(rows)} 列（JSON 陣列順序，1 起算）。")
        L.append("")
        for i, r in enumerate(rows, start=1):
            L.append(f"### 第 {i} 列　{tag_fn(r)}")
            block = render_record(r, props, f"{title} 第 {i} 列")
            miss = missing_fields(block, props)
            if miss:
                problems.append(f"{title} 第 {i} 列少印：{miss}")
            L.extend(block)
            L.append("")

    def crit_tag(r):
        if r.get("indicator_id") not in ids:
            where = "⚠️ indicator_id 不在這頁，生成器會略過"
        elif r.get("category") in gen.TABLE_CATEGORIES:
            where = "渲染位置＝判準表與數線"
        else:
            where = "渲染位置＝不進判準表（category 不在 TABLE_CATEGORIES）"
        return f"`{r.get('indicator_id')}`｜`{r.get('category')}`｜{r.get('org')}｜{where}"

    section(f"一、判準列（data/criteria/{slug}.json）", crit, crit_props, crit_tag)
    section(f"二、沿革列（data/criteria/{slug}-history.json，第③段）", hist, hist_props,
            lambda r: f"{r.get('id')}｜{r.get('year')}｜{r.get('org')}｜status {fmt(r.get('status'))}")
    section(f"三、限制列（data/criteria/{slug}-interference.json，第④段）", intf, intf_props,
            lambda r: f"{r.get('id')}｜direction {fmt(r.get('direction'))}｜{r.get('org')}")

    used = {r["doc_id"] for r in crit} | {r["doc_id"] for r in (hist or [])} | {r["doc_id"] for r in (intf or [])}
    for r in (hist or []):
        used |= {c["doc_id"] for c in r.get("corroboration", [])}
    listed = hl_list(meta.get("sources")) if meta else []
    docs = sorted(used | set(listed))
    L.append("## 四、來源（上面各列引用的 doc_id ∪ 正文 frontmatter 的 sources）")
    L.append("")
    if listed:
        not_listed = sorted(used - set(listed))
        L.append(f"- 列有引用、正文 sources 卻沒列的 doc：{fmt(not_listed)}")
        L.append("")
    for d in docs:
        m = manifest.get(d)
        L.append(f"### `{d}`")
        if m is None:
            L.append("- ☠️ manifest 裡找不到這個 id")
            problems.append(f"manifest 找不到 {d}")
        else:
            block = render_record(m, man_props, f"manifest {d}")
            miss = missing_fields(block, man_props)
            if miss:
                problems.append(f"manifest {d} 少印：{miss}")
            L.extend(block)
        L.append("")

    L.append("## 五、頁面現況（正文 md 逐字）")
    L.append("")
    if text is None:
        L.append("（尚無正文檔）")
    else:
        L.append("````markdown")
        L.append(text.rstrip("\n"))
        L.append("````")
    L.append("")

    if problems:
        raise SystemExit("❌ 事實包欄位不全：\n" + "\n".join(problems))
    return "\n".join(L)


def hl_list(v) -> list:
    """frontmatter 的 `[a, b, c]` → list（healthlib 的解析器回原字串）。"""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [x.strip() for x in s.split(",") if x.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="照 schema 全欄印事實包")
    ap.add_argument("slug")
    ap.add_argument("--ids", help="逗號分隔；正文檔還不存在時用")
    ap.add_argument("--out", help="輸出路徑；不給就印到 stdout")
    a = ap.parse_args(argv)
    ids = [x.strip() for x in a.ids.split(",")] if a.ids else None
    doc = build(a.slug, ids)
    if a.out:
        pathlib.Path(a.out).write_text(doc + "\n", encoding="utf-8")
        print(f"已寫出 {a.out}")
    else:
        sys.stdout.write(doc + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
