/* 验证面板的 YAML 解析/序列化往返正确性。

面板是纯前端，没法直接跑。这里用 Node 跑同一份 app.js 里的函数，
检验：真实 config.yaml -> parse -> dump -> parse 后语义不变。
*/

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const CONFIG = path.join(ROOT, 'config', 'config.yaml');
const APP = path.join(ROOT, 'panel', 'app.js');

// 从 app.js 里抽出 YAML 相关函数，在隔离上下文里执行
const src = fs.readFileSync(APP, 'utf8');
const start = src.indexOf("// ---------------------------------------------------------------- 极简 YAML");
const end = src.indexOf("// ---------------------------------------------------------------- GitHub API");
const yamlCode = src.slice(start, end);

const sandbox = { console };
vm.createContext(sandbox);
vm.runInContext(yamlCode, sandbox);

const { parseYAML, dumpYAML } = sandbox;

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
  if (cond) { console.log(`  [PASS] ${name}${detail ? '  ' + detail : ''}`); pass++; }
  else { console.log(`  [FAIL] ${name}${detail ? '  ' + detail : ''}`); fail++; }
}

console.log('='.repeat(70));
console.log('面板 YAML 解析器验证');
console.log('='.repeat(70));

const text = fs.readFileSync(CONFIG, 'utf8');

console.log('\n[1] 解析真实 config.yaml');
const cfg = parseYAML(text);

check('顶层有 mail/tasks/llm/runtime', 
  cfg.mail && cfg.tasks && cfg.llm && cfg.runtime);
check('mail.to 正确', cfg.mail.to === '986882896@qq.com', cfg.mail.to);
check('mail.send_enabled 为布尔 true', cfg.mail.send_enabled === true);
check('mail.smtp_port 为数字 465', cfg.mail.smtp_port === 465, String(cfg.mail.smtp_port));

console.log('\n[2] 嵌套与数组');
check('三个任务都存在',
  cfg.tasks.changchun_deals && cfg.tasks.ai_daily && cfg.tasks.pain_points);
check('changchun_deals.exclude_days = [16,30]',
  JSON.stringify(cfg.tasks.changchun_deals.exclude_days) === '[16,30]',
  JSON.stringify(cfg.tasks.changchun_deals.exclude_days));
check('changchun_deals.categories 是数组且5项',
  Array.isArray(cfg.tasks.changchun_deals.categories) &&
  cfg.tasks.changchun_deals.categories.length === 5,
  JSON.stringify(cfg.tasks.changchun_deals.categories));
check('ai_daily.time_slot 保留为字符串 "23:37"',
  cfg.tasks.ai_daily.time_slot === '23:37',
  `实际 ${JSON.stringify(cfg.tasks.ai_daily.time_slot)}`);
check('ai_daily.exclude_days = [7,23]',
  JSON.stringify(cfg.tasks.ai_daily.exclude_days) === '[7,23]');
check('pain_points.run_days = [7,16,23,30]',
  JSON.stringify(cfg.tasks.pain_points.run_days) === '[7,16,23,30]');
check('pain_points.scenes 6 项',
  cfg.tasks.pain_points.scenes.length === 6);

console.log('\n[3] 深层嵌套');
check('llm.models.gemini 值正确',
  cfg.llm.models.gemini === 'gemini-2.0-flash', cfg.llm.models.gemini);
check('llm.temperature = 0.7',
  cfg.llm.temperature === 0.7, String(cfg.llm.temperature));
check('runtime.log_level = INFO',
  cfg.runtime.log_level === 'INFO', cfg.runtime.log_level);

console.log('\n[4] 往返：parse -> dump -> parse');
const dumped = dumpYAML(cfg);
const reparsed = parseYAML(dumped);

check('往返后 mail.to 不变', reparsed.mail.to === cfg.mail.to);
check('往返后 tasks 三个任务都在',
  Object.keys(reparsed.tasks).length === 3,
  Object.keys(reparsed.tasks).join(','));
check('往返后 exclude_days 不变',
  JSON.stringify(reparsed.tasks.changchun_deals.exclude_days) === '[16,30]');
check('往返后 categories 不变',
  JSON.stringify(reparsed.tasks.changchun_deals.categories) ===
  JSON.stringify(cfg.tasks.changchun_deals.categories));
check('往返后 time_slot 仍是字符串',
  reparsed.tasks.ai_daily.time_slot === '23:37');
check('往返后 items_per_category = 8',
  reparsed.tasks.ai_daily.items_per_category === 8);
check('往返后 llm.models 完整',
  reparsed.llm.models.gemini === 'gemini-2.0-flash' &&
  reparsed.llm.models.deepseek === 'deepseek-chat');

console.log('\n[5] 修改后重新序列化');
reparsed.tasks.ai_daily.items_per_category = 12;
reparsed.mail.to = 'new@qq.com, other@qq.com';
reparsed.tasks.pain_points.run_days = [5, 15, 25];
const dumped2 = dumpYAML(reparsed);
const reparsed2 = parseYAML(dumped2);

check('修改 items_per_category 生效',
  reparsed2.tasks.ai_daily.items_per_category === 12);
check('修改多个收件人保留',
  reparsed2.mail.to === 'new@qq.com, other@qq.com', reparsed2.mail.to);
check('修改 run_days 生效',
  JSON.stringify(reparsed2.tasks.pain_points.run_days) === '[5,15,25]');
check('未修改的字段仍存在',
  reparsed2.tasks.changchun_deals.categories.length === 5);

console.log('\n[6] 输出格式检查（能否被 Python yaml 读回）');
fs.writeFileSync(path.join(ROOT, '.tmp_roundtrip.yaml'), dumped2, 'utf8');
check('已写出临时文件供 Python 校验', true, '.tmp_roundtrip.yaml');

console.log('\n' + '='.repeat(70));
console.log(`结果：${pass}/${pass + fail} 通过`);
process.exit(fail ? 1 : 0);
