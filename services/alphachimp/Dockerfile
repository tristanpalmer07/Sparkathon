# Stub/CPU image — MODEL_BACKEND=stub (backend.py). For the real model,
# use Dockerfile.pytorch instead, which matches design doc §5.1 exactly
# (CUDA 11.1 base, torch==1.9.1+cu111, mmcv==2.1.0, vendored AlphaChimp repo).
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY shared/ ./shared/
COPY services/alphachimp/ ./services/alphachimp/
WORKDIR /app/services/alphachimp
RUN pip install --no-cache-dir -r requirements.txt
ENV MODEL_BACKEND=stub
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
