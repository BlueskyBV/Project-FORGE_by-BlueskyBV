# Prove the exact kernel on this Windows machine (docs/V2-stage3.md, sections 15 and 17).
#
#   .\scripts\prove_exact_kernel.ps1                 # the Python on PATH
#   .\scripts\prove_exact_kernel.ps1 -Python py      # another one
#   .\scripts\prove_exact_kernel.ps1 -Exit           # the stage's exit test too (about two hours)
#
# Installs the exact kernel's pins into the Python you run Forge with, runs
# `forge doctor`, then the exact-kernel suite (FreeCAD's checks skip
# themselves here: FreeCAD runs only in the Linux root the tests know), and
# ends with one line: PASS or FAIL. Send that line, and the few above it.
#
# It reads no key and shows no secret: nothing here touches ANTHROPIC_API_KEY.

param(
    [string] $Python = "python",
    [switch] $Exit
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $root
$env:PYTHONPATH = Join-Path $root "packages"

Write-Host "== installing the exact kernel's pins into $Python"
& $Python -m pip install --quiet "cadquery-ocp-novtk==7.9.3.1.1" "lib3mf==2.5.0" "numpy>=1.24"
if ($LASTEXITCODE -ne 0) {
    Write-Host "FORGE EXACT KERNEL: FAIL (the pins could not be installed)"
    exit 1
}

Write-Host "== forge doctor"
& $Python -m forge_cli doctor
$doctor = $LASTEXITCODE

$suites = @(
    "test_v2_occ_view.py", "test_v2_occ_cache.py", "test_v2_occ_export.py", "test_v2_occ_assembly.py",
    "test_v2_occ_ops.py", "test_v2_occ_agreement.py", "test_v2_occ_properties.py", "test_v2_ir.py",
    "test_v2_cli_doctor.py", "test_v2_architecture.py"
)
if ($Exit) { $suites += "test_v2_occ_exit.py" }

$failed = @()
foreach ($suite in $suites) {
    Write-Host "== $suite"
    & $Python -m unittest discover -s tests -p $suite
    if ($LASTEXITCODE -ne 0) { $failed += $suite }
}

if ($doctor -eq 0 -and $failed.Count -eq 0) {
    Write-Host "FORGE EXACT KERNEL: PASS ($($suites.Count) suites, forge doctor all ok, $Python)"
    exit 0
}
$why = @()
if ($doctor -ne 0) { $why += "forge doctor" }
$why += $failed
Write-Host "FORGE EXACT KERNEL: FAIL ($($why -join ', '))"
exit 1
