FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
WORKDIR /app/backend
ENV DATABASE_URL=sqlite:////data/stockpilot.db
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "[ -f /data/stockpilot.db ] || python -m app.seed; uvicorn app.main:app --host 0.0.0.0 --port 8000"]
