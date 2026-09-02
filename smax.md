#获取token代码

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$baseUrl = "https://serviceprod.capitaland.com.cn"
$tenantId = "820189321"
$login = "inc.integration"

$securePassword = Read-Host "请输入SMAX密码" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)

$url = "$baseUrl/auth/authentication-endpoint/authenticate/token?TENANTID=$tenantId"

$payload = @{
  login = $login
  password = $password
} | ConvertTo-Json -Compress

try {
  $response = Invoke-WebRequest `
    -Method Post `
    -Uri $url `
    -ContentType "application/json" `
    -Body $payload

  "HTTP状态码：$($response.StatusCode)"
  "返回内容："
  $response.Content

  if ($response.Content -is [string] -and $response.Content.Split(".").Count -eq 3) {
    "Token获取成功。token长度：$($response.Content.Length)"
  }
} catch {
  "请求失败：$($_.Exception.Message)"

  if ($_.Exception.Response) {
    "HTTP状态码：$([int]$_.Exception.Response.StatusCode)"
    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    "服务端返回内容："
    $reader.ReadToEnd()
  }
}


获取成功后，参考


