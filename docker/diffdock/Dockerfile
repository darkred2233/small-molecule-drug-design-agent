ARG CUDA_BASE_IMAGE=m.daocloud.io/docker.io/nvidia/cuda:11.7.1-devel-ubuntu22.04
FROM ${CUDA_BASE_IMAGE}

ARG DIFFDOCK_REF=v1.1.3
ARG TORCH_WHEEL_URL=https://download.pytorch.org/whl/cu117/torch-1.13.1%2Bcu117-cp39-cp39-linux_x86_64.whl
ARG TORCH_WHEEL_FILENAME=torch-1.13.1+cu117-cp39-cp39-linux_x86_64.whl
ARG CONDA_FORGE_CHANNEL=https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

LABEL org.opencontainers.image.source="https://github.com/gcorso/DiffDock" \
      org.opencontainers.image.version="${DIFFDOCK_REF}" \
      org.opencontainers.image.revision="${DIFFDOCK_REF}"

ENV DEBIAN_FRONTEND=noninteractive \
    MAMBA_ROOT_PREFIX=/opt/micromamba \
    PATH=/opt/micromamba/envs/diffdock/bin:/usr/local/bin:${PATH} \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e "s|http://archive.ubuntu.com/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ubuntu|g" \
            -e "s|http://security.ubuntu.com/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ubuntu|g" \
            /etc/apt/sources.list; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends \
    aria2 \
    bzip2 \
    build-essential \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    aria2c \
        --continue=true \
        --max-tries=20 \
        --retry-wait=5 \
        --timeout=120 \
        --connect-timeout=60 \
        --max-connection-per-server=4 \
        --split=4 \
        --min-split-size=1M \
        --file-allocation=none \
        --auto-file-renaming=false \
        --dir=/tmp \
        --out=micromamba.tar.bz2 \
        https://micro.mamba.pm/api/micromamba/linux-64/latest; \
    tar -tjf /tmp/micromamba.tar.bz2 >/dev/null; \
    tar -xjf /tmp/micromamba.tar.bz2 -C /usr/local/bin --strip-components=1 bin/micromamba; \
    rm -f /tmp/micromamba.tar.bz2; \
    micromamba --version

RUN mkdir -p /app/diffdock \
    && aria2c \
        --continue=true \
        --max-tries=20 \
        --retry-wait=5 \
        --timeout=120 \
        --connect-timeout=60 \
        --max-connection-per-server=4 \
        --split=4 \
        --min-split-size=1M \
        --file-allocation=none \
        --auto-file-renaming=false \
        --dir=/tmp \
        --out=diffdock.tar.gz \
        "https://codeload.github.com/gcorso/DiffDock/tar.gz/refs/tags/${DIFFDOCK_REF}" \
    && tar -tzf /tmp/diffdock.tar.gz >/dev/null \
    && tar -xzf /tmp/diffdock.tar.gz -C /app/diffdock --strip-components=1 \
    && rm -f /tmp/diffdock.tar.gz
WORKDIR /app/diffdock

# PyTorch's CUDA 11.7 wheel is the largest dependency (1.8 GB). aria2 uses
# parallel range requests and keeps partial downloads in a BuildKit cache.
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    set -eux; \
    mkdir -p /root/.cache/pip/torch; \
    aria2c \
        --continue=true \
        --max-connection-per-server=8 \
        --split=8 \
        --min-split-size=1M \
        --file-allocation=none \
        --auto-file-renaming=false \
        --dir=/root/.cache/pip/torch \
        --out=${TORCH_WHEEL_FILENAME} \
        ${TORCH_WHEEL_URL}; \
    test -s /root/.cache/pip/torch/${TORCH_WHEEL_FILENAME}

# Install the small Conda base from one verified channel. The upstream
# environment includes several unused channels whose shard metadata can stall
# in Docker Desktop; the GPU packages below are still the upstream pins.
RUN --mount=type=cache,target=/opt/micromamba/pkgs,sharing=locked \
    --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    set -eux; \
    micromamba create -y -n diffdock \
        --override-channels \
        --channel ${CONDA_FORGE_CHANNEL} \
        python=3.9.18 \
        pip \
        python-devtools \
        setuptools=69.5.1 \
        typing_extensions \
        prody=2.2.0 \
        scipy=1.12.0; \
    micromamba run -n diffdock python -m pip install \
        /root/.cache/pip/torch/${TORCH_WHEEL_FILENAME}; \
    micromamba run -n diffdock python -c "import torch; print(torch.__version__, torch.version.cuda)"; \
    micromamba run -n diffdock python -m pip install \
        --extra-index-url https://download.pytorch.org/whl/cu117 \
        --find-links https://pytorch-geometric.com/whl/torch-1.13.1+cu117.html \
        'dllogger @ git+https://github.com/NVIDIA/dllogger.git' \
        e3nn==0.5.1 \
        'fair-esm[esmfold]==2.0.0' \
        networkx==2.8.4 \
        pandas==1.5.1 \
        pybind11==2.11.1 \
        pytorch-lightning==1.9.5 \
        rdkit==2022.03.3 \
        scikit-learn==1.1.0 \
        torch-cluster==1.6.0+pt113cu117 \
        torch-geometric==2.2.0 \
        torch-scatter==2.1.0+pt113cu117 \
        torch-sparse==0.6.16+pt113cu117 \
        torch-spline-conv==1.2.1+pt113cu117 \
        torchmetrics==0.11.0; \
    micromamba run -n diffdock python -m pip install \
        'openfold @ git+https://github.com/aqlaboratory/openfold.git@4b41059694619831a7db195b7e0988fc4ff3a307' \
        'gradio==3.50.*' \
        requests

RUN micromamba run -n diffdock python utils/precompute_series.py
# Model weights are intentionally not baked into the image. Production runs
# mount the upstream score/confidence model directories read-only; availability
# checks require both model_parameters.yml and the exact pinned checkpoint name.
RUN mkdir -p /data/input /data/output

ENTRYPOINT ["micromamba", "run", "-n", "diffdock", "python"]
CMD ["/app/diffdock/inference.py", "--help"]
