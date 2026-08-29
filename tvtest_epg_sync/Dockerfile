ARG BUILD_FROM
FROM ${BUILD_FROM}

LABEL io.hass.type="app"

# The server uses only the Python standard library, so there is nothing to
# install beyond the interpreter itself.
RUN apk add --no-cache python3

COPY app /opt/tvtest_epg_sync
COPY run.sh /
RUN chmod a+x /run.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["/run.sh"]
