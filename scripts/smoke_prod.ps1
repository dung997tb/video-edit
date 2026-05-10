param(
    [string]$BaseUrl = $env:SMOKE_BASE_URL,
    [string]$ApiKey = $env:API_SECRET_KEY,
    [int]$JobCount = 4,
    [int]$PollSeconds = 1,
    [int]$TimeoutSeconds = 420,
    [int]$SyntheticDurationSeconds = 20,
    [string]$InputVideoPath = "",
    [switch]$KeepTempVideo,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

try {
    Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
}
catch {
    # Continue; some PowerShell runtimes already preload System.Net.Http.
}

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = "http://127.0.0.1:6666"
}

$BaseUrl = $BaseUrl.TrimEnd("/")

if ($JobCount -lt 2) {
    throw "JobCount must be >= 2 to validate both done and cancelled states."
}
if ($PollSeconds -lt 1) {
    throw "PollSeconds must be >= 1."
}
if ($TimeoutSeconds -lt 30) {
    throw "TimeoutSeconds must be >= 30."
}
if ($SyntheticDurationSeconds -lt 5) {
    throw "SyntheticDurationSeconds must be >= 5."
}

function Write-Section {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message =="
}

function Get-HttpMethod {
    param([string]$Method)
    switch ($Method.ToUpperInvariant()) {
        "GET" { return [System.Net.Http.HttpMethod]::Get }
        "POST" { return [System.Net.Http.HttpMethod]::Post }
        default { throw "Unsupported HTTP method: $Method" }
    }
}

function Invoke-ApiJson {
    param(
        [string]$Method,
        [string]$Path,
        [object]$Body = $null
    )

    $uri = "$script:BaseUrl$Path"
    $request = [System.Net.Http.HttpRequestMessage]::new((Get-HttpMethod -Method $Method), $uri)
    $request.Headers.Accept.Clear()
    $request.Headers.Accept.Add([System.Net.Http.Headers.MediaTypeWithQualityHeaderValue]::new("application/json"))
    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 30 -Compress
        $request.Content = [System.Net.Http.StringContent]::new(
            $json,
            [System.Text.Encoding]::UTF8,
            "application/json"
        )
    }

    $response = $null
    try {
        try {
            $response = $script:HttpClient.SendAsync($request).GetAwaiter().GetResult()
        }
        catch {
            throw "Network error while calling $uri. Ensure API is reachable and BaseUrl is correct. Details: $($_.Exception.Message)"
        }
        $raw = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            $statusCode = [int]$response.StatusCode
            throw ("HTTP {0} for {1} {2}: {3}" -f $statusCode, $Method, $Path, $raw)
        }
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $null
        }
        return $raw | ConvertFrom-Json
    }
    finally {
        $request.Dispose()
        if ($null -ne $response) {
            $response.Dispose()
        }
    }
}

function Invoke-UploadJob {
    param(
        [string]$FilePath,
        [string]$PipelineType,
        [hashtable]$Payload,
        [hashtable]$Metadata
    )

    $uri = "$script:BaseUrl/jobs/upload"
    $multipart = [System.Net.Http.MultipartFormDataContent]::new()
    $stream = [System.IO.File]::OpenRead($FilePath)
    $response = $null
    try {
        $fileContent = [System.Net.Http.StreamContent]::new($stream)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("video/mp4")
        $multipart.Add($fileContent, "file", [System.IO.Path]::GetFileName($FilePath))
        $multipart.Add([System.Net.Http.StringContent]::new($PipelineType), "pipeline_type")
        $multipart.Add([System.Net.Http.StringContent]::new(($Payload | ConvertTo-Json -Depth 30 -Compress)), "payload_json")
        $multipart.Add([System.Net.Http.StringContent]::new(($Metadata | ConvertTo-Json -Depth 30 -Compress)), "metadata_json")

        try {
            $response = $script:HttpClient.PostAsync($uri, $multipart).GetAwaiter().GetResult()
        }
        catch {
            throw "Network error while calling $uri. Ensure API is reachable and BaseUrl is correct. Details: $($_.Exception.Message)"
        }
        $raw = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            $statusCode = [int]$response.StatusCode
            throw "HTTP $statusCode for POST /jobs/upload: $raw"
        }
        if ([string]::IsNullOrWhiteSpace($raw)) {
            throw "Upload endpoint returned empty response."
        }
        return $raw | ConvertFrom-Json
    }
    finally {
        if ($null -ne $response) {
            $response.Dispose()
        }
        $stream.Dispose()
        $multipart.Dispose()
    }
}

function New-SyntheticVideo {
    param(
        [string]$OutputPath,
        [int]$DurationSeconds
    )

    $ffmpegCommand = Get-Command "ffmpeg" -ErrorAction SilentlyContinue
    if ($null -eq $ffmpegCommand) {
        throw "ffmpeg not found in PATH. Provide -InputVideoPath or install ffmpeg."
    }

    $args = @(
        "-loglevel", "error",
        "-y",
        "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100",
        "-t", "$DurationSeconds",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        $OutputPath
    )

    & $ffmpegCommand.Source @args
    if ($LASTEXITCODE -ne 0) {
        throw "ffmpeg synthetic video generation failed with exit code $LASTEXITCODE."
    }
}

function New-SmokePayload {
    param([switch]$CancelCandidate)

    if ($CancelCandidate) {
        return @{
            operations = @(
                @{
                    name  = "cut"
                    start = 0.0
                    end   = [double]$script:SyntheticDurationSeconds
                },
                @{
                    name = "denoise"
                },
                @{
                    name       = "color_grade"
                    brightness = 0.02
                    contrast   = 1.05
                    saturation = 1.10
                    gamma      = 1.00
                },
                @{
                    name        = "scale"
                    width       = 1280
                    height      = 720
                    keep_aspect = $true
                }
            )
        }
    }

    return @{
        operations = @(
            @{
                name  = "cut"
                start = 0.0
                end   = 8.0
            },
            @{
                name        = "scale"
                width       = 854
                height      = 480
                keep_aspect = $true
            },
            @{
                name = "flip"
                mode = "horizontal"
            }
        )
    }
}

if ($DryRun) {
    Write-Section "Smoke Configuration (DryRun)"
    Write-Host "BaseUrl                   : $BaseUrl"
    Write-Host "ApiKey configured         : $(-not [string]::IsNullOrWhiteSpace($ApiKey))"
    Write-Host "JobCount                  : $JobCount"
    Write-Host "PollSeconds               : $PollSeconds"
    Write-Host "TimeoutSeconds            : $TimeoutSeconds"
    Write-Host "SyntheticDurationSeconds  : $SyntheticDurationSeconds"
    Write-Host "InputVideoPath            : $InputVideoPath"
    exit 0
}

$script:BaseUrl = $BaseUrl
$script:SyntheticDurationSeconds = $SyntheticDurationSeconds
$script:HttpClient = [System.Net.Http.HttpClient]::new()
$script:HttpClient.Timeout = [TimeSpan]::FromSeconds(120)

if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
    $script:HttpClient.DefaultRequestHeaders.Remove("x-api-key") | Out-Null
    $script:HttpClient.DefaultRequestHeaders.Add("x-api-key", $ApiKey)
}

$tempVideoPath = ""
$videoPath = $InputVideoPath
$runId = [Guid]::NewGuid().ToString("N")

try {
    Write-Section "Health Check"
    $health = Invoke-ApiJson -Method "GET" -Path "/health"
    if ($null -eq $health -or $health.status -ne "ok") {
        throw "Health check failed. Response: $($health | ConvertTo-Json -Compress)"
    }
    Write-Host "Health endpoint is OK."

    if ([string]::IsNullOrWhiteSpace($videoPath)) {
        Write-Section "Prepare Synthetic Input"
        $tempVideoPath = Join-Path ([System.IO.Path]::GetTempPath()) ("smoke_input_{0}.mp4" -f $runId)
        New-SyntheticVideo -OutputPath $tempVideoPath -DurationSeconds $SyntheticDurationSeconds
        $videoPath = $tempVideoPath
        Write-Host "Created synthetic video: $videoPath"
    }
    elseif (-not (Test-Path -LiteralPath $videoPath)) {
        throw "Input video not found: $videoPath"
    }

    Write-Section "Enqueue Jobs"
    $jobs = @()
    for ($index = 1; $index -le $JobCount; $index++) {
        $isCancelCandidate = ($index -eq 1)
        $payload = New-SmokePayload -CancelCandidate:$isCancelCandidate
        $metadata = @{
            smoke_run_id    = $runId
            smoke_job_index = $index
            smoke_role      = if ($isCancelCandidate) { "cancel_candidate" } else { "normal" }
            created_at_utc  = [DateTime]::UtcNow.ToString("o")
        }

        $created = Invoke-UploadJob -FilePath $videoPath -PipelineType "low_level" -Payload $payload -Metadata $metadata
        $jobs += [pscustomobject]@{
            id     = [string]$created.id
            role   = [string]$metadata.smoke_role
            status = [string]$created.status
        }
        Write-Host ("Enqueued {0} ({1}) => {2}" -f $created.id, $metadata.smoke_role, $created.status)
    }

    $cancelTarget = $jobs[0]
    Write-Section "Cancel Running Job"
    $cancelSent = $false
    $cancelProbeDeadline = (Get-Date).AddSeconds([Math]::Min(120, $TimeoutSeconds))
    while ((Get-Date) -lt $cancelProbeDeadline) {
        $current = Invoke-ApiJson -Method "GET" -Path "/jobs/$($cancelTarget.id)"
        $status = [string]$current.status
        if ($status -eq "running") {
            $cancelResult = Invoke-ApiJson -Method "POST" -Path "/jobs/$($cancelTarget.id)/cancel"
            Write-Host ("Cancel requested for {0}: status={1} cancel_requested={2}" -f $cancelResult.id, $cancelResult.status, $cancelResult.cancel_requested)
            $cancelSent = $true
            break
        }
        if ($status -in @("done", "failed", "cancelled")) {
            break
        }
        Start-Sleep -Seconds $PollSeconds
    }

    if (-not $cancelSent) {
        throw "Could not catch cancel target in 'running' state. Check worker readiness or increase SyntheticDurationSeconds."
    }

    Write-Section "Poll Terminal States"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $snapshot = @{}
    $allTerminal = $false
    $lastPrintAt = [DateTime]::MinValue
    while ((Get-Date) -lt $deadline) {
        $allTerminal = $true
        foreach ($job in $jobs) {
            $jobState = Invoke-ApiJson -Method "GET" -Path "/jobs/$($job.id)"
            $snapshot[$job.id] = $jobState
            if ([string]$jobState.status -in @("pending", "running")) {
                $allTerminal = $false
            }
        }

        if ($allTerminal) {
            break
        }

        if (((Get-Date) - $lastPrintAt).TotalSeconds -ge 5) {
            foreach ($job in $jobs) {
                $s = $snapshot[$job.id]
                Write-Host ("{0} [{1}] => {2} step={3}" -f $job.id, $job.role, $s.status, $s.current_step)
            }
            $lastPrintAt = Get-Date
        }
        Start-Sleep -Seconds $PollSeconds
    }

    if (-not $allTerminal) {
        throw "Timed out waiting for terminal states after $TimeoutSeconds seconds."
    }

    Write-Section "Validate Outcomes"
    $cancelTargetState = $snapshot[$cancelTarget.id]
    if ([string]$cancelTargetState.status -ne "cancelled") {
        throw "Cancel target expected 'cancelled' but got '$($cancelTargetState.status)'."
    }

    $failedJobs = @()
    foreach ($job in $jobs) {
        $state = $snapshot[$job.id]
        if ($job.id -eq $cancelTarget.id) {
            continue
        }
        if ([string]$state.status -ne "done") {
            $failedJobs += [pscustomobject]@{
                id     = $job.id
                status = [string]$state.status
                error  = [string]$state.error
            }
        }
    }

    if ($failedJobs.Count -gt 0) {
        $payload = $failedJobs | ConvertTo-Json -Depth 10
        throw "Expected non-cancel jobs to finish with status=done. Details: $payload"
    }

    $summary = foreach ($job in $jobs) {
        $state = $snapshot[$job.id]
        [pscustomobject]@{
            id          = $job.id
            role        = $job.role
            status      = [string]$state.status
            attempt     = [int]$state.attempt_count
            step        = [string]$state.current_step
            output_path = [string]$state.output_path
        }
    }
    $summary | Format-Table -AutoSize
    Write-Host ""
    Write-Host "Smoke test passed for run_id=$runId"
}
finally {
    if ($null -ne $script:HttpClient) {
        $script:HttpClient.Dispose()
    }
    if (-not $KeepTempVideo -and -not [string]::IsNullOrWhiteSpace($tempVideoPath) -and (Test-Path -LiteralPath $tempVideoPath)) {
        Remove-Item -LiteralPath $tempVideoPath -Force -ErrorAction SilentlyContinue
    }
}
