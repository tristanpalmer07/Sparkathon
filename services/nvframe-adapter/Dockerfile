# Compiles proto/schema.proto (vendored from
# video-search-and-summarization/libs/nvschema/protobuf/schema.proto)
# at build time so this image has no runtime dependency on the VSS repo
# being checked out alongside it.
FROM python:3.11-slim
WORKDIR /app
COPY shared/ ./shared/
COPY services/nvframe-adapter/ ./services/nvframe-adapter/
WORKDIR /app/services/nvframe-adapter
RUN pip install --no-cache-dir -r requirements.txt \
 && python -m grpc_tools.protoc -I proto --python_out=. proto/schema.proto
CMD ["python", "main.py"]
