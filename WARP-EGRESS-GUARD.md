# WARP 出口健康检查与自动换口（本机运维补丁）

> 状态：**本机已启用**（2026-07-25）  
> 目的：记录 `warp-auto-rotate` 相关改动与文件清单，便于后续维护或**完整移除**时不遗漏。  
> 注意：这是相对上游 `vless-all-in-one` 的**本机运维层补丁**，不完全等于脚本内嵌的 `install_warp_auto_rotate()` 默认实现。

---

## 1. 背景与作用

本机使用 Cloudflare WARP 官方客户端（`warp-svc` + `warp-cli`）提供本机 SOCKS5 出口：

| 项 | 值 |
|---|---|
| 模式 | `WarpProxy`（proxy mode） |
| 监听 | `127.0.0.1:40000` |
| 用途 | Xray / sing-box 将 `x.ai` / `grok.com` / Twitter(X) 等域名分流到该 SOCKS |

历史上出现过：

1. `warp-svc` 进程卡在 **D 状态**（磁盘睡眠），导致 SOCKS 无响应；
2. 仅依赖 soft reconnect 无法恢复；
3. 免费 WARP 出口 IP 被**对端站点** Cloudflare 风控（如 `x.ai` 返回 403）；
4. 旧版 timer 曾被 disable，健康检查长期不跑。

因此部署了增强版 **`warp-auto-rotate`**（名称沿用上游，实际行为 = 健康检查 + 故障恢复 + 条件性换注册/出口）。

---

## 2. 与上游脚本的关系

上游函数（`vless-server.sh`）：

| 函数 | 作用 |
|---|---|
| `install_warp_auto_rotate` | 写入旧版健康检查脚本 + systemd unit/timer |
| `uninstall_warp_auto_rotate` | 关闭 timer 并删除脚本/unit |
| `warp_auto_rotate_status` | 返回 enabled/disabled |

**本机现状：**

- 运行中的 `/usr/local/bin/warp-auto-rotate` **已比仓库内嵌 heredoc 更新**（2026-07-25 手工部署）。
- 若以后在菜单里重新执行「安装 WARP 健康检查」，**可能用旧版覆盖本机增强版**。
- 移除时不要只删脚本：timer、service、状态文件、日志、备份文件都要处理。

---

## 3. 本机文件与路径清单（移除必查）

### 3.1 主文件（当前生效）

| 路径 | 说明 |
|---|---|
| `/usr/local/bin/warp-auto-rotate` | 健康检查 + 恢复 + 换口主脚本 |
| `/etc/systemd/system/warp-auto-rotate.service` | oneshot 服务 |
| `/etc/systemd/system/warp-auto-rotate.timer` | 约每 10 分钟触发 |
| `/var/log/warp-egress-guard.log` | 运行日志（会轮转截断） |
| `/var/run/warp-egress-guard.state` 或 `/run/warp-egress-guard.state` | 失败计数 / 冷却时间戳 |
| `/var/run/warp-egress-guard.lock` 或 `/run/warp-egress-guard.lock` | flock 防并发 |

### 3.2 本机备份（曾改动前留下，可一并清理）

| 路径 |
|---|
| `/usr/local/bin/warp-auto-rotate.bak.20260718-235755` |
| `/usr/local/bin/warp-auto-rotate.bak.20260725-072400` |
| `/etc/systemd/system/warp-auto-rotate.service.bak.20260718-235755` |
| `/etc/systemd/system/warp-auto-rotate.service.bak.20260725-072400` |
| `/etc/systemd/system/warp-auto-rotate.timer.bak.20260718-235755` |
| `/etc/systemd/system/warp-auto-rotate.timer.bak.20260725-072400` |

### 3.3 相关但不属于 auto-rotate 本体（移除 auto-rotate 时**默认保留**）

| 路径 / 单元 | 说明 | 移除 auto-rotate 时 |
|---|---|---|
| `warp-svc.service` | Cloudflare WARP 官方服务 | **保留**（除非卸整个 WARP） |
| `/etc/systemd/system/warp-svc.service.d/memory-guard.conf` | WARP 内存上限 | **保留** |
| `/var/lib/cloudflare-warp/` | WARP 注册/配置目录 | **保留** |
| `/etc/vless-reality/config.json` | Xray 路由里的 `warp` outbound | **保留**（分流规则） |
| `/etc/vless-reality/singbox.json` | sing-box 路由里的 warp socks | **保留** |
| `/etc/vless-reality/warp.json` | 脚本侧 WARP 材料（若存在） | **保留** |
| `/etc/vless-reality/watchdog.sh` | 仅看 xray/sing-box，**不监控 WARP** | 无关 |
| `/var/log/warp-socks-bridge.log` | 历史空日志，可选删 | 可选 |

---

## 4. 当前行为说明

### 4.1 检查项

1. `warp-svc` 是否 active；进程是否 D/Z/missing  
2. SOCKS `127.0.0.1:40000` 是否监听  
3. 经 SOCKS 访问 `https://1.1.1.1/cdn-cgi/trace`：要求 `warp=on|plus`，国家默认 `US`  
4. 目标连通性（返回 `000` 视为硬失败）：
   - `https://x.com/`
   - `https://twitter.com/`
   - `https://grok.com/`
   - `https://x.ai/`

### 4.2 恢复阶梯

| 阶梯 | 动作 |
|---|---|
| 0 | 单次失败只记 state，等下一轮 timer |
| 1 soft | `disconnect` → `connect`；不够则 `systemctl restart warp-svc` 再连 |
| 2 hard | `registration delete` → `registration new` → 恢复 proxy 模式/端口 → connect（**换出口身份**） |

### 4.3 x.ai 403 策略

- `x.ai` 返回 **403/503** 时，**不是本机 WARP 故障**，而是**对端 Cloudflare 对 free WARP 出口段的拦截**。
- 环境变量 `WARP_ROTATE_ON_XAI_BLOCK=1`（service 默认开启）时，会在冷却结束后尝试 hard re-register 换出口。
- 实测：换注册/换 IP 后 `x.ai` 仍可能 403（整段 free 出口被拦概率高）。

### 4.4 环境变量（service 中可改）

| 变量 | 默认 | 含义 |
|---|---|---|
| `WARP_REQUIRED_COUNTRY` | `US` | 要求 egress 国家；空=不限制 |
| `WARP_ROTATE_ON_XAI_BLOCK` | `1` | x.ai 403/503 时是否换注册 |
| `WARP_MIN_RECONNECT_INTERVAL` | `900` | soft reconnect 最小间隔（秒） |
| `WARP_MIN_REREG_INTERVAL` | `3600` | hard re-register 最小间隔（秒） |
| `WARP_FORCE_ROTATE` | `0` | `1` 时强制换注册（受 rereg 冷却约束） |

### 4.5 手动命令

```bash
# 看 timer
systemctl status warp-auto-rotate.timer --no-pager
systemctl list-timers warp-auto-rotate.timer --no-pager

# 手动跑一轮健康检查
/usr/local/bin/warp-auto-rotate

# 强制换出口（跳过冷却）
WARP_FORCE_ROTATE=1 WARP_MIN_REREG_INTERVAL=0 /usr/local/bin/warp-auto-rotate

# 看日志 / 状态
tail -n 50 /var/log/warp-egress-guard.log
cat /run/warp-egress-guard.state 2>/dev/null || cat /var/run/warp-egress-guard.state

# 当前 egress
curl -4 -fsS --socks5-hostname 127.0.0.1:40000 https://1.1.1.1/cdn-cgi/trace
```

### 4.6 当前 systemd timer 要点

- `OnBootSec=2min`
- `OnUnitActiveSec=10min`
- `OnCalendar=*:0/10`（日历触发，避免仅 monotonic 时 Next 显示异常）
- `RandomizedDelaySec=30`
- service `TimeoutStartSec=180`

---

## 5. 完整移除清单（推荐按序执行）

> 仅移除 **auto-rotate 健康检查/换口**，**不卸载** WARP 本身与分流规则。

```bash
# 1) 停用并关闭 timer/service
systemctl disable --now warp-auto-rotate.timer 2>/dev/null || true
systemctl stop warp-auto-rotate.service 2>/dev/null || true
systemctl reset-failed warp-auto-rotate.service 2>/dev/null || true

# 2) 删除 unit 与主脚本
rm -f /etc/systemd/system/warp-auto-rotate.timer
rm -f /etc/systemd/system/warp-auto-rotate.service
rm -f /usr/local/bin/warp-auto-rotate

# 3) 删除 state / lock / 日志
rm -f /run/warp-egress-guard.state /var/run/warp-egress-guard.state
rm -f /run/warp-egress-guard.lock /var/run/warp-egress-guard.lock
rm -f /var/log/warp-egress-guard.log

# 4) 删除历史备份（可选但建议）
rm -f /usr/local/bin/warp-auto-rotate.bak.*
rm -f /etc/systemd/system/warp-auto-rotate.service.bak.*
rm -f /etc/systemd/system/warp-auto-rotate.timer.bak.*

# 5) 重载 systemd 并确认无残留
systemctl daemon-reload
systemctl list-timers --all | grep warp-auto-rotate || echo "timer gone"
ls /usr/local/bin/warp-auto-rotate* 2>/dev/null || echo "script gone"
ls /etc/systemd/system/warp-auto-rotate* 2>/dev/null || echo "units gone"
```

也可调用脚本内函数（若仍保留旧版实现）：

```bash
# 注意：旧版 uninstall 可能漏删日志与 .bak 文件，执行后仍建议按上面清单复核
# 在 vless-server.sh 交互菜单对应 WARP 健康检查关闭项，或 source 后调用：
# uninstall_warp_auto_rotate
```

### 5.1 若要连 WARP 官方客户端一起卸

不要只删 auto-rotate。应使用项目内 **卸载 WARP 官方客户端** 流程（`uninstall_warp_official`），并额外检查：

- 路由里是否仍引用 outbound `warp` / socks `127.0.0.1:40000`
- `/etc/vless-reality/config.json`、`singbox.json`
- `/etc/systemd/system/warp-svc.service.d/memory-guard.conf`
- `/var/lib/cloudflare-warp/`

---

## 6. 移除后验证

```bash
systemctl is-enabled warp-auto-rotate.timer 2>&1 || true   # 应失败/not-found
systemctl is-active warp-svc                                 # 若只卸 rotate，应仍 active
ss -lntp | grep 40000                                        # WARP 仍在则应监听
curl -4 -fsS --socks5-hostname 127.0.0.1:40000 https://1.1.1.1/cdn-cgi/trace | egrep 'ip=|loc=|warp='
```

---

## 7. 重新启用（本机增强版）

若文档中的增强版脚本仍保留备份，或从运维记录恢复：

1. 写回 `/usr/local/bin/warp-auto-rotate`（chmod 755）
2. 写回 `.service` / `.timer`
3. `systemctl daemon-reload && systemctl enable --now warp-auto-rotate.timer`
4. 手动跑一轮：`/usr/local/bin/warp-auto-rotate`
5. 查日志：`tail -n 20 /var/log/warp-egress-guard.log`

**不要盲目执行上游旧版 `install_warp_auto_rotate`**，除非已把仓库内嵌脚本同步到增强版逻辑。

---

## 8. 变更记录（本机）

| 日期 (UTC) | 内容 |
|---|---|
| 2026-07-18 | 旧备份 `*.bak.20260718-235755` |
| 2026-07-21 | 上游 v3.7.1：停止周期性强制换 IP，改为故障后重连 |
| 2026-07-25 | 诊断 WARP D 状态；重启恢复；部署增强版检查/换口；timer 重新 enable；hard re-register 换新 registration / 新出口 IP；文档化本文件 |

---

## 9. 维护提示

1. **改分流域名**时同步检查 Xray/sing-box 路由，与本脚本 `TARGET_CHECKS` 是否一致。  
2. **x.ai 长期 403** 优先视为对端策略，不要无限 hard re-register（有 `MIN_REREG_INTERVAL` 保护）。  
3. **升级/重装 vless-server 菜单 WARP 项**后，复查 `/usr/local/bin/warp-auto-rotate` 是否被旧版覆盖。  
4. 本文件是运维记忆；若确认永久移除 auto-rotate，删除本文件前先完成第 5 节清单，并在 README 更新日志中记一笔。
