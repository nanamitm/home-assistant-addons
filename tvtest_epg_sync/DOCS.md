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
- event blocks sized by their broadcast duration and coloured by genre;
- a shared variable-height timeline that keeps even short events readable;
- day navigation, zoom levels and a current-time marker;
- event details including extended text, video and audio information;
- live refresh when a TVTest instance uploads a service.

Use the **Sync status** tab to see the storage and client information that was
shown by earlier versions of the add-on.

An updated TVTest sends its enabled channel names and order when EPG sharing
starts. Data received from an older TVTest remains fully usable, but the guide
shows `NID/TSID/SID` in place of the channel name until metadata arrives.

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
in `/data/epg/metadata.json`. A full Japanese terrestrial, BS and CS lineup is
roughly 7 MB. If the index is lost it is rebuilt from the files.

## Troubleshooting

**No connected clients.** Check that TVTest can reach the port. TVTest logs
`EPG 共有サーバに接続できません` when it cannot.

**HTTP 401 in the TVTest log.** The token does not match the one set here.

**A service never arrives.** An instance only pulls a service when the add-on
holds a newer version, or more events than it already has. An instance that
already holds a fuller schedule is meant to keep its own.

**The add-on is stopped.** TVTest runs normally from its local `EpgData`. This
add-on only relays; the authoritative copy is each instance's own database.
