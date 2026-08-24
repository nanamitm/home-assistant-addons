FROM ghcr.io/home-assistant/base:3.22

LABEL io.hass.type="app"

RUN apk add --no-cache nginx python3 py3-aiohttp

COPY app /opt/xgps
COPY nginx.conf /etc/nginx/nginx.conf
COPY run.sh /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
