FROM python:3.11-slim
WORKDIR /app
COPY shared/ ./shared/
COPY services/cosmos-vlm/ ./services/cosmos-vlm/
WORKDIR /app/services/cosmos-vlm
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "main.py"]
