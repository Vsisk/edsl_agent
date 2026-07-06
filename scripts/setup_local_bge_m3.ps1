$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

Push-Location $ProjectRoot
try {
    uv venv --python 3.12 .venv
    uv pip install --python $Python 'torch==2.9.1' --index-url 'https://download.pytorch.org/whl/cu128'
    uv pip install --python $Python -r requirements-local-bge-m3.txt
    & $Python -c "import torch; import sentence_transformers; import transformers; import huggingface_hub; print('torch=' + torch.__version__); print('cuda_available=' + str(torch.cuda.is_available()))"
    Write-Host "Environment ready. Download with:"
    Write-Host ".venv\Scripts\python.exe scripts\download_bge_m3.py --model-dir D:\models\bge-m3"
    Write-Host "Verify with:"
    Write-Host ".venv\Scripts\python.exe scripts\verify_bge_m3.py --model-dir D:\models\bge-m3 --device cuda"
}
finally {
    Pop-Location
}
