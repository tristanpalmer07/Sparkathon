FROM python:3.11-slim
WORKDIR /app
COPY shared/ ./shared/
COPY services/clip-retrieval/ ./services/clip-retrieval/
WORKDIR /app/services/clip-retrieval
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "main.py"]
