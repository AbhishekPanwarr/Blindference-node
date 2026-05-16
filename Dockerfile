FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# NVIDIA GPU detection — install only the CLI tools (nvidia-smi).
# For GPU inference inside the container, use the nvidia-docker runtime:
#   docker run --gpus all blindference-node:0.2.0 …
RUN apt-get update && apt-get install -y --no-install-recommends \
    nvidia-cuda-toolkit \
    || true \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY blindference_node/ ./blindference_node/
COPY contracts/ ./contracts/

RUN pip install --no-cache-dir -e .

RUN mkdir -p /root/.blindference

HEALTHCHECK --interval=30s --timeout=3s CMD blindference-node --version

ENTRYPOINT ["blindference-node"]
