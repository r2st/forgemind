FROM python:3.11-slim
WORKDIR /app
COPY shared/ /app/shared/
COPY services/api-gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -e /app/shared && \
    pip install --no-cache-dir -r /app/requirements.txt
COPY services/api-gateway/app /app/app
ENV PYTHONUNBUFFERED=1 SERVICE_NAME=api-gateway
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
