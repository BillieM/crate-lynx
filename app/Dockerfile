FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ffmpeg \
        gcc \
        libchromaprint1 \
        libchromaprint-tools \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt

COPY app /srv/app/app
COPY entrypoint.sh /srv/app/entrypoint.sh

RUN chmod +x /srv/app/entrypoint.sh

EXPOSE 8000

CMD ["/srv/app/entrypoint.sh"]
