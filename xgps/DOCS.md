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
| `mqtt_enabled` | `false` | Publish Home Assistant entities using MQTT Discovery. |
| `device_name` | `xgps Web` | Device name shown in Home Assistant. |
| `device_id` | `xgps_web` | Stable lowercase identifier for topics and entity unique IDs. |
| `device_tracker` | `false` | Also publish the GPS position as a device tracker. |

The optional advanced settings `discovery_prefix`, `mqtt_host`, `mqtt_port`,
`mqtt_ssl`, `mqtt_user` and `mqtt_password` are available in the Configuration
tab. When `mqtt_host` is empty, the add-on automatically uses the MQTT service
supplied by Home Assistant Supervisor, including whether that broker expects
TLS. `mqtt_ssl` applies to an external broker set through `mqtt_host`, and
verifies the broker certificate against the system trust store.

Anyone with access to Home Assistant can open this add-on and see the receiver
position, including non-administrators. Raw JSON, when enabled, exposes the
full gpsd packet stream the same way.

## Home Assistant entities

Enable **Home Assistant entities** and restart the add-on. MQTT Discovery
creates one **xgps Web** device containing GPSD connection, fix mode, visible
and used satellite counts, latitude, longitude, altitude, speed, track, HDOP,
PDOP, VDOP, GDOP, positioning quality, horizontal error and last-update
sensors.

Positioning quality is derived from PDOP and is intended as a compact status
for dashboards and automations: `excellent` below 1, `good` below 2,
`moderate` below 5 and `poor` at 5 or above. The individual DOP values remain
available when more detailed diagnostics are needed.

### Diagnostics and problem sensors

The device also exposes diagnostic entities suitable for dashboards and
automations:

- **Data age** reports whole seconds since the last gpsd packet. **Data stale**
  becomes a problem after 15 seconds without data. Data age is refreshed at
  most every 30 seconds so that an outage does not republish the state
  document once a second; **Data stale** still changes the moment data stops.
- **GPSD reconnect count** counts connection attempts after the initial one for
  the current add-on run.
- **Receiver** reports the gpsd receiver driver or subtype and includes the
  available device path, driver, firmware/subtype, activation time and baud
  rate as attributes.
- **Fix unavailable** is a problem unless gpsd reports a 2D or 3D fix.
- **Positioning quality degraded** is a problem for `moderate` or `poor` PDOP
  quality. `excellent` and `good` are treated as normal.

Diagnostic entities are grouped under the same xgps Web device and can be used
directly as Home Assistant automation triggers. MQTT availability remains the
authoritative indication that the add-on itself can reach the broker.

### Satellite-system entities

The device publishes separate used-satellite counts for GPS, Galileo, BeiDou,
QZSS, GLONASS and IRNSS. SBAS and IMES are published as visible-satellite
counts because neither contributes to the navigation solution, while their
signals remain useful reception diagnostics. These values follow the `gnssid` identifiers
reported by gpsd and update with each satellite-bearing SKY report.

The optional device tracker is disabled by default because the gpsd receiver
may represent a fixed installation rather than a moving device. Enable it only
when its coordinates should be used as a tracked location. Disabling it again
removes its retained Discovery configuration. The tracker publishes
coordinates only, so Home Assistant resolves the zone itself and the entity
shows `home`, a zone name or `not_home` as appropriate.

Entity states are published retained, so the last known position and fix stay
visible after gpsd becomes unreachable. Gate automations that must not act on
an old position on **Data stale** or **GPSD connection** rather than on the
position sensors alone.

Changing `device_id` creates a new set of entity unique IDs. Choose it once and
keep it stable. MQTT credentials are not written to the add-on log.

## Dashboard and automation examples

- [Dashboard example](DASHBOARD.md) includes status, position, a PDOP gauge,
  DOP history, GNSS-specific counts, diagnostics and an optional map.
- [Automation examples](AUTOMATIONS.md) provide persistent notifications for
  gpsd disconnection, stale data, unavailable fixes and degraded quality.

Both examples use Home Assistant built-in features and require no custom
cards. Their entity IDs assume the default `device_id` of `xgps_web`.

Display preferences such as projection, grid, units, labels and rotation are
stored locally in the browser.

## Connection monitoring

The header shows the WebSocket state, configured gpsd endpoint and time of the
last received packet. Position and satellite panels are dimmed when gpsd is
disconnected or no packet has arrived for 15 seconds. **Reconnect gpsd** closes
the current gpsd connection and starts a new connection attempt immediately.

## Satellite table

The table includes GNSS, SVID, sigId, PRN, elevation, azimuth, SNR, Quality,
prRes, Health and Used fields when gpsd provides them. Select a column heading
to toggle ascending or descending sorting. The selected order and the GNSS and
used-only filters are saved in the browser. Less important diagnostic columns
are hidden on narrow mobile screens and remain available on wider displays.

## Troubleshooting

If the status remains disconnected, verify gpsd's listen address, firewall and
port. A gpsd instance bound only to `127.0.0.1` cannot be reached from this
add-on.

If gpsd stops sending without closing the connection, the add-on gives up
after 30 seconds of silence, reports `No gpsd data`, and reconnects.

The Supervisor watchdog polls `/health`. That endpoint stays healthy while
gpsd itself is unreachable, since a remote outage is not the add-on's fault,
and reports a failure only when one of the add-on's own background tasks has
stopped, which restarts the add-on.

## Attribution

The behavior and visual conventions are derived from
[nanamitm/xgps-qt](https://github.com/nanamitm/xgps-qt), licensed under MIT.
