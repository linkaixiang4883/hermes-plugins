/* model-audit 前端冒烟：桩 SDK + 迷你 hook 运行时 → 跑 bundle、渲染、点按钮、断言。
 * 跑法： node tests/smoke.mjs dashboard/dist/index.js
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync(process.argv[2], "utf8");

// ---- 迷你 React 运行时（只够本页用）----
const hookSlots = [];
const effectSlots = [];
let hookIdx = 0;
let currentTree = null;
let rerender = null;

const tick = () => new Promise((r) => setTimeout(r, 0));
const h = (type, props, children) => ({ type, props: props || {}, children });
const React = { createElement: (...a) => h(...a), Fragment: "Fragment" };
const stub = (name) => function Stub(props) { return h(name, props, props && props.children); };
const components = new Proxy({}, { get: (_t, k) => stub(String(k)) });

const PAGE = 200;
// i=2 是「体证层」样本：没有自证头（upstream_model=null），只有 body 的 model，且与请求不同族。
const mkRow = (i) => (i === 2 ? {
  id: i, ts_start: 1790000000 + i, session_id: "s1", session_title: "会话一号",
  profile_key: "default", provider: "openai", base_url: "https://api.openai.com/v1",
  api_mode: "chat_completions", requested_model: "gpt-5-mini",
  upstream_model: null, body_model: "gpt-4o", endpoint_id: null,
  status: "body_mismatch", endpoint_changed: false, duration_s: 0.4, finish_reason: "stop",
} : i === 4 ? {          // 子智能体会话行：标题取自父会话（via=parent → 页面加「↳」前缀）
  id: i, ts_start: 1790000000 + i, session_id: "s-sub", session_title: "父会话标题",
  session_title_via: "parent", profile_key: "default",
  provider: "opencode-go", base_url: "https://opencode.ai/zen/go/v1", api_mode: "chat_completions",
  requested_model: "deepseek-flash", upstream_model: "deepseek-flash", endpoint_id: "deepseek",
  status: "ok", endpoint_changed: false, duration_s: 2.0, finish_reason: "stop",
} : {
  id: i, ts_start: 1790000000 + i, session_id: "s1", session_title: "会话一号",
  profile_key: "default",
  provider: "opencode-go", base_url: "https://opencode.ai/zen/go/v1", api_mode: "chat_completions",
  requested_model: "deepseek-v4.1-flash",
  upstream_model: i === 1 ? "frank/DeepSeek-V4.1-Flash" : "deepseek/deepseek-v4.1-flash",
  endpoint_id: i === 1 ? "frank" : "orcarouter",
  status: i === 0 ? "approved" : (i === 1 ? "new_route" : "ok"),
  endpoint_changed: i === 0, duration_s: 1.2, finish_reason: "stop",
});
const calls = [];
const timers = [];
const refSlots = {};
const store = {};
const sessionStorageStub = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};
const fetchJSON = (url, init) => {
  calls.push({ url, method: (init && init.method) || "GET", body: init && init.body });
  if (url.indexOf("/rows") >= 0) {
    const off = Number((url.match(/offset=(\d+)/) || [0, "0"])[1]);
    const rows = off === 0
      ? Array.from({ length: PAGE }, (_, i) => mkRow(i))
      : [mkRow(PAGE)];
    return Promise.resolve({ rows, total: rows.length, limit: PAGE, offset: off, days: 7 });
  }
  if (url.indexOf("/summary") >= 0) {
    return Promise.resolve({ totals: { calls: PAGE + 1, ok: 199, approved: 1, mismatch: 0, new_route: 1,
                                       endpoint_mismatch: 0, body_mismatch: 1, body_only: 0, no_signal: 0 },
                             profiles: [{ key: "default", calls: PAGE }, { key: "flutter-dev", calls: 1 }],
                             group_by: "upstream",
                             groups: [
                               { key: "deepseek/deepseek-v4.1-flash", calls: 199, anomalies: 0, no_signal: 0,
                                 unverified: 0, approved: 1, avg_duration_s: 12.3, routes: 1, last_ts: 1790000000,
                                 mismatch: 0, new_route: 0, body_mismatch: 0,
                                 aliases: [["deepseek-v4.1-flash", 199]], endpoints: [["orcarouter-dsv4.1flash", 199]] },
                               { key: "frank/DeepSeek-V4.1-Flash", calls: 1, anomalies: 1, no_signal: 0,
                                 unverified: 1, approved: 0, avg_duration_s: 2.3, routes: 1, last_ts: 1790000100,
                                 mismatch: 1, new_route: 0, body_mismatch: 0,
                                 aliases: [["deepseek-v4.1-flash", 1]], endpoints: [["deepinfra-dsv4.1flash", 1]] },
                             ] });
  }
  if (url.indexOf("/health") >= 0) {
    return Promise.resolve({ rows: PAGE + 1, meta: { patch_ok: "1" }, state_db_exists: true });
  }
  if (url.indexOf("/approvals") >= 0) return Promise.resolve({ approvals: [] });
  if (url.indexOf("/builtin") >= 0) {
    return Promise.resolve({ rules: [{ provider: "opencode-go", alias: "deepseek-flash",
                                       model: "deepseek-flash", endpoint: "deepseek" }] });
  }
  if (url.indexOf("/settings") >= 0) return Promise.resolve({ retention_days: "90" });
  return Promise.resolve({});
};

const SDK = {
  sdkVersion: "1.1.0",
  React,
  hooks: {
    useState: (init) => {
      const i = hookIdx++;
      if (!(i in hookSlots)) hookSlots[i] = init;
      return [hookSlots[i], (v) => {
        // 支持函数式更新（React 语义）：插件靠它避免"过期闭包把旧状态整份写回"。
        hookSlots[i] = (typeof v === "function") ? v(hookSlots[i]) : v;
        if (rerender) rerender();
      }];
    },
    useRef: (init) => {
      const i = hookIdx++;
      if (!(i in refSlots)) refSlots[i] = { current: init };
      return refSlots[i];
    },
    useEffect: (fn, deps) => {
      const i = hookIdx++;
      const prev = effectSlots[i];
      const changed = !prev || !deps || deps.some((d, k) => d !== (prev.deps || [])[k]);
      if (changed) {
        // 先占槽再执行：fn() 里可能触发重入渲染（setState → render），
        // 槽位必须已存在，否则同一次 effect 会被重复执行 → 无限递归。
        effectSlots[i] = { deps: deps || [], cleanup: null };
        effectSlots[i].cleanup = fn();
      }
    },
  },
  components,
  api: {},
  fetchJSON,
  utils: { timeAgo: () => "1m ago", cn: (...a) => a.filter(Boolean).join(" ") },
};

let registered = null;
const sandbox = {
  window: { __HERMES_PLUGIN_SDK__: SDK,
            __HERMES_PLUGINS__: { register: (n, c) => { registered = { name: n, comp: c }; } } },
  console,
  sessionStorage: sessionStorageStub,
  setInterval: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
  clearInterval: () => {},
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
new vm.Script(src, { filename: "index.js" }).runInContext(sandbox);

const fail = [];
const ok = (name, cond, detail = "") => {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}  ${detail}`);
  if (!cond) fail.push(name);
};

const render = () => { hookIdx = 0; currentTree = registered.comp(); };
rerender = render;
function walk(node, out = []) {
  if (node === null || node === undefined) return out;
  out.push(node);
  const kids = node && node.children;
  if (Array.isArray(kids)) kids.forEach((k) => walk(k, out));
  else if (kids !== undefined && kids !== null) walk(kids, out);
  return out;
}
const textOf = (node) => JSON.stringify(walk(node).map((n) => (typeof n === "string" ? n : "")));
const classOf = (node) => walk(node).map((n) => (n && n.props && n.props.className) || "").join(" | ");
const styleOf = (node) => walk(node).map((n) => (n && n.props && n.props.style && n.props.style.background) || "").join("|");
const buttons = (node) => walk(node).filter((n) => n.type === "button");
const findBtn = (node, label) => buttons(node).find((n) => n.children === label);

ok("bundle 调用了 register", !!registered);
ok("注册名 = model-audit", !!registered && registered.name === "model-audit");

render();          // 首次渲染（loading），effect 里发起 GET
await tick();
render();          // promise 回来后重渲染出表格

let nodes = walk(currentTree);
ok("渲染出标题", textOf(currentTree).indexOf("模型对账") >= 0);
ok("渲染出「认可管理」切换按钮", !!findBtn(currentTree, "认可管理"));
ok("渲染出「含未自证」复选框", textOf(currentTree).indexOf("含未自证") >= 0);
ok("调用了 /rows", calls.some((c) => c.url.indexOf("/api/plugins/model-audit/rows") === 0));
ok("渲染出会话标题", textOf(currentTree).indexOf("会话一号") >= 0);
ok("渲染出上游 model 行", textOf(currentTree).indexOf("frank/DeepSeek-V4.1-Flash") >= 0);
ok("已认可行是绿色（text-success）", classOf(currentTree).indexOf("text-success") >= 0);
ok("异常行有「认可」按钮", !!findBtn(currentTree, "认可"));
ok("异常行有「仅模型」按钮（只认 model，端点任意）", !!findBtn(currentTree, "仅模型"));
ok("有「加载更多」按钮（满一页时）", !!findBtn(currentTree, "加载更多"));
ok("有 profile 下拉（全部 profile）", textOf(currentTree).indexOf("全部 profile") >= 0);
ok("profile 下拉列出各 profile", textOf(currentTree).indexOf("flutter-dev (1)") >= 0);
ok("表格渲染 profile 列", textOf(currentTree).indexOf("default") >= 0);
ok("表格渲染 provider 列", textOf(currentTree).indexOf("opencode-go") >= 0);
ok("下拉框显式配色（弹出列表可读）", styleOf(currentTree).indexOf("--color-popover") >= 0);
ok("「含未自证」禁用态不用 opacity（可读）", classOf(currentTree).indexOf("opacity-50") < 0);
ok("汇总卡含「体证不同」「仅体证」",
   textOf(currentTree).indexOf("体证不同") >= 0 && textOf(currentTree).indexOf("仅体证") >= 0);
ok("汇总卡含「✅ 一致」（卡片和 = 调用总数）", textOf(currentTree).indexOf("✅ 一致") >= 0);
ok("汇总卡有 tooltip 说明（已认可 ≠ 内置标准命中）",
   walk(currentTree).some((n) => n && n.props && typeof n.props.title === "string"
                                 && n.props.title.indexOf("内置标准命中计入") >= 0));
// 布局：表格关键列必须 inline nowrap（插件用不了 SPA 没编译的类名，如 max-w-[18rem]）
const nowrapCells = walk(currentTree).filter((n) => n && n.props && n.props.style
                                             && n.props.style.whiteSpace === "nowrap");
ok("表格用内联 nowrap（标题过长不会挤垮状态列）", nowrapCells.length >= 12, String(nowrapCells.length));
ok("标题列内联截断（maxWidth + ellipsis）",
   walk(currentTree).some((n) => n && n.props && n.props.style
                                 && n.props.style.maxWidth && n.props.style.textOverflow === "ellipsis"));
ok("体证层行渲染状态文案", textOf(currentTree).indexOf("⚠️ 体证不同") >= 0);
ok("体证层行显示 body 值", textOf(currentTree).indexOf("body: gpt-4o") >= 0);
ok("体证层行也有「认可」按钮", buttons(currentTree).filter((n) => n.children === "认可").length >= 2);
ok("子智能体会话行标题带「↳」前缀", textOf(currentTree).indexOf("↳ 父会话标题") >= 0);
ok("子智能体行 tooltip 说明来源",
   walk(currentTree).some((n) => n && n.props && typeof n.props.title === "string"
                                 && n.props.title.indexOf("子智能体会话（delegate_task）") >= 0));

const approveBtn = findBtn(currentTree, "认可");
if (approveBtn) { approveBtn.props.onClick(); await tick(); render(); }
const post = calls.find((c) => c.method === "POST" && c.url.indexOf("/approvals") >= 0);
ok("点「认可」发出 POST /approvals", !!post, post ? String(post.body).slice(0, 90) : "无 POST");
ok("POST body 带 requested_model/upstream_model",
   !!post && String(post.body).indexOf("requested_model") >= 0
         && String(post.body).indexOf("upstream_model") >= 0);

const moreBtn = findBtn(currentTree, "加载更多");
if (moreBtn) { moreBtn.props.onClick(); await tick(); render(); }
const paged = calls.find((c) => c.url.indexOf("offset=200") >= 0);
ok("点「加载更多」按 offset 翻页", !!paged, paged ? paged.url : "无 offset=200 请求");
nodes = walk(currentTree);
ok("加载更多后行数增加", textOf(currentTree).indexOf("近 7 天调用") >= 0 && nodes.length > 0);

// 分组统计视图
ok("有「分组统计」按钮", !!findBtn(currentTree, "分组统计"));
const groupBtn = findBtn(currentTree, "分组统计");
if (groupBtn) { groupBtn.props.onClick(); await tick(); render(); }
const gtext = textOf(currentTree);
ok("分组视图渲染维度选择", gtext.indexOf("分组维度") >= 0);
ok("分组视图渲染分组行", gtext.indexOf("frank/DeepSeek-V4.1-Flash") >= 0);
ok("分组视图渲染平均耗时", gtext.indexOf("12.3s") >= 0);
ok("分组表头是「未自证」", gtext.indexOf("未自证") >= 0);
ok("分组表拆开异常列（不一致 / 新路由 / 体证不同）",
   gtext.indexOf("❌ 不一致") >= 0 && gtext.indexOf("⚠️ 新路由") >= 0 && gtext.indexOf("⚠️ 体证不同") >= 0);
ok("分组表列出涉及 alias", gtext.indexOf("涉及 alias") >= 0 && gtext.indexOf("deepseek-v4.1-flash ×") >= 0);
ok("分组表列出涉及端点", gtext.indexOf("涉及端点") >= 0 && gtext.indexOf("orcarouter-dsv4.1flash ×") >= 0);
ok("分组表判定基准写在说明里", gtext.indexOf("判定基准") >= 0);

// 认可管理视图：内置标准（只读）+ 自定义认可
const adminBtn = findBtn(currentTree, "认可管理");
if (adminBtn) { adminBtn.props.onClick(); await tick(); render(); }
const atext = textOf(currentTree);
ok("认可管理：渲染内置标准区", atext.indexOf("内置标准") >= 0);
ok("认可管理：内置标准行（deepseek-flash → deepseek）",
   atext.indexOf("deepseek-flash") >= 0 && atext.indexOf("deepseek") >= 0);
ok("认可管理：自定义认可表单含 provider 输入",
   walk(currentTree).some((n) => n && n.props && n.props.placeholder === "provider（可空）"));

// --- 回归：自动刷新（定时器）不得把视图弹回对账页 ---
// 旧版 patch() 按"当次渲染的 s"整份写回，定时器/在途 fetch 一 resolve 就把 view 覆盖回 audit。
const fireTimers = async () => { for (const t of timers) { t.fn(); } await tick(); render(); };
const gBtn2 = findBtn(currentTree, "分组统计");
if (gBtn2) { gBtn2.props.onClick(); await tick(); render(); }
ok("切到分组统计", textOf(currentTree).indexOf("分组维度") >= 0);
await fireTimers();
ok("回归：自动刷新后仍停在分组统计（不被弹回对账）",
   textOf(currentTree).indexOf("分组维度") >= 0 && textOf(currentTree).indexOf("只看异常") < 0,
   textOf(currentTree).slice(0, 200));
const aBtn2 = findBtn(currentTree, "认可管理");
if (aBtn2) { aBtn2.props.onClick(); await tick(); render(); }
await fireTimers();
ok("回归：自动刷新后仍停在认可管理",
   textOf(currentTree).indexOf("自定义认可") >= 0 && textOf(currentTree).indexOf("只看异常") < 0,
   textOf(currentTree).slice(0, 200));
const backBtn = findBtn(currentTree, "对账");
if (backBtn) { backBtn.props.onClick(); await tick(); render(); }
ok("渲染出「自动刷新」开关（对账视图）", textOf(currentTree).indexOf("自动刷新") >= 0);
const arBox = walk(currentTree).find((n) => n.type === "input" && n.props && n.props.type === "checkbox"
                                     && n.props.checked === true && n.props.onChange);
ok("自动刷新开关默认开", !!arBox);
ok("视图状态已持久化（sessionStorage）",
   String(store["model-audit:ui"] || "").indexOf("autoRefresh") >= 0
   && String(store["model-audit:ui"] || "").indexOf('"view":"audit"') >= 0,
   String(store["model-audit:ui"] || "").slice(0, 120));

console.log();
console.log("FAILED:", fail.length ? fail : "none");
process.exit(fail.length ? 1 : 0);
