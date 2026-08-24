# Changelog

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
