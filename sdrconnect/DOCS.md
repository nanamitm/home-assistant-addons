# SDRconnect Server

This add-on runs the SDRplay SDRconnect server against an RSP receiver plugged
into the Home Assistant host, so that the receiver can be tuned from SDRconnect
on another machine.

## Requirements

- An SDRplay RSP receiver (RSP1A, RSP1B, RSPdx, RSPduo, …) on a host USB port.
- A 64-bit host: `amd64` or `aarch64`. SDRplay does not publish a 32-bit ARM
  build, so armv7 boards such as the Raspberry Pi 3 in 32-bit mode cannot run
  this add-on.
- Room for the build: the download is about 120 MB and the resulting image is
  roughly 350 MB.

## Installation

1. Add this repository to the add-on store and install **SDRconnect Server**.
2. The add-on has no prebuilt image, so installing it builds it locally. On a
   Raspberry Pi expect a few minutes, most of it spent downloading.
3. Start the add-on and open the log. Every start prints the receivers it can
   see, including their serial numbers:

   ```text
   Receivers visible to the add-on:
   ...
   Starting SDRconnect server on TCP port 50000
   ```

4. In the SDRconnect client, use *Discover* on the same network, or enter the
   Home Assistant host's IP address and port 50000 by hand.

### Why it is built locally

The SDRplay licence grants the right to run and display the software; it does
not grant the right to redistribute it. Publishing a prebuilt add-on image to a
container registry would do exactly that, so the add-on ships a Dockerfile that
downloads the official package from sdrplay.com during the build instead. The
checksum SDRplay publishes alongside the package is verified as part of the
build.

Note also clause 6 of the licence: the software may send details of the radio
device to an SDRplay server and alert users to firmware updates.

## Options

### Mode and network

| Option | Default | Description |
|---|---|---|
| `mode` | `server` | `server` publishes the receiver on a TCP port for SDRconnect clients. `headless` serves the SDRconnect user interface to a browser over a websocket. |
| `port` | `50000` | TCP port for server mode. |
| `websocket_port` | `5454` | Websocket port for headless mode. |
| `bind_address` | — | Address to listen on. Empty means every interface. |
| `log_level` | `info` | Verbosity of the add-on's own log lines. |

The add-on uses host networking, so these ports are opened directly on the Home
Assistant host and are not listed in the add-on's Network panel.

### Receiver settings

These apply to server mode only. Headless mode is configured from the interface
it serves. Anything left empty stays at the receiver's own default, and in
server mode a connecting client can usually change it — unless `exclusive` is
on.

| Option | Description |
|---|---|
| `device_serial` | Serial number of the receiver to use, from the list printed at start-up. Needed when more than one RSP is connected, or to keep this add-on off a receiver another add-on is using. |
| `samplerate` | Sample rate in Hz. |
| `centerfrequency` | Centre frequency in Hz at start-up. |
| `antenna` | Antenna input number. |
| `lnastate` | LNA state. The useful range depends on the model and band. |
| `ifgr` | IF gain reduction in dB (20–59). Applies when `ifagc` is off. |
| `ifagc` | IF AGC on or off. |
| `setpoint` | AGC set point in dBfs (−72–0). |
| `biast` | Bias-T power on the antenna port. Leave off unless a powered antenna or LNA is attached. |
| `rfnotch` | Broadcast FM/MW notch filter. |
| `dabnotch` | DAB notch filter. |
| `exclusive` | Prevent connecting clients from changing the hardware settings above. |
| `max_clients` | Maximum number of simultaneous clients. |
| `extra_args` | Extra command line arguments passed through verbatim. |

## Notes and limitations

**No sidebar panel.** Server mode speaks SDRconnect's own TCP protocol, which
ingress cannot proxy, so the add-on has no Home Assistant panel. Headless mode
is reached directly at `http://<host>:5454`.

**One user of the receiver at a time.** An RSP belongs to whichever program
claims it first. If another add-on — an ADS-B or AIS receiver, for example —
is already using the receiver, SDRconnect will not see it, and the reverse is
just as true. Use `device_serial` when several receivers are connected.

**No watchdog.** The listening port is an option, and a watchdog cannot read
options; a hard-coded one would restart the add-on in a loop as soon as the port
changed.

**USB permissions.** The add-on runs with protection mode on and gets the host's
USB bus through the `usb` and `udev` flags, which is enough for libusb. If a
receiver is visible to the host but never appears in the add-on's start-up list,
turning protection mode off in the add-on's Info panel is the next thing to try,
and worth reporting as an issue.

## Updating to a new SDRconnect build

SDRplay publishes each build under a hash-suffixed file name and removes older
ones, so a pinned URL stops working when a new build is released. To move to a
new build:

1. Open the Linux download page for either architecture — the two bundles carry
   the same build:
   - x64: <https://sdrplay.com/download/sdrconnect-linux-x64-files/>
   - arm64: <https://sdrplay.com/download/sdrconnect-linux-arm64-files/>
2. Inside the downloaded bundle are `sdrconnect_linux-<arch>_<build>.tar.gz` and
   a matching `.sha256` file. The `<build>` part is the hash.
3. Put the hash in `SDRCONNECT_BUILD` and the two checksums in
   `SDRCONNECT_SHA256_AMD64` and `SDRCONNECT_SHA256_AARCH64` in `build.yaml`,
   bump `version` in `config.yaml`, and rebuild the add-on.

The direct URL the build uses is
`https://sdrplay.com/software/sdrconnect_linux-{x64,arm64}_<build>.tar.gz`.

## Troubleshooting

**The build fails on the checksum.** The pinned build has probably been replaced
upstream and the URL now returns an error page. Follow *Updating to a new
SDRconnect build* above.

**"Could not list receivers" at start-up.** The add-on cannot open the USB
device. Check that the RSP is on a host port (not behind an unpowered hub), that
it is not being used by another add-on, and try turning protection mode off.

**The client's *Discover* finds nothing.** Discovery is a local broadcast and
does not cross subnets or VPNs. Enter the host's IP address and port by hand.

**The add-on starts and immediately stops.** Set `log_level` to `debug` and
check the log for a missing library or a rejected command line argument; an
option in `extra_args` that this build does not accept will do it.
