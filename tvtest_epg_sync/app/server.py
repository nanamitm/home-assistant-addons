#!/usr/bin/env python3
"""TVTest EPG Sync server.

LAN 上の複数の TVTest が取得した EPG を、サービス単位で融通しあうための中継サーバ。

サーバは番組情報の中身(文字列やジャンルなど)を一切解釈しない。
クライアントが送ってきたバイト列(LibISDB の EPGDataSerializer が出力する
"EPG-SVC1" 形式)をそのまま保管し、先頭 32 バイトの固定ヘッダだけを読んで
サービスの識別子とバージョンを取り出す。

そのためサーバ側に LibISDB を持つ必要がなく、Windows と Linux の
wchar_t の差(CharType 問題)の影響も受けない。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import re
import signal
import struct
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator, Optional

LOG = logging.getLogger("epgsync")

# EPG-SVC1 ヘッダ
#   char[8] Type / uint32 Version / uint16 NID / uint16 TSID / uint16 SID
#   uint16 Reserved / uint32 EventCount / uint64 UpdatedTime
HEADER_MAGIC = b"EPG-SVC1"
HEADER_STRUCT = struct.Struct("<8sIHHHHIQ")
HEADER_SIZE = HEADER_STRUCT.size  # 32
MAX_FORMAT_VERSION = 1

MAX_BLOB_SIZE = 64 * 1024 * 1024
SSE_QUEUE_SIZE = 256
SSE_KEEPALIVE_SECONDS = 20.0


class BlobError(ValueError):
    """不正な blob"""


class ServiceKey(tuple):
    """(NetworkID, TransportStreamID, ServiceID)"""

    __slots__ = ()

    def __new__(cls, nid: int, tsid: int, sid: int) -> "ServiceKey":
        for v in (nid, tsid, sid):
            if not 0 <= v <= 0xFFFF:
                raise BlobError(f"ID の範囲が不正です: {nid}/{tsid}/{sid}")
        return super().__new__(cls, (nid, tsid, sid))

    @property
    def nid(self) -> int:
        return self[0]

    @property
    def tsid(self) -> int:
        return self[1]

    @property
    def sid(self) -> int:
        return self[2]

    @property
    def filename(self) -> str:
        return "%04X_%04X_%04X.epgsvc" % self

    def __str__(self) -> str:
        return "%04X/%04X/%04X" % self


def parse_header(blob: bytes) -> tuple[ServiceKey, int, int]:
    """blob の先頭ヘッダから (キー, バージョン, 番組数) を取り出す"""
    if len(blob) < HEADER_SIZE:
        raise BlobError("データが短すぎます")

    magic, fmt_version, nid, tsid, sid, _reserved, event_count, updated_time = (
        HEADER_STRUCT.unpack_from(blob, 0)
    )

    if magic != HEADER_MAGIC:
        raise BlobError("EPG-SVC1 形式ではありません")
    if fmt_version > MAX_FORMAT_VERSION:
        raise BlobError(f"未対応のフォーマットバージョンです: {fmt_version}")

    return ServiceKey(nid, tsid, sid), updated_time, event_count


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Entry:
    """1 サービス分の保管データ"""

    __slots__ = ("key", "version", "event_count", "etag", "size", "updated_at", "source")

    def __init__(
        self,
        key: ServiceKey,
        version: int,
        event_count: int,
        etag: str,
        size: int,
        updated_at: str,
        source: str,
    ) -> None:
        self.key = key
        self.version = version
        self.event_count = event_count
        self.etag = etag
        self.size = size
        self.updated_at = updated_at
        self.source = source

    def to_json(self) -> dict[str, Any]:
        return {
            "nid": self.key.nid,
            "tsid": self.key.tsid,
            "sid": self.key.sid,
            "version": self.version,
            "event_count": self.event_count,
            "etag": self.etag,
            "size": self.size,
            "updated_at": self.updated_at,
            "source": self.source,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Entry":
        return cls(
            ServiceKey(int(data["nid"]), int(data["tsid"]), int(data["sid"])),
            int(data["version"]),
            int(data.get("event_count", 0)),
            str(data["etag"]),
            int(data.get("size", 0)),
            str(data.get("updated_at", "")),
            str(data.get("source", "")),
        )


class Store:
    """サービス単位の blob ストア

    ファイルは data_dir/services/ に置き、索引を index.json に持つ。
    書き込みは一時ファイル + rename で行い、途中で落ちても既存データを壊さない。
    """

    def __init__(self, data_dir: str) -> None:
        self._dir = data_dir
        self._blob_dir = os.path.join(data_dir, "services")
        self._index_path = os.path.join(data_dir, "index.json")
        self._lock = threading.RLock()
        self._entries: dict[ServiceKey, Entry] = {}

        os.makedirs(self._blob_dir, exist_ok=True)
        self._load_index()

    # -- 索引 --------------------------------------------------------------

    def _load_index(self) -> None:
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            LOG.info("索引がありません。新規に作成します。")
            return
        except (OSError, ValueError) as e:
            LOG.warning("索引を読めませんでした (%s)。再構築します。", e)
            self._rebuild_index()
            return

        for item in data.get("services", []):
            try:
                entry = Entry.from_json(item)
            except (KeyError, ValueError) as e:
                LOG.warning("索引の項目を読み飛ばします: %s", e)
                continue
            if os.path.exists(self._blob_path(entry.key)):
                self._entries[entry.key] = entry

        LOG.info("%d サービスを読み込みました。", len(self._entries))

    def _rebuild_index(self) -> None:
        self._entries.clear()
        for name in os.listdir(self._blob_dir):
            if not name.endswith(".epgsvc"):
                continue
            path = os.path.join(self._blob_dir, name)
            try:
                with open(path, "rb") as f:
                    blob = f.read()
                key, version, event_count = parse_header(blob)
            except (OSError, BlobError) as e:
                LOG.warning("%s を読み飛ばします: %s", name, e)
                continue
            self._entries[key] = Entry(
                key,
                version,
                event_count,
                compute_etag(blob),
                len(blob),
                utcnow(),
                "",
            )
        self._save_index()
        LOG.info("索引を再構築しました (%d サービス)。", len(self._entries))

    def _save_index(self) -> None:
        data = {
            "saved_at": utcnow(),
            "services": [e.to_json() for e in self._entries.values()],
        }
        write_atomic(self._index_path, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))

    def _blob_path(self, key: ServiceKey) -> str:
        return os.path.join(self._blob_dir, key.filename)

    # -- 参照 --------------------------------------------------------------

    def list_entries(self) -> list[Entry]:
        with self._lock:
            return sorted(self._entries.values(), key=lambda e: e.key)

    def get_entry(self, key: ServiceKey) -> Optional[Entry]:
        with self._lock:
            return self._entries.get(key)

    def get_blob(self, key: ServiceKey) -> Optional[tuple[Entry, bytes]]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            path = self._blob_path(key)
        try:
            with open(path, "rb") as f:
                return entry, f.read()
        except OSError as e:
            LOG.error("%s を読めませんでした: %s", path, e)
            return None

    # -- 更新 --------------------------------------------------------------

    def put_blob(
        self,
        key: ServiceKey,
        blob: bytes,
        version: int,
        event_count: int,
        source: str,
        if_match: Optional[str],
        force: bool,
    ) -> tuple[str, Entry]:
        """blob を保存する

        戻り値は ("stored" | "unchanged" | "stale" | "conflict", 現在の Entry)。
        """
        etag = compute_etag(blob)

        with self._lock:
            current = self._entries.get(key)

            if current is not None:
                if if_match is not None and if_match != "*" and if_match != current.etag:
                    return "conflict", current
                if current.etag == etag:
                    return "unchanged", current
                if not force and version < current.version:
                    return "stale", current
            elif if_match is not None and if_match != "*":
                return "conflict", Entry(key, 0, 0, "", 0, "", "")

            write_atomic(self._blob_path(key), blob)

            entry = Entry(key, version, event_count, etag, len(blob), utcnow(), source)
            self._entries[key] = entry
            self._save_index()

            return "stored", entry

    def delete(self, key: ServiceKey) -> bool:
        with self._lock:
            if self._entries.pop(key, None) is None:
                return False
            try:
                os.remove(self._blob_path(key))
            except OSError:
                pass
            self._save_index()
            return True

    def purge_older_than(self, days: int) -> int:
        """指定日数以上更新されていないサービスを削除する"""
        if days <= 0:
            return 0

        limit = time.time() - days * 24 * 60 * 60
        removed = 0

        with self._lock:
            for key in list(self._entries):
                path = self._blob_path(key)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    mtime = 0
                if mtime < limit:
                    self._entries.pop(key, None)
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    removed += 1
            if removed:
                self._save_index()

        if removed:
            LOG.info("%d 日以上更新のない %d サービスを削除しました。", days, removed)

        return removed


def compute_etag(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()[:32]


def write_atomic(path: str, data: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class EventBus:
    """SSE の購読者へ更新を配る"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # q -> 状態画面からの購読か(TVTest の購読数に混ぜないため)
        self._subscribers: dict[queue.Queue, bool] = {}

    def subscribe(self, is_ui: bool = False) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=SSE_QUEUE_SIZE)
        with self._lock:
            self._subscribers[q] = is_ui
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.pop(q, None)

    def subscriber_count(self) -> int:
        """TVTest クライアントの購読数(状態画面は含まない)"""
        with self._lock:
            return sum(1 for is_ui in self._subscribers.values() if not is_ui)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            targets = list(self._subscribers.keys())
        for q in targets:
            try:
                q.put_nowait(event)
            except queue.Full:
                # 追いつけていない購読者は取りこぼす(次の全体同期で回復する)
                LOG.debug("SSE の購読者が滞留しています。")


class Context:
    def __init__(self, store: Store, bus: EventBus, token: str) -> None:
        self.store = store
        self.bus = bus
        self.token = token
        self.started_at = utcnow()


SERVICE_PATH_RE = re.compile(r"^/api/service/(\d+)/(\d+)/(\d+)$")


def wants_text(query: str) -> bool:
    """JSON パーサを持たないクライアント向けの行指向形式が要求されているか"""
    return "format=text" in query


def format_event_text(event: dict[str, Any]) -> str:
    """SSE の行指向形式

    updated <nid> <tsid> <sid> <version> <event_count> <etag> <source>
    deleted <nid> <tsid> <sid>

    source は空白を含みうるため必ず末尾に置く。
    """
    kind = event.get("type", "")
    key = (event.get("nid", 0), event.get("tsid", 0), event.get("sid", 0))

    if kind == "updated":
        return "updated %d %d %d %d %d %s %s" % (
            key[0], key[1], key[2],
            event.get("version", 0),
            event.get("event_count", 0),
            event.get("etag", "-"),
            (event.get("source", "") or "-").replace("\n", " "),
        )

    return "%s %d %d %d" % (kind, key[0], key[1], key[2])


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "epgsync"
    sys_version = ""

    # ThreadingHTTPServer が属性としてセットする
    context: Context
    require_token: bool

    # -- 補助 --------------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.debug("%s %s", self.address_string(), fmt % args)

    def _send(
        self,
        status: HTTPStatus,
        body: bytes = b"",
        content_type: str = "application/json; charset=utf-8",
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _send_json(
        self,
        status: HTTPStatus,
        data: dict[str, Any],
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", headers)

    def _send_error_json(self, status: HTTPStatus, message: str, **extra: Any) -> None:
        data: dict[str, Any] = {"error": message}
        data.update(extra)
        self._send_json(status, data)

    def _check_token(self) -> bool:
        if not self.require_token or not self.context.token:
            return True

        supplied = self.headers.get("X-EPG-Token", "")
        if not supplied:
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                supplied = auth[7:]

        if supplied == self.context.token:
            return True

        self._send_error_json(HTTPStatus.UNAUTHORIZED, "トークンが一致しません")
        return False

    def _read_body(self) -> Optional[bytes]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Content-Length が不正です")
            return None

        if length <= 0:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "本文がありません")
            return None
        if length > MAX_BLOB_SIZE:
            self._send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "本文が大きすぎます")
            return None

        body = bytearray()
        while len(body) < length:
            chunk = self.rfile.read(min(65536, length - len(body)))
            if not chunk:
                break
            body.extend(chunk)

        if len(body) != length:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "本文を最後まで受信できませんでした")
            return None

        return bytes(body)

    def _source_name(self) -> str:
        name = self.headers.get("X-EPG-Source", "").strip()
        if not name:
            return self.address_string()
        return name[:64]

    # -- ルーティング ------------------------------------------------------

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_HEAD(self) -> None:
        self._dispatch("GET")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        path = self.path.split("?", 1)[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""

        # Ingress 経由ではパスに接頭辞が付く
        prefix = self.headers.get("X-Ingress-Path", "")
        if prefix and path.startswith(prefix):
            path = path[len(prefix):] or "/"

        try:
            if method == "GET" and path in ("/", "/index.html"):
                self._handle_index(prefix)
                return
            if method == "GET" and path == "/api/health":
                self._handle_health()
                return

            if not self._check_token():
                return

            if method == "GET" and path == "/api/services":
                self._handle_list(query)
                return
            if method == "GET" and path == "/api/events":
                self._handle_events(query)
                return

            m = SERVICE_PATH_RE.match(path)
            if m:
                try:
                    key = ServiceKey(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except BlobError as e:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, str(e))
                    return
                if method == "GET":
                    self._handle_get_service(key)
                    return
                if method == "PUT":
                    self._handle_put_service(key, query)
                    return
                if method == "DELETE":
                    self._handle_delete_service(key)
                    return

            self._send_error_json(HTTPStatus.NOT_FOUND, "見つかりません")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            LOG.exception("要求の処理に失敗しました: %s %s", method, self.path)
            try:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "内部エラー")
            except Exception:
                pass

    # -- 各ハンドラ --------------------------------------------------------

    def _handle_health(self) -> None:
        self._send_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "started_at": self.context.started_at,
                "services": len(self.context.store.list_entries()),
                "subscribers": self.context.bus.subscriber_count(),
            },
        )

    def _handle_list(self, query: str) -> None:
        entries = self.context.store.list_entries()

        if wants_text(query):
            # JSON パーサを持たないクライアント(TVTest)向けの行指向形式
            #   nid tsid sid version event_count etag
            lines = [
                "%d %d %d %d %d %s" % (e.key.nid, e.key.tsid, e.key.sid,
                                       e.version, e.event_count, e.etag)
                for e in entries
            ]
            body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
            self._send(HTTPStatus.OK, body, "text/plain; charset=utf-8")
            return

        self._send_json(
            HTTPStatus.OK,
            {
                "services": [e.to_json() for e in entries],
                "summary": {"subscribers": self.context.bus.subscriber_count()},
            },
        )

    def _handle_get_service(self, key: ServiceKey) -> None:
        result = self.context.store.get_blob(key)
        if result is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "サービスがありません")
            return

        entry, blob = result

        if self.headers.get("If-None-Match") == entry.etag:
            self._send(HTTPStatus.NOT_MODIFIED, b"", "application/octet-stream",
                       {"ETag": entry.etag})
            return

        self._send(
            HTTPStatus.OK,
            blob,
            "application/octet-stream",
            {
                "ETag": entry.etag,
                "X-EPG-Version": str(entry.version),
                "X-EPG-Event-Count": str(entry.event_count),
            },
        )

    def _handle_put_service(self, key: ServiceKey, query: str) -> None:
        blob = self._read_body()
        if blob is None:
            return

        try:
            blob_key, version, event_count = parse_header(blob)
        except BlobError as e:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(e))
            return

        if blob_key != key:
            self._send_error_json(
                HTTPStatus.BAD_REQUEST,
                f"URL とデータのサービスが一致しません (データ: {blob_key})",
            )
            return

        force = "force=1" in query
        source = self._source_name()
        result, entry = self.context.store.put_blob(
            key, blob, version, event_count, source,
            self.headers.get("If-Match"), force,
        )

        headers = {"ETag": entry.etag, "X-EPG-Version": str(entry.version)}

        if result == "conflict":
            self._send_json(
                HTTPStatus.PRECONDITION_FAILED,
                {"result": result, "current": entry.to_json()},
                headers,
            )
            return
        if result == "stale":
            self._send_json(
                HTTPStatus.CONFLICT,
                {"result": result, "current": entry.to_json()},
                headers,
            )
            return

        if result == "stored":
            LOG.info(
                "%s を更新しました (%d 番組, %d バイト, version=%d, from %s)",
                key, event_count, len(blob), version, source,
            )
            self.context.bus.publish(
                {
                    "type": "updated",
                    "nid": key.nid,
                    "tsid": key.tsid,
                    "sid": key.sid,
                    "version": version,
                    "event_count": event_count,
                    "etag": entry.etag,
                    "source": source,
                }
            )

        self._send_json(HTTPStatus.OK, {"result": result, "current": entry.to_json()}, headers)

    def _handle_delete_service(self, key: ServiceKey) -> None:
        if not self.context.store.delete(key):
            self._send_error_json(HTTPStatus.NOT_FOUND, "サービスがありません")
            return
        LOG.info("%s を削除しました。", key)
        self.context.bus.publish(
            {"type": "deleted", "nid": key.nid, "tsid": key.tsid, "sid": key.sid}
        )
        self._send_json(HTTPStatus.OK, {"result": "deleted"})

    def _handle_events(self, query: str) -> None:
        as_text = wants_text(query)
        q = self.context.bus.subscribe(is_ui="ui=1" in query)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        # HTTP/1.1 でボディ長不定のため、この接続は close で終える
        self.close_connection = True

        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()

            while True:
                try:
                    event = q.get(timeout=SSE_KEEPALIVE_SECONDS)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue

                payload = format_event_text(event) if as_text else json.dumps(event, ensure_ascii=False)
                self.wfile.write(b"data: " + payload.encode("utf-8") + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.context.bus.unsubscribe(q)

    def _handle_index(self, prefix: str) -> None:
        entries = self.context.store.list_entries()
        body = render_status_page(entries, self.context, prefix).encode("utf-8")
        self._send(HTTPStatus.OK, body, "text/html; charset=utf-8")


def render_status_page(entries: list[Entry], context: Context, prefix: str) -> str:
    rows = "".join(render_row(e) for e in entries)
    total_size = sum(e.size for e in entries)
    total_events = sum(e.event_count for e in entries)

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVTest EPG Sync</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font-family: system-ui, "Segoe UI", sans-serif; margin: 1.5rem; line-height: 1.5; }}
 h1 {{ font-size: 1.3rem; margin: 0 0 .25rem; }}
 .sub {{ opacity: .7; font-size: .9rem; margin-bottom: 1.25rem; }}
 .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }}
 .card {{ border: 1px solid rgba(128,128,128,.35); border-radius: 8px; padding: .75rem 1rem; min-width: 8rem; }}
 .card .v {{ font-size: 1.5rem; font-weight: 600; }}
 .card .k {{ font-size: .8rem; opacity: .7; }}
 table {{ border-collapse: collapse; width: 100%; font-size: .9rem; }}
 th, td {{ text-align: left; padding: .35rem .6rem; border-bottom: 1px solid rgba(128,128,128,.25); }}
 th {{ font-weight: 600; opacity: .8; }}
 td.id {{ font-family: ui-monospace, Consolas, monospace; }}
 td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
 .empty {{ opacity: .7; padding: 1rem 0; }}
 tr.flash {{ animation: flash 1.6s ease-out; }}
 @keyframes flash {{ from {{ background: rgba(120,170,255,.35); }} to {{ background: transparent; }} }}
 @media (prefers-reduced-motion: reduce) {{ tr.flash {{ animation: none; }} }}
 #live {{ font-size: .8rem; opacity: .6; }}
</style></head><body>
<h1>TVTest EPG Sync</h1>
<div class="sub">起動: {escape(context.started_at)} / 接続中のクライアント:
 <span id="clients">{context.bus.subscriber_count()}</span> <span id="live"></span></div>
<div class="cards">
 <div class="card"><div class="v" id="v-services">{len(entries)}</div><div class="k">サービス</div></div>
 <div class="card"><div class="v" id="v-events">{total_events}</div><div class="k">番組</div></div>
 <div class="card"><div class="v" id="v-size">{total_size / 1024 / 1024:.1f} MB</div><div class="k">保管サイズ</div></div>
</div>
<div id="list">{render_table(rows)}</div>
<p class="sub">API: <code>{escape(prefix)}/api/services</code></p>
<script>
(function () {{
  var base = {json.dumps(prefix)};
  var live = document.getElementById("live");
  var pending = null;

  function pad(n) {{ return ("000" + n.toString(16).toUpperCase()).slice(-4); }}
  function esc(s) {{
    return String(s).replace(/[&<>"]/g, function (c) {{
      return {{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }}[c];
    }});
  }}

  function render(data) {{
    var list = data.services || [];
    var events = 0, size = 0, rows = "";

    list.forEach(function (s) {{
      events += s.event_count;
      size += s.size;
      rows += "<tr data-key=\\"" + s.nid + "_" + s.tsid + "_" + s.sid + "\\">"
        + "<td class=id>" + pad(s.nid) + "/" + pad(s.tsid) + "/" + pad(s.sid) + "</td>"
        + "<td class=num>" + s.event_count + "</td>"
        + "<td class=num>" + Math.round(s.size / 1024) + " KB</td>"
        + "<td>" + esc(s.updated_at) + "</td>"
        + "<td>" + esc(s.source || "-") + "</td></tr>";
    }});

    document.getElementById("v-services").textContent = list.length;
    document.getElementById("v-events").textContent = events;
    document.getElementById("v-size").textContent = (size / 1024 / 1024).toFixed(1) + " MB";
    if (data.summary) document.getElementById("clients").textContent = data.summary.subscribers;

    document.getElementById("list").innerHTML = rows
      ? "<table><thead><tr><th>NID/TSID/SID</th><th class=num>番組数</th>"
        + "<th class=num>サイズ</th><th>最終更新</th><th>更新元</th></tr></thead>"
        + "<tbody>" + rows + "</tbody></table>"
      : '<div class="empty">まだ EPG を受信していません。</div>';
  }}

  function refresh(key) {{
    fetch(base + "/api/services", {{ headers: {{ "Accept": "application/json" }} }})
      .then(function (r) {{ return r.ok ? r.json() : null; }})
      .then(function (data) {{
        if (!data) return;
        render(data);
        if (key) {{
          var row = document.querySelector('tr[data-key="' + key + '"]');
          if (row) row.classList.add("flash");
        }}
      }})
      .catch(function () {{}});
  }}

  // 更新が連続しても再描画は 1 回にまとめる
  function schedule(key) {{
    clearTimeout(pending);
    pending = setTimeout(function () {{ refresh(key); }}, 250);
  }}

  if (!window.EventSource) return;

  // ui=1 を付けると TVTest の接続数に数えられない
  var es = new EventSource(base + "/api/events?ui=1");

  es.onopen = function () {{ live.textContent = "(自動更新中)"; }};
  es.onerror = function () {{ live.textContent = "(再接続中…)"; }};
  es.onmessage = function (ev) {{
    var key = null;
    try {{
      var d = JSON.parse(ev.data);
      key = d.nid + "_" + d.tsid + "_" + d.sid;
    }} catch (e) {{}}
    schedule(key);
  }};

  // SSE が切れている間の保険
  setInterval(function () {{ refresh(null); }}, 60000);
}})();
</script>
</body></html>"""


def render_row(e: Entry) -> str:
    return (
        '<tr data-key="{nid}_{tsid}_{sid}"><td class=id>{nid:04X}/{tsid:04X}/{sid:04X}</td>'
        "<td class=num>{count}</td><td class=num>{size}</td>"
        "<td>{updated}</td><td>{source}</td></tr>".format(
            nid=e.key.nid,
            tsid=e.key.tsid,
            sid=e.key.sid,
            count=e.event_count,
            size=f"{e.size / 1024:.0f} KB",
            updated=escape(e.updated_at),
            source=escape(e.source or "-"),
        )
    )


def render_table(rows: str) -> str:
    if not rows:
        return '<div class="empty">まだ EPG を受信していません。</div>'
    return (
        "<table><thead><tr><th>NID/TSID/SID</th><th class=num>番組数</th>"
        "<th class=num>サイズ</th><th>最終更新</th><th>更新元</th></tr></thead>"
        "<tbody>" + rows + "</tbody></table>"
    )


def escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        """接続が切られただけの場合にトレースバックを出さない

        クライアント(TVTest)が終了すると、キープアライブで待機中の接続や
        SSE の接続が切断される。これは正常な経路であって異常ではないため、
        既定の実装のようにトレースバックを出すと紛らわしい。
        """
        exc = sys.exc_info()[1]

        if exc is None:
            return

        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError, TimeoutError)):
            LOG.debug("%s との接続が切断されました: %s", client_address, exc)
            return

        LOG.exception("要求の処理中に例外が発生しました (%s)", client_address)


def make_server(port: int, context: Context, require_token: bool) -> ThreadingHTTPServer:
    handler = type(
        "BoundHandler",
        (Handler,),
        {"context": context, "require_token": require_token},
    )
    return Server(("0.0.0.0", port), handler)


def purge_loop(store: Store, days: int, stop: threading.Event) -> None:
    while not stop.wait(6 * 60 * 60):
        try:
            store.purge_older_than(days)
        except Exception:
            LOG.exception("古いデータの削除に失敗しました。")


def env_int(name: str, default: int) -> int:
    """整数の環境変数を読む(空や不正な値なら既定値)"""
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        LOG.warning("%s の値が不正なため %d を使います。", name, default)
        return default


def main() -> int:
    level = os.environ.get("EPGSYNC_LOG_LEVEL", "info").strip().upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stdout,
    )

    # 設定はアドオンのオプションから run.sh が環境変数として渡す
    data_dir = os.environ.get("EPGSYNC_DATA_DIR", "/data/epg")
    api_port = env_int("EPGSYNC_API_PORT", 8077)
    ingress_port = env_int("EPGSYNC_INGRESS_PORT", 8099)
    token = os.environ.get("EPGSYNC_TOKEN", "")
    retention_days = env_int("EPGSYNC_RETENTION_DAYS", 14)

    store = Store(data_dir)
    store.purge_older_than(retention_days)

    context = Context(store, EventBus(), token)

    api_server = make_server(api_port, context, require_token=True)
    LOG.info("API を 0.0.0.0:%d で待ち受けます%s。", api_port,
             "(トークン認証あり)" if token else "")

    servers = [api_server]
    if ingress_port > 0:
        ingress_server = make_server(ingress_port, context, require_token=False)
        LOG.info("Ingress を 0.0.0.0:%d で待ち受けます。", ingress_port)
        servers.append(ingress_server)

    stop = threading.Event()

    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    threads.append(
        threading.Thread(target=purge_loop, args=(store, retention_days, stop), daemon=True)
    )
    for t in threads:
        t.start()

    def shutdown(signum: int, _frame: Any) -> None:
        LOG.info("シグナル %d を受信しました。終了します。", signum)
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        while not stop.is_set():
            stop.wait(1.0)
    finally:
        for s in servers:
            s.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
