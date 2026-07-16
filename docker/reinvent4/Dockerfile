ARG PYTORCH_BASE_IMAGE=m.daocloud.io/docker.io/pytorch/pytorch:2.12.0-cuda12.6-cudnn9-runtime
FROM ${PYTORCH_BASE_IMAGE}

WORKDIR /app

ARG UBUNTU_APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/ubuntu
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG REINVENT4_REPO=https://github.com/MolecularAI/REINVENT4.git
ARG REINVENT4_REF=v4.8

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e "s|http://archive.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            -e "s|https://archive.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            -e "s|http://security.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            -e "s|https://security.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            /etc/apt/sources.list; \
    fi; \
    if [ -d /etc/apt/sources.list.d ]; then \
        find /etc/apt/sources.list.d -type f \( -name "*.list" -o -name "*.sources" \) -exec sed -i \
            -e "s|http://archive.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            -e "s|https://archive.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            -e "s|http://security.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            -e "s|https://security.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            {} +; \
    fi

RUN pip config set global.index-url ${PIP_INDEX_URL}

# Install system dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get -o Acquire::Retries=10 update && apt-get -o Acquire::Retries=10 install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libxrender1 \
    libxext6 \
    libsm6 \
    libgl1 \
    ca-certificates

# Install REINVENT4 from the official source tree with GPU support
RUN --mount=type=cache,target=/root/.cache/reinvent4,sharing=locked \
    set -eux; \
    archive="/root/.cache/reinvent4/reinvent4-${REINVENT4_REF}.tar.gz"; \
    rm -f "${archive}.tmp"; \
    curl -fL \
        --retry 20 \
        --retry-all-errors \
        --retry-delay 5 \
        --connect-timeout 60 \
        --max-time 600 \
        -o "${archive}.tmp" \
        "https://codeload.github.com/MolecularAI/REINVENT4/tar.gz/refs/tags/${REINVENT4_REF}"; \
    tar -tzf "${archive}.tmp" >/dev/null; \
    mv "${archive}.tmp" "${archive}"; \
    mkdir -p /app/reinvent4; \
    tar -xzf "${archive}" -C /app/reinvent4 --strip-components=1
WORKDIR /app/reinvent4
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --break-system-packages --prefer-binary \
        "tensorboard>=2,<3" \
        "rdkit>=2025.09.1" \
        "numpy>=2,<3" \
        "pumas>=1.3.0" \
        "molvs>=0.1.1,<0.2" \
        "xxhash>=3,<4" \
        "pydantic>=2,<3" \
        "python-dotenv>=1.0,<2" \
        "matplotlib>=3.7,<4" \
        "apted>=1.0.3,<2" \
        "mmpdb>=2.1,<3" \
        "pandas>=3,<4" \
        "polars<2" \
        "Pillow>=12.2.0" \
        "PyYAML>=6.0" \
        "requests>=2.28,<3" \
        "tqdm>=4.64,<5" \
        "pytest>=9.0.3" \
        "pytest-mock>=3"; \
    python -m pip install --break-system-packages --no-deps .
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --break-system-packages --no-cache-dir scipy
RUN reinvent --help >/dev/null

# Create directories for I/O
RUN mkdir -p /data/input /data/output

WORKDIR /data

ENTRYPOINT ["reinvent"]
CMD ["--help"]
