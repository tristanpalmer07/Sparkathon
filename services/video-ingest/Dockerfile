FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY shared/ ./shared/
COPY services/video-ingest/ ./services/video-ingest/
WORKDIR /app/services/video-ingest
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "main.py"]
