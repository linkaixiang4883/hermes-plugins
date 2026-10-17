"""model-audit 核心单测。跑法（$VENV = Hermes 自带 venv 的 python）：
    "$VENV" tests/test_audit_core.py
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("model_audit_core", ROOT / "model_audit_core.py")
core = importlib.util.module_from_spec(spec)
sys.modules["model_audit_core"] = core
spec.loader.exec_module(core)

# ---- 测试隔离（必读）--------------------------------------------------------
# 默认 home **和「插件根」**都指向临时目录：本套件里任何「不带路径」的调用都不会碰到真实插件
# 存储。教训（v0.4.0 开发中真踩到）：ensure_db(<临时路径>) 若没有安全闸，会把插件树里的生产库
# 整库搬走并改名成 .migrated —— 一跑测试就等于对生产数据做了一次移动。
_TEST_HOME = Path(tempfile.mkdtemp(prefix="ma-test-home-"))
_TEST_PLUGIN_ROOT = Path(tempfile.mkdtemp(prefix="ma-test-root-"))
os.environ["HERMES_HOME"] = str(_TEST_HOME)
core.plugin_root = lambda: _TEST_PLUGIN_ROOT

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        failures.append(name)


def q(db, **kw):
    kw.setdefault("days", 3650); kw.setdefault("limit", 50); kw.setdefault("offset", 0)
    kw.setdefault("only_anomaly", False); kw.setdefault("include_no_signal", False)
    kw.setdefault("alias", None); kw.setdefault("session_id", None)
    return core.query_rows(db, **kw)


# --- 归一化与基础判定 ---
check("归一化：带命名空间算一致", core.model_match("deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash"))
check("归一化：大小写无关", core.model_match("deepseek-v4.1-flash", "frank/DeepSeek-V4.1-Flash"))
check("不匹配：换模型", not core.model_match("deepseek-v4.1-flash", "mimo-v2.6-flash"))
check("无信号：上游为空", core.status_for("deepseek-v4.1-flash", None) == "no_signal")
check("状态：一致 → ok", core.status_for("a", "ns/a") == "ok")
check("状态：换模型 → mismatch", core.status_for("a", "b") == "mismatch")

# --- build_row ---
BASE = time.time() - 10
payload = {
    "session_id": "20260924_031057_c97198", "turn_id": "t1", "task_id": "k1",
    "platform": "desktop", "model": "deepseek-v4.1-flash", "provider": "test-go",
    "base_url": "https://opencode.ai/zen/go/v1", "api_mode": "chat_completions",
    "api_call_count": 7, "api_duration": 9.8, "started_at": BASE, "ended_at": BASE + 9.8,
    "first_chunk_at": BASE + 0.5, "finish_reason": "stop", "response_model": "deepseek-v4.1-flash",
    "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
}
headers = {"x-opencode-upstream-model-id": "deepseek/deepseek-v4.1-flash",
           "x-opencode-endpoint-id": "orcarouter-dsv4.1flash",
           "authorization": "Bearer SHOULD-NEVER-BE-STORED"}
row = core.build_row(payload, headers, BASE + 0.2, profile_home="C:/h")
check("行：请求 alias", row["requested_model"] == "deepseek-v4.1-flash")
check("行：上游 model", row["upstream_model"] == "deepseek/deepseek-v4.1-flash")
check("行：端点", row["endpoint_id"] == "orcarouter-dsv4.1flash")
check("行：ttfb", abs(row["ttfb_s"] - 0.5) < 1e-6, str(row["ttfb_s"]))
check("行：状态", row["status"] == "ok")
check("行：不含敏感头", "authorization" not in (row["headers_json"] or "").lower())
check("行：无头 → no_signal", core.build_row(payload, None, None, profile_home="C:/h")["status"] == "no_signal")

# --- DB + 查询 ---
db = Path(tempfile.mkdtemp(prefix="ma-db-")) / "t.db"
core.ensure_db(db)
core.insert_call(db, row)
core.insert_call(db, core.build_row(payload, None, None, profile_home="C:/h"))
core.set_meta(db, "capture_installed", "1")
out = q(db)
check("查询：2 行", out["total"] == 2, str(out["total"]))
check("查询：meta 读回", core.get_meta(db).get("capture_installed") == "1")
check("查询：limit 钳制", q(db, limit=10**9)["limit"] <= 500)
check("异常筛选：默认不含 no_signal", q(db, only_anomaly=True)["total"] == 0, str(q(db, only_anomaly=True)["total"]))
check("异常筛选：含无信号时命中", q(db, only_anomaly=True, include_no_signal=True)["total"] == 1)
check("查询：offset 生效", q(db, limit=1, offset=1)["total"] == 1)

# --- 判定顺序 ③：model 与期望不同 → mismatch（不一致）；只有端点不同 → new_route（见后一节）---
core.insert_call(db, {**row, "endpoint_id": "orcarouter-dsv4.1flash"})     # 让期望组合成为多数（消除并列）
core.insert_call(db, {**row, "upstream_model": "frank/DeepSeek-V4.1-Flash", "endpoint_id": "frank"})
by_ep = {r["endpoint_id"]: r["status"] for r in q(db)["rows"]}
check("分类：上游 model 与期望不同 → mismatch", by_ep.get("frank") == "mismatch", str(by_ep))
check("分类：命中期望组合 → ok", by_ep.get("orcarouter-dsv4.1flash") == "ok", str(by_ep))
check("分类：只算这一条异常", q(db, only_anomaly=True)["total"] == 1, str(q(db, only_anomaly=True)["total"]))
check("分类：含未自证时 2 条", q(db, only_anomaly=True, include_no_signal=True)["total"] == 2)

# --- 认可规则：alias ＋（上游 model / 端点），留空的那项视为任意 ---
check("认可：两项都空 → 拒绝（不能认可整个 alias）",
      core.add_approval(db, "deepseek-v4.1-flash", "", "") is False)
check("认可：缺 alias → 拒绝", core.add_approval(db, "", "x", "ep") is False)
check("认可：只认 model（端点留空）可写",
      core.add_approval(db, "deepseek-v4.1-flash", "frank/DeepSeek-V4.1-Flash", endpoint_id="", note=""))
aps = core.list_approvals(db)
check("认可：列表 1 条", len(aps) == 1, str(aps))
statuses = {r["endpoint_id"]: r["status"] for r in q(db)["rows"]}
check("认可：端点任意 → frank 行转绿", statuses.get("frank") == "approved", str(statuses))
check("认可：不再进异常筛选", q(db, only_anomaly=True)["total"] == 0, str(q(db, only_anomaly=True)["total"]))
with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as raw:
    stored = raw.execute("select status from calls where upstream_model like 'frank%'").fetchone()[0]
check("认可：原始行 status 仍是事实态 ok", stored == "ok", stored)

# 严格组合：model ＋ 端点都写 → 只有匹配的端点算；同一 model 可按端点各留一条
check("认可：同 model 不同端点的第二条能写进去（旧 UNIQUE 会挡）",
      core.add_approval(db, "deepseek-v4.1-flash", "frank/DeepSeek-V4.1-Flash", endpoint_id="frank"))
check("认可：两条规则并存", len(core.list_approvals(db)) == 2, str(core.list_approvals(db)))
check("认可：同三元组重复写幂等",
      core.add_approval(db, "deepseek-v4.1-flash", "frank/DeepSeek-V4.1-Flash", endpoint_id="frank")
      and len(core.list_approvals(db)) == 2)
check("认可：只认端点（model 留空）也能写",
      core.add_approval(db, "some-alias", upstream_model="", endpoint_id="orcarouter"))
check("认可：只认端点这条删得掉", core.delete_approval(db, core.list_approvals(db)[0]["id"]) is True)

for _a in core.list_approvals(db):
    core.delete_approval(db, _a["id"])
check("认可：全部删除后恢复告警", q(db, only_anomaly=True)["total"] == 1,
      str(q(db, only_anomaly=True)["total"]))
check("认可：删除后列表为空", core.list_approvals(db) == [])

# --- 判定顺序 ③：无内置标准的 alias → 期望 = 该 provider+alias 最常落到的组合 ---
edb = Path(tempfile.mkdtemp(prefix="ma-ep-")) / "t.db"
core.ensure_db(edb)
E = time.time() - 5


def ep_row(upstream, endpoint):
    return core.build_row({**payload, "started_at": E, "ended_at": E + 1},
                          {"x-opencode-upstream-model-id": upstream,
                           "x-opencode-endpoint-id": endpoint},
                          E, profile_home="H:/ep")


for _ in range(3):
    core.insert_call(edb, ep_row("deepseek/deepseek-v4.1-flash", "orcarouter-dsv4.1flash"))
core.insert_call(edb, ep_row("deepseek/deepseek-v4.1-flash", "novita-deepseek"))
core.insert_call(edb, ep_row("deepseek/deepseek-v4.1-flash", "deepseek"))
st_ep = {r["endpoint_id"]: r["status"] for r in q(edb, limit=20)["rows"]}
check("分类：最常见组合 → ok", st_ep.get("orcarouter-dsv4.1flash") == "ok", str(st_ep))
check("分类：只换端点 → new_route", st_ep.get("novita-deepseek") == "new_route", str(st_ep))
check("分类：换到别的端点同样 new_route", st_ep.get("deepseek") == "new_route", str(st_ep))
check("分类：异常 2 条", q(edb, only_anomaly=True)["total"] == 2,
      str(q(edb, only_anomaly=True)["total"]))
core.add_approval(edb, "deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash",
                  endpoint_id="novita-deepseek")
st_ep2 = {r["endpoint_id"]: r["status"] for r in q(edb, limit=20)["rows"]}
check("分类：端点级认可放行例外 → approved", st_ep2.get("novita-deepseek") == "approved", str(st_ep2))
check("分类：其它端点仍 new_route（异常 1 条）", q(edb, only_anomaly=True)["total"] == 1,
      str(q(edb, only_anomaly=True)["total"]))

# --- 判定顺序 ①：内置标准（provider + alias → 期望 model + 端点）优先 ---
bdb = Path(tempfile.mkdtemp(prefix="ma-bi-")) / "t.db"
core.ensure_db(bdb)


def bi_row(model, endpoint, alias="deepseek-flash", provider="opencode-go"):
    return core.build_row({**payload, "model": alias, "provider": provider, "response_model": alias,
                           "started_at": E, "ended_at": E + 1},
                          {"x-opencode-upstream-model-id": model,
                           "x-opencode-endpoint-id": endpoint},
                          E, profile_home="H:/bi")


core.insert_call(bdb, bi_row("deepseek-flash", "deepseek"))                  # 命中内置标准
core.insert_call(bdb, bi_row("deepseek-flash", "novita-deepseek"))           # 端点偏离
core.insert_call(bdb, bi_row("deepseek/deepseek-v4.1-flash", "deepseek"))    # model 偏离


def bi_st():
    return {(r["upstream_model"], r["endpoint_id"]): r["status"] for r in q(bdb, limit=20)["rows"]}


check("内置：命中标准 → ok", bi_st().get(("deepseek-flash", "deepseek")) == "ok", str(bi_st()))
check("内置：端点偏离 → new_route", bi_st().get(("deepseek-flash", "novita-deepseek")) == "new_route",
      str(bi_st()))
check("内置：model 偏离 → mismatch", bi_st().get(("deepseek/deepseek-v4.1-flash", "deepseek")) == "mismatch",
      str(bi_st()))
for _ in range(3):                                # 偏离行变成"最常见"也不影响标准
    core.insert_call(bdb, bi_row("deepseek-flash", "novita-deepseek"))
check("内置：标准不受『最常见』影响", bi_st().get(("deepseek-flash", "deepseek")) == "ok", str(bi_st()))
core.add_approval(bdb, "deepseek-flash", "deepseek-flash", endpoint_id="novita-deepseek")
check("内置：例外经自定义认可放行 → approved",
      bi_st().get(("deepseek-flash", "novita-deepseek")) == "approved", str(bi_st()))
check("内置：其它 provider 不吃这条标准（provider 维度生效）",
      core.builtin_expected("opencode-go", "deepseek-flash") == ("deepseek-flash", "deepseek")
      and core.builtin_expected("other-relay", "deepseek-flash") is None)
check("内置：BUILTIN_RULES 可读（API /builtin 用）", len(core.BUILTIN_RULES) == 2 and
      {r["alias"] for r in core.BUILTIN_RULES} == {"deepseek-flash", "deepseek-v4.1-flash"},
      str(core.BUILTIN_RULES))
check("内置：deepseek-v4.1-flash 钉到 deepseek 端点",
      core.builtin_expected("opencode-go", "deepseek-v4.1-flash")
      == ("deepseek/deepseek-v4.1-flash", "deepseek"))

# --- 体证层：没有自证头时退到 body 的 model（对回声型中转无鉴别力，所以单列状态）---
check("同族：版本后缀容忍", core.family_match("gpt-5-mini", "gpt-5-mini-2025-08-07"))
check("同族：日期后缀容忍（反向）", core.family_match("claude-sonnet-4-5-20250929", "claude-sonnet-4-5"))
check("同族：命名空间剥离", core.family_match("deepseek-v4.1-flash", "ns/DeepSeek-V4.1-Flash"))
check("不同族：-pro 不是版本", not core.family_match("deepseek-v3.2", "deepseek-v3.2-pro"))
check("不同族：mini 不是版本", not core.family_match("gpt-5", "gpt-5-mini"))
check("不同族：换模型", not core.family_match("a", "b"))

fam = Path(tempfile.mkdtemp(prefix="ma-body-")) / "t.db"
core.ensure_db(fam)


def body_row(body, model="gpt-5-mini"):
    p = {**payload, "model": model, "provider": "openai", "response_model": body,
         "base_url": "https://api.openai.com/v1"}
    return core.build_row(p, None, None, profile_home="H:/body")


core.insert_call(fam, body_row("gpt-5-mini"))                  # 同族 → body_only
core.insert_call(fam, body_row("gpt-5-mini-2025-08-07"))       # 仅版本后缀 → body_only
core.insert_call(fam, body_row("gpt-4o"))                      # 不同族 → body_mismatch
core.insert_call(fam, body_row(None))                          # 连 body 都没有 → no_signal
st = {r["body_model"]: r["status"] for r in q(fam, limit=10)["rows"]}
check("体证：同族 → body_only", st.get("gpt-5-mini") == "body_only", str(st))
check("体证：版本后缀 → body_only", st.get("gpt-5-mini-2025-08-07") == "body_only", str(st))
check("体证：不同族 → body_mismatch", st.get("gpt-4o") == "body_mismatch", str(st))
check("体证：无 body → no_signal", st.get(None) == "no_signal", str(st))
with sqlite3.connect(f"file:{fam}?mode=ro", uri=True) as _raw:
    _stored = {r[0] for r in _raw.execute("select distinct status from calls")}
check("体证：原始行只存头部事实态（体验层不落库）", _stored == {"no_signal"}, str(_stored))
check("筛选：异常含体证不同（1 条）", q(fam, only_anomaly=True)["total"] == 1,
      str(q(fam, only_anomaly=True)["total"]))
check("筛选：含未自证再加 无信号+仅体证（4 条 = 全部）",
      q(fam, only_anomaly=True, include_no_signal=True)["total"] == 4,
      str(q(fam, only_anomaly=True, include_no_signal=True)["total"]))
summ_body = core.summarize(fam, days=3650, group_by="status")
tb = summ_body["totals"]
check("汇总：体证层计数", tb["body_only"] == 2 and tb["body_mismatch"] == 1 and tb["no_signal"] == 1, str(tb))
check("汇总：无自证头时 ok 为 0", tb["ok"] == 0, str(tb))
check("汇总：各状态之和 = 调用总数（页面卡片要对得上）",
      sum(tb[k] for k in ("ok", "approved", "mismatch", "new_route", "body_mismatch",
                          "body_only", "no_attestation", "no_signal")) == tb["calls"], str(tb))
gb = {g["key"]: g for g in summ_body["groups"]}
check("分组：未自证 = 无信号 + 仅体证", gb.get("body_only", {}).get("unverified") == 2, str(gb.get("body_only")))
check("分组：异常含体证不同", gb.get("body_mismatch", {}).get("anomalies") == 1, str(gb.get("body_mismatch")))
check("分组：上游维度标注仅体证",
      any("（仅体证）" in str(g["key"])
          for g in core.summarize(fam, days=3650, group_by="upstream")["groups"]),
      str([g["key"] for g in core.summarize(fam, days=3650, group_by="upstream")["groups"]]))

# --- 无自证 provider（commandcode）：结构性不发自证 → 单列 no_attestation ---
na = Path(tempfile.mkdtemp(prefix="ma-noatt-")) / "t.db"
core.ensure_db(na)


def cc_row(body, model="deepseek/deepseek-v4.1-flash"):
    p = {**payload, "model": model, "provider": "commandcode", "response_model": body,
         "base_url": "https://api.commandcode.ai/provider/v1"}
    return core.build_row(p, {"x-trace-id": "902e13a7cf6538e87467a4e4d5e2b9db"}, None, profile_home="H:/cc")


check("无自证：常量表含 commandcode", "commandcode" in core.NO_SELF_ATTESTATION_PROVIDERS)
check("无自证：allowlist 含 x-trace-id", "x-trace-id" in core.HEADER_ALLOWLIST)
cc1 = cc_row("deepseek/deepseek-v4.1-flash")                 # 回声（body == alias）
check("无自证：trace id 落 upstream_log_id",
      cc1["upstream_log_id"] == "902e13a7cf6538e87467a4e4d5e2b9db", str(cc1["upstream_log_id"]))
_both = core.build_row({**payload, "provider": "opencode-go"},
                       {"x-opencode-log-id": "log-1", "x-trace-id": "trace-1"}, None, profile_home="H:/x")
check("无自证：opencode log id 优先于 trace id", _both["upstream_log_id"] == "log-1", str(_both["upstream_log_id"]))
core.insert_call(na, cc1)
core.insert_call(na, {**cc_row("deepseek/deepseek-v4.1-flash"), "ts_start": cc1["ts_start"] + 1})
core.insert_call(na, {**cc_row("mimo-v2.6-flash"), "ts_start": cc1["ts_start"] + 2})   # 不同族 → 仍是异常
na_st = [r["status"] for r in q(na, limit=10)["rows"]]
check("无自证：回声行 → no_attestation（2 条）", na_st.count("no_attestation") == 2, str(na_st))
check("无自证：不同族仍报 body_mismatch（真信号不掩盖）", "body_mismatch" in na_st, str(na_st))
check("无自证：不算异常（只看异常 → 1）", q(na, only_anomaly=True)["total"] == 1,
      str(q(na, only_anomaly=True)["total"]))
check("无自证：含未自证 → 3 条（全部）", q(na, only_anomaly=True, include_no_signal=True)["total"] == 3,
      str(q(na, only_anomaly=True, include_no_signal=True)["total"]))
summ_na = core.summarize(na, days=3650, group_by="status")
check("无自证：汇总单列计数", summ_na["totals"]["no_attestation"] == 2, str(summ_na["totals"]))
check("无自证：各状态之和 = 调用总数",
      sum(summ_na["totals"][k] for k in ("ok", "approved", "mismatch", "new_route", "body_mismatch",
                                         "body_only", "no_attestation", "no_signal")) == summ_na["totals"]["calls"],
      str(summ_na["totals"]))
check("无自证：计进「未自证」桶",
      {g["key"]: g["unverified"] for g in summ_na["groups"]}.get("no_attestation") == 2,
      str([(g["key"], g["unverified"]) for g in summ_na["groups"]]))
check("无自证：上游维度标「（无自证）」",
      any("（无自证）" in str(g["key"]) for g in core.summarize(na, days=3650, group_by="upstream")["groups"]),
      str([g["key"] for g in core.summarize(na, days=3650, group_by="upstream")["groups"]]))

# 体证层也能「认可」：键取 body 值 → 视图层转绿、退出异常
core.add_approval(fam, "gpt-5-mini", "gpt-4o", note="体证层")
after = {r["body_model"]: r["status"] for r in q(fam, limit=10)["rows"]}
check("体证：认可后 → approved", after.get("gpt-4o") == "approved", str(after))
check("体证：认可后不再进异常", q(fam, only_anomaly=True)["total"] == 0, str(q(fam, only_anomaly=True)["total"]))

# --- 跨库取标题：覆盖路径 ---
state = Path(tempfile.mkdtemp(prefix="ma-state-")) / "state.db"
with sqlite3.connect(state) as sc:
    sc.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, title_source TEXT, parent_session_id TEXT)")
    sc.executemany("INSERT INTO sessions VALUES (?,?,?,?)",
                   [("20260924_031057_c97198", "实现股票插件图片展示效果", "llm", None),
                    ("s-other", None, "derived", None)])
    sc.commit()
os.environ["MODEL_AUDIT_STATE_DB"] = str(state)
titles = core.session_titles(["20260924_031057_c97198", "s-other", "nope"])
check("标题：取到 llm 标题", titles.get("20260924_031057_c97198") == "实现股票插件图片展示效果", str(titles))
check("标题：NULL 变空串", titles.get("s-other") == "", str(titles))
check("标题：查不到不报错", "nope" not in titles)

# 压缩链：Hermes 压缩是「分叉」——父会话 end_reason='compression' 且 title 被清成 NULL，
# 标题归新建的子会话（parent_session_id 指向父）→ 按 id 直查永远查不到，要沿链向下找。
with sqlite3.connect(state) as sc:
    sc.executemany("INSERT INTO sessions VALUES (?,?,?,?)",
                   [("s-parent", None, "llm", None),          # 一代压缩：父（NULL）→ 子（有标题）
                    ("s-child", "子会话标题", "llm", "s-parent"),
                    ("s-chain1", None, "llm", None),          # 多代压缩：NULL → NULL → 有标题
                    ("s-chain2", None, "llm", "s-chain1"),
                    ("s-chain3", "孙会话标题", "llm", "s-chain2"),
                    ("s-mid", "中间标题", "llm", None),        # 自己有标题就用自己的（现实里不会出现）
                    ("s-tail", "尾标题", "llm", "s-mid"),
                    ("s-orphan", None, "llm", None)])         # 无子会话
    sc.commit()
chain = core.session_titles(["s-parent", "s-child", "s-chain1", "s-chain2", "s-chain3",
                             "s-mid", "s-orphan"])
check("标题：压缩链 → 父会话取到子会话标题", chain.get("s-parent") == "子会话标题", str(chain))
check("标题：多代压缩 → 跳过中间 NULL 取链尾", chain.get("s-chain1") == "孙会话标题", str(chain))
check("标题：链中间同样取链尾标题", chain.get("s-chain2") == "孙会话标题", str(chain))
check("标题：链尾用自己的标题", chain.get("s-chain3") == "孙会话标题", str(chain))
check("标题：自身有标题则不被更深覆盖", chain.get("s-mid") == "中间标题", str(chain))
check("标题：无子会话仍为空串", chain.get("s-orphan") == "", str(chain))

# 子智能体会话（delegate_task）：自己没有标题 → 取父会话标题（via='parent'）
with sqlite3.connect(state) as sc:
    sc.executemany("INSERT INTO sessions VALUES (?,?,?,?)",
                   [("s-user", "父会话标题", "llm", None),
                    ("s-sub", None, None, "s-user"),
                    ("s-sub2", None, None, "s-sub"),
                    ("s-orphan2", None, "llm", None)])
    sc.commit()
detail = core.session_titles_detail(["s-user", "s-sub", "s-sub2", "s-orphan2"], path=state)
check("标题：子智能体会话取父会话标题（via=parent）",
      detail.get("s-sub", ("", ""))[0] == "父会话标题" and detail.get("s-sub", ("", ""))[1] == "parent",
      str(detail))
check("标题：孙辈子会话沿父链向上取最近的非空",
      detail.get("s-sub2", ("", ""))[0] == "父会话标题", str(detail))
check("标题：自己的标题来源标记为空", detail.get("s-user", ("", "x"))[1] == "", str(detail))
check("标题：无父无子 → 仍为空", detail.get("s-orphan2", ("x", ""))[0] == "", str(detail))
check("标题：旧契约 session_titles 仍只返回字符串",
      core.session_titles(["s-sub"], path=state) == {"s-sub": "父会话标题"})
os.environ["MODEL_AUDIT_STATE_DB"] = str(Path(tempfile.mkdtemp(prefix="ma-nostate-")) / "missing.db")
check("标题：state.db 不存在 → 空 dict", core.session_titles(["x"]) == {})
del os.environ["MODEL_AUDIT_STATE_DB"]

# --- 跨库取标题：按每行的 profile_home 分库 ---
home_a = Path(tempfile.mkdtemp(prefix="ma-home-a-"))
home_b = Path(tempfile.mkdtemp(prefix="ma-home-b-"))
for home, sid, title in ((home_a, "s-a", "A 会话"), (home_b, "s-b", "B 会话")):
    with sqlite3.connect(home / "state.db") as sc:
        sc.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, title_source TEXT)")
        sc.execute("INSERT INTO sessions VALUES (?,?,?)", (sid, title, "llm"))
        sc.commit()
rows = [{"session_id": "s-a", "profile_home": str(home_a)},
        {"session_id": "s-b", "profile_home": str(home_b)},
        {"session_id": "s-missing", "profile_home": str(home_a)}]
core.attach_titles(rows)
check("标题：A profile 取到 A 库标题", rows[0]["session_title"] == "A 会话", str(rows[0]))
check("标题：B profile 取到 B 库标题", rows[1]["session_title"] == "B 会话", str(rows[1]))
check("标题：查不到 → 空串不报错", rows[2]["session_title"] == "", str(rows[2]))

# --- 保留策略（仅手动触发）---
old = {**row, "ts_start": time.time() - 200 * 86400, "created_at": time.time() - 200 * 86400}
core.insert_call(db, old)
core.set_setting(db, "retention_days", "90")
deleted = core.prune_calls(db)
check("清理：删掉 200 天前的行", deleted >= 1, str(deleted))
check("清理：meta 记录", core.get_meta(db).get("last_prune_deleted") is not None)
check("设置：retention_days 读回", core.get_setting(db, "retention_days") == "90")
check("清理：认可表不受影响", len(core.list_approvals(db)) == 0)

# --- 多 profile：归属与基准路由不混算 ---
db2 = Path(tempfile.mkdtemp(prefix="ma-mp-")) / "t.db"
core.ensure_db(db2)
B = time.time() - 5


def mk(profile_home, profile_name, upstream, endpoint):
    return core.build_row(
        {**payload, "started_at": B, "ended_at": B + 1},
        {"x-opencode-upstream-model-id": upstream, "x-opencode-endpoint-id": endpoint},
        B + 0.1, profile_home=profile_home, profile_name=profile_name)


core.insert_call(db2, mk("H:/a", "alpha", "deepseek/deepseek-v4.1-flash", "ep-a"))
core.insert_call(db2, mk("H:/b", "beta", "deepseek/deepseek-v4.1-flash", "ep-b"))
rows_mp = q(db2)["rows"]
by_pk = {(r["profile_key"], r["endpoint_id"]): r["status"] for r in rows_mp}
check("多 profile：各自端点都算 ok（基准按 profile 分桶）",
      by_pk.get(("alpha", "ep-a")) == "ok" and by_pk.get(("beta", "ep-b")) == "ok", str(by_pk))
check("多 profile：profile_key 正确",
      {r["profile_key"] for r in rows_mp} == {"alpha", "beta"},
      str({r["profile_key"] for r in rows_mp}))
check("多 profile：行过滤生效", q(db2, profile="alpha")["total"] == 1)
summ_mp = core.summarize(db2, days=3650)
check("多 profile：summary 列出两个 profile",
      {p["key"] for p in summ_mp["profiles"]} == {"alpha", "beta"}, str(summ_mp["profiles"]))
check("多 profile：summary 可按 profile 过滤",
      core.summarize(db2, days=3650, profile="beta")["totals"]["calls"] == 1)

# --- 分组统计（group by）---
g_db = Path(tempfile.mkdtemp(prefix="ma-grp-")) / "t.db"
core.ensure_db(g_db)
G = time.time() - 3


def grow(upstream, endpoint, provider, dur, offset=0):
    return core.build_row(
        {**payload, "started_at": G + offset, "ended_at": G + offset + dur,
         "api_duration": dur, "provider": provider},
        {"x-opencode-upstream-model-id": upstream, "x-opencode-endpoint-id": endpoint},
        G + offset, profile_home="H:/g", profile_name="gamma")


core.insert_call(g_db, grow("deepseek/deepseek-v4.1-flash", "ep-1", "test-go", 10.0))
core.insert_call(g_db, grow("deepseek/deepseek-v4.1-flash", "ep-1", "test-go", 20.0, 1))
core.insert_call(g_db, grow("mimo-v2.6-flash", "ep-2", "other-go", 5.0, 2))
byk = {g["key"]: g for g in core.summarize(g_db, days=3650, group_by="upstream")["groups"]}
check("分组：按上游 model 分 2 组",
      set(byk) == {"deepseek/deepseek-v4.1-flash", "mimo-v2.6-flash"}, str(set(byk)))
check("分组：请求数正确", byk["deepseek/deepseek-v4.1-flash"]["calls"] == 2, str(byk))
check("分组：平均耗时正确", byk["deepseek/deepseek-v4.1-flash"]["avg_duration_s"] == 15.0,
      str(byk["deepseek/deepseek-v4.1-flash"]["avg_duration_s"]))
check("分组：路由数", byk["deepseek/deepseek-v4.1-flash"]["routes"] == 1)
check("分组：异常拆开（mismatch 计数）", byk["mimo-v2.6-flash"]["mismatch"] == 1, str(byk["mimo-v2.6-flash"]))
check("分组：异常拆开（new_route 计数）", byk["deepseek/deepseek-v4.1-flash"]["new_route"] == 0,
      str(byk["deepseek/deepseek-v4.1-flash"]))
check("分组：列出涉及的 alias（按条数降序）",
      byk["mimo-v2.6-flash"]["aliases"] == [["deepseek-v4.1-flash", 1]],
      str(byk["mimo-v2.6-flash"]["aliases"]))
check("分组：列出涉及的端点",
      byk["deepseek/deepseek-v4.1-flash"]["endpoints"] == [["ep-1", 2]],
      str(byk["deepseek/deepseek-v4.1-flash"]["endpoints"]))
check("分组：按 provider 分组",
      {g["key"] for g in core.summarize(g_db, days=3650, group_by="provider")["groups"]} == {"test-go", "other-go"})
check("分组：group_by 回显", core.summarize(g_db, days=3650, group_by="provider")["group_by"] == "provider")
check("分组：非法维度回退 alias", core.summarize(g_db, days=3650, group_by="nope")["group_by"] == "alias")
check("分组：按 status 分组",
      {g["key"] for g in core.summarize(g_db, days=3650, group_by="status")["groups"]} == {"ok", "mismatch"},
      str([g["key"] for g in core.summarize(g_db, days=3650, group_by="status")["groups"]]))

# --- 旧库迁移：补 profile_name 列 ---
old_db = Path(tempfile.mkdtemp(prefix="ma-old-")) / "old.db"
with sqlite3.connect(old_db) as oc:
    oc.execute("CREATE TABLE calls (id INTEGER PRIMARY KEY, ts_start REAL, requested_model TEXT, status TEXT)")
core.ensure_db(old_db)
with sqlite3.connect(old_db) as oc:
    cols = {r[1] for r in oc.execute("PRAGMA table_info(calls)")}
check("迁移：旧库补上 profile_name 列", "profile_name" in cols, str(sorted(cols)))

# --- 认可表迁移：旧结构（UNIQUE(requested, upstream)）→ 三项联合唯一 ---
ap_db = Path(tempfile.mkdtemp(prefix="ma-apmig-")) / "old.db"
with sqlite3.connect(ap_db) as oc:
    oc.execute("""CREATE TABLE approvals (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  requested_model TEXT NOT NULL, upstream_model TEXT NOT NULL,
                  endpoint_id TEXT, note TEXT, created_at REAL NOT NULL,
                  UNIQUE(requested_model, upstream_model))""")
    oc.execute("INSERT INTO approvals (requested_model, upstream_model, endpoint_id, note, created_at)"
               " VALUES ('a','x','ep-1','旧行',1.0)")
    oc.commit()
core.ensure_db(ap_db)
kept = core.list_approvals(ap_db)
check("认可迁移：旧行保留", len(kept) == 1 and kept[0]["endpoint_id"] == "ep-1", str(kept))
check("认可迁移：同 model 不同端点现在能并存",
      core.add_approval(ap_db, "a", "x", endpoint_id="ep-2") and len(core.list_approvals(ap_db)) == 2)
check("认可迁移：同三元组仍幂等",
      core.add_approval(ap_db, "a", "x", endpoint_id="ep-2") and len(core.list_approvals(ap_db)) == 2)
check("认可迁移：可表达「只认 model」",
      core.add_approval(ap_db, "a", "x", endpoint_id="") and len(core.list_approvals(ap_db)) == 3)
core.ensure_db(ap_db)
check("认可迁移：幂等（再跑一次不炸、不丢行）", len(core.list_approvals(ap_db)) == 3)

# --- 服务端语义：schema_ready / ensure_db（幂等、快路径、自愈、并发） ---
srv = Path(tempfile.mkdtemp(prefix="ma-srv-")) / "s.db"
check("schema_ready：库不存在 → False", core.schema_ready(srv) is False)
core.ensure_db(srv)
check("schema_ready：建库后 → True", core.schema_ready(srv) is True)
core.ensure_db(srv)                                   # 快路径：已就位直接返回
check("ensure_db 幂等：再调一次仍 ready", core.schema_ready(srv) is True)
for suffix in ("", "-wal", "-shm"):                   # 自愈：整个库被删掉（Windows 句柄释放可能略滞后，重试几次）
    p = Path(str(srv) + suffix)
    for _ in range(20):
        if not p.exists():
            break
        try:
            p.unlink()
            break
        except PermissionError:
            time.sleep(0.1)
check("schema_ready：库被删 → False", core.schema_ready(srv) is False)
core.ensure_db(srv)
check("ensure_db 自愈：删掉后能重建", core.schema_ready(srv) is True)

import threading                                      # noqa: E402  （只这一段用到）
conc = Path(tempfile.mkdtemp(prefix="ma-conc-")) / "c.db"
concurrent_errors = []


def _mk() -> None:
    try:
        core.ensure_db(conc)
    except Exception as exc:                          # noqa: BLE001
        concurrent_errors.append(f"{type(exc).__name__}: {exc}")


ths = [threading.Thread(target=_mk) for _ in range(8)]
[t.start() for t in ths]
[t.join(timeout=10) for t in ths]
check("并发 ensure_db ×8：零异常且 schema 就位",
      not concurrent_errors and core.schema_ready(conc), str(concurrent_errors[:2]))

# ---------------------------------------------------------------- v0.4.0 存储位置 + 一次性迁移
_saved_db_override = os.environ.pop("MODEL_AUDIT_DB", None)      # 本节测默认解析 → 必须先清覆盖
_saved_home = os.environ.get("HERMES_HOME")
try:
    _home = Path(tempfile.mkdtemp(prefix="ma-home-"))
    os.environ["HERMES_HOME"] = str(_home)
    _want = _home / "plugin-data" / "model-audit" / "model_audit.db"
    check("路径：db_path 落在 <home>/plugin-data/<slug>/ 下", core.db_path() == _want, str(core.db_path()))
    check("路径：老库位置 = <插件根>/data/model_audit.db（形状不变）",
          core.legacy_db_path() == _TEST_PLUGIN_ROOT / "data" / "model_audit.db",
          str(core.legacy_db_path()))

    def _seed_legacy(suffix="", root=None):
        """造一个真库形状的「老库」（3 行 + 1 认可 + meta），返回 (legacy_root, legacy_path)。"""
        root = Path(root) if root else Path(tempfile.mkdtemp(prefix=f"ma-lroot{suffix}-"))
        legacy = core.legacy_db_path(root)
        legacy.parent.mkdir(parents=True, exist_ok=True)
        core.ensure_db(legacy)
        for i in range(3):
            core.insert_call(legacy, core.build_row({**payload, "api_call_count": i}, headers, BASE + 0.2,
                                                    profile_home="C:/h", profile_name="default"))
        core.add_approval(legacy, "deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash",
                          "orcarouter-dsv4.1flash")
        core.set_meta(legacy, "marker", "before")
        return root, legacy

    _lroot, _legacy = _seed_legacy()
    _before = q(_legacy)["total"]
    _moved = core.adopt_legacy_db(_want, _lroot)
    check("迁移：返回老库路径", bool(_moved), str(_moved))
    check("迁移：行数与老库一致", q(_want)["total"] == _before, f'{q(_want)["total"]} vs {_before}')
    check("迁移：approvals 一并搬来", len(core.list_approvals(_want)) == 1,
          str(len(core.list_approvals(_want))))
    check("迁移：meta 一并搬来", core.get_meta(_want).get("marker") == "before")
    check("迁移：老库退场（*.migrated，不再持有句柄）",
          not _legacy.exists() and _legacy.with_name(_legacy.name + ".migrated").exists())
    check("迁移：幂等（第二次什么都不做）", core.adopt_legacy_db(_want, _lroot) is None)

    # target 已有数据 → 永不覆盖（保护新库）
    _t2 = Path(tempfile.mkdtemp(prefix="ma-t2-")) / "x.db"
    core.ensure_db(_t2)
    core.insert_call(_t2, core.build_row({**payload, "api_call_count": 99}, headers, BASE + 0.2,
                                         profile_home="C:/h"))
    _lroot2, _l2 = _seed_legacy("2")
    check("迁移：target 已存在 → 不动手",
          core.adopt_legacy_db(_t2, _lroot2) is None and q(_t2)["total"] == 1, str(q(_t2)["total"]))
    check("迁移：此时老库原样留着（没被吞）", _l2.exists())

    # env 覆盖时不迁移（测试/临时探测依赖这条）
    _lroot3, _l3 = _seed_legacy("3")
    os.environ["MODEL_AUDIT_DB"] = str(Path(tempfile.mkdtemp(prefix="ma-ovr-")) / "t.db")
    check("迁移：MODEL_AUDIT_DB 覆盖时不动手",
          core.adopt_legacy_db(_home / "plugin-data" / "model-audit" / "t2.db", _lroot3) is None and _l3.exists())
    os.environ.pop("MODEL_AUDIT_DB", None)

    # 端到端：**生产调用形状**（ensure_db() 无参；且插件确实安装在本 home 的 plugins/ 下）
    _home2 = Path(tempfile.mkdtemp(prefix="ma-home2-"))
    os.environ["HERMES_HOME"] = str(_home2)
    _installed = _home2 / "plugins" / "model-audit"                      # 模拟真实安装位置（安全闸 2 要求）
    _lroot4, _l4 = _seed_legacy("4", root=_installed)
    core.plugin_root = lambda: _installed
    core.ensure_db()                                                     # ← 生产形状（无参）
    _want2 = _home2 / "plugin-data" / "model-audit" / "model_audit.db"
    check("端到端：ensure_db() 自动接住老库（生产形状）",
          _want2.exists() and q(_want2)["total"] == 3, str(q(_want2)["total"]))

    # 回归闸 2（本次生产事故的原样复现）：工具类调用用**临时 home** 跑**真实安装目录**的
    # register() → db_path() 在临时 home（闸 1 通过），但 legacy_db_path() 仍指向真实库。
    # 必须拒绝迁移，否则真库被改名、数据留在随后被丢弃的临时 home 里。
    _home3 = Path(tempfile.mkdtemp(prefix="ma-home3-"))
    os.environ["HERMES_HOME"] = str(_home3)
    _lroot6, _l6 = _seed_legacy("6")                                     # 老库在「别处」
    core.plugin_root = lambda: _lroot6                                   # ≠ <home3>/plugins/model-audit
    core.ensure_db()
    _t6 = _home3 / "plugin-data" / "model-audit" / "model_audit.db"
    check("回归闸 2：插件不在本 home 的 plugins/ 下 → 不迁移（真库原样、没被取走一行）",
          _l6.exists() and q(_t6)["total"] == 0,
          f"legacy_alive={_l6.exists()} target_rows={q(_t6)['total']}")

    # 回归闸（显式路径）：显式路径**永不**触发迁移
    _lroot5, _l5 = _seed_legacy("5")
    core.plugin_root = lambda: _lroot5
    _explicit = Path(tempfile.mkdtemp(prefix="ma-expl-")) / "t.db"
    core.ensure_db(_explicit)
    check("回归闸：显式路径不迁移（老库原样留着、临时库为空）",
          _l5.exists() and q(_explicit)["total"] == 0,
          f"legacy_alive={_l5.exists()} explicit_rows={q(_explicit)['total']}")
finally:
    core.plugin_root = lambda: _TEST_PLUGIN_ROOT                        # 归还到隔离根（不是真实插件目录）
    if _saved_home is None:
        os.environ.pop("HERMES_HOME", None)
    else:
        os.environ["HERMES_HOME"] = _saved_home
    if _saved_db_override is not None:
        os.environ["MODEL_AUDIT_DB"] = _saved_db_override

print()
print("FAILED:", failures if failures else "none")
sys.exit(1 if failures else 0)
