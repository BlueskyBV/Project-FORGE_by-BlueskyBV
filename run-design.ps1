# Run a Forge design with the settings tuned for the local forge-qwen model.
#
#   .\run-design.ps1 "A 3D-printed PLA spacer block. ..."
#
# Exists so the command never has to be pasted as a multi-line block again.
# A stray paste of terminal output into PowerShell runs every line as a
# command; a single argument cannot.

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $Brief
)

Set-Location -Path $PSScriptRoot

forge design $Brief `
    --provider ollama `
    --base-url http://localhost:11434 `
    --model forge-qwen `
    --context-window 32768 `
    --max-output-tokens 6144 `
    --timeout 2400 `
    --gate-repairs 3 `
    --assume `
    --verbose
