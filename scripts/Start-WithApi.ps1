param(
    [ValidateSet('deepseek', 'kimi', 'both')]
    [string]$Provider = 'both',
    [Parameter(Mandatory = $true)]
    [string]$KnowledgeRoot,
    [string]$RunName = 'api-models',
    [int]$Port = 18894,
    [int]$FhirPort = 18895
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Install the locked Python environment first.' }
if (-not (Test-Path -LiteralPath (Join-Path $KnowledgeRoot 'app\extractive.py'))) {
    throw 'A validated local knowledge project is required.'
}
foreach ($ListenPort in @($Port, $FhirPort)) {
    if (Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue) {
        throw 'A selected port is already in use. Close only its own launcher or choose separate ports.'
    }
}
$Names = if ($Provider -eq 'both') { @('DEEPSEEK_API_KEY', 'MOONSHOT_API_KEY') }
         elseif ($Provider -eq 'deepseek') { @('DEEPSEEK_API_KEY') }
         else { @('MOONSHOT_API_KEY') }
$Previous = @{}
Push-Location -LiteralPath $ProjectRoot
try {
    foreach ($Name in $Names) {
        $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
        $SecureKey = Read-Host -Prompt ('Enter ' + $Name + ' (hidden; process only)') -AsSecureString
        $Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
        try {
            [Environment]::SetEnvironmentVariable($Name, [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer), 'Process')
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
            $SecureKey.Dispose()
        }
    }
    & $Python -B scripts/start.py --knowledge-mode fulltext --knowledge-root $KnowledgeRoot --run-name $RunName --port $Port --fhir-port $FhirPort
    if ($LASTEXITCODE -ne 0) { throw 'Workbench startup failed. Existing data is preserved.' }
}
finally {
    foreach ($Name in $Previous.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], 'Process')
    }
    $Previous.Clear()
    Pop-Location
}
