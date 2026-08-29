## 1.0.0

Initial release.

- Relays EPG between TVTest instances one service at a time, over HTTP with
  Server-Sent Events for update notices.
- Stores each service as opaque bytes and reads only the 32-byte header, so the
  add-on needs no knowledge of ARIB event information.
- Status page over Ingress, updating live as instances push.
- Optional token, and deletion of services that stop being updated.
