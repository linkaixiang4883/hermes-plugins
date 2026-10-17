"""model-audit 路由单测（临时库 + 假 state.db + TestClient）。
    "$VENV" tests/test_plugin_api.py
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("model_audit_core", ROOT / "model_audit_core.py")
core = importlib.util.module_from_spec(spec)
sys.modules["model_audit_core"] = core
spec.loader.exec_module(core)

db = Path(tempfile.mkdtemp(prefix="ma-api-")) / "t.db"
core.ensure_db(db)
now = time.time()
base = dict(ts_start=now, ts_end=now + 1, duration_s=1.0, ttfb_s=0.2, session_id="s1", turn_id="t",
            task_id="k", api_call_index=1, platform="desktop", provider="test-go",
            base_url="https://opencode.ai/zen/go/v1", api_mode="chat_completions",
            requested_model="deepseek-v4.1-flash", body_model="deepseek-v4.1-flash",
            upstream_model="deepseek/deepseek-v4.1-flash", endpoint_id="orcarouter-dsv4.1flash",
            zen_model="deepseek-v4.1-flash", upstream_log_id="x", header_ts=now,
            finish_reason="stop", input_tokens=1, output_tokens=2, total_tokens=3,
            profile_home="C:/h", status="ok", created_at=now, headers_json="{}")
core.insert_call(db, dict(base))                                                  # ok
core.insert_call(db, {**base, "requested_model": "muse-spark-1.3-contributor",
                      "upstream_model": "frank/Other", "endpoint_id": "frank",
                      "status": "mismatch"})                                      # mismatch
core.insert_call(db, {**base, "session_id": "s2", "upstream_model": None,
                      "endpoint_id": None, "status": "no_signal"})                # no_signal
os.environ["MODEL_AUDIT_DB"] = str(db)

state = Path(tempfile.mkdtemp(prefix="ma-api-state-")) / "state.db"
with sqlite3.connect(state) as sc:
    sc.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, title_source TEXT)")
    sc.execute("INSERT INTO sessions VALUES ('s1','会话一号','llm')")
    sc.commit()
os.environ["MODEL_AUDIT_STATE_DB"] = str(state)

spec2 = importlib.util.spec_from_file_location("model_audit_api", ROOT / "dashboard" / "plugin_api.py")
api = importlib.util.module_from_spec(spec2)
sys.modules["model_audit_api"] = api
spec2.loader.exec_module(api)
client = TestClient(FastAPI())
client.app.include_router(api.router, prefix="/api/plugins/model-audit")

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        failures.append(name)


# 读端点
r = client.get("/api/plugins/model-audit/health")
check("health 200", r.status_code == 200, r.text[:120])
check("health 有 rows", "rows" in r.json())
check("health 报 state_db 可达", r.json().get("state_db_exists") is True, str(r.json().get("state_db_exists")))

r = client.get("/api/plugins/model-audit/rows?days=30&limit=10")
check("rows 200 / 3 行", r.status_code == 200 and r.json()["total"] == 3, r.text[:120])
titles = {x["session_id"]: x.get("session_title") for x in r.json()["rows"]}
check("rows 带会话标题（跨库只读）", titles.get("s1") == "会话一号", str(titles))
check("rows 不再带 endpoint_changed（端点不参与判定）",
      all("endpoint_changed" not in x for x in r.json()["rows"]))

r = client.get("/api/plugins/model-audit/rows?days=30&limit=2&offset=0")
check("分页：offset=0 取 2 行", r.json()["total"] == 2, str(r.json().get("total")))
r = client.get("/api/plugins/model-audit/rows?days=30&limit=2&offset=2")
check("分页：offset=2 取 1 行", r.json()["total"] == 1, str(r.json().get("total")))

r = client.get("/api/plugins/model-audit/rows?days=30&only_anomaly=1")
check("默认异常筛选 = mismatch+new_route", r.json()["total"] == 1, str(r.json().get("total")))
r = client.get("/api/plugins/model-audit/rows?days=30&only_anomaly=1&include_no_signal=1")
check("含无信号 → 2 条", r.json()["total"] == 2, str(r.json().get("total")))
r = client.get("/api/plugins/model-audit/rows?days=30&limit=999999")
check("limit 越界被拒", r.status_code in (400, 422), str(r.status_code))
r = client.get("/api/plugins/model-audit/rows?days=30&limit=abc")
check("非法 limit 被拒", r.status_code in (400, 422), str(r.status_code))
r = client.get("/api/plugins/model-audit/summary?days=30")
check("summary 计数", r.status_code == 200 and r.json()["totals"]["calls"] == 3, str(r.json())[:200])
check("summary：没有自证头但 body 同族 → 算 body_only 而不是 no_signal",
      r.json()["totals"]["no_signal"] == 0 and r.json()["totals"]["body_only"] == 1,
      str(r.json()["totals"]))

# 认可写端点
r = client.post("/api/plugins/model-audit/approvals",
                json={"requested_model": "deepseek-v4.1-flash", "upstream_model": "frank/DeepSeek-V4.1-Flash",
                      "endpoint_id": "frank", "note": "手动认可"})
check("POST approvals 200", r.status_code == 200, r.text[:160])
check("POST 幂等（同 alias+model+端点 三元组）", client.post("/api/plugins/model-audit/approvals",
      json={"requested_model": "deepseek-v4.1-flash",
            "upstream_model": "frank/DeepSeek-V4.1-Flash",
            "endpoint_id": "frank"}).status_code == 200)
check("POST 同 alias+model 但端点留空 → 是另一条规则", client.post("/api/plugins/model-audit/approvals",
      json={"requested_model": "deepseek-v4.1-flash",
            "upstream_model": "frank/DeepSeek-V4.1-Flash"}).status_code == 200)
r = client.get("/api/plugins/model-audit/approvals")
check("GET approvals 2 条（严格 + 端点任意）", len(r.json()["approvals"]) == 2, r.text[:160])
aid = r.json()["approvals"][0]["id"]
aid2 = r.json()["approvals"][1]["id"]
check("空字段被拒", client.post("/api/plugins/model-audit/approvals",
      json={"requested_model": "", "upstream_model": "x"}).status_code in (400, 422))
check("DELETE approvals", client.delete(f"/api/plugins/model-audit/approvals/{aid}").status_code == 200)
check("DELETE 第二条", client.delete(f"/api/plugins/model-audit/approvals/{aid2}").status_code == 200)
check("DELETE 不存在 → 404", client.delete("/api/plugins/model-audit/approvals/999999").status_code == 404)

# 设置 + 手动清理
check("GET settings 默认 90", client.get("/api/plugins/model-audit/settings").json()["retention_days"] == "90")
check("PUT settings 200", client.put("/api/plugins/model-audit/settings", json={"retention_days": 30}).status_code == 200)
check("PUT settings 非法被拒", client.put("/api/plugins/model-audit/settings",
      json={"retention_days": 0}).status_code in (400, 422))
r = client.post("/api/plugins/model-audit/maintenance/prune")
check("prune 200 且带 deleted", r.status_code == 200 and "deleted" in r.json(), r.text[:160])

# 多 profile：过滤 + profiles 列表
core.insert_call(db, {**base, "session_id": "s3", "profile_home": "H:/b", "profile_name": "beta",
                      "requested_model": "deepseek-v4.1-flash",
                      "upstream_model": "deepseek/deepseek-v4.1-flash", "endpoint_id": "ep-b",
                      "status": "ok"})
r = client.get("/api/plugins/model-audit/rows?days=30&profile=beta")
check("rows?profile=beta 只回该 profile", r.json()["total"] == 1, str(r.json().get("total")))
check("rows 带 profile_key", r.json()["rows"][0].get("profile_key") == "beta",
      str(r.json()["rows"][0].get("profile_key")))
r = client.get("/api/plugins/model-audit/summary?days=30")
check("summary 带 profiles 列表", {p["key"] for p in r.json()["profiles"]} == {"C:/h", "beta"},
      str(r.json().get("profiles")))
r = client.get("/api/plugins/model-audit/summary?days=30&profile=beta")
check("summary?profile=beta 计数=1", r.json()["totals"]["calls"] == 1, str(r.json()["totals"]))
r = client.get("/api/plugins/model-audit/rows?days=30&profile=" + "x" * 400)
check("超长 profile 被拒", r.status_code in (400, 422), str(r.status_code))

# 分组统计
r = client.get("/api/plugins/model-audit/summary?days=30&group_by=provider")
check("summary?group_by=provider", r.status_code == 200 and {g["key"] for g in r.json()["groups"]} == {"test-go"},
      r.text[:160])
check("group_by 回显", r.json()["group_by"] == "provider", str(r.json().get("group_by")))
r = client.get("/api/plugins/model-audit/summary?days=30&group_by=status")
check("按 status 分组有 ok 组", {g["key"] for g in r.json()["groups"]} >= {"ok"}, r.text[:160])
check("非法 group_by → 400",
      client.get("/api/plugins/model-audit/summary?days=30&group_by=nope").status_code == 400)

# --- 体证层走 API：body 不同族 → 计入异常；认可键取 body 值 ---
core.insert_call(db, {**base, "session_id": "s-body", "upstream_model": None, "endpoint_id": None,
                      "requested_model": "gpt-5-mini", "body_model": "gpt-4o", "status": "no_signal"})
r = client.get("/api/plugins/model-audit/summary?days=30")
check("summary：体证不同计数", r.json()["totals"]["body_mismatch"] == 1, str(r.json()["totals"]))
r = client.get("/api/plugins/model-audit/rows?days=30&only_anomaly=1")
check("异常筛选：含体证不同（mismatch 1 + 这条）", r.json()["total"] == 2, str(r.json().get("total")))
r = client.get("/api/plugins/model-audit/rows?days=30&only_anomaly=1&include_no_signal=1")
check("含未自证：仅体证也进来（共 3 条）", r.json()["total"] == 3, str(r.json().get("total")))
r = client.post("/api/plugins/model-audit/approvals",
                json={"requested_model": "gpt-5-mini", "upstream_model": "gpt-4o", "note": "体证层"})
check("体证层可写认可（键取 body 值）", r.status_code == 200, r.text[:160])
rows = client.get("/api/plugins/model-audit/rows?days=30&limit=50").json()["rows"]
bod = [x for x in rows if x.get("body_model") == "gpt-4o"]
check("体证层行展示态变 approved", bod and bod[0]["status"] == "approved", str(bod[:1]))
check("体证层认可后不再进异常", client.get("/api/plugins/model-audit/rows?days=30&only_anomaly=1").json()["total"] == 1)
client.delete(f"/api/plugins/model-audit/approvals/{client.get('/api/plugins/model-audit/approvals').json()['approvals'][0]['id']}")

# --- 认可校验：两项至少填一项、alias 必填 ---
r = client.post("/api/plugins/model-audit/approvals", json={"requested_model": "x"})
check("认可：model 与端点都空 → 400", r.status_code == 400, r.text[:160])
r = client.post("/api/plugins/model-audit/approvals", json={"upstream_model": "y", "endpoint_id": "ep"})
check("认可：缺 alias → 400", r.status_code == 400, r.text[:160])
r = client.post("/api/plugins/model-audit/approvals",
                json={"requested_model": "x", "endpoint_id": "ep-a"})
check("认可：只认端点（model 留空）可写", r.status_code == 200, r.text[:160])
r = client.post("/api/plugins/model-audit/approvals",
                json={"requested_model": "x", "upstream_model": "y", "endpoint_id": "ep-a"})
check("认可：同 alias 同 model 不同端点可并存", r.status_code == 200, r.text[:160])
r = client.post("/api/plugins/model-audit/approvals",
                json={"requested_model": "x", "upstream_model": "y", "endpoint_id": "ep-b"})
check("认可：再来一条不同端点", r.status_code == 200, r.text[:160])
n = len(client.get("/api/plugins/model-audit/approvals").json()["approvals"])
check("认可：共 3 条（端点任意 1 + ep-a 1 + ep-b 1）", n == 3, str(n))
for a in client.get("/api/plugins/model-audit/approvals").json()["approvals"]:
    client.delete(f"/api/plugins/model-audit/approvals/{a['id']}")

# --- 内置标准端点（API 侧） + provider 维度 ---
r = client.get("/api/plugins/model-audit/builtin")
check("GET /builtin 返回内置标准",
      r.status_code == 200 and r.json()["rules"][0]["provider"] == "opencode-go", r.text[:200])
r = client.post("/api/plugins/model-audit/approvals",
                json={"provider": "opencode-go", "requested_model": "x", "upstream_model": "y"})
check("认可：可带 provider", r.status_code == 200, r.text[:160])
aps = client.get("/api/plugins/model-audit/approvals").json()["approvals"]
check("认可：provider 落库", any(a.get("provider") == "opencode-go" for a in aps), str(aps[:2]))
r = client.post("/api/plugins/model-audit/approvals",
                json={"requested_model": "x", "upstream_model": "y", "endpoint_id": "ep"})
check("认可：provider 留空 = 任意（另一条）", r.status_code == 200, r.text[:160])
for a in client.get("/api/plugins/model-audit/approvals").json()["approvals"]:
    client.delete(f"/api/plugins/model-audit/approvals/{a['id']}")

# --- 回归（0.3.0 客户端语义）：全新库 → 读接口 200 + 空结果 + initialized=false；后端半**不建库**；写接口 503 ---
fresh = Path(tempfile.mkdtemp(prefix="ma-api-fresh-"))
os.environ["MODEL_AUDIT_DB"] = str(fresh / "model_audit.db")          # 故意不存在
os.environ["MODEL_AUDIT_STATE_DB"] = str(fresh / "no-state.db")
for ep in ("/rows", "/summary", "/approvals", "/settings"):
    r = client.get(f"/api/plugins/model-audit{ep}")
    check(f"回归：全新库 GET {ep} → 200 且 initialized=false",
          r.status_code == 200 and r.json().get("initialized") is False, f"{r.status_code} {r.text[:110]}")
check("回归：客户端不建库（DB 文件仍不存在）", not (fresh / "model_audit.db").exists(), str(fresh))
r = client.delete("/api/plugins/model-audit/approvals/1")
check("回归：未初始化时 DELETE → 503（不是 500）", r.status_code == 503, f"{r.status_code} {r.text[:110]}")
r = client.post("/api/plugins/model-audit/approvals",
                json={"requested_model": "x", "upstream_model": "y"})
check("回归：未初始化时 POST → 503（不是 500）", r.status_code == 503, f"{r.status_code} {r.text[:110]}")
# 服务端（agent 半的 register）建库后，同一批接口转为正常
core.ensure_db(fresh / "model_audit.db")
r = client.get("/api/plugins/model-audit/rows")
check("服务端建库后 GET /rows → 200 且 initialized=true",
      r.status_code == 200 and r.json().get("initialized") is True, f"{r.status_code} {r.text[:110]}")
r = client.delete("/api/plugins/model-audit/approvals/1")
check("服务端建库后 DELETE → 404（空表语义，不是 500/503）", r.status_code == 404, f"{r.status_code} {r.text[:110]}")

print()
print("FAILED:", failures if failures else "none")
sys.exit(1 if failures else 0)
