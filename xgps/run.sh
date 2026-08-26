#!/usr/bin/with-contenv bashio
set -e

export GPSD_HOST="$(bashio::config 'gpsd_host')"
export GPSD_PORT="$(bashio::config 'gpsd_port')"
export RECONNECT_INTERVAL="$(bashio::config 'reconnect_interval')"
export RAW_JSON="$(bashio::config 'raw_json')"
export MQTT_ENABLED="$(bashio::config 'mqtt_enabled')"
export DEVICE_NAME="$(bashio::config 'device_name')"
export DEVICE_ID="$(bashio::config 'device_id')"
export DEVICE_TRACKER="$(bashio::config 'device_tracker')"
export DISCOVERY_PREFIX="$(bashio::config 'discovery_prefix' 'homeassistant')"

if bashio::config.true 'mqtt_enabled'; then
    if bashio::config.has_value 'mqtt_host'; then
        bashio::log.info "Using the MQTT broker from the add-on options."
        export MQTT_HOST="$(bashio::config 'mqtt_host')"
        export MQTT_PORT="$(bashio::config 'mqtt_port' '1883')"
        export MQTT_USER="$(bashio::config 'mqtt_user' '')"
        export MQTT_PASS="$(bashio::config 'mqtt_password' '')"
    else
        if ! bashio::services.available 'mqtt'; then
            bashio::log.fatal "MQTT entities are enabled, but no MQTT service was found."
            bashio::log.fatal "Install Mosquitto or configure mqtt_host and credentials."
            bashio::exit.nok
        fi
        bashio::log.info "Using the MQTT broker provided by the Supervisor."
        export MQTT_HOST="$(bashio::services mqtt 'host')"
        export MQTT_PORT="$(bashio::services mqtt 'port')"
        export MQTT_USER="$(bashio::services mqtt 'username')"
        export MQTT_PASS="$(bashio::services mqtt 'password')"
    fi
fi

mkdir -p /tmp/nginx_client_body /tmp/nginx_proxy /run/nginx

if ! nginx -t; then
    bashio::log.fatal "Invalid nginx configuration"
    bashio::exit.nok
fi

APP_PID=""
NGINX_PID=""

cleanup() {
    if [ -n "${APP_PID}" ]; then
        kill "${APP_PID}" 2>/dev/null || true
    fi
    if [ -n "${NGINX_PID}" ]; then
        kill "${NGINX_PID}" 2>/dev/null || true
    fi
    return 0
}

trap cleanup EXIT INT TERM

python3 /opt/xgps/server.py &
APP_PID=$!

bashio::log.info "Starting xgps Web for gpsd at ${GPSD_HOST}:${GPSD_PORT}"
nginx -g "daemon off;" &
NGINX_PID=$!

# `set -e` would abort the script on a non-zero `wait -n`, skipping the
# shutdown below, so capture the status instead of letting it propagate.
STATUS=0
wait -n "${APP_PID}" "${NGINX_PID}" || STATUS=$?

bashio::log.info "A service exited with status ${STATUS}; stopping the add-on."
cleanup
wait || true
exit "${STATUS}"
