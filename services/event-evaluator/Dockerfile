FROM python:3.11-slim
WORKDIR /app
COPY shared/ ./shared/
COPY services/event-evaluator/ ./services/event-evaluator/
WORKDIR /app/services/event-evaluator
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "main.py"]
