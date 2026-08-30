# TVTest EPG Sync

## Setup

1. Install and start the add-on.
2. Set a **Token** in the Configuration tab if the network is shared with
   others, then restart the add-on.
3. In each TVTest, open **Settings → EPG/Program information** and fill in the
   **EPG sharing** group:

   | Field | Value |
   |---|---|
   | Share EPG with other TVTest | checked |
   | Server | `http://<home-assistant>:8077` |
   | Token | the token set above, if any |
   | Name | a name for that machine, such as `living-pc` |

4. Open **EPG Sync** from the Home Assistant sidebar. Each running TVTest
   counts as one connected client.

Settings take effect when the dialog is closed; TVTest does not need
restarting.

## Web program guide

The add-on opens on a program guide built from the EPG already held by the
sync store. It provides:

- service columns and a vertical time axis starting at 04:00;
- instant filtering between terrestrial, BS, CS and other services;
- a **Services** filter that shows only the main services by default;
- the channel logo in front of each station name, where one has arrived;
- a genre filter that fades out the programs it does not match;
- event blocks sized by their broadcast duration and coloured by genre;
- a shared variable-height timeline that keeps even short events readable;
- day navigation, zoom levels and a current-time marker;
- event details including extended text, video and audio information;
- live refresh when a TVTest instance uploads a service.

Use the **Sync status** tab to see the storage and client information that was
shown by earlier versions of the add-on.

The **Services** filter defaults to **Main only**, which leaves out one-seg and
data broadcast services (ARIB service type `0xC0`), services whose name had to
be guessed, and sub channels that only simulcast their base service. Choose
**All** to list every service the store holds.

A sub channel counts as a simulcast when at least 90% of the events it holds
are linked to another service on the same transport stream by the EIT event
sharing descriptor. Names cannot be used for this: BS Nittele and BS-TBS give
their sub channels exactly the same name as the base service, yet some of them
carry their own programs.

The genre buttons filter on the ARIB level 1 genre. Pick as many as you like and
a program is kept when it carries any of them, so a film that is also an
animation answers to either. Programs that do not match stay in place but fade
into the background, which keeps the surrounding schedule readable while the
matches stand out; hovering one brings it back to full strength. Reserved
genres and programs with no genre at all are gathered under **Other**.

The broadcast network, service and genre filters are remembered, so the guide
opens the way it was left. They are kept in the browser rather than on the
server, so each device keeps its own choice, and a browser that refuses to store
anything simply opens with the defaults.

## Channel logos

An updated TVTest uploads the logos it has collected from the broadcast when
EPG sharing starts, and sends only the ones the add-on does not already hold.
A logo belongs to a network and a logo ID rather than to a single service, so
the stations of one network share a single copy.

The bytes are stored exactly as they were broadcast. ARIB delivers a logo as an
indexed PNG that carries no `PLTE` chunk, because the receiver is expected to
apply the 128 colour palette the standard defines; a browser shown such a file
draws nothing. The add-on inserts that palette after the header, leaving the
image data untouched, and serves the result from `/api/logo/<nid>/<id>/<type>`
with a long cache lifetime keyed to the logo version.

Only logo type 5 (64x36) reaches advanced BS, so TVTest prefers that type. A
logo is left out of the guide until it arrives; the station name is shown on
its own in the meantime. Logos are drawn on a dark chip because their artwork
assumes a dark background.

An updated TVTest sends its channel names, order and broadcast network type
when EPG sharing starts. Data received from an older TVTest remains fully
usable; known Japanese BS/CS network IDs are classified automatically, while
the guide shows `NID/TSID/SID` in place of the channel name until metadata
arrives. Services that are absent from every TVTest channel list borrow the
name of the base service on their transport stream, followed by a sub-channel
number or their service ID.

Advanced BS (`NID 0x000B`) is grouped under BS. SKY PerfecTV! Premium
(`NID 0x000A`) is grouped under **Other**, separately from the 110-degree CS
networks (`NID 0x0006` and `0x0007`). Metadata saved by older clients is
corrected when it is loaded.

## Options

| Option | Default | Description |
|---|---:|---|
| `token` | empty | Required in the `X-EPG-Token` header. Empty accepts any host that can reach the port. |
| `log_level` | `info` | Set to `debug` to log every connection and transfer. |
| `retention_days` | `14` | Services untouched for this long are deleted. `0` keeps everything. |

## How instances stay in step

Each TVTest owns merging; the add-on cannot merge because it does not read the
contents.

- On startup an instance compares what the add-on holds against its own
  database and pulls only the services that are newer, or that hold more
  events than it does.
- While running it pushes the services it received from a tuner itself, and
  applies what other instances push.
- Sending is a read-modify-write guarded by an ETag. If another instance got
  there first, the sender re-reads, merges again and retries.

Versions come from the broadcast time signal rather than the PC clock, so
instances whose clocks disagree still order updates correctly.

## Ports

Port `8077` is what TVTest connects to. The status page is served over Ingress
and needs no port of its own.

## Storage

Services are written under `/data/epg`, one file per service plus an index,
and are included in Home Assistant backups. Channel names and ordering are kept
in `/data/epg/metadata.json`, channel logos under `/data/epg/logos` with their
own index. A full Japanese terrestrial, BS and CS lineup is roughly 7 MB, and
its logos add well under 100 KB. If the index is lost it is rebuilt from the
files.

## Troubleshooting

**No connected clients.** Check that TVTest can reach the port. TVTest logs
`EPG 共有サーバに接続できません` when it cannot.

**HTTP 401 in the TVTest log.** The token does not match the one set here.

**A service never arrives.** An instance only pulls a service when the add-on
holds a newer version, or more events than it already has. An instance that
already holds a fuller schedule is meant to keep its own.

**The add-on is stopped.** TVTest runs normally from its local `EpgData`. This
add-on only relays; the authoritative copy is each instance's own database.
