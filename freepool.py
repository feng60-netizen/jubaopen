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

# ---------------- 自适应调度器（五维评分融合） ----------------
# score = 0.35*速度分 + 0.25*成功分 + 0.15*质量分 + 0.15*积分分 + 0.10*额度分
# 速度分: 实测延迟映射(0-1000ms → 100-0)
# 成功分: 近期成功/失败滑动窗口
# 质量分: /v1/compare 中各模型表现(答得快+答得全加分)
# 积分分: 聚宝盆积分余额归一化
# 额度分: 今日剩余额度归一化
SCORE_LOCK = threading.Lock()
MODEL_SCORES = {}   # name -> {"lat": 最近延迟, "ok": 成功次数, "fail": 失败次数, "quality": 0-100}

def score_update(name, key, value):
    with SCORE_LOCK:
        s = MODEL_SCORES.setdefault(name, {"lat": None, "ok": 0, "fail": 0, "quality": 50})
        if key == "lat":
            s["lat"] = value
        elif key == "ok":
            s["ok"] += 1
        elif key == "fail":
            s["fail"] += 1
        elif key == "quality":
            s["quality"] = value

def model_scores_snapshot():
    with SCORE_LOCK:
        return dict(MODEL_SCORES)

def jubao_weights():
    """从聚宝盆拉积分+剩余额度, 归一化成 0-1 权重; 离线时全 0.5"""
    try:
        q = json.loads(urllib.request.urlopen(f"{JUBAO_URL}/quota", timeout=2).read().decode())
        remain = {a["name"]: a.get("remainToday") or 0 for a in q.get("accounts", [])}
        mx = max(remain.values()) or 1
        remain_w = {k: v / mx for k, v in remain.items()}
    except Exception:
        remain_w = {}
    try:
        p = json.loads(urllib.request.urlopen(f"{JUBAO_URL}/points", timeout=2).read().decode())
        pts = {a["name"]: a.get("points", 0) for a in p.get("accounts", [])}
        mx = max(pts.values()) or 1
        pts_w = {k: v / mx for k, v in pts.items()}
    except Exception:
        pts_w = {}
    return remain_w, pts_w

# ---------------- 本人优先通道 ----------------
# 自己用的时候请求带上特殊 Key(X-API-Key 或 Bearer 都行), 调度时:
#   1. 评分整体加 OWNER_BOOST 分(碾压其他来源)
#   2. 挤占排队: 高峰期本人请求插队
#   3. 冷却豁免: 本人请求允许试冷却中的模型(优先级最高, 别人不行)
OWNER_KEY = CONFIG.get("owner_key", "sk-owner-me-2026")
OWNER_BOOST = 40   # 评分加成, 足够把本人排到最前

def is_owner(headers):
    auth = headers.get("Authorization", "")
    xkey = headers.get("X-Owner-Key", "")
    return xkey == OWNER_KEY or auth == f"Bearer {OWNER_KEY}"

def adaptive_score(name, snapshot, owner=False):
    """0-100 综合评分; owner=True 时整体加成, 保证本人请求优先"""
    s = snapshot.get(name, {"lat": None, "ok": 0, "fail": 0, "quality": 50})
    # 速度分
    lat = s.get("lat")
    speed = max(0, 100 - (lat or 500) / 10) if lat else 50
    # 成功分
    ok, fail = s.get("ok", 0), s.get("fail", 0)
    total = ok + fail
    success = (ok / total * 100) if total else 60
    quality = s.get("quality", 50)
    remain_w, pts_w = jubao_weights()
    credit = pts_w.get(name, 0.5) * 100
    quota = remain_w.get(name, 0.5) * 100
    base = (0.35 * speed + 0.25 * success + 0.15 * quality + 0.15 * credit + 0.10 * quota)
    return min(200, base + (OWNER_BOOST if owner else 0))

def pick_by_adaptive(candidates, owner=False):
    """自适应策略: 综合评分排序"""
    snap = model_scores_snapshot()
    scored = [(adaptive_score(m["name"], snap, owner), m) for m in candidates]
    scored.sort(key=lambda x: -x[0])
    if scored:
        log.info(f"自适应评分" + ("[本人]" if owner else "") + ": " + ", ".join(f"{m['name']}={sc:.0f}" for sc, m in scored))
    return scored[0][1] if scored else None


    global RR_INDEX
    if not candidates:
        return None
    with STATE_LOCK:
        m = candidates[RR_INDEX % len(candidates)]
        RR_INDEX += 1
    return m

# ---------------- Magpie 式路由策略 ----------------
ADAPTIVE_STRATEGIES = {"adaptive", "智能", "auto"}
# 智能auto / 按顺序priority / 轮流round_robin / 用量少优先least_used / 免费优先free_first / 速度优先speed_first
def pick_by_strategy(candidates, strategy=None):
    strategy = strategy or CONFIG.get("route_mode", "priority")
    if strategy in ADAPTIVE_STRATEGIES:
        return pick_by_adaptive(candidates)
    if strategy == "round_robin":
        return pick_by_round_robin(candidates)
    if strategy == "least_used":
        # 今日用量最少的优先(从聚宝盆读, 读不到按优先级)
        try:
            q = json.loads(urllib.request.urlopen(f"{JUBAO_URL}/quota", timeout=2).read().decode())
            used = {a["name"]: a.get("usedToday", 0) for a in q.get("accounts", [])}
            return sorted(candidates, key=lambda m: used.get(m["name"], 0))[0]
        except Exception:
            return candidates[0]
    if strategy == "free_first":
        # 标记 free:true 的模型优先, 其次按优先级
        free = [m for m in candidates if m.get("free")]
        return (free or candidates)[0]
    if strategy == "speed_first":
        # 并行测延迟, 最快优先
        lat = probe_latencies(candidates)
        return sorted(candidates, key=lambda m: lat.get(m["name"], 9999))[0]
    # smart / priority: 优先级顺序, 但综合延迟微调
    return candidates[0]

# auto 路由模型名: free-pool / free-pool:fast / free-pool:smart
def resolve_auto_model(model_name):
    """返回 (路由策略, 指定模型名或None)。支持:
    free-pool → 按配置默认策略
    free-pool:fast → 速度优先
    free-pool:smart → 智能(优先级+延迟)
    free-pool:free → 免费优先
    free-pool:least → 用量少优先
    free-pool:轮 → 轮流
    free-pool:glm-4-flash → 指定具体模型"""
    if not model_name or model_name in (CONFIG.get("model_name"), "auto"):
        return None, None
    if ":" in model_name:
        pfx, tag = model_name.split(":", 1)
        if pfx in (CONFIG.get("model_name"), "auto"):
            m = {"fast": "speed_first", "smart": "smart", "free": "free_first",
                 "least": "least_used", "轮": "round_robin", "robin": "round_robin"}.get(tag)
            if m:
                return m, None
            return None, tag  # 具体模型名
    return None, model_name  # 直接指定模型名

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

def pick_model_fast(session_id, body, owner=False):
    """加速版选模型: 并行测延迟, 优先选 (低延迟 + 未冷却 + 会话粘性) 的模型。
    高延迟时: 若粘性模型延迟超过阈值, 立即换最快的, 不傻等。
    owner=True: 冷却豁免(可用冷却中的模型), 评分加成。"""
    ordered = get_ordered_models()
    if owner:
        alive = ordered  # 本人: 冷却豁免
    else:
        alive = [m for m in ordered if not is_cooled_down(m["name"])]
    if not alive:
        alive = ordered
    lat = probe_latencies(alive)
    fast = sorted(alive, key=lambda m: lat.get(m["name"], 9999))
    if CONFIG.get("session_sticky") and session_id:
        bound = SESSIONS.get(session_id)
        threshold = CONFIG.get("latency_switch_ms", 1200)
        for m in fast:
            if m["name"] == bound and (owner or lat.get(m["name"], 9999) <= threshold):
                return m
        if fast:
            log.info(f"会话 {session_id} 粘性模型慢/挂" + ("[本人]" if owner else "") + f", 切到: {fast[0]['name']}")
            return fast[0]
    if CONFIG.get("route_mode") in ADAPTIVE_STRATEGIES:
        return pick_by_adaptive(fast, owner)
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

def try_generate(body, stream=False, session_id=None, owner=False):
    """带自动降级+加速+策略的生成; 返回 (model_name, raw_response) 或抛异常"""
    max_retries = CONFIG.get("max_retries", 3)
    last_err = None
    tried = set()
    # 解析 auto 路由名
    strategy, pinned = resolve_auto_model(body.get("model"))
    candidates = [m for m in get_ordered_models() if not pinned or m["name"] == pinned or m["model"] == pinned]
    for attempt in range(max_retries):
        alive = [m for m in candidates if not is_cooled_down(m["name"])] or candidates
        if strategy:
            m = pick_by_strategy(alive, strategy) if not owner else pick_by_adaptive(alive, True)
        else:
            m = pick_model_fast(session_id, body, owner)
        if not m:
            raise RuntimeError("无可用上游模型, 请检查 config.json")
        if m["name"] in tried and len(tried) >= len(CONFIG["models"]):
            break
        tried.add(m["name"])
        try:
            t0 = time.time()
            log.info(f"[{attempt+1}/{max_retries}] 路由[{strategy or CONFIG.get('route_mode')}{' [本人]' if owner else ''}] → {m['name']} ({m['provider']}) stream={stream}")
            resp = call_upstream_fast(m, body, stream)
            latency = int((time.time() - t0) * 1000)
            clear_cooldown(m["name"])
            with STATE_LOCK:
                FAIL_COUNT[m["name"]] = 0
            score_update(m["name"], "lat", latency)
            score_update(m["name"], "ok", 1)
            jubao_record_use(m["name"], 1)
            return m["name"], resp
        except urllib.error.HTTPError as e:
            code = e.code
            last_err = f"{m['name']} HTTP {code}"
            log.warning(f"{last_err}")
            score_update(m["name"], "fail", 1)
            if code in (429, 500, 502, 503, 504) or code == 401 or code == 403:
                set_cooldown(m["name"])
            with STATE_LOCK:
                FAIL_COUNT[m["name"]] = FAIL_COUNT.get(m["name"], 0) + 1
        except Exception as e:
            last_err = f"{m['name']} {type(e).__name__}: {e}"
            log.warning(last_err)
            score_update(m["name"], "fail", 1)
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
        if auth == f"Bearer {key}":
            return True
        return is_owner(self.headers)  # 本人 key 放行

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
        if self.path == "/scores":
            """自适应调度评分表(驾驶舱核心)"""
            snap = model_scores_snapshot()
            enabled = [m for m in CONFIG["models"] if m.get("enabled", True)]
            remain_w, pts_w = jubao_weights()
            rows = []
            for m in enabled:
                sc = adaptive_score(m["name"], snap)
                s = snap.get(m["name"], {})
                rows.append({
                    "name": m["name"], "provider": m.get("provider", ""),
                    "score": round(sc, 1),
                    "latencyMs": s.get("lat"),
                    "success": f"{s.get('ok',0)}/{s.get('ok',0)+s.get('fail',0)}",
                    "quality": s.get("quality", 50),
                    "pointsWeight": round(pts_w.get(m["name"], 0.5), 2),
                    "quotaWeight": round(remain_w.get(m["name"], 0.5), 2),
                })
            rows.sort(key=lambda r: -r["score"])
            return self._send_json(200, {"strategy": CONFIG.get("route_mode"),
                                          "weights": "速度0.35 成功0.25 质量0.15 积分0.15 额度0.10",
                                          "models": rows})
        if self.path == "/catalog":
            """TryModels 式: 免费模型目录(本池 + 公共免费源快照)"""
            mine = [{"id": m["name"], "provider": m.get("provider"), "free": bool(m.get("free")),
                      "status": "healthy" if not is_cooled_down(m["name"]) else "cooldown"}
                     for m in CONFIG["models"] if m.get("enabled", True)]
            public = [
                {"id": "glm-4-flash", "provider": "zhipu", "note": "智谱免费高速", "signup": "open.bigmodel.cn"},
                {"id": "qwen-turbo", "provider": "dashscope", "note": "阿里免费额度", "signup": "dashscope.aliyuncs.com"},
                {"id": "deepseek-chat", "provider": "deepseek", "note": "注册赠额度", "signup": "platform.deepseek.com"},
                {"id": "kimi-k2", "provider": "moonshot", "note": "月之暗面免费档", "signup": "platform.moonshot.cn"},
                {"id": "hunyuan-lite", "provider": "tencent", "note": "腾讯混元免费", "signup": "cloud.tencent.com"},
                {"id": "grok-mini-free", "provider": "xai", "note": "xAI 免费档", "signup": "console.x.ai"},
            ]
            return self._send_json(200, {"mine": mine, "public": public,
                                          "note": "public 为免费模型目录快照, 注册后加进 config.json 即可入池"})
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
            # 转发到聚宝盆统一签到
            try:
                data = json.dumps({}).encode()
                req = urllib.request.Request(f"{JUBAO_URL}/signin", data=data,
                    headers={"Content-Type": "application/json"}, method="POST")
                j = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
                return self._send_json(200, j)
            except Exception as e:
                return self._send_json(502, {"message": f"聚宝盆离线: {e}"})
        if self.path in ("/v1/embeddings", "/embeddings"):
            if not self._auth_ok():
                return self._send_json(401, {"error": {"message": "invalid api key"}})
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                return self._send_json(400, {"error": {"message": f"bad request: {e}"}})
            emb_models = [m for m in CONFIG["models"]
                          if m.get("embeddings_base_url") and m.get("enabled", True)]
            if not emb_models:
                return self._send_json(501, {"error": {"message": "未配置 embeddings 模型(在 config.json 加 embeddings_base_url)"}})
            last_err = None
            for m in emb_models:
                try:
                    payload = {"model": m.get("embeddings_model", "embedding-3"),
                               "input": body.get("input", "")}
                    data = json.dumps(payload).encode()
                    req = urllib.request.Request(m["embeddings_base_url"], data=data,
                        headers={"Content-Type": "application/json",
                                 "Authorization": f"Bearer {m['api_key']}"}, method="POST")
                    raw = urllib.request.urlopen(req, timeout=CONFIG.get("timeout_seconds", 60)).read()
                    return self._send_json(200, json.loads(raw.decode()))
                except Exception as e:
                    last_err = e
            return self._send_json(502, {"error": {"message": f"embeddings 全部失败: {last_err}"}})
        if self.path in ("/v1/chat/completions", "/chat/completions"):
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
                model_name, resp = try_generate(body, want_stream, session_id=sid,
                                                 owner=is_owner(self.headers))
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

        # Cherry Studio 式一问多答: 并行发给N个模型对比
        # 动态切换路由策略(驾驶舱用, 持久化)
        if self.path in ("/pool/strategy", "/strategy"):
            if not self._auth_ok():
                return self._send_json(401, {"error": {"message": "invalid api key"}})
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                return self._send_json(400, {"error": {"message": f"bad request: {e}"}})
            mode = body.get("mode")
            valid = {"adaptive", "priority", "round_robin", "least_used", "free_first", "speed_first", "智能", "auto"}
            if mode not in valid:
                return self._send_json(400, {"error": {"message": f"mode 必须是 {sorted(valid)}"}})
            with STATE_LOCK:
                CONFIG["route_mode"] = mode
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(CONFIG, f, ensure_ascii=False, indent=2)
            log.info(f"路由策略切换 → {mode}")
            return self._send_json(200, {"ok": True, "strategy": mode, "message": f"策略已切换为 {mode} 并持久化"})
        # 目录一键入池: 把公共免费目录的模型写进 config.json
        if self.path in ("/catalog/add", "/pool/add"):
            if not self._auth_ok():
                return self._send_json(401, {"error": {"message": "invalid api key"}})
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                return self._send_json(400, {"error": {"message": f"bad request: {e}"}})
            required = ("name", "base_url")
            if not all(body.get(k) for k in required):
                return self._send_json(400, {"error": {"message": f"必填: {required}"}})
            with STATE_LOCK:
                if any(m["name"] == body["name"] for m in CONFIG["models"]):
                    return self._send_json(409, {"error": {"message": f"模型 {body['name']} 已在池中"}})
                CONFIG["models"].append({
                    "name": body["name"],
                    "provider": body.get("provider", "custom"),
                    "base_url": body["base_url"],
                    "api_key": body.get("api_key", ""),
                    "model": body.get("model", body["name"]),
                    "priority": body.get("priority", 99),
                    "free": body.get("free", False),
                    "enabled": True,
                })
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(CONFIG, f, ensure_ascii=False, indent=2)
            log.info(f"入池: {body['name']} ({body.get('provider')})")
            return self._send_json(200, {"ok": True, "message": f"{body['name']} 已入池并保存到 config.json"})
        if self.path in ("/v1/compare", "/compare"):
            if not self._auth_ok():
                return self._send_json(401, {"error": {"message": "invalid api key"}})
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                return self._send_json(400, {"error": {"message": f"bad request: {e}"}})
            targets = [m for m in CONFIG["models"] if m.get("enabled", True)][:4]
            results, lock = [], threading.Lock()
            def _ask(m):
                try:
                    payload = dict(body); payload["model"] = m["model"]; payload["stream"] = False
                    data = json.dumps(payload).encode()
                    req = urllib.request.Request(m["base_url"], data=data,
                        headers={"Content-Type": "application/json",
                                 "Authorization": f"Bearer {m['api_key']}"}, method="POST")
                    t0 = time.time()
                    raw = urllib.request.urlopen(req, timeout=CONFIG.get("timeout_seconds", 60)).read()
                    up = json.loads(raw.decode())
                    text = (up.get("choices") or [{}])[0].get("message", {}).get("content", "")
                    lat = int((time.time()-t0)*1000)
                    # 质量分: 内容长度(信息量) + 速度加权 → 0-100, 反哺自适应调度
                    qlen = min(100, len(text) // 20)
                    qspeed = max(0, 100 - lat // 100)
                    q = int(0.6 * qlen + 0.4 * qspeed)
                    score_update(m["name"], "quality", q)
                    with lock:
                        results.append({"model": m["name"], "ok": True, "latencyMs": lat,
                                         "qualityScore": q, "content": text, "usage": up.get("usage")})
                except Exception as e:
                    with lock:
                        results.append({"model": m["name"], "ok": False, "error": str(e)[:120]})
            threads = [threading.Thread(target=_ask, args=(m,), daemon=True) for m in targets]
            for t in threads: t.start()
            for t in threads: t.join(timeout=CONFIG.get("timeout_seconds", 60) + 2)
            return self._send_json(200, {"compare": results, "asked": len(targets),
                                          "note": "同一问题并行发给所有启用模型, 一问多答横向对比"})

        # embeddings: 取第一个启用 embeddings 的模型
        if self.path in ("/v1/embeddings", "/embeddings"):
            if not self._auth_ok():
                return self._send_json(401, {"error": {"message": "invalid api key"}})
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                return self._send_json(400, {"error": {"message": f"bad request: {e}"}})
            emb_models = [m for m in CONFIG["models"]
                          if m.get("embeddings_base_url") and m.get("enabled", True)]
            if not emb_models:
                return self._send_json(501, {"error": {"message": "未配置 embeddings 模型(在 config.json 加 embeddings_base_url)"}})
            last_err = None
            for m in emb_models:
                try:
                    payload = {"model": m.get("embeddings_model", "embedding-3"),
                               "input": body.get("input", "")}
                    data = json.dumps(payload).encode()
                    req = urllib.request.Request(m["embeddings_base_url"], data=data,
                        headers={"Content-Type": "application/json",
                                 "Authorization": f"Bearer {m['api_key']}"}, method="POST")
                    raw = urllib.request.urlopen(req, timeout=CONFIG.get("timeout_seconds", 60)).read()
                    return self._send_json(200, json.loads(raw.decode()))
                except Exception as e:
                    last_err = e
            return self._send_json(502, {"error": {"message": f"embeddings 全部失败: {last_err}"}})

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
