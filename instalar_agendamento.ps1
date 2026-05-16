# ============================================================
#  instalar_agendamento.ps1 — CONTALEV
#  Registra o pipeline diário no Agendador de Tarefas do Windows
#
#  Como executar:
#  Clique direito no arquivo → "Executar como Administrador"
# ============================================================

$NomeTarefa    = "CONTALEV Pipeline Diario"
$PastaContalev = "C:\Rede\CONTALEV"
$ArquivoBat    = "$PastaContalev\pipeline_mensal.bat"
$Hora          = "22:00"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  CONTALEV — Instalador de Agendamento" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Verifica se está rodando como Administrador
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERRO: Execute como Administrador." -ForegroundColor Red
    Write-Host "Clique direito no arquivo .ps1 -> 'Executar como administrador'" -ForegroundColor Yellow
    Read-Host "Pressione Enter para sair"
    exit 1
}

if (-not (Test-Path $ArquivoBat)) {
    Write-Host "ERRO: Arquivo nao encontrado: $ArquivoBat" -ForegroundColor Red
    Read-Host "Pressione Enter para sair"
    exit 1
}

# Remove tarefa antiga se existir
if (Get-ScheduledTask -TaskName $NomeTarefa -ErrorAction SilentlyContinue) {
    Write-Host "Removendo tarefa antiga..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $NomeTarefa -Confirm:$false
}

# Gatilho: todo dia às 22:00
$gatilho = New-ScheduledTaskTrigger -Daily -At "22:00"

# Ação
$acao = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$ArquivoBat`"" `
    -WorkingDirectory $PastaContalev

# Configurações
$config = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

# Registra
Register-ScheduledTask `
    -TaskName $NomeTarefa `
    -Trigger $gatilho `
    -Action $acao `
    -Settings $config `
    -RunLevel Highest `
    -Description "CONTALEV: pipeline diario as 22h." `
    -Force | Out-Null

$tarefa = Get-ScheduledTask -TaskName $NomeTarefa -ErrorAction SilentlyContinue

if ($tarefa) {
    Write-Host ""
    Write-Host "SUCESSO! Tarefa registrada." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Nome:    $NomeTarefa"
    Write-Host "  Horario: Todo dia as $Hora"
    Write-Host "  Arquivo: $ArquivoBat"
    Write-Host ""
    Write-Host "Proxima execucao:" -ForegroundColor Cyan
    (Get-ScheduledTaskInfo -TaskName $NomeTarefa).NextRunTime
    Write-Host ""
    Write-Host "LEMBRE-SE: Para ativar o envio WhatsApp, edite pipeline_mensal.bat" -ForegroundColor Yellow
    Write-Host "e troque:  set ENVIAR_WHATSAPP=NAO" -ForegroundColor Yellow
    Write-Host "por:       set ENVIAR_WHATSAPP=SIM" -ForegroundColor Yellow
    Write-Host ""

    $testar = Read-Host "Deseja executar AGORA para testar? (s/n)"
    if ($testar -eq "s" -or $testar -eq "S") {
        Start-ScheduledTask -TaskName $NomeTarefa
        Write-Host "Pipeline iniciado! Log em: $PastaContalev\logs\" -ForegroundColor Green
    }
} else {
    Write-Host "ERRO ao registrar tarefa." -ForegroundColor Red
}

Write-Host ""
Read-Host "Pressione Enter para sair"
