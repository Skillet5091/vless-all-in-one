# AGENTS.md

本文件定义本项目（`vless-all-in-one`）的变更与验证规则，供后续维护时统一执行。

## 1. 变更流程（必须）

1. 每次改动前，先确认当前仓库状态可读、可追踪。
2. 每次完成一轮修改后，先本地提交，不直接 push。
3. 仅在用户明确确认后，才执行 `git push`。
4. 服务端脚本改动后，同步到 `/root/vless-server.sh` 再验证。

## 2. Clash/Mihomo 订阅生成规则

1. `rule-providers` 中凡是 `Loyalsoldier/*.txt` 规则源，必须显式加：
   `format: text`
2. 生成外部节点（`external_link_to_clash`）时，禁止输出空值或 `null` 字段（旧内核会崩溃/判格式错误），尤其是：
   `flow:`、`servername:`、`public-key: null`、`short-id: null`、`sni:`
3. `vless + reality` 仅在 `publicKey` 非空时输出 `reality-opts`。
4. 外部 `vless` 字段读取优先使用：
   `publicKey` / `shortId`，兼容回退 `pbk` / `sid`

## 3. Telegram 分流优先级规则

1. Telegram 规则必须放在 Google 规则之前，避免被 `RuleSet(Google)` 抢先命中。
2. 保留 Telegram 双重匹配：
   进程规则（如 `PROCESS-NAME,Telegram.exe,Telegram`）和规则集（`RULE-SET,telegram,Telegram` + `RULE-SET,telegramcidr,Telegram,no-resolve`）
3. `telegram` 规则源使用可用地址：
   `blackmatrix7/.../Telegram.yaml`

## 4. 最小验证清单

每次相关改动后至少执行：

1. `bash -n vless-server.sh`
2. 刷新订阅（脚本菜单 `4 -> 2`）
3. 检查生成的 `clash.yaml` 中关键规则是否存在（如 Telegram 规则）
4. 用 Mihomo 进行配置测试（建议至少覆盖旧版和新版内核）

## 5. 敏感信息与 Push 前检查（必须）

1. 严禁提交真实生产敏感信息：域名、私钥、证书、API Token、密码、用户凭据、真实订阅 UUID 等。
2. 文档和示例必须使用脱敏占位符（如 `example.com`、`your_domain`、`YOUR_UUID`）。
3. 每次 `git push` 前必须执行暂存区敏感信息扫描：
   `git diff --cached | rg -n "-----BEGIN|PRIVATE KEY|api[_-]?key|token|secret|password|private_key|public_key|short_id|uuid|sub_domain|sni"`
4. 每次 `git push` 前必须执行域名扫描并人工确认：
   `git diff --cached | rg -n "([a-zA-Z0-9-]+\\.)+[a-zA-Z]{2,}"`
5. 发现可疑信息时，立即停止 push，先脱敏/替换后再提交。
