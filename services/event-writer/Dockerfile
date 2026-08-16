FROM python:3.11-slim
WORKDIR /app
COPY shared/ ./shared/
COPY services/event-writer/ ./services/event-writer/
WORKDIR /app/services/event-writer
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "main.py"]
