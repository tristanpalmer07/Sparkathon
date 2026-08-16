FROM python:3.11-slim
WORKDIR /app
COPY shared/ ./shared/
COPY scripts/ ./scripts/
RUN pip install --no-cache-dir pydantic kafka-python psycopg2-binary
WORKDIR /app/scripts
