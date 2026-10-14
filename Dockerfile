FROM python:3.11-slim-bookworm

# Индекс колёс PyTorch. По умолчанию CPU, чтобы образ запускался без NVIDIA.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    HF_HOME=/opt/hf \
    HOME=/home/forecast \
    PATH="/home/forecast/.local/bin:${PATH}" \
    TORCH_INDEX=${TORCH_INDEX}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        python3-dev \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin forecast \
    && mkdir -p /opt/hf /app \
    && chown forecast:forecast /opt/hf /app

WORKDIR /app

COPY requirements.txt /app/requirements.txt

# Prophet на установке компилирует CmdStan в домашний каталог пользователя forecast.
# В конце принудительно ставим то колесо PyTorch, которое задано TORCH_INDEX,
# чтобы зависимость chronos не подменила его на тяжёлую CUDA-сборку.
USER forecast
RUN python -m pip install --user --upgrade pip \
    && python -m pip install --user -r /app/requirements.txt \
    && python -m pip install --user --force-reinstall --index-url "${TORCH_INDEX}" torch

USER root
COPY app /app/app
COPY docker/entrypoint.py /entrypoint.py
RUN chmod -R a+rX /app /entrypoint.py

ENTRYPOINT ["/usr/bin/tini", "--", "python", "/entrypoint.py"]
