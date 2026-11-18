#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聚宝盆 (JubaoPen) — AI 账号保险箱 + 每日额度管家
================================================
- 存放各种 AI 账号（平台、Key、账号名、每日额度）
- 快捷加入账号：命令行 / HTTP 接口 两种方式
- 每日额度：记录每个账号当日已用/剩余，自动按天重置
- 数据本地保存 accounts.json，不外传

启动:  python3 jubaopen.py          (默认端口 6210)
接口:
  GET  /accounts              列出全部账号(额度打码可选)
  POST /accounts              添加账号  {"name","platform","api_key","daily_quota"}
  POST /accounts/delete       {"name": "..."}
  GET  /quota                 今日额度总览
  POST /quota/use             记一次消耗 {"name","amount"}
  POST /quota/reset           手动重置某账号 {"name"}
  GET  /health
"""
import json, os, sys, time, threading, http.server, socketserver, logging, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "accounts.json")
PORT = 6210

logging.basicConfig(level=logging.INFO, format="%(asctime)s [聚宝盆] %(message)s")
log = logging.getLogger("jubaopen")

DEFAULT_DB = {"accounts": [], "usage": {}}   # usage: {name: {"date":"2026-11-19","used":3}}

LOCK = threading.Lock()

def today():
    return datetime.date.today().isoformat()

def load_db():
    if os.path.exists(DB):
        try:
            return json.load(open(DB, encoding="utf-8"))
        except Exception as e:
            log.error(f"数据库损坏,重建: {e}")
    return json.loads(json.dumps(DEFAULT_DB))

def save_db(db):
    tmp = DB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB)

def mask_key(k):
    if not k: return ""
    return k[:6] + "****" + k[-4:] if len(k) > 12 else "****"

def get_usage(db, name):
    u = db["usage"].get(name)
    if not u or u.get("date") != today():
        return {"date": today(), "used": 0}
    return u

def acct_view(a, db, show_key=False):
    u = get_usage(db, a["name"])
    quota = a.get("daily_quota", 0)
    used = u["used"]
    remain = max(0, quota - used) if quota else None
    v = {
        "name": a["name"],
        "platform": a.get("platform", ""),
        "key": mask_key(a.get("api_key","")) if not show_key else a.get("api_key",""),
        "dailyQuota": quota,
        "usedToday": used,
        "remainToday": remain,
        "percent": round(used/quota*100) if quota else None,
        "addedAt": a.get("added_at",""),
    }
    return v

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def _json(self, code, obj):
        d = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(d)))
        self.end_headers(); self.wfile.write(d)
    def _body(self):
        n = int(self.headers.get("Content-Length",0))
        return json.loads(self.rfile.read(n).decode()) if n else {}

    def do_GET(self):
        with LOCK:
            db = load_db()
        if self.path == "/health":
            return self._json(200, {"status":"ok","service":"聚宝盆","accounts":len(db["accounts"])})
        if self.path == "/accounts":
            show = "show_key" in self.path
            return self._json(200, {"accounts":[acct_view(a,db,show) for a in db["accounts"]]})
        if self.path == "/quota":
            items = [acct_view(a,db) for a in db["accounts"]]
            total = sum(i["dailyQuota"] or 0 for i in items)
            used = sum(i["usedToday"] for i in items)
            return self._json(200, {"date":today(),"totalQuota":total,"totalUsed":used,
                                     "totalRemain":total-used,"accounts":items,
                                     "signedToday": [k for k,v in db.get("signin",{}).items() if v.get("date")==today()],
                                     "unsignedToday": [i["name"] for i in items if db.get("signin",{}).get(i["name"],{}).get("date")!=today()]})
        return self._json(404, {"error":"not found"})

    def do_POST(self):
        body = self._body()
        with LOCK:
            db = load_db()
        if self.path == "/accounts":
            name = (body.get("name") or "").strip()
            if not name: return self._json(400, {"error":"name 必填"})
            if any(a["name"]==name for a in db["accounts"]):
                return self._json(409, {"error":f"账号 {name} 已存在"})
            db["accounts"].append({
                "name": name,
                "platform": body.get("platform",""),
                "api_key": body.get("api_key",""),
                "daily_quota": int(body.get("daily_quota",0) or 0),
                "added_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
            save_db(db)
            log.info(f"新增账号 {name} ({body.get('platform','')})")
            return self._json(200, {"ok":True,"message":f"账号 {name} 已加入聚宝盆"})
        if self.path == "/accounts/delete":
            name = body.get("name","")
            before = len(db["accounts"])
            db["accounts"] = [a for a in db["accounts"] if a["name"]!=name]
            if len(db["accounts"])==before:
                return self._json(404, {"error":f"账号 {name} 不存在"})
            db["usage"].pop(name, None)
            save_db(db)
            log.info(f"删除账号 {name}")
            return self._json(200, {"ok":True,"message":f"账号 {name} 已移除"})
        if self.path == "/quota/use":
            name = body.get("name","")
            a = next((a for a in db["accounts"] if a["name"]==name), None)
            if not a: return self._json(404, {"error":f"账号 {name} 不存在"})
            amount = int(body.get("amount",1) or 1)
            u = get_usage(db, name)
            u["used"] += amount
            db["usage"][name] = u
            save_db(db)
            remain = max(0, a.get("daily_quota",0)-u["used"])
            return self._json(200, {"ok":True,"used":u["used"],"remain":remain,
                                     "message":f"{name} 今日已用 {u['used']}, 剩余 {remain}"})
        if self.path == "/quota/reset":
            name = body.get("name","")
            if name:
                db["usage"][name] = {"date":today(),"used":0}
                save_db(db)
                return self._json(200, {"ok":True,"message":f"{name} 已重置"})
            db["usage"] = {}
            save_db(db)
            return self._json(200, {"ok":True,"message":"全部账号已重置"})
        if self.path in ("/signin", "/signin/"):
            name = (body.get("name") or "").strip()
            reward = int(body.get("reward", 50) or 50)
            with LOCK:
                db = load_db()
            targets = [a for a in db["accounts"] if not name or a["name"]==name]
            if name and not targets:
                return self._json(404, {"error":f"账号 {name} 不存在"})
            results, gained = [], 0
            for a in targets:
                sg = db.setdefault("signin", {})
                rec = sg.get(a["name"], {})
                if rec.get("date") == today():
                    results.append({"name":a["name"],"ok":False,"message":"今日已签到","reward":rec.get("reward",0)})
                    continue
                bonus = reward + a.get("daily_quota", 0)  # 签到后当日额度刷新+奖励
                a["daily_quota"] = a.get("daily_quota", 0) + reward
                sg[a["name"]] = {"date": today(), "reward": reward, "streak": rec.get("streak",0)+1}
                gained += reward
                results.append({"name":a["name"],"ok":True,"message":f"签到成功 +{reward}","reward":reward,"streak":sg[a["name"]]["streak"]})
            save_db(db)
            ok_n = sum(1 for r in results if r["ok"])
            return self._json(200, {"ok":True,"signedIn":ok_n,"skipped":len(results)-ok_n,
                                     "gained":gained,"results":results,
                                     "message":f"签到完成: {ok_n} 成功 / {len(results)-ok_n} 已签过, 共领 {gained} 额度"})
        return self._json(404, {"error":"not found"})

class TS(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True

def cli():
    """命令行快捷添加: python3 jubaopen.py add 名称 平台 Key 每日额度"""
    if len(sys.argv) >= 2 and sys.argv[1] == "add":
        _,_,name,platform,key,quota = sys.argv[:6]
        db = load_db()
        if any(a["name"]==name for a in db["accounts"]):
            print(f"账号 {name} 已存在"); return
        db["accounts"].append({"name":name,"platform":platform,"api_key":key,
            "daily_quota":int(quota),"added_at":datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
        save_db(db)
        print(f"✅ 已加入聚宝盆: {name} ({platform}) 每日额度 {quota}")
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        db = load_db()
        if not db["accounts"]: print("聚宝盆是空的"); return
        for a in db["accounts"]:
            u = get_usage(db, a["name"])
            q = a.get("daily_quota",0)
            r = max(0,q-u["used"]) if q else "∞"
            print(f"  {a['name']:20} {a.get('platform',''):12} 今日 {u['used']}/{q or '∞'} 剩余 {r}  Key {mask_key(a.get('api_key',''))}")
        return
    if len(sys.argv) >= 2 and sys.argv[1] in ("serve",""):
        serve()

def serve():
    log.info("="*44)
    log.info("聚宝盆启动 — AI账号保险箱")
    log.info(f"  地址 : http://127.0.0.1:{PORT}")
    log.info(f"  数据 : {DB}")
    log.info("="*44)
    TS(("127.0.0.1", PORT), Handler).serve_forever()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] not in ("serve",):
        cli()
    else:
        serve()
