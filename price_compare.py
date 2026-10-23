#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
price_compare.py —— 把不同厂商、不同计价口径的模型价格，归一化成同一张表。

为什么需要它：
  同样是「输入 100 万 tokens 多少钱」，有人报 $/1M，有人报 ¥/1K，
  有人报「每 token 0.000003」，还有人只给你一个「5 折」。
  不先统一口径，比价等于算命。

用法：
  python3 price_compare.py prices.csv --rate 7.10 --out-share 0.3 --cache-hit 0.4

CSV 列（表头必须一致，顺序随意）：
  provider,model,currency,unit,input,output,cache_read,cache_write
  - currency: USD | CNY
  - unit:     per_1k | per_1m | per_token
  - 后四列填该口径下的单价，没有的留空

输出：按「混合成本」排序的 Markdown 表格，单位统一为 元 / 百万 tokens。
"""

import argparse
import csv
import sys
from decimal import Decimal, InvalidOperation

UNIT_TO_PER_TOKEN = {
    "per_1m": Decimal("1000000"),
    "per_1k": Decimal("1000"),
    "per_token": Decimal("1"),
}


def to_cny_per_mtok(value, unit, currency, rate):
    """把任意口径的单价换算成 元/百万 tokens。空值返回 None。"""
    if value is None:
        return None
    raw = str(value).strip()
    if raw == "" or raw == "-":
        return None
    try:
        v = Decimal(raw)
    except InvalidOperation:
        raise SystemExit(f"无法解析的价格：{raw!r}")
    if unit not in UNIT_TO_PER_TOKEN:
        raise SystemExit(f"未知单位：{unit!r}（只支持 {'/'.join(UNIT_TO_PER_TOKEN)}）")
    per_token = v / UNIT_TO_PER_TOKEN[unit]
    per_mtok = per_token * Decimal("1000000")
    if currency.upper() == "USD":
        per_mtok *= Decimal(str(rate))
    elif currency.upper() != "CNY":
        raise SystemExit(f"未知币种：{currency!r}")
    return per_mtok


def blended(row, out_share, cache_hit):
    """
    算「每 100 万 tokens 的综合成本」。

    假设总量 100 万 tokens，其中 out_share 是输出、其余是输入；
    输入里 cache_hit 比例命中缓存（按 cache_read 计价），其余按 input 计价。
    没有 cache_read 价的，命中的部分按 input 价算（保守估计）。
    """
    inp, out, cr = row["input"], row["output"], row["cache_read"]
    if inp is None or out is None:
        return None
    cr = cr if cr is not None else inp
    in_tokens = Decimal("1000000") * (Decimal("1") - Decimal(str(out_share)))
    out_tokens = Decimal("1000000") * Decimal(str(out_share))
    hit = Decimal(str(cache_hit))
    return in_tokens * ((Decimal("1") - hit) * inp + hit * cr) / Decimal("1000000") + \
        out_tokens * out / Decimal("1000000")


def fmt(v):
    if v is None:
        return "—"
    if v >= 100:
        return f"{v:,.0f}"
    if v >= 1:
        return f"{v:,.2f}"
    if v >= 0.01:
        return f"{v:.3f}"
    return f"{v:.4f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--rate", type=float, default=7.10, help="美元兑人民币汇率，默认 7.10")
    ap.add_argument("--out-share", type=float, default=0.30, help="输出 token 占比，默认 0.30")
    ap.add_argument("--cache-hit", type=float, default=0.40, help="输入命中缓存的比例，默认 0.40")
    args = ap.parse_args()

    if not (0 <= args.out_share <= 1) or not (0 <= args.cache_hit <= 1):
        raise SystemExit("占比必须在 0~1 之间")

    rows = []
    with open(args.csv_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            row = {
                "provider": (r.get("provider") or "").strip(),
                "model": (r.get("model") or "").strip(),
                "input": to_cny_per_mtok(r.get("input"), (r.get("unit") or "").strip(),
                                         (r.get("currency") or "").strip(), args.rate),
                "output": to_cny_per_mtok(r.get("output"), (r.get("unit") or "").strip(),
                                          (r.get("currency") or "").strip(), args.rate),
                "cache_read": to_cny_per_mtok(r.get("cache_read"), (r.get("unit") or "").strip(),
                                              (r.get("currency") or "").strip(), args.rate),
            }
            b = blended(row, args.out_share, args.cache_hit)
            if b is not None:
                row["blended"] = b
                rows.append(row)

    if not rows:
        raise SystemExit("没有可比较的行：检查 CSV 表头与数值")

    rows.sort(key=lambda x: x["blended"])

    print(f"汇率 1 USD = {args.rate} CNY ｜ 输出占比 {args.out_share:.0%} ｜ 缓存命中 {args.cache_hit:.0%}")
    print()
    print("| 排名 | 供应商 | 模型 | 输入(元/1M) | 输出(元/1M) | 缓存读(元/1M) | 混合成本(元/1M) |")
    print("|---|---|---|---:|---:|---:|---:|")
    for i, r in enumerate(rows, 1):
        print(f"| {i} | {r['provider']} | `{r['model']}` | {fmt(r['input'])} | "
              f"{fmt(r['output'])} | {fmt(r['cache_read'])} | **{fmt(r['blended'])}** |")

    cheapest, priciest = rows[0], rows[-1]
    print()
    print(f"最便宜：{cheapest['provider']} / {cheapest['model']} — {fmt(cheapest['blended'])} 元/1M")
    print(f"最贵：  {priciest['provider']} / {priciest['model']} — {fmt(priciest['blended'])} 元/1M")
    if cheapest["blended"] > 0:
        print(f"差距：  {priciest['blended'] / cheapest['blended']:.1f} 倍")


if __name__ == "__main__":
    sys.exit(main())
