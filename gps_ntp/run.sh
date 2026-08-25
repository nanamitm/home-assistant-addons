#!/usr/bin/with-contenv bash
set -euo pipefail

GPS_DEVICE="$(bashio::config gps_device)"
PPS_DEVICE="$(bashio::config pps_device)"
USE_PPS="$(bashio::config use_pps)"
PPS_VIA_GPSD="$(bashio::config pps_via_gpsd)"
REMOTE_ACCESS="$(bashio::config gpsd_remote_access)"

if [[ ! -c "${GPS_DEVICE}" ]]; then
    bashio::exit.nok "GPS serial device not found or is not a character device: ${GPS_DEVICE}"
fi

if bashio::var.true "${USE_PPS}" && [[ ! -c "${PPS_DEVICE}" ]]; then
    bashio::exit.nok "PPS is enabled but its device was not found: ${PPS_DEVICE}"
fi

/usr/local/bin/render-chrony-config /data/options.json /etc/chrony/chrony.conf

gpsd_args=(-N -n -F /run/gpsd.sock)
if bashio::var.true "${REMOTE_ACCESS}"; then
    gpsd_args+=(-G)
fi
gpsd_args+=("${GPS_DEVICE}")
if bashio::var.true "${USE_PPS}" && bashio::var.true "${PPS_VIA_GPSD}"; then
    gpsd_args+=("${PPS_DEVICE}")
fi

bashio::log.info "Starting gpsd with ${GPS_DEVICE}"
gpsd "${gpsd_args[@]}" &
gpsd_pid=$!

cleanup() {
    kill "${gpsd_pid}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for attempt in $(seq 1 20); do
    [[ -S /run/gpsd.sock ]] && break
    if ! kill -0 "${gpsd_pid}" 2>/dev/null; then
        bashio::exit.nok "gpsd stopped during startup"
    fi
    sleep 0.25
done

if [[ ! -S /run/gpsd.sock ]]; then
    bashio::exit.nok "gpsd did not create /run/gpsd.sock"
fi

bashio::log.info "Starting chronyd; NTP is available on UDP port 123"
chronyd -d -f /etc/chrony/chrony.conf &
chrony_pid=$!

set +e
wait -n "${gpsd_pid}" "${chrony_pid}"
status=$?
set -e
kill "${gpsd_pid}" "${chrony_pid}" 2>/dev/null || true
wait || true
exit "${status}"
