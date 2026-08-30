## 1.2.0

- Show the channel logo in front of each station name in the program guide.
- Accept logos uploaded by an updated TVTest and hand them to the browser as
  ordinary PNGs. ARIB carries them as indexed PNGs with no palette, so the
  add-on inserts the 128 colour palette the standard defines.
- Prefer logo type 5 (64x36), the only type advanced BS broadcasts.

## 1.1.5

- Decide which sub channels are simulcasts from the EIT event sharing
  descriptor instead of the channel name. BS Nittele and BS-TBS name their sub
  channels exactly like the base service, so the guide dropped the ones that
  carry their own programs.

## 1.1.4

- Show only the main services by default, hiding one-seg, data broadcast and
  sub channels that repeat the name of the service beside them. Switch the new
  **Services** filter to **All** to see every service again.
- Name services that never reach a TVTest channel list, such as data broadcast
  services, after the base service on their transport stream.

## 1.1.3

- Classify Advanced BS network ID `0x000B` as BS so 4K/8K services no longer
  appear under terrestrial services.
- Classify SKY PerfecTV! Premium network ID `0x000A` as other, while keeping
  network IDs `0x0006` and `0x0007` under CS.
- Correct persisted metadata written by older clients when it is loaded.

## 1.1.2

- Add instant program-guide filtering for terrestrial, BS, CS and other
  broadcast networks.
- Accept TVTest's network classification in channel metadata while retaining a
  compatible fallback for older clients.

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
