# -*- coding: utf-8 -*-
"""
志邦业绩抓取 —— 公共核心模块
负责：读表格文件 / 自动识别列 / 门店归类 / 金额日期解析 / 人员拆分
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import math
import re
from pathlib import Path

# --------------------------------------------------------------------------
# 路径与配置
# --------------------------------------------------------------------------

BASE = Path(__file__).resolve().parent


def load_config(path: Path | None = None) -> dict:
    p = Path(path) if path else BASE / "config.json"
    if not p.exists():
        raise SystemExit(f"找不到配置文件：{p}")
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


def cfg_path(cfg: dict, key: str) -> Path:
    """取配置里的相对目录，统一转成绝对路径"""
    raw = cfg.get("数据源", {}).get(key) or cfg.get("输出", {}).get(key) or ""
    p = Path(raw)
    return p if p.is_absolute() else BASE / p


# --------------------------------------------------------------------------
# 文本 / 数值 / 日期 解析
# --------------------------------------------------------------------------

_FULLWIDTH = {ord(c): ord(c) - 0xFEE0 for c in "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"}


def norm(s) -> str:
    """归一化表头 / 文本：去空白、全角转半角、转小写、去常见标点"""
    if s is None:
        return ""
    t = str(s).translate(_FULLWIDTH)
    t = t.replace("（", "(").replace("）", ")").replace("：", ":")
    t = re.sub(r"[\s\u3000*#※\-_()\[\]{}<>《》\"'`~!@$%^&+=|\\;:,.?/]+", "", t)
    return t.strip().lower()


def cell_text(v) -> str:
    """单元格转成干净字符串"""
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%Y-%m-%d")
    t = str(v).strip()
    if t.lower() in ("nan", "none", "nat", "null"):
        return ""
    return t


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def to_money(v) -> float:
    """把 '￥1,234.56元' / '1.2万' / '(500)' / 1234.5 统一转成 float"""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return 0.0
        return float(v)

    s = cell_text(v)
    if not s:
        return 0.0

    neg = s.startswith("(") and s.endswith(")")
    s = s.replace(",", "").replace("，", "")

    mult = 1.0
    if "亿" in s:
        mult = 100_000_000.0
    elif "万" in s:
        mult = 10_000.0
    elif "千" in s:
        mult = 1_000.0

    m = _NUM_RE.search(s)
    if not m:
        return 0.0
    try:
        val = float(m.group()) * mult
    except ValueError:
        return 0.0
    return -val if neg else val


_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
    "%Y.%m.%d", "%Y年%m月%d日", "%Y%m%d",
    "%d/%m/%Y", "%m/%d/%Y", "%Y-%m", "%Y年%m月",
)


def to_date(v):
    """尽量解析出日期，失败返回 None"""
    if v is None:
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v

    # Excel 序列号
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        f = float(v)
        if 20000 <= f <= 60000:
            try:
                return (_dt.date(1899, 12, 30) + _dt.timedelta(days=int(f)))
            except Exception:
                pass
        return None

    s = cell_text(v)
    if not s:
        return None
    s = s.split("T")[0] if "T" in s else s
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})", s)
    if m:
        try:
            return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------
# 表格读取
# --------------------------------------------------------------------------

def _read_csv(path: Path) -> list[list]:
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030", "utf-16"):
        try:
            with open(path, encoding=enc, newline="") as f:
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
                except csv.Error:
                    dialect = csv.excel
                return [row for row in csv.reader(f, dialect)]
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法识别编码：{path.name}")


def read_tables(path: Path) -> list[tuple[str, list[list]]]:
    """读取一个文件，返回 [(sheet名, 二维表), ...]"""
    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt"):
        return [(path.stem, _read_csv(path))]

    if suffix in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        out = []
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            if rows:
                out.append((ws.title, rows))
        wb.close()
        return out

    if suffix == ".xls":
        try:
            import xlrd  # type: ignore
        except ImportError:
            raise ValueError(
                f"{path.name} 是老的 .xls 格式。请用 Excel 打开后「另存为 .xlsx」再放进原始数据目录。"
            )
        book = xlrd.open_workbook(str(path))
        return [
            (sh.name, [sh.row_values(i) for i in range(sh.nrows)])
            for sh in book.sheets()
        ]

    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return [(path.stem, json_to_table(data))]

    if suffix in (".html", ".htm"):
        return [(path.stem, parse_html_tables(path.read_text(encoding="utf-8-sig", errors="ignore"))[0])]

    return []


TABLE_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".csv", ".txt", ".json", ".html", ".htm")


def collect_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    files = [
        p for p in sorted(directory.rglob("*"))
        if p.is_file() and p.suffix.lower() in TABLE_SUFFIXES and not p.name.startswith("~$")
    ]
    return files


# --------------------------------------------------------------------------
# HTML / JSON 解析（无第三方依赖）
# --------------------------------------------------------------------------

def parse_html_tables(html: str) -> list[list[list]]:
    """从 HTML 里提取所有 <table>，返回 [[行], ...]，每个表是二维数组"""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.tables: list[list[list]] = []
            self._table = None
            self._row = None
            self._cell = None

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self._table = []
            elif tag == "tr" and self._table is not None:
                self._row = []
            elif tag in ("td", "th") and self._row is not None:
                self._cell = []

        def handle_endtag(self, tag):
            if tag == "table" and self._table is not None:
                self.tables.append(self._table)
                self._table = None
            elif tag == "tr" and self._row is not None:
                if any(c.strip() for c in self._row):
                    self._table.append(self._row)
                self._row = None
            elif tag in ("td", "th") and self._cell is not None:
                self._row.append("".join(self._cell).strip())
                self._cell = None

        def handle_data(self, data):
            if self._cell is not None:
                self._cell.append(data)

    p = P()
    p.feed(html)
    return [t for t in p.tables if len(t) >= 2]


_LIST_KEYS = ("list", "rows", "records", "items", "data", "result", "content",
              "detail", "details", "orderList", "dataList", "pageList")


def _find_list(node, depth: int = 0):
    """在嵌套 JSON 里找出真正的数据数组（志邦接口常见 code/msg/data/list 结构）"""
    if depth > 8 or node is None:
        return None
    if isinstance(node, list):
        return node
    if not isinstance(node, dict):
        return None

    for key in _LIST_KEYS:
        v = node.get(key)
        if isinstance(v, list) and v:
            return v
    for key in _LIST_KEYS:
        v = node.get(key)
        if isinstance(v, dict):
            found = _find_list(v, depth + 1)
            if found:
                return found
    # 键名不在常见列表里，就按值类型兜底
    for v in node.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    for v in node.values():
        if isinstance(v, dict):
            found = _find_list(v, depth + 1)
            if found:
                return found
    return None


def json_to_table(data, path: str = "") -> list[list]:
    """把 JSON 转成二维表。data 为数组时取其中的 dict 列表。"""
    node = None
    if path:
        node = dig(data, path)
    if node is None:
        node = _find_list(data)
    if node is None:
        node = data
    if isinstance(node, dict):
        node = [node]
    if not isinstance(node, list):
        return []

    rows: list[dict] = []
    for item in node:
        if isinstance(item, dict):
            rows.append(item)
        else:
            rows.append({"值": item})
    if not rows:
        return []

    headers: list[str] = []
    for r in rows:
        for k in r.keys():
            if k not in headers:
                headers.append(k)
    table = [headers]
    for r in rows:
        table.append([flatten_value(r.get(h, "")) for h in headers])
    return table


def flatten_value(v):
    """嵌套值压平成字符串，保证能写进 Excel"""
    if v is None or isinstance(v, (str, int, float, bool)):
        return "" if v is None else v
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v
    if isinstance(v, (list, tuple)):
        return "、".join(str(flatten_value(x)) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def dig(obj, path: str):
    """按 'data.list' 这样的路径取值"""
    node = obj
    for part in [p for p in str(path).split(".") if p]:
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.isdigit():
            idx = int(part)
            node = node[idx] if 0 <= idx < len(node) else None
        else:
            return None
    return node


# --------------------------------------------------------------------------
# 列识别
# --------------------------------------------------------------------------

FIELDS = ("销售员", "门店", "金额", "日期", "订单号", "客户", "产品")


def detect_columns(header: list, mapping: dict) -> dict[str, int]:
    """返回 {字段: 列下标}。按「匹配到的关键词越长越优先」打分。"""
    normed = [norm(h) for h in header]
    best: dict[str, tuple[int, int]] = {}  # 字段 -> (得分, 列号)

    for field in FIELDS:
        patterns = mapping.get(field, [])
        for idx, h in enumerate(normed):
            if not h:
                continue
            score = 0
            for pat in patterns:
                p = norm(pat)
                if p and p in h:
                    score = max(score, len(p))
            if score:
                cur = best.get(field)
                if cur is None or score > cur[0]:
                    best[field] = (score, idx)

    # 一个列不能同时当两个字段：冲突时把列让给得分更高的字段
    used: dict[int, str] = {}
    result: dict[str, int] = {}
    for field, (score, idx) in sorted(best.items(), key=lambda kv: -kv[1][0]):
        if idx in used:
            continue
        used[idx] = field
        result[field] = idx
    return result


def find_header_row(rows: list[list], mapping: dict, scan: int = 8):
    """在前若干行里找最像表头的一行，返回 (行号, 列映射)"""
    best = (-1, None, None)
    for i, row in enumerate(rows[:scan]):
        if not row or not any(cell_text(c) for c in row):
            continue
        cols = detect_columns(row, mapping)
        # 销售员 + 金额 是硬指标，门店/日期加分
        score = 0
        if "销售员" in cols:
            score += 5
        if "金额" in cols:
            score += 5
        if "门店" in cols:
            score += 3
        if "日期" in cols:
            score += 2
        if score > best[0]:
            best = (score, i, cols)
    if best[1] is None or best[0] < 5:
        return None, {}
    return best[1], best[2] or {}


# --------------------------------------------------------------------------
# 门店归类
# --------------------------------------------------------------------------

def build_store_matcher(cfg: dict):
    """返回 match(text) -> 门店名 或 None。关键词长的优先，避免「济南万象城」被「万象城」抢。"""
    pairs: list[tuple[str, str]] = []
    for store, spec in cfg.get("门店", {}).items():
        kws = spec.get("关键词") if isinstance(spec, dict) else spec
        for kw in (kws or [store]):
            pairs.append((norm(kw), store))
    pairs.sort(key=lambda kv: -len(kv[0]))

    def match(text: str):
        t = norm(text)
        if not t:
            return None
        for kw, store in pairs:
            if kw and kw in t:
                return store
        return None

    return match


def split_people(raw: str, cfg: dict) -> list[str]:
    """处理 '张三/李四' 这类多人接单"""
    s = cell_text(raw)
    if not s:
        return []
    seps = cfg.get("多人接单", {}).get("分隔符") or ["/", "、", ",", "，", "+", "&"]
    parts = [s]
    for sep in seps:
        nxt = []
        for p in parts:
            nxt.extend(p.split(sep))
        parts = nxt
    out = []
    for p in parts:
        p = re.sub(r"[\s\u3000]+", "", p)
        p = re.sub(r"^(导购|销售|店员)[:：]?", "", p)
        if p:
            out.append(p)
    # 去重保序
    seen, res = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            res.append(p)
    return res or [s]


# --------------------------------------------------------------------------
# 统一加载：文件 -> 记录列表
# --------------------------------------------------------------------------

def load_records(cfg: dict, directory: Path | None = None, log=print) -> tuple[list[dict], list[str]]:
    """读目录下所有表格，产出归一化记录。返回 (记录列表, 警告列表)"""
    directory = directory or cfg_path(cfg, "原始数据目录")
    mapping = cfg.get("列名映射", {})
    match_store = build_store_matcher(cfg)
    warnings: list[str] = []
    records: list[dict] = []

    dr = cfg.get("数据源", {}).get("日期范围", {}) or {}
    d_from = to_date(dr.get("开始")) if dr.get("开始") else None
    d_to = to_date(dr.get("结束")) if dr.get("结束") else None

    files = collect_files(directory)
    if not files:
        warnings.append(f"原始数据目录里没有任何表格文件：{directory}")
        return records, warnings

    for path in files:
        try:
            tables = read_tables(path)
        except Exception as e:
            warnings.append(f"跳过 {path.name}：{e}")
            continue

        for sheet, rows in tables:
            if not rows:
                continue
            hdr_i, cols = find_header_row(rows, mapping)
            if hdr_i is None:
                warnings.append(f"跳过 {path.name}[{sheet}]：没找到像业绩表的表头（需含销售员列和金额列）")
                continue
            if "销售员" not in cols:
                warnings.append(f"跳过 {path.name}[{sheet}]：识别不到「销售员/导购」列")
                continue
            if "金额" not in cols:
                warnings.append(f"跳过 {path.name}[{sheet}]：识别不到「金额」列")
                continue

            header = rows[hdr_i]
            fill_down = cfg.get("数据源", {}).get("门店向下填充", True)
            store_col = cols.get("门店")
            last_store_raw = ""

            for raw in rows[hdr_i + 1:]:
                if raw is None or not any(cell_text(c) for c in raw):
                    continue

                def at(field):
                    i = cols.get(field)
                    return raw[i] if i is not None and i < len(raw) else None

                people = split_people(cell_text(at("销售员")), cfg)
                if not people:
                    continue

                amount = to_money(at("金额"))
                dt = to_date(at("日期"))

                store_raw = cell_text(at("门店"))
                if store_raw:
                    last_store_raw = store_raw
                elif fill_down and store_col is not None and last_store_raw:
                    # 志邦导出常见：门店列是合并单元格，只有第一行有值
                    store_raw = last_store_raw

                store = match_store(store_raw)
                if store is None:
                    # 门店列没写全（如只有「贵和店」），就在整行里找关键词
                    store = match_store(" ".join(cell_text(c) for c in raw))
                if store is None:
                    store = match_store(path.stem + sheet)

                if d_from and dt and dt < d_from:
                    continue
                if d_to and dt and dt > d_to:
                    continue

                mode = cfg.get("多人接单", {}).get("拆分方式", "全部计入")
                if len(people) > 1 and mode == "均分":
                    share = amount / len(people)
                elif len(people) > 1 and mode == "只算第一个":
                    people = people[:1]
                    share = amount
                else:
                    share = amount

                for person in people:
                    records.append({
                        "门店": store or "未匹配门店",
                        "销售员": person,
                        "金额": share,
                        "原始金额": amount,
                        "日期": dt,
                        "订单号": cell_text(at("订单号")),
                        "客户": cell_text(at("客户")),
                        "产品": cell_text(at("产品")),
                        "来源": path.name if sheet == path.stem else f"{path.name}[{sheet}]",
                        "门店原文": store_raw,
                        "多人": len(people) > 1,
                    })

    # 去重兜底：同一区间重复导出会留下多份文件，直接相加会翻倍。
    # 按（合同号+销售员+日期+原始金额）去重，倒序扫描以保留最新那份文件里的版本。
    by_key: dict[tuple, int] = {}
    deduped: list[dict] = []
    dup = 0
    for r in reversed(records):
        k = (r.get("订单号"), r.get("销售员"), r.get("日期"), r.get("原始金额"))
        if k[0]:
            if k in by_key:
                dup += 1
                continue
            by_key[k] = 1
        deduped.append(r)
    deduped.reverse()
    if dup:
        warnings.append(
            f"原始数据目录里有覆盖同一区间的重复文件，已按合同号去重 {dup} 条"
            f"（{len(records)} → {len(deduped)}）。建议清理 {directory} 里多余的旧文件。")
        records = deduped

    return records, warnings


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------

def cross_store_people(records: list[dict]) -> dict[str, list[str]]:
    """找出同时出现在多个门店的销售员——通常意味着门店关键词认错，或该人调过店。"""
    m: dict[str, set] = {}
    for r in records:
        m.setdefault(r["销售员"], set()).add(r["门店"])
    return {n: sorted(s) for n, s in m.items() if len(s) > 1}


def summarize(records: list[dict], cfg: dict) -> dict:
    """按门店 -> 人 汇总，并算占比。列入固定名单的 0 业绩人员也会出现。"""
    stores = list(cfg.get("门店", {}).keys())
    buckets: dict[str, dict[str, dict]] = {s: {} for s in stores}
    buckets.setdefault("未匹配门店", {})

    for r in records:
        store = r["门店"]
        buckets.setdefault(store, {})
        p = buckets[store].setdefault(r["销售员"], {
            "订单数": 0, "金额": 0.0, "最大单": 0.0,
            "最早": None, "最晚": None, "明细": [],
        })
        p["订单数"] += 1
        p["金额"] += r["金额"]
        p["最大单"] = max(p["最大单"], r["金额"])
        if r["日期"]:
            if p["最早"] is None or r["日期"] < p["最早"]:
                p["最早"] = r["日期"]
            if p["最晚"] is None or r["日期"] > p["最晚"]:
                p["最晚"] = r["日期"]
        p["明细"].append(r)

    # 补齐固定名单
    for store, spec in cfg.get("门店", {}).items():
        names = spec.get("人员") if isinstance(spec, dict) else None
        for n in (names or []):
            n = cell_text(n)
            if n and n not in buckets.setdefault(store, {}):
                buckets[store][n] = {
                    "订单数": 0, "金额": 0.0, "最大单": 0.0,
                    "最早": None, "最晚": None, "明细": [],
                }

    # 排名
    for store, people in buckets.items():
        total = sum(v["金额"] for v in people.values())
        for name, v in people.items():
            v["占比"] = (v["金额"] / total) if total else 0.0
            v["平均单值"] = (v["金额"] / v["订单数"]) if v["订单数"] else 0.0
        ranked = sorted(people.items(), key=lambda kv: (-kv[1]["金额"], kv[0]))
        for i, (name, v) in enumerate(ranked, 1):
            v["排名"] = i
        buckets[store] = dict(ranked)

    return {k: v for k, v in buckets.items()}

# --------------------------------------------------------------------------
# 任务指标
# --------------------------------------------------------------------------

def task_months(start: str, end: str) -> float:
    """目标按**整月**算：区间碰到哪个月，那个月就算一整个月。

    为什么：目标是一月一定、一月一个数的。
    看 10-01~10-16 如果按 16/30.44=0.53 个月折算，
    万象城 80万 的月目标会显示成 42.4万，销售会以为月目标就是 42.4万，
    而且这个数每天都在变。

    碰到就算整月：
        2026-10-01 ~ 2026-10-16  ->  1 个月（10月）
        2026-01-01 ~ 2026-10-16  -> 10 个月（1~10月）
        2026-01-01 ~ 2026-12-31  -> 12 个月
    """
    try:
        a = _dt.date.fromisoformat(start)
        b = _dt.date.fromisoformat(end)
    except (ValueError, TypeError):
        return 0.0
    if b < a:
        return 0.0
    return float((b.year - a.year) * 12 + (b.month - a.month) + 1)


def month_span(start: str, end: str) -> float:
    """区间**实际**过了几个月（整月按整数，零头按天数折算）。

    用于算「时间进度」——目标用 task_months，进度用这个。
    """
    try:
        a = _dt.date.fromisoformat(start)
        b = _dt.date.fromisoformat(end)
    except (ValueError, TypeError):
        return 0.0
    if b < a:
        return 0.0
    if a.day == 1 and (b + _dt.timedelta(days=1)).day == 1:      # 整月区间，如 9/1~9/30
        return float((b.year - a.year) * 12 + (b.month - a.month) + 1)
    days = (b - a).days + 1
    if days <= 31:
        return 1.0 if days >= 20 else round(days / 30.44, 2)
    return round(days / 30.44, 2)


def task_of(cfg: dict, store: str, span: float) -> dict | None:
    """某门店在这个区间的任务额"""
    spec = (cfg.get("门店", {}) or {}).get(store)
    if not isinstance(spec, dict):
        return None
    t = spec.get("月度任务") or {}
    lo, std = t.get("最低万"), t.get("标准万")
    if not lo and not std:
        return None
    r = {"月数": span, "最低": None, "标准": None, "最低万": lo, "标准万": std}
    if lo:
        r["最低"] = round(float(lo) * 10000 * span, 2)
    if std:
        r["标准"] = round(float(std) * 10000 * span, 2)
    return r
