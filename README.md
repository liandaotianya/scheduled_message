# 定时任务机器人

用 GitHub Actions 免费执行三个定时任务，替代 Coze（积分不够用的问题彻底解决）。

## 三个任务

| 任务 | 触发规则 | 时间 | 交付 |
|---|---|---|---|
| 长春薅羊毛活动收集 | 每月双号（排除 16/30 号） | 17:03 | HTML 邮件 |
| AI 日报 | 每月单号（排除 7/23 号） | 17:03 | HTML 邮件 + 仓库存档 |
| 用户痛点快报 | 每月 7/16/23/30 号 | 17:03 | HTML 邮件 |

---

## 部署四步

### 第一步：在 GitHub 建一个**私有**仓库

名字随意，例如 `ai-daily-bot`。建议私有 —— 存档和配置都在里面。

### 第二步：把本项目文件推上去

```bash
cd ai-daily-bot
git init
git add .
git commit -m "init: 定时任务机器人"
git branch -M main
git remote add origin https://github.com/<你的用户名>/ai-daily-bot.git
git push -u origin main
```

### 第三步：配置 Secrets（这是唯一必做的手工步骤）

进入仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret 名称 | 值从哪来 | 用途 |
|---|---|---|
| `MAIL_AUTH_CODE` | 见下方说明 | QQ 邮箱发信 |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey | 主 LLM |
| `DEEPSEEK_API_KEY` | https://platform.deepseek.com/api_keys | 兜底 LLM |

**QQ 邮箱授权码怎么拿：**
1. 登录 QQ 邮箱 → 设置 → 账户
2. 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」
3. 开启 **SMTP 服务**，按提示发短信验证
4. 生成的 16 位字符串就是授权码 —— **注意这不是你的 QQ 密码**

> `GITHUB_TOKEN` 不需要手动配，Actions 自动提供。

### 第四步：开启 Pages（管理面板用）

仓库 → **Settings** → **Pages** → Source 选 **GitHub Actions**

推送后 `pages.yml` 会自动部署，面板地址是：
```
https://<你的用户名>.github.io/ai-daily-bot/
```

---

## 管理面板怎么用

打开上面的 Pages 地址，首次需要填三样东西：

| 字段 | 填什么 |
|---|---|
| 仓库 | `你的用户名/ai-daily-bot` |
| 分支 | `main` |
| Token | GitHub 细粒度 Token（见下） |

**Token 怎么创建：**
1. GitHub → Settings → Developer settings → **Personal access tokens** → **Fine-grained tokens** → Generate new token
2. Repository access 选 **Only select repositories** → 选中 `ai-daily-bot`
3. Permissions 里配两项：
   - **Contents**: Read and write（读写 config.yaml）
   - **Actions**: Read and write（触发任务、看执行记录）
4. 生成后复制，填进面板

> Token 只存在你自己浏览器的 localStorage，不会上传到任何地方。面板是纯静态页，所有请求直接发给 GitHub API。

**面板能做什么：**
- 看三个任务的开关状态、触发规则、下次执行时间
- 一键开关某个任务
- 在线改所有参数（收件人、条数、排除日期、分类清单等），保存即提交到仓库
- 手动触发执行，可临时覆盖收件人和条数，可开「试跑模式」不发信
- 查看最近 20 次执行记录与日志

---

## 想改参数？三种方式

| 方式 | 操作 | 适合 |
|---|---|---|
| **管理面板** | 网页上改，点保存 | 日常调参，手机也能改 |
| **改配置文件** | 编辑 `config/config.yaml` 后提交 | 批量改、加注释 |
| **临时覆盖** | 手动执行时填「条数覆盖」「收件人覆盖」 | 单次测试 |

所有参数都在 `config/config.yaml`，**不需要改任何代码**。

### 常见调参示例

```yaml
# 换收件人
mail:
  to: "新地址@qq.com"

# AI日报每分类改 10 条
tasks:
  ai_daily:
    items_per_category: 10

# 薅羊毛改到每月 3 次（5/15/25 号）
tasks:
  changchun_deals:
    days: special
    run_days: [5, 15, 25]

# 暂时停用某个任务
tasks:
  pain_points:
    enabled: false
```

---

## 抓取源说明

抓取源在 `config/sources.yaml`，默认启用的都是**不需要登录的稳定公开源**：

- 36氪、少数派、InfoQ 中文站（RSS）
- Hacker News（官方 API）
- GitHub Search API（比爬 trending 页稳定）
- V2EX（公开 API）

**小红书 / 知乎 / 微博 / 即刻** 这几个源默认关闭，因为 GitHub 服务器 IP 在这些平台大概率被拦截，且需要登录态。已预留插件位：

1. 在 `scripts/core/plugins/` 下新建 `<模块名>.py`
2. 实现 `fetch(keyword: str, limit: int) -> List[dict]`
3. 把 `sources.yaml` 里对应源的 `enabled` 改成 `true`

详细约定见 `scripts/core/plugins/README.md`。

---

## 本地调试

```bash
pip install -r requirements.txt
cp .env.example .env        # 填入真实的 key

# 试跑（不发信），看流程是否通
python scripts/dispatch.py --date 2026-09-20 --dry-run

# 看某天该跑哪些任务
python scripts/dispatch.py --date 2026-09-23

# 手动跑单个任务
python scripts/run_manual.py --task ai_daily --dry-run
```

### 跑验证脚本

```bash
# 日期调度逻辑（1月/2月/9月 全部天数）
python scripts/test_schedule.py

# 端到端链路（渲染/发信约束/期数计数/容错）
python scripts/test_e2e.py

# 面板 YAML 解析器
node scripts/test_panel_yaml.js
```

---

## 目录结构

```
ai-daily-bot/
├── .github/workflows/
│   ├── run.yml              # 定时执行（2 个 cron + 手动触发）
│   └── pages.yml            # 部署管理面板
├── scripts/
│   ├── dispatch.py          # 定时入口：判断该跑哪个任务
│   ├── run_manual.py        # 手动入口：明确指定跑什么
│   ├── test_schedule.py     # 调度逻辑验证
│   ├── test_e2e.py          # 端到端验证
│   ├── test_panel_yaml.js   # 面板 YAML 验证
│   ├── core/
│   │   ├── config.py        # 配置加载
│   │   ├── llm.py           # Gemini + DeepSeek 双通道
│   │   ├── fetcher.py       # 抓取层（RSS/API/HTML/插件）
│   │   ├── render.py        # Jinja2 渲染
│   │   ├── mailer.py        # QQ SMTP 发信
│   │   └── issue_no.py      # 期数计数与存档
│   └── tasks/
│       ├── changchun_deals.py
│       ├── ai_daily.py
│       └── pain_points.py
├── config/
│   ├── config.yaml          # ★ 所有参数在这里
│   └── sources.yaml         # 抓取源清单
├── templates/               # 邮件 HTML 模板
├── data/                    # 期数计数 + 存档（自动提交回仓库）
└── panel/                   # 管理面板（部署到 GitHub Pages）
```

---

## 常见问题

**Q：定时任务没执行？**
A：两个可能。一是 GitHub 定时任务在整点前后高峰期会延迟，几分钟到十几分钟都正常；二是仓库连续 60 天无任何提交会暂停 schedule —— 但本项目每天都有存档提交，不会触发这条。

**Q：想改触发时间？**
A：改 `.github/workflows/run.yml` 里的 cron。**注意 cron 用 UTC，北京时间要减 8 小时**：
```yaml
- cron: '23 15 * * *'   # 北京 17:03
- cron: '37 15 * * *'   # 北京 17:03
```

**Q：邮件没收到？**
A：先看 Actions 日志。常见原因是授权码失效（重新生成）或主题被 QQ 邮箱判为垃圾邮件（去垃圾箱找找）。

**Q：LLM 调用失败？**
A：脚本会自动从 Gemini 切到 DeepSeek。如果两个都失败，日志里会列出具体错误。免费额度用尽时 Gemini 会返回 429，属于正常情况，会自动兜底。

**Q：期号算错了？**
A：期号来自 `data/issue_counter.json` 与当月存档文件的最大值取大 +1。如果手动改过存档，可以同步修正这个 json。

**Q：Actions 的免费额度够吗？**
A：公开仓库完全免费不限量。私有仓库每月 2000 分钟，本项目单次执行几分钟，每月约 20 次，用不到 2000 分钟的零头。
