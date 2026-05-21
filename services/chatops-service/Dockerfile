FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc git ripgrep ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY shared/ /app/shared/
COPY AGENTS.md /app/AGENTS.md
COPY services/chatops-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -e /app/shared && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY services/chatops-service/app /app/app

ENV PYTHONUNBUFFERED=1 \
    SERVICE_NAME=chatops-service \
    HERMES_CONFIG_DIR=/app/.hermes
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
