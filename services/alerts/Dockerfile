FROM python:3.11-slim
WORKDIR /app
COPY shared/ ./shared/
COPY services/alerts/ ./services/alerts/
WORKDIR /app/services/alerts
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "main.py"]
