#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreePool —— 通用免费AI模型聚合网关
纯本地 / Termux 可部署 / OpenAI 协议兼容
固定地址: http://127.0.0.1:6120/v1
固定 Key: sk-freepool-fixed-2026
统一模型名: free-pool
"""
import json
import time
import uuid
import threading
import urllib.request
import urllib.error
import http.server
import socketserver
import os
import sys
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "freepool.log")

# ---------------- 日志 ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("freepool")

# ---------------- 配置 ----------------
DEFAULT_CONFIG = {
    "listen_host": "127.0.0.1",
    "listen_port": 6120,
    "api_key": "sk-freepool-fixed-2026",
    "model_name": "free-pool",
    "route_mode": "priority",           # priority | round_robin
    "timeout_seconds": 60,
    "cooldown_seconds": 30,
    "max_retries": 3,
    "session_sticky": True,
    "models": [
        {
            "name": "glm-4-flash",
            "provider": "zhipu",
            "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "api_key": "YOUR_ZHIPU_KEY",
            "model": "glm-4-flash",
            "priority": 1,
            "enabled": True
        },
        {
            "name": "qwen2.5-7b",
            "provider": "dashscope",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "api_key": "YOUR_DASHSCOPE_KEY",
            "model": "qwen2.5-7b-instruct",
            "priority": 2,
            "enabled": True
        },
        {
            "name": "workbuddy-1",
            "provider": "tencent",
            "base_url": "https://api.workbuddy.tencent.com/v1/chat/completions",
            "api_key": "YOUR_WORKBUDDY_KEY_1",
            "model": "workbuddy-chat",
            "priority": 3,
            "enabled": False
        }
    ]
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg
        except Exception as e:
            log.error(f"配置文件损坏, 使用默认: {e}")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    return json.loads(json.dumps(DEFAULT_CONFIG))

CONFIG = load_config()

# ---------------- 运行时状态 ----------------
STATE_LOCK = threading.Lock()
COOLDOWN = {}          # model_name -> cooldown_until_ts
RR_INDEX = 0
SESSIONS = {}          # session_id -> model_name
FAIL_COUNT = {}        # model_name -> consecutive fail count

def probe_quota(m):
    """查询各平台剩余额度。已知平台真实接口优先, 查不到回落 config 声明值。"""
    provider = (m.get("provider") or "").lower()
    key = m.get("api_key", "")
    cfg_text = m.get("quota_text", "")
    cfg_credits = m.get("credits", 0)
    endpoints = {
        "deepseek": "https://api.deepseek.com/user/balance",
        "tencent": "https://api.workbuddy.tencent.com/v1/account/credits",
    }
    url = endpoints.get(provider)
    if url and key and not key.startswith("YOUR_"):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
            data = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))
            if provider == "deepseek":
                bal = data.get("balance_infos", [{}])[0].get("total_balance")
                if bal is not None:
                    return f"余额 ¥{bal}", bal, True
            if "credits" in data:
                c = int(data["credits"])
                return f"剩余 {c} 积分", c, True
        except Exception:
            pass
    if cfg_text:
        return cfg_text, cfg_credits, False
    if cfg_credits:
        return f"剩余 {cfg_credits} 积分", cfg_credits, False
    return "额度未知", 0, False

def probe_latency(m):
    """测上游连通延迟(ms); 返回 (latency_ms, err)"""
    t0 = time.time()
    try:
        urllib.request.urlopen(
            urllib.request.Request(m["base_url"], method="GET"), timeout=5)
        return int((time.time() - t0) * 1000), None
    except urllib.error.HTTPError:
        return int((time.time() - t0) * 1000), None
    except Exception as e:
        return None, type(e).__name__

def is_cooled_down(name):
    with STATE_LOCK:
        t = COOLDOWN.get(name, 0)
        return time.time() < t

def set_cooldown(name):
    sec = CONFIG.get("cooldown_seconds", 30)
    with STATE_LOCK:
        COOLDOWN[name] = time.time() + sec
    log.warning(f"模型 {name} 进入冷却 {sec}s")

def clear_cooldown(name):
    with STATE_LOCK:
        COOLDOWN.pop(name, None)

def get_ordered_models():
    ms = [m for m in CONFIG["models"] if m.get("enabled", True)]
    if CONFIG.get("route_mode") == "round_robin":
        return ms
    return sorted(ms, key=lambda m: m.get("priority", 99))

def pick_by_round_robin(candidates):
    global RR_INDEX
    if not candidates:
        return None
    with STATE_LOCK:
        m = candidates[RR_INDEX % len(candidates)]
        RR_INDEX += 1
    return m

def pick_model(session_id):
    """按策略选模型; 会话粘性优先"""
    ordered = get_ordered_models()
    alive = [m for m in ordered if not is_cooled_down(m["name"])]
    if not alive:
        alive = ordered  # 全冷却时兜底重试
    if CONFIG.get("session_sticky") and session_id:
        bound = SESSIONS.get(session_id)
        for m in alive:
            if m["name"] == bound:
                return m
        # 绑定的模型失效 → 重新绑定
    if CONFIG.get("route_mode") == "round_robin":
        return pick_by_round_robin(alive)
    return alive[0] if alive else None

def bind_session(session_id, model_name):
    if CONFIG.get("session_sticky") and session_id:
        with STATE_LOCK:
            SESSIONS[session_id] = model_name

def extract_session_id(body, headers):
    sid = headers.get("X-Session-Id")
    if sid:
        return sid
    msgs = body.get("messages") or []
    if msgs:
        first = msgs[0].get("content", "")
        key = json.dumps(first, ensure_ascii=False)[:200]
        return "s-" + str(uuid.uuid5(uuid.NAMESPACE_URL, key))[:12]
    return None

# ---------------- 上游调用 ----------------
def call_upstream(model_cfg, body, stream=False):
    url = model_cfg["base_url"]
    payload = dict(body)
    payload["model"] = model_cfg["model"]
    payload["stream"] = stream
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {model_cfg['api_key']}"
        },
        method="POST"
    )
    timeout = CONFIG.get("timeout_seconds", 60)
    resp = urllib.request.urlopen(req, timeout=timeout)
    return resp

# ---------------- 聚宝盆对接 ----------------
JUBAO_URL = CONFIG.get("jubaopen_url", "http://127.0.0.1:6210")

def jubao_record_use(model_name, amount=1):
    """每次成功调用后, 异步向聚宝盆记一次消耗(失败不影响主流程)"""
    def _task():
        try:
            data = json.dumps({"name": model_name, "amount": amount}).encode()
            req = urllib.request.Request(
                f"{JUBAO_URL}/quota/use", data=data,
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass  # 聚宝盆离线时静默, 保证不断连
    threading.Thread(target=_task, daemon=True).start()

def probe_latencies(models):
    """并行探测各模型延迟(ms), 高延迟场景快速排序用"""
    results = {}
    def _probe(m):
        t0 = time.time()
        try:
            urllib.request.urlopen(
                urllib.request.Request(m["base_url"], method="GET"), timeout=3)
            results[m["name"]] = (time.time() - t0) * 1000
        except urllib.error.HTTPError:
            results[m["name"]] = (time.time() - t0) * 1000  # 4xx也算连通
        except Exception:
            results[m["name"]] = 9999  # 不可达
    threads = [threading.Thread(target=_probe, args=(m,), daemon=True) for m in models]
    for t in threads: t.start()
    for t in threads: t.join(timeout=3.5)
    return results

def pick_model_fast(session_id, body):
    """加速版选模型: 并行测延迟, 优先选 (低延迟 + 未冷却 + 会话粘性) 的模型。
    高延迟时: 若粘性模型延迟超过阈值, 立即换最快的, 不傻等。"""
    ordered = get_ordered_models()
    alive = [m for m in ordered if not is_cooled_down(m["name"])]
    if not alive:
        alive = ordered
    lat = probe_latencies(alive)
    # 按延迟排序(快的在前)
    fast = sorted(alive, key=lambda m: lat.get(m["name"], 9999))
    if CONFIG.get("session_sticky") and session_id:
        bound = SESSIONS.get(session_id)
        threshold = CONFIG.get("latency_switch_ms", 1200)
        for m in fast:
            if m["name"] == bound and lat.get(m["name"], 9999) <= threshold:
                return m  # 粘性且不慢, 保持
        # 粘性模型太慢或挂了 → 自动换最快并重新绑定
        if fast:
            log.info(f"会话 {session_id} 粘性模型慢/挂, 切到最快: {fast[0]['name']} ({lat.get(fast[0]['name']):.0f}ms)")
            return fast[0]
    if CONFIG.get("route_mode") == "round_robin":
        return pick_by_round_robin(fast)
    return fast[0] if fast else None

def call_upstream_fast(model_cfg, body, stream=False, connect_timeout=5):
    """上游调用: 高延迟时由 pick_model_fast 的延迟排序保证快速选择;
    连接阶段的快速失败由延迟探测+冷却机制承担。"""
    url = model_cfg["base_url"]
    payload = dict(body)
    payload["model"] = model_cfg["model"]
    payload["stream"] = stream
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {model_cfg['api_key']}"
        },
        method="POST"
    )
    resp = urllib.request.urlopen(req, timeout=CONFIG.get("timeout_seconds", 60))
    return resp

def try_generate(body, stream=False, session_id=None):
    """带自动降级+加速的生成; 返回 (model_name, raw_response) 或抛异常"""
    max_retries = CONFIG.get("max_retries", 3)
    last_err = None
    tried = set()
    for attempt in range(max_retries):
        m = pick_model_fast(session_id, body)
        if not m:
            raise RuntimeError("无可用上游模型, 请检查 config.json")
        if m["name"] in tried and len(tried) >= len(CONFIG["models"]):
            break
        tried.add(m["name"])
        try:
            log.info(f"[{attempt+1}/{max_retries}] 路由 → {m['name']} ({m['provider']}) stream={stream}")
            resp = call_upstream_fast(m, body, stream)
            clear_cooldown(m["name"])
            with STATE_LOCK:
                FAIL_COUNT[m["name"]] = 0
            jubao_record_use(m["name"], 1)  # 聚宝盆记账
            return m["name"], resp
        except urllib.error.HTTPError as e:
            code = e.code
            last_err = f"{m['name']} HTTP {code}"
            log.warning(f"{last_err}")
            if code in (429, 500, 502, 503, 504) or code == 401 or code == 403:
                set_cooldown(m["name"])
            with STATE_LOCK:
                FAIL_COUNT[m["name"]] = FAIL_COUNT.get(m["name"], 0) + 1
        except Exception as e:
            last_err = f"{m['name']} {type(e).__name__}: {e}"
            log.warning(last_err)
            set_cooldown(m["name"])
            with STATE_LOCK:
                FAIL_COUNT[m["name"]] = FAIL_COUNT.get(m["name"], 0) + 1
    raise RuntimeError(f"全部上游失败: {last_err}")

# ---------------- HTTP Server ----------------
class PoolHandler(http.server.BaseHTTPRequestHandler):
    server_version = "FreePool/1.0"

    def log_message(self, fmt, *args):
        log.info("%s - %s" % (self.address_string(), fmt % args))

    def _send_json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth_ok(self):
        key = CONFIG.get("api_key", "")
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {key}"

    def do_GET(self):
        if self.path == "/v1/models":
            if not self._auth_ok():
                return self._send_json(401, {"error": {"message": "invalid api key"}})
            now = int(time.time())
            data = []
            for m in CONFIG["models"]:
                if not m.get("enabled", True):
                    continue
                cooled = is_cooled_down(m["name"])
                data.append({
                    "id": m["name"],
                    "object": "model",
                    "created": now,
                    "owned_by": m.get("provider", "free-pool"),
                    "status": "cooldown" if cooled else "healthy"
                })
            return self._send_json(200, {"object": "list", "data": data})
        if self.path == "/health":
            return self._send_json(200, {"status": "ok", "models": len(CONFIG["models"])})
        # FreePool 插件聚合接口
        if self.path == "/pool/status":
            now = int(time.time())
            models = []
            total_credits = 0
            for m in CONFIG["models"]:
                if not m.get("enabled", True):
                    continue
                cooled = is_cooled_down(m["name"])
                status = "cooldown" if cooled else "healthy"
                quota_text = m.get("quota_text", "")
                credits = 0
                try:
                    credits = int(m.get("credits", 0))
                except (TypeError, ValueError):
                    credits = 0
                total_credits += credits
                # 繁忙度与网速、额度探测
                latency_ms, probe_err = probe_latency(m)
                busy = latency_ms is not None and latency_ms > 1500
                if cooled:
                    status = "cooldown"
                elif probe_err:
                    status = "unreachable"
                else:
                    status = "healthy"
                quota_text, credits, live = probe_quota(m)
                try:
                    credits = int(credits or 0)
                except (TypeError, ValueError):
                    credits = 0
                total_credits += credits
                if busy:
                    busy_level = "繁忙"
                elif probe_err:
                    busy_level = f"异常({probe_err})"
                elif latency_ms is not None:
                    busy_level = f"{latency_ms}ms"
                else:
                    busy_level = "不可达"
                models.append({
                    "name": m["name"],
                    "provider": m.get("provider", ""),
                    "status": status,
                    "quotaText": quota_text,
                    "quotaLive": live,
                    "credits": credits,
                    "busy": busy,
                    "busyLevel": busy_level,
                    "latencyMs": latency_ms,
                })
            return self._send_json(200, {
                "status": "ok",
                "models": models,
                "totalCredits": total_credits,
                "routeMode": CONFIG.get("route_mode"),
                "checkedAt": now,
            })
        if self.path in ("/pool/signin", "/pool/signin/"):
            # 占位: 各平台签到逻辑按 provider 自行扩展
            n = len([m for m in CONFIG["models"] if m.get("enabled", True)])
            return self._send_json(200, {"message": f"已对 {n} 个账号执行签到流程（示例）", "signedIn": n})

    def do_POST(self):
        if self.path in ("/pool/signin", "/pool/signin/"):
            n = len([m for m in CONFIG["models"] if m.get("enabled", True)])
            return self._send_json(200, {"message": f"已对 {n} 个账号执行签到流程（示例）", "signedIn": n})
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            return self._send_json(404, {"error": "not found"})
        if not self._auth_ok():
            return self._send_json(401, {"error": {"message": "invalid api key"}})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._send_json(400, {"error": {"message": f"bad request: {e}"}})

        want_stream = bool(body.get("stream"))
        sid = extract_session_id(body, self.headers)

        try:
            model_name, resp = try_generate(body, want_stream, session_id=sid)
        except Exception as e:
            log.error(f"最终失败: {e}")
            return self._send_json(502, {"error": {"message": str(e), "type": "all_upstreams_failed"}})

        bind_session(sid, model_name)
        log.info(f"会话 {sid} → 绑定 {model_name}")

        if want_stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for raw in resp:
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        out = line
                    else:
                        try:
                            obj = json.loads(line)
                            out = "data: " + json.dumps(obj, ensure_ascii=False)
                        except Exception:
                            continue
                    self.wfile.write((out + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                log.info("客户端断开流式连接")
            return

        # 非流式: 读上游, 原样透传
        try:
            raw = resp.read()
            up = json.loads(raw.decode("utf-8"))
            if "model" in up:
                up["model"] = model_name
            up.setdefault("freepool", {})
            up["freepool"]["routed_to"] = model_name
            return self._send_json(200, up)
        except Exception as e:
            return self._send_json(502, {"error": {"message": f"upstream read error: {e}"}})

class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def main():
    host = CONFIG.get("listen_host", "127.0.0.1")
    port = CONFIG.get("listen_port", 6120)
    log.info("=" * 50)
    log.info("FreePool 网关启动")
    log.info(f"  地址  : http://{host}:{port}/v1")
    log.info(f"  Key   : {CONFIG.get('api_key')}")
    log.info(f"  模型名: {CONFIG.get('model_name')}")
    log.info(f"  路由  : {CONFIG.get('route_mode')}")
    log.info(f"  粘性  : {CONFIG.get('session_sticky')}")
    for m in CONFIG["models"]:
        st = "启用" if m.get("enabled", True) else "禁用"
        log.info(f"  - {m['name']} [{st}] priority={m.get('priority')} provider={m.get('provider')}")
    log.info("=" * 50)
    srv = ThreadedServer((host, port), PoolHandler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("收到退出信号, 关闭网关")
        srv.shutdown()

if __name__ == "__main__":
    main()
