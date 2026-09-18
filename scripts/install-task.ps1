[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config.toml'),
    [string]$TaskName = 'SwimmingTicketAssistant',
    [switch]$TestOnly
)
$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonExecutable = (Resolve-Path -LiteralPath $PythonPath).Path
$configurationFile = (Resolve-Path -LiteralPath $ConfigPath).Path
$entryPoint = Join-Path $projectPath 'auto_grab.py'
if ($pythonExecutable.Contains('"') -or $configurationFile.Contains('"')) {
    throw '路径不能包含双引号'
}
& $pythonExecutable $entryPoint --config $configurationFile --doctor
if ($LASTEXITCODE -ne 0) { throw '环境检查未通过，未安装定时任务。请先补齐配置。' }
$arguments = '-u "{0}" --config "{1}" --scheduled' -f $entryPoint, $configurationFile
if ($TestOnly) { $arguments += ' --test' }
$action = New-ScheduledTaskAction -Execute $pythonExecutable -Argument $arguments -WorkingDirectory $projectPath -ErrorAction Stop
$trigger = New-ScheduledTaskTrigger -Daily -At '23:58' -ErrorAction Stop
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited -ErrorAction Stop
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 8) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ErrorAction Stop
# 不启用 StartWhenAvailable，避免次日补跑后再等待一个零点。
# 使用交互式登录令牌，不保存密码；桌面必须保持解锁。
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "任务 $TaskName 已存在；请先检查或卸载它，避免覆盖其他任务。"
}
if ($PSCmdlet.ShouldProcess($TaskName, '创建每日 23:58 的交互式计划任务')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "游泳馆自动预约；配置=$configurationFile；测试模式=$TestOnly" -ErrorAction Stop | Out-Null
    Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
}
