param(
    [Parameter(Position = 0)]
    [string]$Message = "",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-ExecutablePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LocalPath,
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    $candidate = Join-Path $PSScriptRoot $LocalPath
    if (Test-Path $candidate) {
        return $candidate
    }

    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    throw "Required executable '$CommandName' was not found. Expected local path: $candidate"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter()]
        [string[]]$Arguments = @(),
        [switch]$AllowFailure
    )

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()

    try {
        $argumentLine = ($Arguments | ForEach-Object {
                if ($_ -match '[\s"]') {
                    '"' + ($_ -replace '(\\*)"', '$1$1\"') + '"'
                } else {
                    $_
                }
            }) -join " "

        $process = Start-Process `
            -FilePath $Executable `
            -ArgumentList $argumentLine `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath

        $stdout = if (Test-Path $stdoutPath) { [System.IO.File]::ReadAllText($stdoutPath) } else { "" }
        $stderr = if (Test-Path $stderrPath) { [System.IO.File]::ReadAllText($stderrPath) } else { "" }
        $exitCode = $process.ExitCode
    } finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }

    $combined = @($stdout, $stderr) -join ""
    if (-not $AllowFailure -and $exitCode -ne 0) {
        $rendered = $combined.Trim()
        if ($rendered) {
            throw $rendered
        }
        throw "Command failed with exit code ${exitCode}: $Executable $($Arguments -join ' ')"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = $combined.TrimEnd()
    }
}

function Get-GitOutput {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    return (Invoke-Checked -Executable $script:GitExe -Arguments $Arguments -AllowFailure:$AllowFailure).Output
}

$script:GitExe = Get-ExecutablePath -LocalPath "tools\mingit\cmd\git.exe" -CommandName "git"
$ghExe = Get-ExecutablePath -LocalPath "tools\gh\bin\gh.exe" -CommandName "gh"

$localGhConfig = Join-Path $PSScriptRoot ".gh"
if ((Test-Path $localGhConfig) -and -not $env:GH_CONFIG_DIR) {
    $env:GH_CONFIG_DIR = $localGhConfig
}

$repoRoot = Get-GitOutput -Arguments @("rev-parse", "--show-toplevel")
if (-not $repoRoot) {
    throw "This directory is not a Git repository."
}

$status = Get-GitOutput -Arguments @("status", "--short")
$branch = Get-GitOutput -Arguments @("branch", "--show-current")
$remote = Get-GitOutput -Arguments @("remote", "get-url", "origin") -AllowFailure

if (-not $Message) {
    $Message = "Update $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
}

if (-not $status) {
    Write-Output "No changes to sync."
    exit 0
}

if ($DryRun) {
    Write-Output "Repo   : $repoRoot"
    Write-Output "Branch : $branch"
    Write-Output "Remote : $remote"
    Write-Output "Commit : $Message"
    Write-Output ""
    Write-Output $status
    exit 0
}

Invoke-Checked -Executable $script:GitExe -Arguments @("add", "-A") | Out-Null

$staged = Invoke-Checked -Executable $script:GitExe -Arguments @("diff", "--cached", "--quiet") -AllowFailure
if ($staged.ExitCode -eq 0) {
    Write-Output "No staged changes to commit."
    exit 0
}

Invoke-Checked -Executable $script:GitExe -Arguments @("commit", "-m", $Message) | Out-Null

$upstream = Get-GitOutput -Arguments @("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") -AllowFailure
$pushArgs = if ($upstream) { @("push", "origin", $branch) } else { @("push", "-u", "origin", $branch) }

$token = ""
try {
    $token = (Invoke-Checked -Executable $ghExe -Arguments @("auth", "token")).Output.Trim()
} catch {
    $token = ""
}

if ($token) {
    $basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$token"))
    Invoke-Checked -Executable $script:GitExe -Arguments @(
        "-c",
        "http.https://github.com/.extraheader=AUTHORIZATION: basic $basic"
    ) + $pushArgs | Out-Null
} else {
    Invoke-Checked -Executable $script:GitExe -Arguments $pushArgs | Out-Null
}

Write-Output "Synced '$branch' to origin."
