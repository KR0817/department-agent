param(
    [int]$Port = 18894,
    [int]$FhirPort = 18895,
    [string]$RunName = 'default'
)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    & uv run --frozen python scripts/start.py --port $Port --fhir-port $FhirPort --run-name $RunName
    if ($LASTEXITCODE -ne 0) { throw 'Department Agent exited with an error.' }
}
finally {
    Pop-Location
}
