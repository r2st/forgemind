FROM python:3.11-slim
WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential gcc && rm -rf /var/lib/apt/lists/*
COPY --chown=appuser:appuser shared/ /app/shared/
COPY --chown=appuser:appuser services/reporting-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -e /app/shared && \
    pip install --no-cache-dir -r /app/requirements.txt
COPY --chown=appuser:appuser services/reporting-service/app /app/app
ENV PYTHONUNBUFFERED=1 SERVICE_NAME=reporting-service
EXPOSE 8000
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
