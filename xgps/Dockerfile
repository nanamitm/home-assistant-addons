ARG BUILD_FROM
FROM ${BUILD_FROM}

LABEL io.hass.type="app"

RUN apk add --no-cache nginx python3 py3-aiohttp py3-paho-mqtt

COPY app /opt/xgps
COPY nginx.conf /etc/nginx/nginx.conf
COPY run.sh /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
