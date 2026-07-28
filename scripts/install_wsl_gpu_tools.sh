#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root: wsl -d Ubuntu -u root -- bash scripts/install_wsl_gpu_tools.sh" >&2
  exit 1
fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/.local/tools"
MODELS="$ROOT/.local/models"
MINIFORGE=/opt/medagent/miniforge3
ENVS=/opt/medagent/envs
GNINA="$TOOLS/gnina-linux/gnina"
TARGETDIFF="$TOOLS/TargetDiff"
AUTOGROW4="$TOOLS/AutoGrow4"
GNINA_SHA256=714ef2928a22c7b20680ccfeade3c2a652a4e452a1f64343da541434528ed9cd
MINIFORGE_VERSION=26.3.2-3
TARGETDIFF_COMMIT=142f1eb7178480d435fe0b8cb95a99beb48997c7

apt-get update
apt-get install -y ca-certificates curl git
mkdir -p "$TOOLS/gnina-linux" "$MODELS/targetdiff" "$ENVS"

if [[ ! -x "$MINIFORGE/bin/conda" ]]; then
  installer=/tmp/Miniforge3-Linux-x86_64.sh
  curl -fL --retry 3 -o "$installer" \
    "https://github.com/conda-forge/miniforge/releases/download/${MINIFORGE_VERSION}/Miniforge3-${MINIFORGE_VERSION}-Linux-x86_64.sh"
  bash "$installer" -b -p "$MINIFORGE"
fi
CONDA="$MINIFORGE/bin/conda"

if [[ ! -f "$GNINA" ]]; then
  curl -fL -C - --retry 3 --retry-delay 5 -o "$GNINA" \
    https://github.com/gnina/gnina/releases/download/v1.3.2/gnina.1.3.2.cuda12.8
fi
echo "$GNINA_SHA256  $GNINA" | sha256sum --check --status
chmod +x "$GNINA"

if [[ ! -d "$ENVS/gnina-runtime/conda-meta" ]]; then
  "$CONDA" create -y -p "$ENVS/gnina-runtime" -c conda-forge \
    --strict-channel-priority cuda-libraries=12.8 cudnn=9.10.2.21
fi
LD_LIBRARY_PATH="$ENVS/gnina-runtime/lib" "$GNINA" --version

if [[ ! -f "$TARGETDIFF/scripts/sample_for_pocket.py" ]]; then
  git init "$TARGETDIFF"
  git -C "$TARGETDIFF" remote add origin https://github.com/guanjq/targetdiff.git
  git -C "$TARGETDIFF" fetch --depth 1 origin "$TARGETDIFF_COMMIT"
  git -C "$TARGETDIFF" checkout --detach FETCH_HEAD
fi
checkpoint="$TARGETDIFF/pretrained_models/pretrained_diffusion.pt"
if [[ ! -f "$checkpoint" && -f "$MODELS/targetdiff/pretrained_diffusion.pt" ]]; then
  mkdir -p "$(dirname "$checkpoint")"
  cp "$MODELS/targetdiff/pretrained_diffusion.pt" "$checkpoint"
fi
if [[ ! -f "$checkpoint" ]]; then
  echo "Missing TargetDiff checkpoint: $checkpoint" >&2
  exit 1
fi

if [[ ! -x "$ENVS/targetdiff/bin/python" ]]; then
  "$CONDA" create -y -p "$ENVS/targetdiff" -c conda-forge \
    --strict-channel-priority \
    python=3.8 pip setuptools wheel numpy=1.24 scipy=1.10 rdkit=2022.03 \
    openbabel=3.1.1 pyyaml easydict tqdm python-lmdb scikit-learn matplotlib
fi
TARGET_PY="$ENVS/targetdiff/bin/python"
if ! "$TARGET_PY" -c 'import torch; assert torch.__version__.startswith("1.13.1")' 2>/dev/null; then
  "$TARGET_PY" -m pip install --no-cache-dir 'torch==1.13.1+cu116' \
    --extra-index-url https://download.pytorch.org/whl/cu116
fi
if ! "$TARGET_PY" -c 'import torch_geometric, torch_scatter, torch_sparse, torch_cluster' 2>/dev/null; then
  "$TARGET_PY" -m pip install --no-cache-dir \
    torch-scatter==2.1.0 torch-sparse==0.6.17 torch-cluster==1.6.1 \
    torch-spline-conv==1.2.2 \
    -f https://data.pyg.org/whl/torch-1.13.0+cu116.html
  "$TARGET_PY" -m pip install --no-cache-dir torch-geometric==2.2.0
fi
(
  cd "$TARGETDIFF"
  PYTHONPATH="$TARGETDIFF" "$TARGET_PY" scripts/sample_for_pocket.py --help >/dev/null
  "$TARGET_PY" -c 'import torch; c=torch.load("pretrained_models/pretrained_diffusion.pt", map_location="cpu"); assert "model" in c'
  "$TARGET_PY" -c 'import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))'
)

if [[ ! -f "$AUTOGROW4/RunAutogrow.py" ]]; then
  git clone --depth 1 --branch v4.0.3 https://github.com/durrantlab/autogrow4.git "$AUTOGROW4"
fi
AUTOGROW_NN1="$AUTOGROW4/autogrow/docking/scoring/nn_score_exe/nnscore1/NNScore.py"
AUTOGROW_NN2="$AUTOGROW4/autogrow/docking/scoring/nn_score_exe/nnscore2/NNScore2.py"
if [[ ! -f "$AUTOGROW_NN1" || ! -f "$AUTOGROW_NN2" ]]; then
  echo "AutoGrow4 source is incomplete; install the complete v4.0.3 tag." >&2
  exit 1
fi
AUTOGROW_ENV="$ENVS/autogrow4-v403"
if [[ ! -x "$AUTOGROW_ENV/bin/python" ]]; then
  "$CONDA" create -y -p "$AUTOGROW_ENV" -c conda-forge \
    --strict-channel-priority python=3.7 rdkit=2020.03.1 numpy=1.18.1 \
    scipy=1.4.1 matplotlib=3.2.1 openbabel=3.1.1 pip
  "$AUTOGROW_ENV/bin/python" -m pip install --no-cache-dir func-timeout==4.3.5
fi
AUTOGROW_PY="$AUTOGROW_ENV/bin/python"
AUTOGROW_VINA="$AUTOGROW4/autogrow/docking/docking_executables/vina/autodock_vina_1_1_2_linux_x86/bin/vina"
"$AUTOGROW_PY" "$ROOT/scripts/patch_autogrow4.py" --root "$AUTOGROW4"
chmod +x "$AUTOGROW_VINA"
(
  cd "$AUTOGROW4"
  PYTHONPATH="$AUTOGROW4" "$AUTOGROW_PY" RunAutogrow.py --help >/dev/null
  "$AUTOGROW_VINA" --help >/dev/null
)

echo "GNINA, TargetDiff, and AutoGrow4 WSL runtimes are ready."
