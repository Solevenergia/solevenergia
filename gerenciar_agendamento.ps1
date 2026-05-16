# ============================================================
#  gerenciar_agendamento.ps1 — CONTALEV
#  Gerencia o agendamento e a opção de envio WhatsApp
# ============================================================

$NomeTarefa    = "CONTALEV Pipeline Diario"
$PastaContalev = "C:\Rede\CONTALEV"
$ArquivoBat    = "$PastaContalev\pipeline_mensal.bat"

function Ler-ConfigWhatsApp {
    if (-not (Test-Path $ArquivoBat)) { return "DESCONHECIDO" }
    $conteudo = Get-Content $ArquivoBat -Raw
    if ($conteudo -match "set ENVIAR_WHATSAPP=SIM") { return "SIM" }
    return "NAO"
}

function Salvar-ConfigWhatsApp($valor) {
    $conteudo = Get-Content $ArquivoBat -Raw
    $conteudo = $conteudo -replace "set ENVIAR_WHATSAPP=(SIM|NAO)", "set ENVIAR_WHATSAPP=$valor"
    Set-Content $ArquivoBat -Value $conteudo -NoNewline
}

function Mostrar-Status {
    Clear-Host
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  CONTALEV — Gerenciar Agendamento" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""

    # Status da tarefa
    $tarefa = Get-ScheduledTask -TaskName $NomeTarefa -ErrorAction SilentlyContinue
    if (-not $tarefa) {
        Write-Host "  Agendamento:  " -NoNewline
        Write-Host "NAO INSTALADO" -ForegroundColor Red
    } else {
        $cor = if ($tarefa.State -eq "Ready") { "Green" } elseif ($tarefa.State -eq "Disabled") { "Red" } else { "Yellow" }
        Write-Host "  Agendamento:  " -NoNewline
        Write-Host $tarefa.State -ForegroundColor $cor

        $info = Get-ScheduledTaskInfo -TaskName $NomeTarefa
        if ($info.NextRunTime.Year -gt 1999) {
            $dias = [math]::Round(($info.NextRunTime - (Get-Date)).TotalHours, 1)
            Write-Host "  Proxima exec: $($info.NextRunTime.ToString('dd/MM/yyyy HH:mm')) (em $dias horas)"
        }
        if ($info.LastRunTime.Year -gt 1999) {
            $res = if ($info.LastTaskResult -eq 0) { "Sucesso" } else { "Falhou ($($info.LastTaskResult))" }
            $corRes = if ($info.LastTaskResult -eq 0) { "Green" } else { "Red" }
            Write-Host "  Ultima exec:  $($info.LastRunTime.ToString('dd/MM/yyyy HH:mm')) — " -NoNewline
            Write-Host $res -ForegroundColor $corRes
        }
    }

    # Status WhatsApp
    $waConfig = Ler-ConfigWhatsApp
    Write-Host ""
    Write-Host "  Envio WhatsApp: " -NoNewline
    if ($waConfig -eq "SIM") {
        Write-Host "ATIVADO (envia automaticamente)" -ForegroundColor Green
    } else {
        Write-Host "DESATIVADO (só gera PDFs)" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "─────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host ""
    return $tarefa
}

do {
    $tarefa = Mostrar-Status

    Write-Host "  [1] Executar pipeline AGORA"
    Write-Host "  [2] Ativar envio WhatsApp"
    Write-Host "  [3] Desativar envio WhatsApp (modo teste)"
    Write-Host "  [4] Ver ultimo log"
    if ($tarefa) {
        if ($tarefa.State -eq "Disabled") {
            Write-Host "  [5] Habilitar agendamento"
        } else {
            Write-Host "  [5] Desabilitar agendamento (pausar)"
        }
        Write-Host "  [6] Remover agendamento"
    } else {
        Write-Host "  [5] Instalar agendamento"
    }
    Write-Host "  [0] Sair"
    Write-Host ""

    $opcao = Read-Host "  Opcao"

    switch ($opcao) {
        "1" {
            if ($tarefa) {
                $waAtual = Ler-ConfigWhatsApp
                Write-Host ""
                Write-Host "  WhatsApp esta: $waAtual" -ForegroundColor Cyan
                Write-Host "  Executando pipeline..." -ForegroundColor Yellow
                Start-ScheduledTask -TaskName $NomeTarefa
                Write-Host "  Iniciado! Log em: $PastaContalev\logs\" -ForegroundColor Green
            } else {
                Write-Host "  Agendamento nao instalado. Use opcao [5]." -ForegroundColor Red
            }
            Start-Sleep 3
        }
        "2" {
            Salvar-ConfigWhatsApp "SIM"
            Write-Host ""
            Write-Host "  Envio WhatsApp ATIVADO." -ForegroundColor Green
            Write-Host "  O pipeline vai enviar as cobranças automaticamente." -ForegroundColor Green
            Start-Sleep 2
        }
        "3" {
            Salvar-ConfigWhatsApp "NAO"
            Write-Host ""
            Write-Host "  Envio WhatsApp DESATIVADO." -ForegroundColor Yellow
            Write-Host "  O pipeline vai gerar os PDFs mas NAO vai enviar." -ForegroundColor Yellow
            Start-Sleep 2
        }
        "4" {
            $pastaLogs = "$PastaContalev\logs"
            $logs = Get-ChildItem $pastaLogs -Filter "pipeline_*.txt" -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($logs) {
                Write-Host ""
                Write-Host "─── $($logs.FullName) ───" -ForegroundColor Gray
                Get-Content $logs.FullName | Select-Object -Last 50
                Write-Host "─────────────────────────────────────────" -ForegroundColor Gray
            } else {
                Write-Host "  Nenhum log encontrado ainda." -ForegroundColor Gray
            }
            Read-Host "`n  Enter para continuar"
        }
        "5" {
            if ($tarefa) {
                if ($tarefa.State -eq "Disabled") {
                    Enable-ScheduledTask -TaskName $NomeTarefa | Out-Null
                    Write-Host "  Agendamento HABILITADO." -ForegroundColor Green
                } else {
                    Disable-ScheduledTask -TaskName $NomeTarefa | Out-Null
                    Write-Host "  Agendamento DESABILITADO." -ForegroundColor Yellow
                }
            } else {
                Start-Process powershell -ArgumentList "-File `"$PSScriptRoot\instalar_agendamento.ps1`"" -Verb RunAs
            }
            Start-Sleep 2
        }
        "6" {
            if ($tarefa) {
                $confirmar = Read-Host "  Confirma remocao? (sim/nao)"
                if ($confirmar -eq "sim") {
                    Unregister-ScheduledTask -TaskName $NomeTarefa -Confirm:$false
                    Write-Host "  Agendamento removido." -ForegroundColor Red
                    Start-Sleep 2
                }
            }
        }
    }

} while ($opcao -ne "0")

Write-Host ""
Write-Host "Ate mais!" -ForegroundColor Cyan
