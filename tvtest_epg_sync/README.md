# TVTest EPG Sync

Lets several [TVTest](https://github.com/DBCTRADO/TVTest) instances on a LAN
share the EPG they receive, so a schedule picked up by one is available to the
others within seconds.

TVTest reads and writes its own `EpgData` file only at startup and shutdown, so
pointing them all at a shared folder does not make new data appear while they
are running. This add-on relays it instead.

TVTest EPG Sync provides:

- a store holding one blob per service, keyed by network, stream and service ID;
- update notices over Server-Sent Events, so instances apply changes live;
- ETag-guarded writes, so two instances updating the same service cannot lose
  each other's work;
- an Ingress status page showing what is held and which instance sent it.

The add-on never parses event information. It keeps the bytes TVTest sends and
reads only the 32-byte header to tell services apart and compare versions, so it
needs no knowledge of ARIB encoding and works regardless of how the sending
platform represents text.

Requires a TVTest build with EPG sharing support. See [DOCS.md](DOCS.md) for
setup.
