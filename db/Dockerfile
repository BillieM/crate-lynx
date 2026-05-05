FROM postgres:16-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN apk add --no-cache \
    python3 \
    py3-pip

COPY app/requirements.txt /tmp/requirements.txt

RUN pip3 install --break-system-packages --upgrade pip \
    && pip3 install --break-system-packages -r /tmp/requirements.txt

COPY db /srv/db
COPY app/app /srv/app

RUN chmod +x /srv/db/entrypoint.sh

ENTRYPOINT ["/srv/db/entrypoint.sh"]
CMD ["postgres"]
