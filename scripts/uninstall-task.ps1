[CmdletBinding(SupportsShouldProcess)]
param([string]$TaskName = 'SwimmingTicketAssistant')
$ErrorActionPreference = 'Stop'
if ($PSCmdlet.ShouldProcess($TaskName, '删除计划任务')) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
