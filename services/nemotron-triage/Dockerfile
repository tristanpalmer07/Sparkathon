FROM python:3.11-slim
WORKDIR /app
COPY shared/ ./shared/
COPY services/nemotron-triage/ ./services/nemotron-triage/
WORKDIR /app/services/nemotron-triage
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "main.py"]
