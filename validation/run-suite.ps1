# Run the Forge V1 validation suite, unattended and resumable.
#
#   .\validation\run-suite.ps1                  every test not yet run
#   .\validation\run-suite.ps1 -Tier R          one tier (R P H C A V L X)
#   .\validation\run-suite.ps1 -Only P04,H07    chosen tests
#   .\validation\run-suite.ps1 -Repeat 2        each test twice (-r1, -r2)
#   .\validation\run-suite.ps1 -Force           rerun even if a run exists
#   .\validation\run-suite.ps1 -Claude          on Anthropic's Claude instead of
#                                               the local model (needs
#                                               ANTHROPIC_API_KEY, as
#                                               run-design-claude.ps1 does)
#   .\validation\run-suite.ps1 -Claude -Model claude-opus-5 -MaxCost 3
#
# Stop it any time with Ctrl+C; run it again and it carries on where it left
# off. When it finishes it grades everything with check-suite.py.

param(
    [string] $Tier = "",
    [string[]] $Only = @(),
    [int] $Repeat = 1,
    [switch] $Force,
    # Run on Anthropic's Claude with the settings run-design-claude.ps1 uses,
    # instead of the local forge-qwen model. The key is read from the
    # ANTHROPIC_API_KEY environment variable and never from this file.
    [switch] $Claude,
    [string] $Model = "claude-sonnet-5",
    [double] $MaxCost = 2.00
)

if ($Claude -and -not $env:ANTHROPIC_API_KEY) {
    Write-Host "ANTHROPIC_API_KEY is not set in this window. Set it first:"
    Write-Host '    $env:ANTHROPIC_API_KEY = "<your key>"'
    exit 1
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $root
$suite = Get-Content -Raw -Encoding UTF8 "validation\suite.json" | ConvertFrom-Json
$runs = "validation\runs"
New-Item -ItemType Directory -Force -Path $runs | Out-Null
$log = "validation\results.csv"
if (-not (Test-Path $log)) { "id,run,exit,minutes,finished" | Out-File -Encoding utf8 $log }

$tests = $suite.tests
if ($Tier) { $tests = $tests | Where-Object { $_.tier -eq $Tier } }
if ($Only.Count -gt 0) {
    $wanted = $Only | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() }
    $tests = $tests | Where-Object { $wanted -contains $_.id }
}
$total = @($tests).Count * $Repeat
$n = 0
foreach ($t in $tests) {
    for ($r = 1; $r -le $Repeat; $r++) {
        $n++
        $name = if ($Repeat -gt 1) { "$($t.id)-r$r" } else { $t.id }
        $out = Join-Path $runs $name
        if ((Test-Path (Join-Path $out "run.json")) -and -not $Force) {
            Write-Host "[$n/$total] $name already run -- skipped"
            continue
        }
        Write-Host ""
        Write-Host "==================================================================="
        Write-Host "[$n/$total] $name  $($t.title)"
        Write-Host "  $($t.brief)"
        Write-Host "==================================================================="
        $start = Get-Date
        if ($Claude) {
            forge design $t.brief `
                --provider anthropic `
                --model $Model `
                --max-cost $MaxCost `
                --timeout 600 `
                --gate-repairs 3 `
                --assume `
                --no-open `
                --out $out 2>&1 | Tee-Object -FilePath (Join-Path $runs "$name.console.txt")
        } else {
            forge design $t.brief `
                --provider ollama `
                --base-url http://localhost:11434 `
                --model forge-qwen `
                --context-window 32768 `
                --max-output-tokens 6144 `
                --timeout 2400 `
                --gate-repairs 3 `
                --assume `
                --out $out 2>&1 | Tee-Object -FilePath (Join-Path $runs "$name.console.txt")
        }
        $code = $LASTEXITCODE
        $minutes = [math]::Round(((Get-Date) - $start).TotalMinutes, 1)
        "$($t.id),$name,$code,$minutes,$(Get-Date -Format s)" | Out-File -Append -Encoding utf8 $log
    }
}

Write-Host ""
Write-Host "Grading..."
python validation\check-suite.py
