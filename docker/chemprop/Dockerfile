ARG PYTORCH_BASE_IMAGE=m.daocloud.io/docker.io/pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime
FROM ${PYTORCH_BASE_IMAGE}

WORKDIR /app

ARG UBUNTU_APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/ubuntu
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Use China-friendly package mirrors for Ubuntu
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
    build-essential \
    ca-certificates

# Install the Chemprop version validated with the project's ADMET-AI environment.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install chemprop==2.2.4

# Create directories for I/O
RUN mkdir -p /data/input /data/output /data/models

# Default entrypoint
ENTRYPOINT ["chemprop"]
CMD ["--help"]
