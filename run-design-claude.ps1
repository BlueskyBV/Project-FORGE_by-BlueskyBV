# Run a Forge design on Anthropic's Claude instead of the local model.
#
#   .\run-design-claude.ps1 "A 3D-printed PLA spacer block. ..."
#   .\run-design-claude.ps1 "..." -Model claude-opus-5 -MaxCost 3
#   .\run-design-claude.ps1 "..." -Thinking off      # answer at once, no thinking
#   .\run-design-claude.ps1 "..." -Effort medium     # think less, cost less
#
# A live page opens in the browser as the run starts: every step, every model
# call, and a six-view picture of the part each time it is built (the same
# picture Claude is shown). Add -NoOpen to only write it (runs\<run>\live.html).
#
# The key is read from the ANTHROPIC_API_KEY environment variable and never
# from this file or the command line, so it stays out of shell history.
# Set it once per PowerShell window:
#     $env:ANTHROPIC_API_KEY = "<your key>"
# or for good (new windows only):
#     setx ANTHROPIC_API_KEY "<your key>"

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $Brief,
    [string] $Model = "claude-sonnet-5",
    [double] $MaxCost = 3.00,
    # How Claude reasons before it answers: auto (the default) lets it think
    # first, the way the model can; off makes it answer at once -- cheaper,
    # and how every run before 14 October 2026 was made.
    [ValidateSet("auto", "adaptive", "enabled", "off")]
    [string] $Thinking = "auto",
    # How much a thinking model puts into each answer; its own default when
    # not given. One of low, medium, high, xhigh, max.
    [string] $Effort = "",
    # Do not open the live page in the browser (it is still written).
    [switch] $NoOpen
)

if (-not $env:ANTHROPIC_API_KEY) {
    Write-Host "ANTHROPIC_API_KEY is not set in this window. Set it first:"
    Write-Host '    $env:ANTHROPIC_API_KEY = "<your key>"'
    exit 1
}

Set-Location -Path $PSScriptRoot

$extra = @()
if ($NoOpen) { $extra += "--no-open" }
$extra += @("--thinking", $Thinking)
if ($Effort) { $extra += @("--effort", $Effort) }

forge design $Brief `
    --provider anthropic `
    --model $Model `
    --max-cost $MaxCost `
    --timeout 600 `
    --gate-repairs 3 `
    --assume `
    --verbose `
    @extra
