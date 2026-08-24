# xgps Web

xgps Web displays GPS/GNSS information received from an existing gpsd server.
It does not require direct access to a USB receiver.

## Setup

1. Make sure gpsd accepts TCP clients from the Home Assistant host.
2. Set **gpsd host** and **gpsd port** in the Configuration tab.
3. Start the add-on and open **GPS Satellites** from the sidebar.

The standard gpsd port is `2947`. Do not expose gpsd to the public internet;
use a trusted local network or a secured tunnel.

## Options

| Option | Default | Description |
|---|---:|---|
| `gpsd_host` | `192.168.1.10` | gpsd hostname or IP address. |
| `gpsd_port` | `2947` | gpsd TCP port. |
| `reconnect_interval` | `5` | Delay in seconds between connection attempts. |
| `raw_json` | `false` | Expose recent raw packets in the UI. |

Display preferences such as projection, grid, units, labels and rotation are
stored locally in the browser.

## Connection monitoring

The header shows the WebSocket state, configured gpsd endpoint and time of the
last received packet. Position and satellite panels are dimmed when gpsd is
disconnected or no packet has arrived for 15 seconds. **Reconnect gpsd** closes
the current gpsd connection and starts a new connection attempt immediately.

## Troubleshooting

If the status remains disconnected, verify gpsd's listen address, firewall and
port. A gpsd instance bound only to `127.0.0.1` cannot be reached from this
add-on.

## Attribution

The behavior and visual conventions are derived from
[nanamitm/xgps-qt](https://github.com/nanamitm/xgps-qt), licensed under MIT.
