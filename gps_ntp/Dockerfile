FROM ghcr.io/home-assistant/base:3.22

LABEL io.hass.type="app"

RUN apk add --no-cache chrony gpsd gpsd-clients

COPY rootfs /
COPY run.sh /
RUN chmod a+x /run.sh /usr/local/bin/render-chrony-config

CMD ["/run.sh"]
