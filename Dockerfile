FROM docker:27-cli AS docker-cli

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY docs ./docs
COPY database/README.md ./database/README.md

RUN python -m pip install --upgrade pip \
    && python -m pip install -e ".[rag]"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "medagent.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
