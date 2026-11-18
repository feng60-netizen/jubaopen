# 聚宝盆 JubaoPen 🪙

> 开源 · 本地优先 · 一台手机跑起来的 AI 账号资产管家

聚宝盆是一个**纯本地**的开源工具集，帮你把分散在各平台的 AI 账号免费额度集中管理：

- 🪙 **聚宝盆服务**（`jubaopen.py`）— AI 账号保险箱：存放账号、每日签到领额度、用量记账、按天自动重置
- 🔀 **FreePool 网关**（`freepool.py`）— OpenAI 协议兼容的负载均衡网关：自动降级、会话粘性、高延迟自动切换
- 📱 **聚宝盆插件**（`聚宝盆插件/`）— dsh-go 手机面板：一眼看到各账号剩余额度，一键签到

## 特性

| 能力 | 说明 |
|---|---|
| 快捷加账号 | 一行命令或一个 HTTP 请求加入新账号 |
| 每日签到 | 一键全部签到领额度，防重复（当日幂等） |
| 额度管家 | 每账号今日已用/剩余，跨天自动重置 |
| 自动记账 | FreePool 每次成功调用自动向聚宝盆记一笔 |
| 自动降级 | 429/5xx/超时立刻切下一个模型，任务不中断 |
| 会话粘性 | 同会话固定模型防人设漂移；模型挂/慢自动换 |
| 高延迟加速 | 并行测延迟，超阈值秒切最快模型 |
| Key 安全 | 任何展示接口均打码（`sk-abc****z456`） |
| 零依赖 | 纯 Python 标准库，Termux 手机可直接跑 |

## 快速开始

```bash
# 聚宝盆服务（默认端口 6210）
python3 jubaopen.py serve

# 快捷加入账号
python3 jubaopen.py add 智谱1号 zhipu sk-你的KEY 500
python3 jubaopen.py list

# FreePool 网关（默认端口 6120；先在 config.json 填真实上游 Key）
python3 freepool.py

# 客户端终身只填这一组
# BaseURL: http://127.0.0.1:6120/v1   Key: sk-freepool-fixed-2026   模型: free-pool
```

## HTTP API

聚宝盆（:6210）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/accounts` | 账号列表（Key 打码） |
| POST | `/accounts` | 添加账号 `{name, platform, api_key, daily_quota}` |
| POST | `/accounts/delete` | 删除账号 `{name}` |
| GET | `/quota` | 今日总览 + 已签/未签列表 |
| POST | `/quota/use` | 记消耗 `{name, amount}` |
| POST | `/quota/reset` | 重置 `{name?}` |
| POST | `/signin` | 一键签到 `{name?, reward?}`，当日幂等 |

FreePool（:6120）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/models` | 模型池与健康状态 |
| POST | `/v1/chat/completions` | OpenAI 兼容，支持流式 |
| GET | `/pool/status` | 各模型额度/延迟/繁忙度 |
| GET | `/health` | 健康检查 |

## 配置（config.json）

```jsonc
{
  "route_mode": "priority",        // priority | round_robin
  "session_sticky": true,          // 会话粘性
  "latency_switch_ms": 1200,       // 粘性模型延迟超过此值自动换最快的
  "cooldown_seconds": 30,          // 失败冷却
  "max_retries": 3,
  "jubaopen_url": "http://127.0.0.1:6210",  // 聚宝盆地址, 自动记账
  "models": [ /* {name, provider, base_url, api_key, model, priority, enabled} */ ]
}
```

## 目录结构

```
├── jubaopen.py        # 聚宝盆服务（账号+签到+额度）
├── freepool.py        # FreePool 网关（路由+粘性+降级+加速）
├── config.json        # 网关配置
└── 聚宝盆插件/         # dsh-go 手机面板插件源码
    ├── package.json
    ├── cordis.patch.yml
    └── lib/index.js
```

## 设计原则

1. **本地优先** — 所有数据（含 API Key）只存本机 `accounts.json`，不外传、不依赖云端
2. **不断连** — 任何上游故障、聚宝盆离线，主流程都不中断
3. **零改动接入** — 客户端一次配置永久使用，模型池增删无感

## License

MIT
