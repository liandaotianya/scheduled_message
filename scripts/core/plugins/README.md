"""插件位说明。

强反爬平台（小红书 / 知乎 / 微博 / 即刻）默认关闭，因为 GitHub Actions
的服务器 IP 在这些平台上大概率被拦截，且需要登录态。

接入方式：
    1. 在本目录新建与 sources.yaml 里 module 同名的 .py，
       例如 module: "xiaohongshu" -> 新建 xiaohongshu.py
    2. 模块内暴露 fetch(keyword: str, limit: int) -> List[dict]
    3. 每个 dict 至少包含 title 与 url，可选 summary
    4. 把 sources.yaml 里对应源的 enabled 改为 true

示例：

    def fetch(keyword: str, limit: int = 30):
        # 这里放你的抓取逻辑
        # 建议带上重试与随机 UA，必要时挂代理
        return [{"title": "...", "url": "https://...", "summary": "..."}]
"""
