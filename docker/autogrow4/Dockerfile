ARG PYTHON_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.10-slim
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

ARG DEBIAN_APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG AUTOGROW4_REPO=https://github.com/durrantlab/autogrow4.git

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
    openbabel \
    ca-certificates

# Install RDKit and dependencies
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install rdkit-pypi numpy scipy

# Install AutoGrow4
RUN git clone --depth 1 --filter=blob:none ${AUTOGROW4_REPO} /app/autogrow4

# AutoGrow4 is a script-style source tree, not a pip-installable package.
# Keep the upstream source and expose a module shim for `python -m autogrow4`.
RUN mkdir -p /opt/autogrow4_wrapper/autogrow4 && \
    printf '%s\n' "__version__ = 'source'" > /opt/autogrow4_wrapper/autogrow4/__init__.py && \
    printf '%s\n' \
    "from pathlib import Path" \
    "import runpy" \
    "import sys" \
    "candidates = [Path('/app/autogrow4/RunAutogrow.py'), Path('/app/autogrow4/run_autogrow.py')]" \
    "script = next((path for path in candidates if path.exists()), None)" \
    "if '--help' in sys.argv or script is None:" \
    "    print('AutoGrow4 source installed at /app/autogrow4')" \
    "else:" \
    "    runpy.run_path(str(script), run_name='__main__')" \
    > /opt/autogrow4_wrapper/autogrow4/__main__.py

ENV PYTHONPATH=/opt/autogrow4_wrapper:/app/autogrow4:${PYTHONPATH}

# Create directories for I/O
RUN mkdir -p /data/input /data/output

WORKDIR /data

ENTRYPOINT ["python"]
CMD ["-m", "autogrow4", "--help"]
