FROM node:20-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.25-alpine
RUN adduser -D -u 1000 appuser && \
    chown -R appuser:appuser /usr/share/nginx/html /var/cache/nginx /var/run /var/log/nginx && \
    touch /var/run/nginx.pid && \
    chown appuser:appuser /var/run/nginx.pid
COPY --from=build --chown=appuser:appuser /app/dist /usr/share/nginx/html
COPY --chown=appuser:appuser frontend/nginx.conf /etc/nginx/conf.d/default.conf
USER appuser
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
