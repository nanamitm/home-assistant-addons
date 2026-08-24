# Home Assistant dashboard example

The example uses only cards included with Home Assistant. No custom frontend
components are required.

1. Enable **Home Assistant entities** in the xgps Web add-on and restart it.
2. Open the target dashboard, select **Edit dashboard**, open the three-dot
   menu and choose **Raw configuration editor**.
3. Copy the contents of [`examples/dashboard.yaml`](examples/dashboard.yaml),
   or copy individual cards into an existing view.

The entity IDs assume the default `device_id` of `xgps_web`. Adjust them if the
add-on uses another device ID.

The final map card requires the optional **Device tracker** setting. Delete the
map card when the receiver is fixed or the tracker is disabled. Enabling a
tracker for a stationary receiver is normally unnecessary.

## PDOP gauge

The gauge follows the same thresholds as the positioning-quality sensor:

- Green: below 2 (`excellent` or `good`)
- Yellow: 2 to below 5 (`moderate`)
- Red: 5 or above (`poor`)

The gauge maximum is 10 so severely degraded values remain visually obvious.
The underlying sensor still retains values above 10.
