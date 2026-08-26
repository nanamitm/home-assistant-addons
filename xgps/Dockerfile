ARG BUILD_FROM
FROM ${BUILD_FROM}

# Passed by the Home Assistant builder, and by the Supervisor for local
# builds. It is the single source of the version reported over MQTT.
ARG BUILD_VERSION
ENV XGPS_VERSION=${BUILD_VERSION}

LABEL io.hass.type="app"

RUN apk add --no-cache nginx python3 py3-aiohttp py3-paho-mqtt

COPY app /opt/xgps
COPY nginx.conf /etc/nginx/nginx.conf
COPY run.sh /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
