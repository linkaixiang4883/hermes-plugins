/* model-audit —— dashboard 页面（无构建、无 import；一切从 window.__HERMES_PLUGIN_SDK__ 取）
 * 三个视图：audit（对账） / groups（分组统计） / admin（认可管理），用普通 button 切换。
 * 展示态两层：① 自证（响应头）→ ok / mismatch / new_route；② 体证（无自证头时看 body 的 model）
 * → body_only / body_mismatch；结构性无自证的 provider（如 commandcode）→ no_attestation（回声=没证据）。
 * 都写在查询期算（原始记录里没有这些状态）。 */
(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var C = SDK.components;
  var NAME = "model-audit";
  var API = "/api/plugins/model-audit";
  var PAGE_SIZE = 200;
  var STATUS_TEXT = {
    ok: "✅ 一致", approved: "🟢 已认可", mismatch: "❌ 不匹配",
    new_route: "⚠️ 新路由", body_mismatch: "⚠️ 体证不同", body_only: "○ 仅体证",
    no_attestation: "◌ 无自证", no_signal: "— 无信号",
  };
  var STATUS_CLASS = {
    ok: "text-muted-foreground", approved: "text-success", mismatch: "text-destructive",
    new_route: "text-warning", body_mismatch: "text-warning", body_only: "text-muted-foreground",
    no_attestation: "text-muted-foreground", no_signal: "text-muted-foreground",
  };
  var STATUS_TIP = {
    ok: "命中内置标准（或该 alias 最常见的组合）——model 与端点都对得上",
    approved: "命中自定义认可（对内置标准的例外）",
    mismatch: "上游 model 与期望不符（❌ 不一致）",
    new_route: "model 对得上，但端点不是期望的那个（⚠️ 新路由）",
    body_mismatch: "无自证头，只有响应体里的 model，且它与请求不同族 —— 对这个 provider 可能是真信号，建议人工确认",
    body_only: "无自证头，只有响应体里的 model，与请求同族（容忍版本后缀）。对「回声型」中转（body 原样回 alias）没有鉴别力",
    no_attestation: "该 provider 结构性不发自证：响应头没有上游 model，响应体里的 model 又是请求别名回声 → 拿不到任何上游凭据，掉包无法检测（信息缺口，不是采集故障）",
    no_signal: "既没有自证头、响应体也没有 model —— 这次调用拿不到任何上游信息",
  };
  var ANOMALY = { mismatch: true, new_route: true, body_mismatch: true };
  var GROUP_LABELS = { upstream: "上游 model", alias: "请求 alias", provider: "provider",
                       endpoint: "端点", profile: "profile", status: "状态" };
  // 原生 <select> 的弹出选项会跟随元素的 background/color：深色主题下若留 bg-transparent，
  // 弹出列表可能变成"浅字白底"看不清 —— 必须显式给底色（用主题变量，不写死颜色）。
  var SELECT_STYLE = { background: "var(--color-popover)", color: "var(--color-popover-foreground)" };
  // 表格布局：插件能用的 CSS 类名只有 SPA 已编译的那部分（任意值类如 max-w-[18rem] 压根不在
  // 编译产物里 → 等于没写），所以「不换行 / 截断宽度」这类布局关键项一律用内联 style。
  var TD_STYLE = { whiteSpace: "nowrap" };
  var TITLE_STYLE = { maxWidth: "16rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
  var TABLE_WRAP_STYLE = { overflowX: "auto" };

  function statusClass(status) { return STATUS_CLASS[status] || "text-muted-foreground"; }

  function when(unixSeconds) {
    if (!unixSeconds) return "-";
    try { if (SDK.utils && typeof SDK.utils.timeAgo === "function") return SDK.utils.timeAgo(unixSeconds); } catch (e) {}
    return new Date(unixSeconds * 1000).toLocaleString();
  }

  function absolute(unixSeconds) {
    if (!unixSeconds) return "";
    try { return new Date(unixSeconds * 1000).toLocaleString(); } catch (e) { return ""; }
  }

  function jsonInit(method, body) {
    return { method: method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  }

  var UI_KEY = "model-audit:ui";
  function readUiState() {
    try { return JSON.parse(sessionStorage.getItem(UI_KEY) || "{}") || {}; } catch (e) { return {}; }
  }
  function writeUiState(k, v) {
    try {
      var cur = readUiState();
      cur[k] = v;
      sessionStorage.setItem(UI_KEY, JSON.stringify(cur));
    } catch (e) { /* sessionStorage 不可用就算了 */ }
  }

  function Page() {
    var st = SDK.hooks.useState({
      view: "audit", days: 7, onlyAnomaly: false, includeNoSignal: false, offset: 0,
      profile: "", profiles: [], groupBy: "upstream", groups: [],
      loading: true, error: null, rows: [], summary: null, health: null,
      approvals: [], retention: "90", toast: null, autoRefresh: true,
    });
    var s = st[0];
    // 定时器 / 异步回调要读"最新"状态：闭包里的 s 只是那一次渲染的快照，会过期。
    var sRef = SDK.hooks.useRef(s);
    sRef.current = s;
    function patch(part) {
      // **必须用函数式更新**：异步回调（fetch / setInterval）常在状态已变之后才 resolve，
      // 若按当次渲染的 s 展开写回，就会把旧快照整体盖回去 —— 实测症状：自动刷新把视图弹回对账页。
      st[1](function (prev) {
        var next = {};
        for (var k in prev) { next[k] = prev[k]; }
        for (var k2 in part) { next[k2] = part[k2]; }
        return next;
      });
      for (var k3 in part) {
        if (k3 === "view" || k3 === "days" || k3 === "onlyAnomaly" ||
            k3 === "includeNoSignal" || k3 === "autoRefresh" ||
            k3 === "profile" || k3 === "groupBy") {
          writeUiState(k3, part[k3]);        // 视图/筛选持久化：组件被重挂载也不丢
        }
      }
    }

    function loadAudit(days, onlyAnomaly, includeNoSignal, offset) {
      var off = offset || 0;
      patch({ days: days, onlyAnomaly: onlyAnomaly, includeNoSignal: includeNoSignal,
              offset: off, loading: true, error: null });
      var q = "?days=" + days + "&limit=" + PAGE_SIZE + "&offset=" + off
            + (onlyAnomaly ? "&only_anomaly=1" : "")
            + (onlyAnomaly && includeNoSignal ? "&include_no_signal=1" : "")
            + (s.profile ? "&profile=" + encodeURIComponent(s.profile) : "");
      Promise.all([
        SDK.fetchJSON(API + "/rows" + q),
        SDK.fetchJSON(API + "/summary?days=" + days + "&group_by=" + s.groupBy
                      + (s.profile ? "&profile=" + encodeURIComponent(s.profile) : "")),
        SDK.fetchJSON(API + "/health"),
      ]).then(function (res) {
        var page = (res[0] && res[0].rows) || [];
        patch({ loading: false, offset: off,
                rows: off > 0 ? s.rows.concat(page) : page,
                summary: res[1], health: res[2],
                profiles: (res[1] && res[1].profiles) || [],
                groups: (res[1] && res[1].groups) || [] });
      }).catch(function (err) {
        patch({ loading: false, error: String((err && err.message) || err), rows: [] });
      });
    }

    function loadAdmin() {
      Promise.all([SDK.fetchJSON(API + "/approvals"), SDK.fetchJSON(API + "/settings"),
                   SDK.fetchJSON(API + "/builtin")])
        .then(function (res) {
          patch({ approvals: (res[0] && res[0].approvals) || [],
                  retention: (res[1] && res[1].retention_days) || "90",
                  builtin: (res[2] && res[2].rules) || [] });
        })
        .catch(function (err) { patch({ error: String((err && err.message) || err) }); });
    }

    function approve(row, mode) {
      var served = row.upstream_model || row.body_model;   // 体证层行没有头值 → 用 body 值当认可键
      var ep = (mode === "model") ? "" : (row.endpoint_id || "");   // 仅模型 = 端点留空（任意）
      SDK.fetchJSON(API + "/approvals", jsonInit("POST", {
        requested_model: row.requested_model, upstream_model: served, endpoint_id: ep,
        provider: row.provider || "",
        note: (mode === "model") ? "从对账页认可（仅 model，端点任意）"
              : (row.upstream_model ? "从对账页认可" : "从对账页认可（体证层，键取 body 值）"),
      })).then(function () {
        patch({ toast: "已认可（仅视图标记）：" + row.requested_model + " → " + served
                       + (ep ? " @" + ep : "（端点任意）") });
        loadAudit(s.days, s.onlyAnomaly, s.includeNoSignal, 0);
      }).catch(function (err) { patch({ toast: "认可失败：" + ((err && err.message) || err) }); });
    }

    function removeApproval(a) {
      SDK.fetchJSON(API + "/approvals/" + a.id, { method: "DELETE" }).then(function () {
        patch({ toast: "已删除认可 #" + a.id });
        loadAdmin();
      }).catch(function (err) { patch({ toast: "删除失败：" + ((err && err.message) || err) }); });
    }

    function saveRetention() {
      SDK.fetchJSON(API + "/settings", jsonInit("PUT", { retention_days: Number(s.retention) }))
        .then(function () { patch({ toast: "保留天数已保存：" + s.retention + "（仅手动清理时生效）" }); })
        .catch(function (err) { patch({ toast: "保存失败：" + ((err && err.message) || err) }); });
    }

    function addApprovalManual() {
      var req = String(s.newReq || "").trim(), up = String(s.newUp || "").trim(), ep = String(s.newEp || "").trim();
      var prov = String(s.newProv || "").trim();
      if (!req) { patch({ toast: "请求 alias 必填" }); return; }
      if (!up && !ep) { patch({ toast: "上游 model 与端点至少填一项" }); return; }
      SDK.fetchJSON(API + "/approvals", jsonInit("POST", {
        requested_model: req, upstream_model: up, endpoint_id: ep, provider: prov, note: "管理页手动新增",
      })).then(function () {
        patch({ toast: "已新增认可：" + req + " → " + (up || "（任意 model）") + (ep ? " @" + ep : "（端点任意）"),
                newReq: "", newUp: "", newEp: "", newProv: "" });
        loadAdmin();
      }).catch(function (err) { patch({ toast: "新增失败：" + ((err && err.message) || err) }); });
    }

    function runPrune() {
      SDK.fetchJSON(API + "/maintenance/prune", { method: "POST" }).then(function (r) {
        patch({ toast: "清理完成：删除 " + ((r && r.deleted) || 0) + " 行（保留 " + ((r && r.retention_days) || "?") + " 天）" });
        loadAudit(s.days, s.onlyAnomaly, s.includeNoSignal, 0);
      }).catch(function (err) { patch({ toast: "清理失败：" + ((err && err.message) || err) }); });
    }

    SDK.hooks.useEffect(function () {
      var saved = readUiState();                       // 恢复上次的视图/筛选
      patch({ view: saved.view || "audit", days: saved.days || 7,
              autoRefresh: saved.autoRefresh !== false,
              profile: saved.profile || "", groupBy: saved.groupBy || "upstream" });
      loadAudit(saved.days || 7, saved.onlyAnomaly || false, saved.includeNoSignal || false, 0);
      var t = setInterval(function () {
        var cur = sRef.current;                        // 读最新状态，不用过期闭包
        if (cur.autoRefresh === false) return;         // 自动刷新可关（用户要求）
        if (cur.view === "admin") { loadAdmin(); }
        else { loadAudit(cur.days, cur.onlyAnomaly, cur.includeNoSignal, 0); }
      }, 15000);
      return function () { clearInterval(t); };
    }, []);

    SDK.hooks.useEffect(function () {
      if (s.view === "admin") { loadAdmin(); }
    }, [s.view]);

    var totals = (s.summary && s.summary.totals) ||
      { calls: 0, ok: 0, approved: 0, mismatch: 0, new_route: 0, body_mismatch: 0,
        body_only: 0, no_attestation: 0, no_signal: 0 };
    var cards = [
      ["近 " + s.days + " 天调用", totals.calls, "该时间窗内的全部调用（下面各卡之和 = 这张）"],
      ["✅ 一致", totals.ok, "命中内置标准；没有内置标准的 alias 则按「该 provider+alias 最常落到的组合」算"],
      ["🟢 已认可", totals.approved, "命中自定义认可规则（认可管理里加的例外）；内置标准命中计入「一致」，不计这里"],
      ["❌ 不匹配", totals.mismatch, "上游 model 与期望不符"],
      ["⚠️ 新路由", totals.new_route, "model 对得上，但端点不是期望的那个"],
      ["⚠️ 体证不同", totals.body_mismatch, "无自证头，body 的 model 与请求不同族"],
      ["○ 仅体证", totals.body_only, "无自证头，只有 body 的 model（与请求同族）"],
      ["◌ 无自证", totals.no_attestation, "该 provider 结构性不发自证（无自证头 + body 是 alias 回声）——掉包无法检测；属信息缺口，不是采集故障"],
      ["— 无信号", totals.no_signal, "既无自证头、响应体也没有 model"],
    ];

    var header = h(C.CardHeader, { key: "h" }, [
      h(C.CardTitle, { key: "t" }, "模型对账 —— 请求 alias vs 上游实际返回"),
      h("p", { key: "d", className: "text-sm text-muted-foreground" },
        "原始记录只增不改；判定顺序：① 内置标准（provider+alias → 期望 model+端点）→ ② 自定义认可 → "
        + "③ 都不命中才分类：model 变了 = ❌不一致，只有端点变了 = ⚠️新路由。"
        + "🟢 绿标 = 命中自定义认可，删掉即恢复原判定。"),
    ]);

    var viewButtons = h("div", { key: "v", className: "flex items-center gap-2 text-xs" }, [
      h("button", { key: "a", className: "rounded border border-border/60 px-3 py-1 " + (s.view === "audit" ? "bg-current/10" : ""),
                    onClick: function () { patch({ view: "audit" }); } }, "对账"),
      h("button", { key: "g", className: "rounded border border-border/60 px-3 py-1 " + (s.view === "groups" ? "bg-current/10" : ""),
                    onClick: function () { patch({ view: "groups" }); } }, "分组统计"),
      h("button", { key: "b", className: "rounded border border-border/60 px-3 py-1 " + (s.view === "admin" ? "bg-current/10" : ""),
                    onClick: function () { patch({ view: "admin" }); } }, "认可管理"),
      s.toast ? h("span", { key: "c", className: "text-muted-foreground" }, s.toast) : null,
    ]);

    var summaryRow = h("div", { key: "s", className: "flex flex-wrap gap-4" }, cards.map(function (c) {
      return h("div", { key: c[0], className: "rounded border border-border/60 px-3 py-2",
                        title: c[2] || "" }, [
        h("div", { key: "k", className: "text-xs text-muted-foreground" }, c[0]),
        h("div", { key: "v", className: "text-lg font-mono" }, String(c[1])),
      ]);
    }));

    var controls = h("div", { key: "c", className: "flex items-center gap-3 text-xs" }, [
      h("label", { key: "a", className: "flex items-center gap-1" }, [
        h("input", { key: "i", type: "checkbox", checked: s.onlyAnomaly,
                     onChange: function (e) { loadAudit(s.days, e.target.checked, s.includeNoSignal, 0); } }), "只看异常",
      ]),
      h("label", { key: "b", className: "flex items-center gap-1 " + (s.onlyAnomaly ? "" : "text-muted-foreground"),
                   title: s.onlyAnomaly ? "把「未自证」（无信号 + 仅体证 + 无自证）也纳入筛选" : "先勾选「只看异常」才生效" }, [
        h("input", { key: "i", type: "checkbox", checked: s.includeNoSignal, disabled: !s.onlyAnomaly,
                     onChange: function (e) { loadAudit(s.days, s.onlyAnomaly, e.target.checked, 0); } }), "含未自证",
      ]),
      h("label", { key: "ar", className: "flex items-center gap-1",
                   title: "每 15 秒自动拉一次数据；关掉后只有点「刷新」才更新（设置会记住）" }, [
        h("input", { key: "i", type: "checkbox", checked: s.autoRefresh !== false,
                     onChange: function (e) { patch({ autoRefresh: e.target.checked }); } }), "自动刷新",
      ]),
      h("select", { key: "pf", className: "rounded border border-border/60 px-2 py-1", style: SELECT_STYLE,
                    value: s.profile,
                    onChange: function (e) { patch({ profile: e.target.value }); loadAudit(s.days, s.onlyAnomaly, s.includeNoSignal, 0); } },
        [{ key: "", label: "全部 profile" }]
          .concat((s.profiles || []).map(function (p) { return { key: p.key, label: p.key + " (" + p.calls + ")" }; }))
          .map(function (o) { return h("option", { key: o.key, value: o.key }, o.label); })),
      h("select", { key: "d", className: "rounded border border-border/60 px-2 py-1", style: SELECT_STYLE,
                    value: String(s.days),
                    onChange: function (e) { loadAudit(Number(e.target.value), s.onlyAnomaly, s.includeNoSignal, 0); } },
        [1, 7, 30, 90].map(function (d) { return h("option", { key: d, value: String(d) }, d + " 天"); })),
      h("button", { key: "r", className: "rounded border border-border/60 px-2 py-1",
                    onClick: function () { loadAudit(s.days, s.onlyAnomaly, s.includeNoSignal, 0); } }, "刷新"),
      (s.rows.length >= PAGE_SIZE || s.offset > 0)
        ? h("button", { key: "m", className: "rounded border border-border/60 px-2 py-1",
                        onClick: function () { loadAudit(s.days, s.onlyAnomaly, s.includeNoSignal, s.rows.length); } }, "加载更多")
        : null,
      s.loading ? h("span", { key: "l", className: "text-muted-foreground" }, "加载中…") : null,
      h("span", { key: "n", className: "text-muted-foreground" }, "已显示 " + s.rows.length + " 行"),
      s.health && s.health.meta && s.health.meta.patch_ok === "0"
        ? h("span", { key: "w", className: "text-destructive" }, "⚠️ 采集补丁未生效（上游 model 将为空）") : null,
      s.health && s.health.state_db_exists === false
        ? h("span", { key: "w2", className: "text-muted-foreground" }, "（未找到 state.db，标题列留空）") : null,
    ]);

    var auditTable = h("table", { key: "tb", className: "w-full text-left" }, [
      h("thead", { key: "th" }, h("tr", null,
        ["时间", "会话 id", "会话标题", "profile", "provider", "请求 alias", "上游 model", "端点", "状态", "耗时", "finish", "操作"]
          .map(function (t) { return h("th", { key: t, className: "py-1 pr-4 text-xs text-muted-foreground", style: TD_STYLE }, t); }))),
      h("tbody", { key: "tb2" }, s.rows.map(function (r) {
        var approveKey = r.upstream_model || r.body_model;   // 体证层行用 body 值当键
        var canApprove = !!ANOMALY[r.status] && !!approveKey;
        return h("tr", { key: r.id, className: "border-b border-border/40" }, [
          h("td", { key: "1", className: "py-1.5 pr-4 text-xs text-muted-foreground", style: TD_STYLE,
                    title: absolute(r.ts_start) }, when(r.ts_start)),
          h("td", { key: "2", className: "py-1.5 pr-4 font-mono text-xs", style: TD_STYLE }, r.session_id || "-"),
          h("td", { key: "3", className: "py-1.5 pr-4 text-xs", style: TITLE_STYLE,
                    title: r.session_title_via === "parent"
                      ? "子智能体会话（delegate_task）：标题取自父会话；" + (r.session_title || "")
                      : (r.session_title_via === "compression"
                         ? "压缩前的会话：标题取自压缩后的子会话；" + (r.session_title || "")
                         : (r.session_title || "")) },
            (r.session_title_via === "parent" ? "↳ " : "")
              + (r.session_title || "-")),
          h("td", { key: "3b", className: "py-1.5 pr-4 text-xs text-muted-foreground", style: TD_STYLE }, r.profile_key || "-"),
          h("td", { key: "3c", className: "py-1.5 pr-4 text-xs", style: TD_STYLE,
                    title: (r.base_url || "") + "  " + (r.api_mode || "") },
            r.provider || "-"),
          h("td", { key: "4", className: "py-1.5 pr-4 text-xs", style: TD_STYLE }, r.requested_model || "-"),
          h("td", { key: "5", className: "py-1.5 pr-4 text-xs" + (r.upstream_model ? "" : " text-muted-foreground"),
                    style: TD_STYLE,
                    title: r.upstream_model
                      ? "上游自证头（x-opencode-upstream-model-id / x-litellm-model-id）"
                      : (r.body_model
                         ? (r.status === "no_attestation"
                            ? "该 provider 结构性不发自证：这里显示的是响应体里的 model，且与请求同名（回声）→ 零鉴别力，掉包无法检测"
                            : "无自证头：这里显示的是响应体里的 model（仅体证）")
                         : "") },
            r.upstream_model || (r.body_model ? "body: " + r.body_model : "—")),
          h("td", { key: "6", className: "py-1.5 pr-4 text-xs text-muted-foreground", style: TD_STYLE }, r.endpoint_id || "-"),
          h("td", { key: "7", className: "py-1.5 pr-4 text-xs", style: TD_STYLE }, [
            h("span", { key: "s", className: statusClass(r.status),
                        title: STATUS_TIP[r.status] || "" }, STATUS_TEXT[r.status] || r.status),
          ]),
          h("td", { key: "8", className: "py-1.5 pr-4 text-xs text-muted-foreground", style: TD_STYLE },
            r.duration_s ? r.duration_s.toFixed(1) + "s" : "-"),
          h("td", { key: "9", className: "py-1.5 pr-4 text-xs text-muted-foreground", style: TD_STYLE }, r.finish_reason || "-"),
          h("td", { key: "10", className: "py-1.5 text-xs", style: TD_STYLE }, canApprove
            ? [
                h("button", { key: "a", className: "rounded border border-border/60 px-2 py-0.5",
                              title: r.endpoint_id
                                ? "认可这个组合：model = " + approveKey + " ＋ 端点 = " + r.endpoint_id
                                : "认可这个上游 model（体证层没有端点信息）",
                              onClick: function () { approve(r, r.endpoint_id ? "both" : "model"); } }, "认可"),
                r.endpoint_id
                  ? h("button", { key: "b", className: "ml-1 rounded border border-border/60 px-2 py-0.5 text-muted-foreground",
                                  title: "只认 model、端点任意（端点换机房/路由池不再算异常）",
                                  onClick: function () { approve(r, "model"); } }, "仅模型")
                  : null,
              ]
            : h("span", { className: "text-muted-foreground" }, "—")),
        ]);
      })),
    ]);

    var groupView = h("div", { key: "gv", className: "flex flex-col gap-3" }, [
      h("div", { key: "ctl", className: "flex items-center gap-3 text-xs" }, [
        "分组维度：",
        h("select", { key: "g", className: "rounded border border-border/60 px-2 py-1", style: SELECT_STYLE,
                      value: s.groupBy,
                      onChange: function (e) { patch({ groupBy: e.target.value }); loadAudit(s.days, s.onlyAnomaly, s.includeNoSignal, 0); } },
          Object.keys(GROUP_LABELS).map(function (k) { return h("option", { key: k, value: k }, GROUP_LABELS[k]); })),
        h("span", { key: "n", className: "text-muted-foreground" }, "共 " + (s.groups || []).length + " 组"),
        h("span", { key: "h", className: "text-muted-foreground" },
          "（判定基准：内置标准 → 你认可的 → 该 alias 最常见的组合。「不一致」= 上游 model 与基准不同；"
          + "「新路由」= model 对得上但端点不是基准；「体证不同」= 没有自证头且 body 与请求不同族；"
          + "「无自证」= 该 provider 结构性不发自证（body 是 alias 回声），掉包无法检测）"),
      ]),
      h("table", { key: "tb", className: "w-full text-left" }, [
        h("thead", { key: "th" }, h("tr", null,
          ["组", "请求数", "❌ 不一致", "⚠️ 新路由", "⚠️ 体证不同", "○ 未自证", "🟢 已认可",
           "平均耗时", "涉及 alias", "涉及端点", "最近一次"]
            .map(function (t) { return h("th", { key: t, className: "py-1 pr-4 text-xs text-muted-foreground", style: TD_STYLE }, t); }))),
        h("tbody", { key: "tb2" }, (s.groups || []).map(function (g) {
          var als = g.aliases || [], eps = g.endpoints || [];
          var fmt = function (arr) {
            return arr.slice(0, 2).map(function (x) { return x[0] + " ×" + x[1]; }).join(" · ")
              + (arr.length > 2 ? " …(+" + (arr.length - 2) + ")" : "");
          };
          var tip = function (arr) { return arr.map(function (x) { return x[0] + " ×" + x[1]; }).join("\n"); };
          return h("tr", { key: g.key, className: "border-b border-border/40" }, [
            h("td", { key: "1", className: "py-1.5 pr-4 text-xs", style: TITLE_STYLE, title: g.key || "" },
              g.key || "(空)"),
            h("td", { key: "2", className: "py-1.5 pr-4 text-xs font-mono", style: TD_STYLE }, String(g.calls)),
            h("td", { key: "3", className: "py-1.5 pr-4 text-xs font-mono " + (g.mismatch ? "text-destructive" : "text-muted-foreground"),
                      style: TD_STYLE, title: "上游 model 与判定基准不同（基准 = 内置标准 / 你认可的 / 该 alias 最常见的组合）" },
              String(g.mismatch || 0)),
            h("td", { key: "4", className: "py-1.5 pr-4 text-xs font-mono " + (g.new_route ? "text-warning" : "text-muted-foreground"),
                      style: TD_STYLE, title: "model 对得上，但端点不是基准的那个" }, String(g.new_route || 0)),
            h("td", { key: "5", className: "py-1.5 pr-4 text-xs font-mono " + (g.body_mismatch ? "text-warning" : "text-muted-foreground"),
                      style: TD_STYLE, title: "没有自证头，响应体里的 model 与请求不同族" }, String(g.body_mismatch || 0)),
            h("td", { key: "6", className: "py-1.5 pr-4 text-xs font-mono text-muted-foreground", style: TD_STYLE,
                      title: "未自证 = 无信号 + 仅体证（覆盖缺口，不算异常）" }, String(g.unverified || 0)),
            h("td", { key: "7", className: "py-1.5 pr-4 text-xs font-mono text-success", style: TD_STYLE }, String(g.approved || 0)),
            h("td", { key: "8", className: "py-1.5 pr-4 text-xs text-muted-foreground", style: TD_STYLE },
              g.avg_duration_s ? g.avg_duration_s.toFixed(1) + "s" : "-"),
            h("td", { key: "9", className: "py-1.5 pr-4 text-xs text-muted-foreground", style: TITLE_STYLE,
                      title: "组内涉及的请求 alias：\n" + tip(als) }, fmt(als)),
            h("td", { key: "10", className: "py-1.5 pr-4 text-xs text-muted-foreground", style: TITLE_STYLE,
                      title: "组内涉及的路由端点：\n" + tip(eps) }, fmt(eps)),
            h("td", { key: "11", className: "py-1.5 text-xs text-muted-foreground", style: TD_STYLE }, when(g.last_ts)),
          ]);
        })),
      ]),
    ]);

    var adminView = h("div", { key: "ad", className: "flex flex-col gap-4" }, [
      h("div", { key: "bi", className: "flex flex-col gap-1" }, [
        h("span", { key: "l", className: "text-xs text-muted-foreground" },
          "内置标准（代码级常量，只读）—— 命中即 ✅一致；偏离时由下面的自定义认可放行例外："),
        h("table", { key: "tb", className: "w-full text-left" }, [
          h("thead", { key: "th" }, h("tr", null,
            ["provider", "请求 alias", "期望 model", "期望端点"]
              .map(function (t) { return h("th", { key: t, className: "py-1 pr-4 text-xs text-muted-foreground" }, t); }))),
          h("tbody", { key: "tb2" }, (s.builtin || []).map(function (b, i) {
            return h("tr", { key: i, className: "border-b border-border/40" }, [
              h("td", { key: "1", className: "py-1.5 pr-4 text-xs" }, b.provider || "（任意）"),
              h("td", { key: "2", className: "py-1.5 pr-4 text-xs" }, b.alias || "-"),
              h("td", { key: "3", className: "py-1.5 pr-4 text-xs text-success" }, b.model || "（任意）"),
              h("td", { key: "4", className: "py-1.5 pr-4 text-xs text-success" }, b.endpoint || "（任意）"),
            ]);
          })),
        ]),
      ]),
      h("div", { key: "add", className: "flex flex-wrap items-center gap-2 text-xs" }, [
        h("span", { key: "l", className: "text-muted-foreground" },
          "自定义认可（对内置标准的例外；model 与端点至少填一项，留空 = 任意）："),
        h("input", { key: "p", value: s.newProv || "", placeholder: "provider（可空）",
                     className: "w-32 rounded border border-border/60 bg-transparent px-2 py-1",
                     onChange: function (e) { patch({ newProv: e.target.value }); } }),
        h("input", { key: "a", value: s.newReq || "", placeholder: "请求 alias（必填）",
                     className: "w-40 rounded border border-border/60 bg-transparent px-2 py-1",
                     onChange: function (e) { patch({ newReq: e.target.value }); } }),
        h("input", { key: "m", value: s.newUp || "", placeholder: "上游 model（可空）",
                     className: "w-52 rounded border border-border/60 bg-transparent px-2 py-1",
                     onChange: function (e) { patch({ newUp: e.target.value }); } }),
        h("input", { key: "e", value: s.newEp || "", placeholder: "端点（可空）",
                     className: "w-44 rounded border border-border/60 bg-transparent px-2 py-1",
                     onChange: function (e) { patch({ newEp: e.target.value }); } }),
        h("button", { key: "b", className: "rounded border border-border/60 px-3 py-1",
                      onClick: addApprovalManual }, "新增"),
      ]),
      h("div", { key: "set", className: "flex items-center gap-3 text-xs" }, [
        "保留天数（手动清理时生效）：",
        h("input", { key: "i", type: "number", min: "1", max: "3650", value: s.retention,
                     className: "w-24 rounded border border-border/60 bg-transparent px-2 py-1",
                     onChange: function (e) { patch({ retention: e.target.value }); } }),
        h("button", { key: "s", className: "rounded border border-border/60 px-2 py-1", onClick: saveRetention }, "保存"),
        h("button", { key: "p", className: "rounded border border-border/60 px-2 py-1", onClick: runPrune }, "立即清理"),
      ]),
      h("table", { key: "tb", className: "w-full text-left" }, [
        h("thead", { key: "th" }, h("tr", null,
          ["provider", "请求 alias", "上游 model", "端点", "备注", "认可时间", "操作"]
            .map(function (t) { return h("th", { key: t, className: "py-1 pr-4 text-xs text-muted-foreground" }, t); }))),
        h("tbody", { key: "tb2" }, (s.approvals || []).map(function (a) {
          return h("tr", { key: a.id, className: "border-b border-border/40" }, [
            h("td", { key: "0", className: "py-1.5 pr-4 text-xs text-muted-foreground" },
              a.provider || "（任意）"),
            h("td", { key: "1", className: "py-1.5 pr-4 text-xs" }, a.requested_model),
            h("td", { key: "2", className: "py-1.5 pr-4 text-xs " + (a.upstream_model ? "text-success" : "text-muted-foreground") },
              a.upstream_model || "（任意）"),
            h("td", { key: "3", className: "py-1.5 pr-4 text-xs text-muted-foreground" },
              a.endpoint_id || "（任意）"),
            h("td", { key: "4", className: "py-1.5 pr-4 text-xs text-muted-foreground" }, a.note || "-"),
            h("td", { key: "5", className: "py-1.5 pr-4 text-xs text-muted-foreground" }, when(a.created_at)),
            h("td", { key: "6", className: "py-1.5 text-xs" },
              h("button", { className: "rounded border border-border/60 px-2 py-0.5 text-destructive",
                            onClick: function () { removeApproval(a); } }, "删除")),
          ]);
        })),
      ]),
    ]);

    var body = s.error
      ? h("p", { className: "text-sm text-destructive" }, "加载失败：" + s.error)
      : h("div", { className: "flex flex-col gap-3" },
          s.view === "audit" ? [summaryRow, controls,
                                h("div", { key: "tw", style: TABLE_WRAP_STYLE }, auditTable)]
            : (s.view === "groups" ? [summaryRow, groupView] : [adminView]));

    return h(C.Card, null, [header, h(C.CardContent, { key: "b" }, [viewButtons, body])]);
  }

  window.__HERMES_PLUGINS__.register(NAME, Page);
})();
