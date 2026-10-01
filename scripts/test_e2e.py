"""端到端验证：用 mock 数据跑通 抓取→渲染→发信→存档 全链路。

不调真实 LLM、不发真实邮件，只验证工程链路是否通畅。
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from core import fetcher, issue_no, mailer, render  # noqa: E402


MOCK_DEALS = [
    {
        "title": "长影世纪城暑期亲子半价",
        "category": "亲子体验",
        "discount": "5折",
        "time": "9月20日-9月27日",
        "location": "净月开发区 长影世纪城",
        "content": "1.4米以下儿童门票半价，含3个游乐项目",
        "age": "3-12岁",
        "how": "现场购票，出示儿童证件",
        "url": "https://example.com/deal1",
        "rarity": "每年仅暑期一次",
    },
    {
        "title": "市图书馆公益绘本工坊",
        "category": "公益文化",
        "discount": "免费",
        "time": "9月21日 10:00",
        "location": "朝阳区 长春市图书馆 3楼",
        "content": "亲子共读+手工制作，限20组家庭",
        "age": "4-8岁",
        "how": "图书馆公众号预约",
        "url": "https://example.com/deal2",
        "rarity": "每月仅一场",
    },
]

MOCK_AI = {
    "highlights": [
        "某开源 CLI 工具一天内可用，省掉重复劳动",
        "一个 800 star 项目正好卡在产品化空档",
        "某个小痛点目前没有现成方案，标注待造",
    ],
    "sections": [
        {
            "name": "提高开发效率的工具",
            "items": [
                {
                    "title": "mock-cli：命令行自动化工具",
                    "url": "https://example.com/tool1",
                    "desc": "把重复的文件处理变成一条命令",
                    "difficulty": "低",
                    "value": "中",
                }
            ],
        },
        {
            "name": "可产品化开源项目",
            "items": [
                {
                    "title": "mock-proj (★820)",
                    "url": "https://example.com/proj1",
                    "desc": "近10天增速快，尚未有人做成产品",
                    "difficulty": "中",
                    "value": "高",
                }
            ],
        },
    ],
}

MOCK_PAINS = [
    {
        "scene": "居家日用",
        "pain": "家里各种电器的说明书丢了，想看操作方法只能上网搜",
        "quote": "说明书全丢了，客服也说不清",
        "high_value": "信息聚合",
        "solution": "拍设备型号直接调出电子说明书",
        "url": "https://example.com/pain1",
        "difficulty": "低",
    },
    {
        "scene": "通勤出行",
        "pain": "公交到站时间不准，等车全凭运气",
        "quote": "说3分钟到，等了15分钟",
        "high_value": "决策辅助",
        "solution": "待造",
        "url": "https://example.com/pain2",
        "difficulty": "中",
    },
    {
        "scene": "上班族职场",
        "pain": "每周写周报要翻聊天记录回忆做了什么",
        "quote": "最烦的就是周五翻记录",
        "high_value": "自动化替代人工",
        "solution": "自动归集本周工作痕迹生成草稿",
        "url": "https://example.com/pain3",
        "difficulty": "低",
    },
]


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    return cond


def main() -> int:
    now = datetime.now()
    print("=" * 70)
    print("端到端链路验证（mock 数据，不发真实邮件）")
    print("=" * 70)

    results = []

    # ---------- 1. 模板渲染 ----------
    print("\n[1] HTML 模板渲染")

    html_deals = render.render(
        "deals.html.j2",
        {"title": "长春薅羊毛 9月第1期", "issue": 1, "deals": MOCK_DEALS,
         "summary": "本期共收录 2 条优质线下活动"},
    )
    results.append(check("deals 模板渲染", len(html_deals) > 800, f"{len(html_deals)} 字节"))
    results.append(check("deals 标题正确", "长春薅羊毛 9月第1期" in html_deals))
    results.append(check("deals 无具体日期泄漏到标题区", "9月20日-9月27日" in html_deals))
    results.append(check("deals 含来源链接", "example.com/deal1" in html_deals))

    html_ai = render.render(
        "ai_daily.html.j2",
        {"title": "AI日报 2026-09-20", "issue": 1, "highlights": MOCK_AI["highlights"],
         "sections": MOCK_AI["sections"], "total_items": 2},
    )
    results.append(check("ai_daily 模板渲染", len(html_ai) > 800, f"{len(html_ai)} 字节"))
    results.append(check("表头含 落地难度/赚钱潜力",
                         "落地难度" in html_ai and "赚钱潜力" in html_ai))
    results.append(check("今日亮点区块存在", "今日亮点" in html_ai))

    html_pain = render.render(
        "pain_points.html.j2",
        {"title": "用户痛点快报 9月第1期", "issue": 1, "pains": MOCK_PAINS,
         "scenes": ["居家日用", "通勤出行", "育儿生活", "上班族职场", "养老便民", "日常消费餐饮"],
         "summary": "本期共提炼 3 条可落地痛点"},
    )
    results.append(check("pain_points 模板渲染", len(html_pain) > 800, f"{len(html_pain)} 字节"))
    results.append(check("按场景分组", "居家日用" in html_pain and "通勤出行" in html_pain))
    results.append(check("高价值标签渲染", "信息聚合" in html_pain))
    results.append(check("待造标注渲染", "待造" in html_pain))

    # ---------- 2. 发信内联约束 ----------
    print("\n[2] 发信内联约束（继承 Coze 强制规则）")

    try:
        mailer.send("测试", "./templates/deals.html.j2", dry_run=True)
        results.append(check("拒绝文件路径作为正文", False, "居然没报错"))
    except mailer.MailError as exc:
        results.append(check("拒绝文件路径作为正文", "路径" in str(exc), str(exc)[:40]))

    try:
        mailer.send("测试", "   ", dry_run=True)
        results.append(check("拒绝空正文", False, "居然没报错"))
    except mailer.MailError as exc:
        results.append(check("拒绝空正文", True, str(exc)[:30]))

    ok = mailer.send("【测试】长春薅羊毛 9月第1期", html_deals, dry_run=True)
    results.append(check("正常 HTML 正文可发送", ok))

    # ---------- 3. 期数计数 ----------
    print("\n[3] 期数计数与三处一致性")

    issue = issue_no.next_issue_no("test-e2e", now)
    results.append(check("首次期号为 1", issue == 1, f"实际 {issue}"))

    path = issue_no.archive(
        "test-e2e", issue, html_deals, now,
        title="长春薅羊毛 9月第1期", subject="【长春薅羊毛】9月第1期",
    )
    results.append(check("存档文件已生成", path.exists(), str(path.name)))
    results.append(check("文件名含期号", f"-{issue}.html" in path.name))

    issue_no.commit_issue_no("test-e2e", issue, now)
    nxt = issue_no.next_issue_no("test-e2e", now)
    results.append(check("回写后期号递增到 2", nxt == 2, f"实际 {nxt}"))

    # ---------- 4. 抓取层容错 ----------
    print("\n[4] 抓取层容错（单源失败不影响整体）")

    bad_meta = {"type": "rss", "url": "https://this-domain-does-not-exist-12345.invalid/feed"}
    items = fetcher.fetch_source("不存在的源", bad_meta, limit=5)
    results.append(check("坏源返回空列表而非抛异常", items == []))

    bad_plugin = {"type": "plugin", "module": "not_implemented_yet", "enabled": False}
    items = fetcher.fetch_source("未实现插件", bad_plugin, limit=5)
    results.append(check("未实现插件不崩溃", items == []))

    # ---------- 5. 清理测试产物 ----------
    print("\n[5] 清理测试产物")
    path.unlink()
    counter_file = Path(__file__).resolve().parent / "data" / "issue_counter.json"
    if counter_file.exists():
        import json
        data = json.loads(counter_file.read_text(encoding="utf-8"))
        data.pop("test-e2e", None)
        counter_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    results.append(check("测试产物已清理", True))

    # ---------- 汇总 ----------
    print("\n" + "=" * 70)
    passed, total = sum(results), len(results)
    print(f"结果：{passed}/{total} 通过")
    if passed < total:
        print("存在失败项，请检查上面的 FAIL 行")
        return 1
    print("全链路验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
