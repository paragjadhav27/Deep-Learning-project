# syntax=docker/dockerfile:1.7
# One image, two roles: API (default CMD) and Celery worker (see docker-compose.yml).
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
# CPU-only PyTorch: the "+cpu" builds from the PyTorch index sort above PyPI's CUDA builds.
RUN pip wheel --wheel-dir /wheels ".[prod,ml]" \
      --index-url https://download.pytorch.org/whl/cpu \
      --extra-index-url https://pypi.org/simple

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FACELENS_STORAGE_DIR=/data/blobs \
    FACELENS_MODEL_DIR=/opt/models
# libglib2.0-0: runtime dependency of the OpenCV wheels on slim images.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app && mkdir -p /data && chown app /data
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
# Pinned model weights, SHA-256 verified at download and again at startup. SAM (2.2 GB,
# needed only for FACELENS_AGING_MODEL=sam) is opt-in:
#   docker build --build-arg MODELS=yunet-2026may,mivolo-v2,sam-ffhq-aging ...
ARG MODELS=yunet-2026may,mivolo-v2
# fetch-models writes owner-only (0600) files as root; the app user needs read access.
RUN facelens-api fetch-models --dir /opt/models --only "$MODELS" && chmod -R a+rX,a-w /opt/models
USER app
WORKDIR /home/app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
# SIGTERM -> uvicorn graceful shutdown (30 s): running jobs finish, sweeper stops.
CMD ["facelens-api", "serve", "--host", "0.0.0.0", "--port", "8000"]
