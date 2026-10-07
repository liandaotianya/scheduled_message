/* ============================================================
   定时任务管理面板
   纯静态页，直接调用 GitHub REST API，无需后端。
   Token 只存 localStorage，不上传任何第三方服务器。
   ============================================================ */

'use strict';

// ---------------------------------------------------------------- 常量
const LS_KEY = 'ai-daily-bot:cfg';
const CONFIG_PATH = 'config/config.yaml';

const TASK_META = {
  changchun_deals: {
    label: '长春薅羊毛活动收集',
    slot: '17:03',
    rule: '每月双号（排除 16/30 号）',
    desc: '收集长春本地线下限时优惠活动',
  },
  ai_daily: {
    label: 'AI 日报',
    slot: '17:03',
    rule: '每月单号（排除 7/23 号）',
    desc: '5 个分类各 10 条，聚焦赚钱与落地',
  },
  pain_points: {
    label: '用户痛点快报',
    slot: '17:03',
    rule: '每月 7 / 16 / 23 / 30 号',
    desc: '从真实吐槽中提炼可落地痛点',
  },
};

const TASK_KEY_TO_YAML = {
  changchun_deals: 'changchun_deals',
  ai_daily: 'ai_daily',
  pain_points: 'pain_points',
};

// ---------------------------------------------------------------- 状态
let CFG = null;          // {repo, branch, token}
let REPO_CFG = null;     // 解析后的 config.yaml 对象
let REPO_CFG_SHA = null; // 文件 sha，更新时需要

// ---------------------------------------------------------------- 工具
const $ = (id) => document.getElementById(id);

function setMsg(el, text, kind = '') {
  el.textContent = text;
  el.className = 'msg' + (kind ? ' ' + kind : '');
}

function showBanner(text, kind = 'err') {
  const b = $('banner');
  b.textContent = text;
  b.className = 'banner ' + kind;
}

function hideBanner() {
  $('banner').className = 'banner hidden';
}

function fmtTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// ---------------------------------------------------------------- 极简 YAML
/* 只支持 config.yaml 用到的子集：
   嵌套映射、标量、行内数组 [a, b]、块数组、注释、引号字符串。
   目的是零依赖，直接跑在浏览器里。 */

function parseYAML(text) {
  const lines = text.split(/\r?\n/);
  const root = {};
  const stack = [{ indent: -1, node: root }];

  for (let raw of lines) {
    if (!raw.trim() || /^\s*#/.test(raw)) continue;

    // 去掉行尾注释（不在引号内）
    let line = stripInlineComment(raw);
    if (!line.trim()) continue;

    const indent = line.match(/^\s*/)[0].length;
    const content = line.trim();

    // 弹出到合适的父级
    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) {
      stack.pop();
    }
    const parent = stack[stack.length - 1].node;

    // 数组项： "- xxx"
    if (content.startsWith('- ')) {
      if (!Array.isArray(parent.__lastArray)) {
        parent.__lastArray = [];
      }
      const val = content.slice(2).trim();
      parent.__lastArray.push(parseScalar(val));
      continue;
    }

    const m = content.match(/^([^:]+):\s*(.*)$/);
    if (!m) continue;

    const key = m[1].trim().replace(/^["']|["']$/g, '');
    const rest = m[2].trim();

    if (rest === '') {
      // 可能是映射或数组，先建容器占位
      const container = {};
      parent[key] = container;
      // 记录：如果下一行是 "- " 开头，则转数组
      parent.__pendingArrayKey = key;
      stack.push({ indent, node: container, key: key, parent });
    } else {
      // 已有值占位的话，看是不是数组
      if (parent.__pendingArrayKey === key && Array.isArray(parent[key])) {
        // 不会走到
      }
      parent[key] = parseScalar(rest);
    }
  }

  // 后处理：把 __lastArray 挂到对应 key 上
  fixArrays(root);
  return root;
}

function fixArrays(node) {
  if (node === null || typeof node !== 'object') return;

  if (Array.isArray(node.__lastArray)) {
    // 这种结构出现在 obj 直接跟数组项的情况，很少见，忽略
  }

  for (const key of Object.keys(node)) {
    if (key.startsWith('__')) continue;
    const val = node[key];
    if (val && typeof val === 'object' && !Array.isArray(val)) {
      if (Array.isArray(val.__lastArray)) {
        node[key] = val.__lastArray;
        delete val.__lastArray;
      } else if (Object.keys(val).length === 0) {
        node[key] = null; // 空映射变 null
      } else {
        fixArrays(val);
      }
    }
  }
  delete node.__lastArray;
  delete node.__pendingArrayKey;
}

function stripInlineComment(line) {
  let inSingle = false, inDouble = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === "'" && !inDouble) inSingle = !inSingle;
    else if (c === '"' && !inSingle) inDouble = !inDouble;
    else if (c === '#' && !inSingle && !inDouble) {
      if (i === 0 || /\s/.test(line[i - 1])) return line.slice(0, i);
    }
  }
  return line;
}

function parseScalar(v) {
  if (v === '' || v === 'null' || v === '~') return null;
  if (v === 'true') return true;
  if (v === 'false') return false;

  // 行内数组
  if (v.startsWith('[') && v.endsWith(']')) {
    const inner = v.slice(1, -1).trim();
    if (!inner) return [];
    return inner.split(',').map((s) => parseScalar(s.trim()));
  }

  // 引号字符串
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
    return v.slice(1, -1);
  }

  // 数字
  if (/^-?\d+$/.test(v)) return parseInt(v, 10);
  if (/^-?\d+\.\d+$/.test(v)) return parseFloat(v);

  return v;
}

function dumpYAML(obj, indent = 0) {
  const pad = '  '.repeat(indent);
  let out = '';

  for (const [key, val] of Object.entries(obj)) {
    if (key.startsWith('__')) continue;

    if (Array.isArray(val)) {
      if (val.length === 0) {
        out += `${pad}${key}: []\n`;
      } else {
        out += `${pad}${key}:\n`;
        for (const item of val) {
          out += `${pad}  - ${formatScalar(item)}\n`;
        }
      }
    } else if (val !== null && typeof val === 'object') {
      out += `${pad}${key}:\n${dumpYAML(val, indent + 1)}`;
    } else {
      out += `${pad}${key}: ${formatScalar(val)}\n`;
    }
  }
  return out;
}

function formatScalar(v) {
  if (v === null || v === undefined) return '""';
  if (typeof v === 'boolean' || typeof v === 'number') return String(v);
  const s = String(v);
  // 需要引号的情况：空串、含特殊字符、看起来像数字/布尔
  if (s === '' || /[:#\[\]{},"']/.test(s) || /^-?\d+(\.\d+)?$/.test(s) ||
      ['true', 'false', 'null', '~'].includes(s) || /^\s|\s$/.test(s)) {
    return `"${s.replace(/"/g, '\\"')}"`;
  }
  return s;
}

// ---------------------------------------------------------------- GitHub API
function ghHeaders() {
  return {
    'Authorization': `Bearer ${CFG.token}`,
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };
}

function ghUrl(path) {
  return `https://api.github.com/repos/${CFG.repo}${path}`;
}

async function ghGetFile(filePath) {
  const url = ghUrl(`/contents/${filePath}?ref=${encodeURIComponent(CFG.branch)}`);
  const resp = await fetch(url, { headers: ghHeaders() });
  if (resp.status === 404) throw new Error(`文件不存在: ${filePath}`);
  if (!resp.ok) throw new Error(`读取失败 (${resp.status}): ${await resp.text()}`);
  const data = await resp.json();

  // base64 解码（支持中文）
  const bin = atob(data.content.replace(/\n/g, ''));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const text = new TextDecoder('utf-8').decode(bytes);

  return { text, sha: data.sha };
}

async function ghPutFile(filePath, content, sha, message) {
  const body = {
    message,
    content: b64EncodeUnicode(content),
    branch: CFG.branch,
  };
  if (sha) body.sha = sha;

  const resp = await fetch(ghUrl(`/contents/${filePath}`), {
    method: 'PUT',
    headers: { ...ghHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`保存失败 (${resp.status}): ${await resp.text()}`);
  return resp.json();
}

function b64EncodeUnicode(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

async function ghDispatchWorkflow(inputs) {
  const resp = await fetch(ghUrl('/actions/workflows/run.yml/dispatches'), {
    method: 'POST',
    headers: { ...ghHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ ref: CFG.branch, inputs }),
  });
  if (resp.status !== 204) {
    throw new Error(`触发失败 (${resp.status}): ${await resp.text()}`);
  }
  return true;
}

async function ghListRuns() {
  const resp = await fetch(
    ghUrl(`/actions/workflows/run.yml/runs?per_page=20`),
    { headers: ghHeaders() }
  );
  if (!resp.ok) throw new Error(`加载失败 (${resp.status}): ${await resp.text()}`);
  const data = await resp.json();
  return data.workflow_runs || [];
}

// ---------------------------------------------------------------- 配置存取
function loadCfgFromLS() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function saveCfgToLS(cfg) {
  localStorage.setItem(LS_KEY, JSON.stringify(cfg));
}

async function verifyConnection() {
  const resp = await fetch(ghUrl(''), { headers: ghHeaders() });
  if (!resp.ok) {
    throw new Error(`仓库 ${CFG.repo} 无法访问 (${resp.status})，请检查仓库名与 Token 权限`);
  }
  const data = await resp.json();
  return data.full_name;
}

// ---------------------------------------------------------------- 视图：任务总览
function renderTasks() {
  const grid = $('taskGrid');
  grid.innerHTML = '';

  for (const [key, meta] of Object.entries(TASK_META)) {
    const tc = (REPO_CFG && REPO_CFG.tasks && REPO_CFG.tasks[key]) || {};
    const enabled = tc.enabled !== false;
    const dayRule = tc.exclude_days && tc.exclude_days.length
      ? `${meta.rule}`
      : meta.rule;

    const el = document.createElement('div');
    el.className = 'task-item';
    el.innerHTML = `
      <div class="t-head">
        <span class="t-name">${meta.label}</span>
        <div style="display:flex;align-items:center;gap:10px;">
          <span class="badge ${enabled ? 'on' : 'off'}">${enabled ? '已启用' : '已停用'}</span>
          <label class="switch">
            <input type="checkbox" data-task="${key}" ${enabled ? 'checked' : ''}>
            <span class="slider"></span>
          </label>
        </div>
      </div>
      <div class="t-meta">
        <div>触发规则：<b>${dayRule}</b>，每天 <b>${meta.slot}</b></div>
        <div>内容说明：${meta.desc}</div>
        <div>下次执行：<b>${nextRunText(key, tc)}</b></div>
      </div>
    `;
    grid.appendChild(el);
  }

  grid.querySelectorAll('input[data-task]').forEach((input) => {
    input.addEventListener('change', (e) => onToggleTask(e.target.dataset.task, e.target.checked));
  });
}

/** 按配置推算下次执行日期（本地估算，实际以 GitHub 调度为准） */
function nextRunText(key, tc) {
  if (tc.enabled === false) return '已停用';

  const exclude = tc.exclude_days || [];
  const slot = TASK_META[key].slot.split(':');
  const now = new Date();

  for (let i = 0; i < 70; i++) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i);
    const day = d.getDate();

    // 今天的时刻是否已过
    if (i === 0) {
      const slotTime = new Date(d);
      slotTime.setHours(parseInt(slot[0]), parseInt(slot[1]), 0, 0);
      if (slotTime <= now) continue;
    }

    if (exclude.includes(day)) continue;

    let hit = false;
    const base = `tasks.${key}`;
    if (key === 'pain_points') {
      hit = (tc.run_days || []).includes(day);
    } else if (key === 'ai_daily') {
      hit = day % 2 === 1;
    } else if (key === 'changchun_deals') {
      hit = day % 2 === 0;
    }
    if (hit) {
      return `${d.getMonth() + 1}月${day}日 ${TASK_META[key].slot}`;
    }
  }
  return '无（近 70 天不需执行）';
}

async function onToggleTask(key, checked) {
  try {
    if (!REPO_CFG) await loadRepoConfig();
    REPO_CFG.tasks[key].enabled = checked;
    await saveRepoConfig(`chore: ${checked ? '启用' : '停用'}任务 ${key}`);
    renderTasks();
    showBanner(`任务「${TASK_META[key].label}」已${checked ? '启用' : '停用'}`, 'ok');
    setTimeout(hideBanner, 3000);
  } catch (err) {
    showBanner('切换失败：' + err.message);
    renderTasks(); // 回滚 UI
  }
}

// ---------------------------------------------------------------- 视图：参数配置表单
function renderConfigForm() {
  const form = $('configForm');
  if (!REPO_CFG) {
    form.innerHTML = '<p class="hint">点击「读取当前配置」从仓库加载 config.yaml。</p>';
    return;
  }

  form.innerHTML = '';

  // 邮件组
  form.appendChild(buildGroup('邮件设置', [
    field('收件人（多个用逗号分隔）', 'text', 'mail.to', REPO_CFG.mail.to),
    field('发件人', 'text', 'mail.from', REPO_CFG.mail.from),
    field('邮件主题前缀', 'text', 'mail.subject_prefix', REPO_CFG.mail.subject_prefix || ''),
    checkbox('启用邮件发送（关闭则只跑流程不发信）', 'mail.send_enabled', REPO_CFG.mail.send_enabled !== false),
  ]));

  // 每个任务一组
  for (const [key, meta] of Object.entries(TASK_META)) {
    const tc = REPO_CFG.tasks[key] || {};
    const fields = [
      checkbox('启用该任务', `tasks.${key}.enabled`, tc.enabled !== false),
      field('触发时间（只读参考）', 'text', `tasks.${key}.time_slot`, tc.time_slot, true),
    ];

    if (key === 'changchun_deals') {
      fields.push(field('每期最少条数', 'number', `tasks.${key}.min_items`, tc.min_items));
      fields.push(field('活动有效窗口（天）', 'number', `tasks.${key}.search_recent_days`, tc.search_recent_days));
      fields.push(field('列表抓取窗口（天）', 'number', `tasks.${key}.source_recent_days`, tc.source_recent_days));
      fields.push(tagsField('排除日期', `tasks.${key}.exclude_days`, tc.exclude_days || []));
      fields.push(tagsField('品类优先级（顺序即优先级）', `tasks.${key}.categories`, tc.categories || []));
    } else if (key === 'ai_daily') {
      fields.push(field('每个分类条数', 'number', `tasks.${key}.items_per_category`, tc.items_per_category));
      fields.push(tagsField('排除日期', `tasks.${key}.exclude_days`, tc.exclude_days || []));
      fields.push(checkbox('存档到仓库 data/archive/', `tasks.${key}.archive`, tc.archive !== false));
      fields.push(tagsField('分类清单', `tasks.${key}.categories`, tc.categories || []));
    } else {
      fields.push(field('总条数', 'number', `tasks.${key}.total_items`, tc.total_items));
      fields.push(tagsField('执行日期', `tasks.${key}.run_days`, tc.run_days || []));
      fields.push(tagsField('场景清单', `tasks.${key}.scenes`, tc.scenes || []));
    }

    form.appendChild(buildGroup(meta.label, fields));
  }

  // LLM 组
  const llm = REPO_CFG.llm || {};
  form.appendChild(buildGroup('LLM 设置', [
    selectField('主通道', 'llm.primary', llm.primary, ['gemini', 'deepseek']),
    selectField('兜底通道', 'llm.fallback', llm.fallback, ['gemini', 'deepseek']),
    field('温度（0-1，越高越随机）', 'number', 'llm.temperature', llm.temperature, false, '0.1'),
    field('单次请求超时（秒）', 'number', 'llm.timeout', llm.timeout),
  ]));
}

function buildGroup(title, fields) {
  const g = document.createElement('div');
  g.className = 'cfg-group';
  const h = document.createElement('h3');
  h.textContent = title;
  g.appendChild(h);

  const grid = document.createElement('div');
  grid.className = 'grid2';
  for (const f of fields) grid.appendChild(f);
  g.appendChild(grid);
  return g;
}

function field(label, type, path, value, readonly = false, step = '') {
  const wrap = document.createElement('div');
  wrap.className = 'field';
  const id = 'f_' + path.replace(/\./g, '_');
  wrap.innerHTML = `
    <label for="${id}">${label}</label>
    <input id="${id}" type="${type}" data-path="${path}"
           value="${value === null || value === undefined ? '' : String(value)}"
           ${readonly ? 'readonly style="background:#f9fafb;color:#888;"' : ''}
           ${step ? `step="${step}"` : ''}>
  `;
  return wrap;
}

function checkbox(label, path, checked) {
  const wrap = document.createElement('div');
  wrap.className = 'field';
  wrap.innerHTML = `
    <label class="check" style="margin:0;">
      <input type="checkbox" data-path="${path}" ${checked ? 'checked' : ''}>
      <span>${label}</span>
    </label>
  `;
  return wrap;
}

function selectField(label, path, value, options) {
  const wrap = document.createElement('div');
  wrap.className = 'field';
  const id = 'f_' + path.replace(/\./g, '_');
  const opts = options.map(o => `<option value="${o}" ${o === value ? 'selected' : ''}>${o}</option>`).join('');
  wrap.innerHTML = `<label for="${id}">${label}</label><select id="${id}" data-path="${path}">${opts}</select>`;
  return wrap;
}

function tagsField(label, path, values) {
  const wrap = document.createElement('div');
  wrap.className = 'field';
  wrap.dataset.path = path;
  wrap.dataset.kind = 'tags';

  const render = (list) => {
    const container = wrap.querySelector('.tags');
    container.innerHTML = '';
    list.forEach((v, i) => {
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.innerHTML = `${v} <button type="button" data-idx="${i}">&times;</button>`;
      tag.querySelector('button').addEventListener('click', () => {
        list.splice(i, 1);
        render(list);
      });
      container.appendChild(tag);
    });
  };

  const list = [...values];
  wrap.innerHTML = `
    <label>${label}</label>
    <div class="tags"></div>
    <div class="tag-add">
      <input type="text" placeholder="输入后回车添加">
      <button type="button" class="ghost small">添加</button>
    </div>
  `;

  const input = wrap.querySelector('input');
  const add = () => {
    const v = input.value.trim();
    if (!v || list.includes(v)) { input.value = ''; return; }
    list.push(v);
    input.value = '';
    render(list);
  };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  wrap.querySelector('.tag-add button').addEventListener('click', add);

  render(list);
  wrap._getValue = () => list;
  return wrap;
}

function collectFormValues() {
  const result = { tags: {} };

  document.querySelectorAll('#configForm [data-path]').forEach((el) => {
    const path = el.dataset.path;

    if (el.closest('[data-kind="tags"]')) return; // 标签组单独处理

    if (el.type === 'checkbox') {
      setByPath(result, path, el.checked);
    } else if (el.type === 'number') {
      const v = el.value.trim();
      setByPath(result, path, v === '' ? null : Number(v));
    } else {
      setByPath(result, path, el.value);
    }
  });

  document.querySelectorAll('#configForm [data-kind="tags"]').forEach((el) => {
    const path = el.dataset.path;
    const list = el._getValue ? el._getValue() : [];
    setByPath(result, path, list.map((v) => (typeof v === 'string' && /^\d+$/.test(v) ? Number(v) : v)));
  });

  delete result.tags;
  return result;
}

function setByPath(obj, path, value) {
  const parts = path.split('.');
  let node = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    if (!node[parts[i]] || typeof node[parts[i]] !== 'object') node[parts[i]] = {};
    node = node[parts[i]];
  }
  node[parts[parts.length - 1]] = value;
}

// ---------------------------------------------------------------- 仓库配置读写
async function loadRepoConfig() {
  const { text, sha } = await ghGetFile(CONFIG_PATH);
  REPO_CFG = parseYAML(text);
  REPO_CFG_SHA = sha;
  return REPO_CFG;
}

async function saveRepoConfig(message) {
  const text = dumpYAML(REPO_CFG);
  const res = await ghPutFile(CONFIG_PATH, text, REPO_CFG_SHA, message);
  REPO_CFG_SHA = res.content.sha;
  return res;
}

// ---------------------------------------------------------------- 执行历史
function renderRuns(runs) {
  const list = $('runList');
  if (!runs.length) {
    list.innerHTML = '<p class="hint">暂无执行记录。</p>';
    return;
  }

  list.innerHTML = '';
  for (const r of runs) {
    const statusMap = {
      success: 'success', failure: 'failure',
      in_progress: 'running', queued: 'running',
    };
    const cls = statusMap[r.status] || (r.conclusion === 'success' ? 'success' : 'other');
    const labelMap = {
      success: '成功', failure: '失败', cancelled: '已取消',
      in_progress: '运行中', queued: '排队中',
    };
    const label = labelMap[r.conclusion] || labelMap[r.status] || r.status;

    const row = document.createElement('div');
    row.className = 'run-row';
    row.innerHTML = `
      <span class="status ${cls}">${label}</span>
      <span>
        <b style="font-weight:500;">#${r.run_number}</b>
        <span style="color:#888;font-size:12px;">${r.name || ''}</span>
      </span>
      <a href="${r.html_url}" target="_blank" rel="noopener">日志 &rarr;</a>
      <div class="when">${fmtTime(r.created_at)} · 耗时 ${duration(r)}</div>
    `;
    list.appendChild(row);
  }
}

function duration(run) {
  if (!run.updated_at || !run.created_at) return '-';
  const sec = Math.round((new Date(run.updated_at) - new Date(run.created_at)) / 1000);
  if (sec < 60) return `${sec} 秒`;
  return `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`;
}

// ---------------------------------------------------------------- 事件绑定
function bindEvents() {
  $('btnSettings').addEventListener('click', () => {
    $('setup').classList.remove('hidden');
    if (CFG) {
      $('cfgRepo').value = CFG.repo;
      $('cfgBranch').value = CFG.branch;
      $('cfgToken').value = CFG.token;
    }
    $('setup').scrollIntoView({ behavior: 'smooth' });
  });

  $('btnSaveCfg').addEventListener('click', async () => {
    const repo = $('cfgRepo').value.trim();
    const branch = $('cfgBranch').value.trim() || 'main';
    const token = $('cfgToken').value.trim();

    if (!repo || !token) {
      setMsg($('cfgMsg'), '仓库与 Token 均为必填', 'err');
      return;
    }
    if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) {
      setMsg($('cfgMsg'), '仓库格式应为 owner/repo', 'err');
      return;
    }

    CFG = { repo, branch, token };
    setMsg($('cfgMsg'), '正在连接…');

    try {
      await verifyConnection();
      saveCfgToLS(CFG);
      setMsg($('cfgMsg'), '连接成功', 'ok');
      await initMain();
    } catch (err) {
      setMsg($('cfgMsg'), err.message, 'err');
    }
  });

  $('btnCancelCfg').addEventListener('click', () => {
    $('setup').classList.add('hidden');
  });

  $('btnRefresh').addEventListener('click', () => initMain());

  $('btnLoadCfg').addEventListener('click', async () => {
    try {
      await loadRepoConfig();
      renderConfigForm();
      renderTasks();
      showBanner('配置已加载', 'ok');
      setTimeout(hideBanner, 2000);
    } catch (err) {
      showBanner('加载配置失败：' + err.message);
    }
  });

  $('btnSaveParams').addEventListener('click', async () => {
    if (!REPO_CFG) {
      setMsg($('paramMsg'), '请先读取当前配置', 'err');
      return;
    }
    const btn = $('btnSaveParams');
    btn.disabled = true;
    setMsg($('paramMsg'), '正在保存…');

    try {
      const vals = collectFormValues();
      // 合并：只覆盖表单里出现的字段，保留其余（如 llm.models、runtime）
      deepMerge(REPO_CFG, vals);
      await saveRepoConfig('chore: 更新任务参数配置');
      renderTasks();
      setMsg($('paramMsg'), '已保存到仓库，下次执行生效', 'ok');
    } catch (err) {
      setMsg($('paramMsg'), err.message, 'err');
    } finally {
      btn.disabled = false;
    }
  });

  $('btnRun').addEventListener('click', async () => {
    const task = $('runTask').value;
    const btn = $('btnRun');
    btn.disabled = true;
    setMsg($('runMsg'), '正在触发…');

    try {
      const inputs = { task, dry_run: $('runDry').checked };
      const to = $('runTo').value.trim();
      const items = $('runItems').value.trim();
      if (to) inputs.to = to;
      if (items) inputs.items = items;

      await ghDispatchWorkflow(inputs);
      setMsg($('runMsg'), '已触发，约 1 分钟后可在下方「执行历史」查看进度', 'ok');
      setTimeout(() => $('btnLoadRuns').click(), 4000);
    } catch (err) {
      setMsg($('runMsg'), err.message, 'err');
    } finally {
      btn.disabled = false;
    }
  });

  $('btnLoadRuns').addEventListener('click', async () => {
    const btn = $('btnLoadRuns');
    btn.disabled = true;
    try {
      const runs = await ghListRuns();
      renderRuns(runs);
    } catch (err) {
      $('runList').innerHTML = `<p class="msg err">${err.message}</p>`;
    } finally {
      btn.disabled = false;
    }
  });
}

function deepMerge(target, source) {
  for (const [k, v] of Object.entries(source)) {
    if (v && typeof v === 'object' && !Array.isArray(v) &&
        target[k] && typeof target[k] === 'object' && !Array.isArray(target[k])) {
      deepMerge(target[k], v);
    } else {
      target[k] = v;
    }
  }
  return target;
}

// ---------------------------------------------------------------- 初始化
async function initMain() {
  const dot = document.querySelector('.dot');
  try {
    const fullName = await verifyConnection();
    dot.className = 'dot on';
    $('connInfo').textContent = `已连接 ${fullName} @ ${CFG.branch}`;

    $('setup').classList.add('hidden');
    $('main').classList.remove('hidden');
    hideBanner();

    await loadRepoConfig();
    renderTasks();
    renderConfigForm();
  } catch (err) {
    dot.className = 'dot err';
    $('connInfo').textContent = '连接失败';
    showBanner('连接失败：' + err.message + '（点右上角 ⚙ 修改配置）');
    $('setup').classList.remove('hidden');
  }
}

async function boot() {
  bindEvents();
  CFG = loadCfgFromLS();

  if (!CFG) {
    $('setup').classList.remove('hidden');
    $('connInfo').textContent = '未配置仓库';
    return;
  }
  await initMain();
}

document.addEventListener('DOMContentLoaded', boot);
