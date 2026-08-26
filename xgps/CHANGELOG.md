# Changelog

## 1.1.0

- Fixed the optional device tracker reporting `not_home` inside every zone.
- Fixed the gpsd connection hanging forever when a peer went away silently.
- Fixed unexpected errors in the gpsd and status loops going unlogged and
  leaving the add-on running with no data.
- Fixed a crashed background task being invisible to the Supervisor watchdog.
- Fixed the shutdown path in `run.sh` being skipped, which left nginx running.
- Stopped republishing the whole MQTT state document once a second during a
  gpsd outage.
- Stopped one unresponsive browser from blocking every other viewer and the
  gpsd read loop behind it.
- Fixed the web interface and the Home Assistant sensor disagreeing about
  altitude; both now prefer height above mean sea level.
- Fixed SKY and TPV overwriting each other's HDOP.
- Fixed assets failing to load when the ingress page was opened without a
  trailing slash.
- Fixed nginx requesting a connection upgrade on ordinary requests.
- Added MQTT over TLS, automatic for the Supervisor broker and configurable
  through `mqtt_ssl` for an external one.
- Added visible IMES and used IRNSS satellite counts.
- Reported the add-on version from the image build instead of a hardcoded
  literal.
- Pinned the base image per architecture instead of relying on a multi-arch
  tag resolving on the build machine.

## 1.0.0

- Promoted xgps Web from experimental to stable.
- Added a complete Home Assistant dashboard example using built-in cards only.
- Added a PDOP gauge, DOP history, GNSS counts, diagnostics and optional map examples.
- Added notification automation examples for connection, stale data, fix and quality problems.
- Added CI validation for the published dashboard and automation YAML examples.

## 0.8.0

- Added Home Assistant entities for used GPS, Galileo, BeiDou, QZSS and GLONASS satellite counts.
- Added a Home Assistant entity for the visible SBAS satellite count.
- Kept per-system counts stable across gpsd DOP-only SKY reports.

## 0.7.0

- Added diagnostic sensors for data age, GPSD reconnect count and receiver information.
- Added problem binary sensors for stale data, unavailable fixes and degraded positioning quality.
- Added receiver driver, firmware/subtype, device path, activation and baud-rate attributes.
- Avoided duplicate MQTT publishes when diagnostic state has not changed.

## 0.6.0

- Added PDOP, VDOP and GDOP to the web position panel and Home Assistant entities.
- Added a positioning-quality entity and localized web display based on PDOP.
- Classified quality as excellent below 1, good below 2, moderate below 5 and poor otherwise.

## 0.5.2

- Fixed the web position panel to display HDOP received in gpsd SKY reports.
- Included the latest HDOP in live WebSocket updates and initial snapshots.

## 0.5.1

- Fixed the Home Assistant HDOP sensor by reading HDOP from gpsd SKY reports.
- Handled DOP-only SKY reports without resetting the retained satellite counts.

## 0.5.0

- Added optional Home Assistant entity integration through MQTT Discovery.
- Added GPSD connection, fix, satellite, position and accuracy sensors grouped under one device.
- Added automatic Supervisor MQTT credential discovery and external broker overrides.
- Added an opt-in GPS `device_tracker` with retained Discovery cleanup when disabled.
- Added retained state and MQTT availability reporting with reconnect republishing.

## 0.4.0

- Expanded the satellite table with SVID, sigId, Quality, prRes and Health.
- Added separate received and used satellite counts.
- Added persistent ascending and descending sorting for every table column.
- Added GNSS type and used-only table filters.
- Added a compact mobile table layout that prioritizes key columns.

## 0.3.1

- Fixed the UI remaining in a reconnecting/stale state after a fast manual reconnect.
- Disabled the reconnect button while a reconnect is already in progress.

## 0.3.0

- Added separate WebSocket and gpsd connection states.
- Added the configured gpsd endpoint and last packet time to the header.
- Added a stale-data warning and dimmed data panels after 15 seconds without updates.
- Localized gpsd connection states in English and Japanese.
- Added a manual gpsd reconnect button.

## 0.2.3

- Made GNSS type legend shapes neutral and added a separate signal-strength color legend.

## 0.2.2

- Matched sky-view and legend marker shapes to the original xgps-qt GNSS types.

## 0.2.1

- Added persistent GNSS type filters for the sky view.

## 0.2.0

- Added Japanese localization for the web interface.
- Added add-on icon and logo.
- Added a health endpoint and Supervisor watchdog.
- Added DMS coordinates, local time, HDOP, error, climb and used-satellite displays.
- Added pre-built amd64 and aarch64 images published to GHCR.

## 0.1.1

- Reduced the satellite marker size in the sky view.

## 0.1.0

- Initial experimental release.
- gpsd SKY and TPV support.
- Ingress-native sky view, position panel, satellite table and optional raw JSON.
