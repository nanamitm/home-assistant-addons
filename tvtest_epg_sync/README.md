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
- a TVTest-style web program guide, updated live over Ingress;
- an Ingress status tab showing what is held and which instance sent it.

The synchronization store keeps the bytes TVTest sends as its authoritative
copy and reads only the 32-byte header when comparing versions. The web guide
decodes that same portable `EPG-SVC1` data into display-only fields such as
titles, times, descriptions and genres; it never rewrites the stored data.

Requires a TVTest build with EPG sharing support. See [DOCS.md](DOCS.md) for
setup.
