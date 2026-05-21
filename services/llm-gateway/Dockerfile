FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Install shared package
COPY --chown=appuser:appuser shared /shared
RUN pip install --no-cache-dir /shared

# Install service dependencies
COPY --chown=appuser:appuser services/llm-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code
COPY --chown=appuser:appuser services/llm-gateway/app ./app

USER appuser

# Run the service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
