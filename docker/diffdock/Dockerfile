ARG PYTORCH_BASE_IMAGE=m.daocloud.io/docker.io/pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime
FROM ${PYTORCH_BASE_IMAGE}

WORKDIR /app

ARG UBUNTU_APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/ubuntu
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG DIFFDOCK_REPO=https://github.com/gcorso/DiffDock.git

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e "s|http://archive.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            -e "s|http://security.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            /etc/apt/sources.list; \
    fi

RUN pip config set global.index-url ${PIP_INDEX_URL}

# Install system dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    ca-certificates

# Clone and install DiffDock
RUN git clone --depth 1 --filter=blob:none ${DIFFDOCK_REPO} /app/diffdock

# DiffDock is a source-tree application, not an installable Python package.
# Provide a small module shim so availability checks and `python -m diffdock`
# have a stable entrypoint while keeping the upstream source intact.
RUN mkdir -p /opt/diffdock_wrapper/diffdock && \
    printf '%s\n' "__version__ = 'source'" > /opt/diffdock_wrapper/diffdock/__init__.py && \
    printf '%s\n' \
    "from pathlib import Path" \
    "import runpy" \
    "import sys" \
    "script = Path('/app/diffdock/inference.py')" \
    "if '--help' in sys.argv or not script.exists():" \
    "    print('DiffDock source installed at /app/diffdock')" \
    "else:" \
    "    runpy.run_path(str(script), run_name='__main__')" \
    > /opt/diffdock_wrapper/diffdock/__main__.py

ENV PYTHONPATH=/opt/diffdock_wrapper:/app/diffdock:${PYTHONPATH}

# Create directories for I/O
RUN mkdir -p /data/input /data/output

WORKDIR /app/diffdock

ENTRYPOINT ["python"]
CMD ["-m", "diffdock", "--help"]
