"""验证 dispatch 的日期判断逻辑：1-31 号全跑一遍，对照原始日历规则。

原始规则：
  ① 长春薅羊毛：双号，排除 16/30       （17:03 槽）
  ② AI日报：   单号，排除 7/23        （17:03 槽）
  ③ 痛点快报： 7/16/23/30            （17:03 槽）
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from dispatch import resolve, day_matches  # noqa: E402


def expected(day: int):
    """按原始规则算出期望结果。"""
    exp = set()
    if day % 2 == 0 and day not in (16, 30):
        exp.add("changchun_deals")
    if day % 2 == 1 and day not in (7, 23):
        exp.add("ai_daily")
    if day in (7, 16, 23, 30):
        exp.add("pain_points")
    return exp


def main() -> int:
    months = [datetime(2026, 1, 1), datetime(2026, 2, 1), datetime(2026, 9, 1)]
    failures = []

    for month_start in months:
        year, month = month_start.year, month_start.month
        # 该月天数
        if month == 12:
            nxt = datetime(year + 1, 1, 1)
        else:
            nxt = datetime(year, month + 1, 1)
        days_in_month = (nxt - datetime(year, month, 1)).days

        print(f"\n===== {year} 年 {month} 月（共 {days_in_month} 天）=====")
        print(f"{'日期':<6}{'槽位17:03':<22}{'槽位17:03':<26}{'状态'}")
        print("-" * 76)

        for day in range(1, days_in_month + 1):
            when = datetime(year, month, day, 23, 30)

            got_deals = set(resolve(when, "deals"))
            got_report = set(resolve(when, "report"))
            got_all = got_deals | got_report

            exp = expected(day)
            ok = got_all == exp
            if not ok:
                failures.append((f"{year}-{month:02d}-{day:02d}", exp, got_all))

            mark = "OK" if ok else "FAIL"
            print(
                f"{day:<6}{str(sorted(got_deals) or '-'):<22}"
                f"{str(sorted(got_report) or '-'):<26}{mark}"
            )

    print("\n" + "=" * 76)
    if failures:
        print(f"\n共 {len(failures)} 天不符合预期：")
        for d, exp, got in failures:
            print(f"  {d}: 期望 {sorted(exp)}  实际 {sorted(got)}")
        return 1

    print("\n全部日期判断正确")
    return 0


if __name__ == "__main__":
    sys.exit(main())
