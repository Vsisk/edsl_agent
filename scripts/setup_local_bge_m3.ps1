$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

Push-Location $ProjectRoot
try {
    if (-not (Test-Path $Python)) {
        uv venv --python 3.12 .venv
        if ($LASTEXITCODE -ne 0) { throw "uv venv failed with exit code $LASTEXITCODE" }
    }
    uv pip install --python $Python 'torch==2.9.1' --index-url 'https://download.pytorch.org/whl/cu128'
    if ($LASTEXITCODE -ne 0) { throw "PyTorch installation failed with exit code $LASTEXITCODE" }
    uv pip install --python $Python -r requirements-local-bge-m3.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed with exit code $LASTEXITCODE" }
    & $Python -c "import torch; import sentence_transformers; import transformers; import huggingface_hub; print('torch=' + torch.__version__); print('cuda_available=' + str(torch.cuda.is_available()))"
    if ($LASTEXITCODE -ne 0) { throw "Dependency verification failed with exit code $LASTEXITCODE" }
    Write-Host "Environment ready. Download with:"
    Write-Host ".venv\Scripts\python.exe scripts\download_bge_m3.py --model-dir D:\models\bge-m3"
    Write-Host "Verify with:"
    Write-Host ".venv\Scripts\python.exe scripts\verify_bge_m3.py --model-dir D:\models\bge-m3 --device cuda"
}
finally {
    Pop-Location
}
