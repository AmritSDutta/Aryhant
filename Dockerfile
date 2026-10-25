# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PYTHONPATH="/app/src:${PYTHONPATH}"

WORKDIR /app

# minimal system deps with full Indic (Hindi/Bengali) fonts
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    fonts-noto-core \
    fonts-noto-extra \
    fonts-lohit-beng-bengali \
    fonts-lohit-deva \
    fonts-freefont-ttf \
 && rm -rf /var/lib/apt/lists/*

# create non-root user and group
RUN groupadd -r appgroup && useradd -r -u 10001 -g appgroup appuser

# install Python deps (expect requirements.txt at repo root)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# copy source and grant non-root ownership
COPY . /app
RUN chown -R appuser:appgroup /app
#composio needs some space
RUN mkdir -p /home/appuser/.composio && chown -R appuser:appgroup /home/appuser/.composio

# switch to non-root user
USER appuser

# expose FastAPI port
EXPOSE ${PORT}

# start FastAPI application
CMD uvicorn chat_agent.app:app --host 0.0.0.0 --port ${PORT}