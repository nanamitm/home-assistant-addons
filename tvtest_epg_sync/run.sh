#!/usr/bin/with-contenv bashio
set -e

export EPGSYNC_TOKEN="$(bashio::config 'token' '')"
export EPGSYNC_LOG_LEVEL="$(bashio::config 'log_level' 'info')"
export EPGSYNC_RETENTION_DAYS="$(bashio::config 'retention_days' '14')"

# /data survives add-on restarts and is included in Home Assistant backups.
export EPGSYNC_DATA_DIR="/data/epg"
export EPGSYNC_API_PORT="8077"
export EPGSYNC_INGRESS_PORT="8099"

mkdir -p "${EPGSYNC_DATA_DIR}"

if bashio::config.has_value 'token'; then
    bashio::log.info "TVTest clients must present the configured token."
else
    bashio::log.warning "No token is set; any host that can reach port 8077 may read and write EPG."
fi

bashio::log.info "Starting TVTest EPG Sync on port ${EPGSYNC_API_PORT}"

exec python3 /opt/tvtest_epg_sync/server.py
