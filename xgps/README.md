# xgps Web

An Ingress-native GPS/GNSS viewer for Home Assistant, based on the behavior of
[xgps-qt](https://github.com/nanamitm/xgps-qt).

xgps Web connects to an existing gpsd server and provides:

- an interactive sky view and detailed satellite table;
- position, accuracy, DOP and receiver diagnostics;
- optional Home Assistant entities through MQTT Discovery;
- connection, stale-data, fix and quality problem sensors;
- GNSS-specific satellite counts and an optional GPS device tracker.

See [DOCS.md](DOCS.md) for setup, [DASHBOARD.md](DASHBOARD.md) for a built-in
Lovelace dashboard, and [AUTOMATIONS.md](AUTOMATIONS.md) for notification
examples.
