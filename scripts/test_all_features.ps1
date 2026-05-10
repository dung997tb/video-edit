$ErrorActionPreference = "Continue"

$ffmpeg = $env:FFMPEG_PATH
$ffprobe = $env:FFPROBE_PATH
if (-not $ffmpeg) {
    $candidate = Join-Path $PSScriptRoot "..\tools\ffmpeg\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe"
    if (Test-Path $candidate) { $ffmpeg = (Resolve-Path $candidate).Path }
}
if (-not $ffprobe) {
    $candidate = Join-Path $PSScriptRoot "..\tools\ffmpeg\ffmpeg-8.1-essentials_build\bin\ffprobe.exe"
    if (Test-Path $candidate) { $ffprobe = (Resolve-Path $candidate).Path }
}
if (-not $ffmpeg -or -not (Test-Path $ffmpeg)) {
    throw "ffmpeg not found. Set FFMPEG_PATH or install ffmpeg in tools\ffmpeg."
}
if (-not $ffprobe -or -not (Test-Path $ffprobe)) {
    throw "ffprobe not found. Set FFPROBE_PATH or install ffmpeg in tools\ffmpeg."
}
$env:FFMPEG_PATH = $ffmpeg
$env:FFPROBE_PATH = $ffprobe

if (-not (Test-Path ".\test_input.mp4")) {
    & $ffmpeg -y `
        -f lavfi -i testsrc2=duration=30:size=1280x720:rate=30 `
        -f lavfi -i sine=frequency=440:duration=30 `
        -c:v libx264 -c:a aac .\test_input.mp4
}

$testCases = @(
    "test_suite_basic.json",
    "test_suite_portrait.json",
    "test_suite_audio.json",
    "workflow_dag_example.json",
    "semantic_silence_cut.json",
    "phase1a_test.json",
    "content_variant.json",
    "loop_test.json",
    "delogo_test.json",
    "random_mirror_test.json",
    "convert_mp3_test.json",
    "hstack_test.json",
    "split_screen_tiktok.json",
    "chromakey_test.json",
    "grid_test.json",
    "split_video_example.json",
    "extract_frames_example.json"
)

foreach ($test in $testCases) {
    Write-Host "Testing: $test" -ForegroundColor Cyan
    python main.py run .\test_input.mp4 --config-file ".\pipelines\examples\$test"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PASS: $test" -ForegroundColor Green
    } else {
        Write-Host "FAIL: $test" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}
