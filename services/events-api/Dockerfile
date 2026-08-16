FROM python:3.11-slim
WORKDIR /app
COPY services/events-api/ ./services/events-api/
WORKDIR /app/services/events-api
RUN pip install --no-cache-dir -r requirements.txt
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
