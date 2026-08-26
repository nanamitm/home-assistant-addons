#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

# Where the tarball was unpacked.  Overridable so that the argument building
# below can be exercised outside the container.
SDRCONNECT_DIR="${SDRCONNECT_DIR:-/opt/sdrconnect}"

# SDRconnect keeps its settings under $HOME.  /data is the add-on's own volume,
# so pointing HOME at it is what makes those settings survive a restart or an
# add-on update -- the container filesystem does not.
export HOME=/data
mkdir -p "${HOME}"

bashio::log.level "$(bashio::config 'log_level')"

MODE="$(bashio::config 'mode')"
declare -a ARGS

# --hwser and friends are the documented SDRconnect server options; every one of
# them is optional, and anything left unset stays at the receiver's own default
# rather than being forced to a value the user never asked for.
add_value_arg() {
    local key="${1}" flag="${2}"
    if bashio::config.has_value "${key}"; then
        ARGS+=("--${flag}=$(bashio::config "${key}")")
    fi
}

# The boolean options take 0 or 1 rather than being bare flags, so an option the
# user explicitly turned off is passed as =0 instead of being dropped.
add_bool_arg() {
    local key="${1}" flag="${2}"
    if bashio::config.true "${key}"; then
        ARGS+=("--${flag}=1")
    elif bashio::config.false "${key}"; then
        ARGS+=("--${flag}=0")
    fi
}

if [ "${MODE}" = "headless" ]; then
    # Headless mode serves the SDRconnect user interface to a browser over a
    # websocket and is configured from that interface, so the tuner options
    # below are deliberately not passed to it.
    BINARY="${SDRCONNECT_DIR}/SDRconnect_headless"
    ARGS+=("--websocket_port=$(bashio::config 'websocket_port')")
else
    BINARY="${SDRCONNECT_DIR}/SDRconnect"
    ARGS+=(--server)
    ARGS+=("--port=$(bashio::config 'port')")
    add_value_arg 'bind_address'    'ip'
    add_value_arg 'device_serial'   'hwser'
    add_value_arg 'samplerate'      'samplerate'
    add_value_arg 'centerfrequency' 'centerfrequency'
    add_value_arg 'antenna'         'antenna'
    add_value_arg 'lnastate'        'lnastate'
    add_value_arg 'ifgr'            'ifgr'
    add_value_arg 'setpoint'        'setpoint'
    add_value_arg 'max_clients'     'max-clients'
    add_bool_arg  'ifagc'           'ifagc'
    add_bool_arg  'biast'           'biast'
    add_bool_arg  'rfnotch'         'rfnotch'
    add_bool_arg  'dabnotch'        'dabnotch'
    if bashio::config.true 'exclusive'; then
        ARGS+=(--exclusive)
    fi
fi

if bashio::config.has_value 'extra_args'; then
    # Deliberately unquoted: this is a command line the user typed, and it is
    # meant to split into separate arguments.
    # shellcheck disable=SC2206
    ARGS+=($(bashio::config 'extra_args'))
fi

cd "${SDRCONNECT_DIR}"

# Printed on every start.  Which receivers the add-on can actually see -- and
# their serial numbers, which is what `device_serial` wants -- is the first
# thing anyone needs when a client connects to a server with no hardware.
# The timeout is a seatbelt: --listdevices is documented to print the list and
# exit, and if a future build ever kept running instead, the add-on would hang
# here before ever starting the server.
bashio::log.info "Receivers visible to the add-on:"
timeout 20 "${SDRCONNECT_DIR}/SDRconnect" --server --listdevices || \
    bashio::log.warning "Could not list receivers. Is an RSP plugged in?"

if [ "${MODE}" = "headless" ]; then
    bashio::log.info "Starting SDRconnect headless on websocket port $(bashio::config 'websocket_port')"
else
    bashio::log.info "Starting SDRconnect server on TCP port $(bashio::config 'port')"
fi

exec "${BINARY}" "${ARGS[@]}"
