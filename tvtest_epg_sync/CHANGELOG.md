## 1.1.1

- Align program text to the top of each card.
- Expand timeline intervals containing short programs so every program keeps at
  least one readable title row without breaking alignment across services.

## 1.1.0

- Add a TVTest-style web program guide with day navigation, genre colours,
  event details, zoom controls and live updates.
- Decode the portable service blobs into a cached, read-only guide API while
  keeping the original bytes authoritative for synchronization.
- Accept and persist channel names and ordering uploaded by updated TVTest
  clients.

## 1.0.0

Initial release.

- Relays EPG between TVTest instances one service at a time, over HTTP with
  Server-Sent Events for update notices.
- Stores each service as opaque bytes and reads only the 32-byte header, so the
  add-on needs no knowledge of ARIB event information.
- Status page over Ingress, updating live as instances push.
- Optional token, and deletion of services that stop being updated.
