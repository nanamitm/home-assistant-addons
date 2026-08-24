#!/usr/bin/with-contenv bashio
set -e

export GPSD_HOST="$(bashio::config 'gpsd_host')"
export GPSD_PORT="$(bashio::config 'gpsd_port')"
export RECONNECT_INTERVAL="$(bashio::config 'reconnect_interval')"
export RAW_JSON="$(bashio::config 'raw_json')"

mkdir -p /tmp/nginx_client_body /tmp/nginx_proxy /run/nginx

python3 /opt/xgps/server.py &
APP_PID=$!

trap 'kill "${APP_PID}" 2>/dev/null || true' EXIT INT TERM

if ! nginx -t; then
    bashio::log.fatal "Invalid nginx configuration"
    exit 1
fi

bashio::log.info "Starting xgps Web for gpsd at ${GPSD_HOST}:${GPSD_PORT}"
nginx -g "daemon off;" &
NGINX_PID=$!

wait -n "${APP_PID}" "${NGINX_PID}"
STATUS=$?
kill "${APP_PID}" "${NGINX_PID}" 2>/dev/null || true
wait || true
exit "${STATUS}"
