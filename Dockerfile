FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client && apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ARG BACKEND_REVISION=development
ENV BACKEND_REVISION=$BACKEND_REVISION DATABASE_URL=sqlite:////data/app.db MEDIA_ROOT=/data/media MINIWORLDS_GIT_ROOT=/data/git BASE_URL=http://localhost:8000 COOKIE_SECURE=1 PYTHONDONTWRITEBYTECODE=1
RUN chmod -R a+rX /app && groupadd --gid 10001 miniworlds && useradd --uid 10001 --gid miniworlds --no-create-home miniworlds && mkdir -p /data /backups && chown miniworlds:miniworlds /data /backups
VOLUME ["/data"]
EXPOSE 8000
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
