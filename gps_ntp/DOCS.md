# GPS NTP Server

This experimental app runs `gpsd` and `chronyd` in the same container. NMEA is
passed through gpsd SHM 0. PPS can use gpsd SHM 1 or be read directly by chrony.

## Prerequisites

The Home Assistant host must expose both the serial device and `/dev/pps0`. If
Home Assistant OS runs in a VM, configure USB/PPS passthrough first. The app
cannot create a host PPS device.

The app requests `SYS_TIME` because chrony adjusts the host clock. Review this
permission before installation. Make sure no other service is listening on the
host's UDP port 123.

## Initial configuration

Select the stable serial path shown by the Home Assistant hardware page. A
`/dev/serial/by-id/...` path is preferred over `/dev/ttyUSB0` when available.

Set `allow_network` to the smallest LAN subnet which needs NTP, for example
`192.168.10.0/24`. Do not expose UDP port 123 to the internet.

`pps_via_gpsd: true` matches configurations using gpsd SHM 1. Set it to `false`
to let chrony read `/dev/pps0` directly and lock it to the NMEA source.

Port 2947 is disabled by default. To use xgps or another gpsd client, enable
`gpsd_remote_access` and assign host port 2947 in the Network section.

## Verification

After startup, use the app terminal or logs to diagnose the sources:

```text
chronyc tracking
chronyc sources -v
chronyc sourcestats -v
gpspipe -w -n 10
```

From another LAN host, query the Home Assistant host address with an NTP client.
Do not tune `nmea_offset` or `pps_offset` until GPS has a stable fix and PPS is
visible consistently.

## Known hardware-dependent work

- Confirm the actual serial and PPS device paths.
- Confirm whether gpsd produces SHM 1 on the target hardware.
- Compare SHM PPS with chrony's direct PPS driver.
- Tune offsets only after collecting measurements over several hours.
