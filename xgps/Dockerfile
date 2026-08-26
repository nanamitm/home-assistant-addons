# The Home Assistant builder action passes BUILD_ARCH and BUILD_VERSION; it
# does not read build.yaml and does not pass BUILD_FROM. Selecting the base
# by architecture keeps each published image pinned to its own base rather
# than to whatever a multi-arch tag resolves to on the build machine.
ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:3.22

# Passed by the builder action. It is the single source of the version
# reported over MQTT.
ARG BUILD_VERSION
ENV XGPS_VERSION=${BUILD_VERSION}

LABEL io.hass.type="app"

# ca-certificates backs the default TLS trust store used for MQTT over TLS.
RUN apk add --no-cache ca-certificates nginx python3 py3-aiohttp py3-paho-mqtt

COPY app /opt/xgps
COPY nginx.conf /etc/nginx/nginx.conf
COPY run.sh /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
