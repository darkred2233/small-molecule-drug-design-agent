#!/usr/bin/env bash
# Run from an Ubuntu WSL shell after scripts/install_local_tools.ps1 -InstallWsl
# has installed the distribution. This is a project-local WSL deployment.
set -euo pipefail

ROOT="/mnt/c/Users/zhihong/Desktop/small-molecule-drug-design-agent"
TOOLS="$ROOT/.local/tools"
ENVS="$ROOT/.local/envs"

sudo apt-get update
sudo apt-get install -y git wget curl python3-venv build-essential
mkdir -p "$TOOLS/gnina-linux" "$ENVS"

if [ ! -x "$TOOLS/gnina-linux/gnina" ]; then
  wget -O "$TOOLS/gnina-linux/gnina" \
    https://github.com/gnina/gnina/releases/download/v1.3.2/gnina
  chmod +x "$TOOLS/gnina-linux/gnina"
fi
"$TOOLS/gnina-linux/gnina" --version

if [ ! -d "$TOOLS/TargetDiff/.git" ]; then
  git clone --depth 1 https://github.com/guanjq/targetdiff.git "$TOOLS/TargetDiff"
fi

echo "TargetDiff source is present. Download its official checkpoint only after recording its release URL and SHA-256 in configs/tools.yaml."
echo "Run scripts/check_local_tools.py after configuring the WSL command wrapper."
