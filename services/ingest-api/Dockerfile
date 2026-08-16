# Base on the official docker CLI image (Alpine) so `docker compose run`
# is available for driving the existing video-ingest one-shot job from
# inside this container (docker-outside-of-docker via the host socket) —
# see main.py's docstring for the path-mirroring reason this works.
FROM docker:27-cli
RUN apk add --no-cache python3 py3-pip ffmpeg
WORKDIR /app
COPY services/ingest-api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt
COPY services/ingest-api/main.py ./main.py
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
