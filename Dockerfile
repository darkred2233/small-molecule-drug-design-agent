FROM m.daocloud.io/docker.io/docker:27-cli AS docker-cli

FROM m.daocloud.io/docker.io/python:3.11-slim

ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e "s|http://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            -e "s|https://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            -e "s|http://security.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            -e "s|https://security.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            /etc/apt/sources.list; \
    fi; \
    if [ -d /etc/apt/sources.list.d ]; then \
        find /etc/apt/sources.list.d -type f \( -name "*.list" -o -name "*.sources" \) -exec sed -i \
            -e "s|http://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            -e "s|https://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            -e "s|http://security.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            -e "s|https://security.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            {} +; \
    fi; \
    apt-get -o Acquire::Retries=10 update \
    && apt-get -o Acquire::Retries=10 install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./

# Install stable dependencies before copying application code so source edits do not
# invalidate the multi-gigabyte CUDA/Torch layer.
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir -p src/medagent \
    && touch src/medagent/__init__.py \
    && python -m pip install --upgrade pip \
    && python -m pip install -e ".[chem,rag]"

COPY src ./src
COPY docs ./docs
COPY database/README.md ./database/README.md

RUN python -c "import torch; from medagent.services.admet_adapter import check_chemprop_available; s=check_chemprop_available(); assert torch.version.cuda is not None, torch.version.cuda; assert s.get('mode') == 'admet_ai' and s.get('version') == '2.0.1' and s.get('model_count') == 10, s"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "medagent.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
