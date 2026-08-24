# Home Assistant automation examples

[`examples/automations.yaml`](examples/automations.yaml) contains four optional
notification automations:

- gpsd disconnected or the MQTT device unavailable for 30 seconds;
- gpsd data stale for an additional 15 seconds;
- no 2D/3D fix for two minutes;
- moderate or poor positioning quality for five minutes.

The examples use Home Assistant's built-in persistent notifications, so no
mobile notification integration is required. To send notifications to a
phone, replace `persistent_notification.create` with the relevant
`notify.mobile_app_...` action and remove `notification_id` if that notify
service does not accept it.

Copy the list entries into `automations.yaml`, then reload automations from
Home Assistant. When using the automation UI's YAML editor, copy one list item
at a time and remove its leading `-`.

Entity IDs assume the default add-on `device_id` of `xgps_web`. The delays are
deliberately longer than short receiver transitions and can be adjusted for
the installation. The stale sensor itself turns on after 15 seconds without a
gpsd packet; the example waits another 15 seconds before notifying.
