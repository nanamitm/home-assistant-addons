# SDRconnect Server

Run the [SDRconnect](https://www.sdrplay.com/sdrconnect/) server on Home
Assistant, with an SDRplay RSP receiver plugged into the host, and tune it from
SDRconnect on a PC, Mac, phone or browser anywhere on the network.

- **Server mode** — the RSP is published on TCP port 50000 for the SDRconnect
  desktop and mobile clients, which can also find it with *Discover*.
- **Headless mode** — SDRconnect serves its own user interface to a browser
  over a websocket, with no client to install.
- Receiver settings (antenna, gain, bias-T, notch filters, sample rate) can be
  fixed from the add-on options, or left to the connecting client.

The add-on is built on your own machine and downloads the official SDRplay
package during the build; no prebuilt image is published. See [DOCS.md](DOCS.md)
for setup, the full option list, and how to move to a new SDRconnect build.
