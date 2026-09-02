# SMAX Token 低风险探针

> 用途：在 `smax.md` 获取到 token 之后，验证该 token 能否用于工单（EMS bulk）API。
> 修正点：token 必须作为 **Cookie**（`SMAX_AUTH_TOKEN=<token>`）发送，不能当作自定义请求头，否则 401。

## 前置

先执行 `smax.md` 里的取 token 代码，得到 `$response`（响应体本身就是 JWT）。本脚本复用同一个会话里的 `$response`。

## 探针脚本

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# $response 来自 smax.md 获取 token 那一步；token 就是响应体本身
$token = $response.Content.Trim()

# 调试用：确认 token 干净（长度>0 且三段）
Write-Host "token len=$($token.Length) parts=$($token.Split('.').Count)"

# ★关键：用 WebSession 把 token 作为 Cookie 发出去（等价于 Cookie: SMAX_AUTH_TOKEN=<token>）
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$session.Cookies.Add(
  (New-Object System.Net.Cookie("SMAX_AUTH_TOKEN", $token, "/", "serviceprod.capitaland.com.cn"))
)

$probeBody = @{
  entities  = @()
  operation = "UPDATE"
} | ConvertTo-Json -Depth 10 -Compress

$result = Invoke-WebRequest `
  -Method Post `
  -Uri "https://serviceprod.capitaland.com.cn/rest/820189321/ems/bulk" `
  -WebSession $session `
  -Headers @{ 'User-Agent' = 'AutomationScript/1.0' } `
  -ContentType 'application/json; charset=utf-8' `
  -Body $probeBody

$result.StatusCode
$result.Content
```

## 预期结果

- 返回 `200` 且 `meta.completion_status` 为 `OK` → token 对工单 API 有效。
- 返回非 401 的业务错误（如 400）→ 鉴权已通过，token 仍然有效，只是请求体本身被业务校验拒绝（对探针目的而言也算成功）。
- 仍返回 `401` → 见下方排查。

## 更稳的只读探针（零副作用，可选）

用 GET 拉一条 Incident，不写任何数据：

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$token = $response.Content.Trim()

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$session.Cookies.Add(
  (New-Object System.Net.Cookie("SMAX_AUTH_TOKEN", $token, "/", "serviceprod.capitaland.com.cn"))
)

$result = Invoke-WebRequest `
  -Method Get `
  -Uri "https://serviceprod.capitaland.com.cn/rest/820189321/ems/Incident?fields=Id&limit=1" `
  -WebSession $session `
  -Headers @{ 'User-Agent' = 'AutomationScript/1.0' }

$result.StatusCode
$result.Content
```

能 200 拿到 Id 列表即说明 token 可用。

## 仍然 401 的排查顺序

1. token 过期——重跑 `smax.md` 拿新 token 后立刻测。
2. `$response.Content` 是否真的是 token——看上面的调试输出，长度>0 且三段才算干净。
3. 登录账号 `inc.integration` 是否有该租户 REST API 的访问权限——找同事确认服务账号授权。
4. 代理把 Cookie 头剥掉——`netsh winhttp show proxy` 查代理；如有，给 `Invoke-WebRequest` 加 `-Proxy`，或把 `serviceprod.capitaland.com.cn` 放行。

## 关键差异对照（为何原来 401）

| | 原探针（401） | 修正后（本文件） |
|---|---|---|
| token 传递 | 自定义请求头 `SMAX_AUTH_TOKEN` | Cookie `SMAX_AUTH_TOKEN=<token>`（经 WebSession） |
| 端点 | `/rest/820189321/ces` | `/rest/820189321/ems/bulk` |
| User-Agent | 无 | `AutomationScript/1.0` |
| Content-Type | `application/json` | `application/json; charset=utf-8` |
