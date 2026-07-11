ARG PYTHON_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

ARG DEBIAN_APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG REINVENT4_REPO=https://github.com/MolecularAI/REINVENT4.git

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i \
            -e "s|http://deb.debian.org/debian|${DEBIAN_APT_MIRROR}|g" \
            -e "s|http://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
            /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e "s|http://deb.debian.org/debian|${DEBIAN_APT_MIRROR}|g" \
            -e "s|http://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
            /etc/apt/sources.list; \
    fi

RUN pip config set global.index-url ${PIP_INDEX_URL}

# Install system dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    ca-certificates

# Install REINVENT4 from the official source tree. The PyPI package name is
# not `reinvent4`; the repository installs the `reinvent` CLI.
RUN git clone --depth 1 --filter=blob:none ${REINVENT4_REPO} /app/reinvent4
WORKDIR /app/reinvent4
RUN --mount=type=cache,target=/root/.cache/pip \
    python install.py cpu -d none

# Create directories for I/O
RUN mkdir -p /data/input /data/output

WORKDIR /data

ENTRYPOINT ["reinvent"]
CMD ["--help"]
