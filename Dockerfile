FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY public ./public
COPY storage.py video_cache.py server.py prepare_data.py ./
EXPOSE 8768
CMD ["python", "server.py", "--config", "/config/config.local.json", "--host", "0.0.0.0"]
