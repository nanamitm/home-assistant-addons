#!/usr/bin/env python3
"""TVTest EPG Sync server.

LAN 上の複数の TVTest が取得した EPG を、サービス単位で融通しあうための中継サーバ。

同期ストアは、クライアントが送ってきたバイト列(LibISDB の
EPGDataSerializer が出力する "EPG-SVC1" 形式)をそのまま正本として保管する。
番組表 API が要求された時だけ別モジュールで内容を読み取り、表示用にキャッシュする。

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
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator, Optional
from urllib.parse import parse_qs

# server.py はアドオンでは直接実行され、テストではファイルパスから読み込まれる。
# どちらでも同じディレクトリのデコーダーを見つけられるようにする。
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import epg_parser

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

    @property
    def data_dir(self) -> str:
        return self._dir

    # -- 索引 --------------------------------------------------------------

    def _load_index(self) -> None:
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            LOG.info("索引がありません。保存ファイルから再構築します。")
            self._rebuild_index()
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


NETWORK_TYPES = frozenset(("terrestrial", "bs", "cs", "other"))


def normalize_network_type(value: Any, network_id: int) -> str:
    network_type = str(value or "").strip().lower()

    # 1.1.2 以前のクライアントは、未登録だった高度BSの NID 0x000B を
    # 地デジ、スカパー!プレミアムの NID 0x000A を通常のCSとして送っていた。
    # 保存済みのメタデータも読み込み時に正しい分類へ移行する。
    if network_id == 0x000B and network_type in ("", "terrestrial"):
        return "bs"
    if network_id == 0x000A and network_type in ("", "cs"):
        return "other"

    if not network_type:
        if network_id == 4:
            return "bs"
        if network_id in (6, 7):
            return "cs"
        return "terrestrial"
    if network_type not in NETWORK_TYPES:
        raise ValueError("放送波種別が不正です")
    return network_type


class ServiceMetadata:
    __slots__ = (
        "key", "name", "group", "network_type", "remote_control_key", "service_type",
        "order", "source", "updated_at",
    )

    def __init__(
        self,
        key: ServiceKey,
        name: str,
        group: str,
        network_type: str,
        remote_control_key: int,
        service_type: int,
        order: int,
        source: str,
        updated_at: str,
    ) -> None:
        self.key = key
        self.name = name
        self.group = group
        self.network_type = network_type
        self.remote_control_key = remote_control_key
        self.service_type = service_type
        self.order = order
        self.source = source
        self.updated_at = updated_at

    def to_json(self) -> dict[str, Any]:
        return {
            "nid": self.key.nid,
            "tsid": self.key.tsid,
            "sid": self.key.sid,
            "name": self.name,
            "group": self.group,
            "network_type": self.network_type,
            "remote_control_key": self.remote_control_key,
            "service_type": self.service_type,
            "order": self.order,
            "source": self.source,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ServiceMetadata":
        return cls(
            ServiceKey(int(data["nid"]), int(data["tsid"]), int(data["sid"])),
            str(data.get("name", "")),
            str(data.get("group", "")),
            normalize_network_type(data.get("network_type"), int(data["nid"])),
            int(data.get("remote_control_key", 0)),
            int(data.get("service_type", 0)),
            int(data.get("order", 0)),
            str(data.get("source", "")),
            str(data.get("updated_at", "")),
        )


class MetadataStore:
    """TVTest から受け取った局名と番組表上の順序を保管する。"""

    MAX_SERVICES_PER_UPDATE = 10_000
    MAX_NAME_LENGTH = 128
    MAX_GROUP_LENGTH = 64

    def __init__(self, data_dir: str) -> None:
        self._path = os.path.join(data_dir, "metadata.json")
        self._lock = threading.RLock()
        self._items: dict[ServiceKey, ServiceMetadata] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            LOG.warning("局メタデータを読めませんでした: %s", exc)
            return

        for raw in data.get("services", []):
            try:
                item = ServiceMetadata.from_json(raw)
                self._validate(item)
            except (KeyError, TypeError, ValueError, BlobError):
                continue
            self._items[item.key] = item

    def _save(self) -> None:
        data = {
            "saved_at": utcnow(),
            "services": [item.to_json() for item in self._items.values()],
        }
        write_atomic(
            self._path,
            json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"),
        )

    @classmethod
    def _validate(cls, item: ServiceMetadata) -> None:
        if not item.name or len(item.name) > cls.MAX_NAME_LENGTH:
            raise ValueError("局名が空か長すぎます")
        if len(item.group) > cls.MAX_GROUP_LENGTH:
            raise ValueError("グループ名が長すぎます")
        if not 0 <= item.remote_control_key <= 999:
            raise ValueError("リモコン番号の範囲が不正です")
        if not 0 <= item.service_type <= 0xFF:
            raise ValueError("サービスタイプの範囲が不正です")
        if not 0 <= item.order <= 1_000_000:
            raise ValueError("表示順の範囲が不正です")

    def update(self, raw_services: Any, source: str) -> int:
        if not isinstance(raw_services, list):
            raise ValueError("services は配列で指定してください")
        if len(raw_services) > self.MAX_SERVICES_PER_UPDATE:
            raise ValueError("サービス数が多すぎます")

        now = utcnow()
        validated: list[ServiceMetadata] = []
        for raw in raw_services:
            if not isinstance(raw, dict):
                raise ValueError("サービスの形式が不正です")
            try:
                item = ServiceMetadata(
                    ServiceKey(int(raw["nid"]), int(raw["tsid"]), int(raw["sid"])),
                    str(raw.get("name", "")).strip(),
                    str(raw.get("group", "")).strip(),
                    normalize_network_type(raw.get("network_type"), int(raw["nid"])),
                    int(raw.get("remote_control_key", 0)),
                    int(raw.get("service_type", 0)),
                    int(raw.get("order", len(validated))),
                    source,
                    now,
                )
            except (KeyError, TypeError, ValueError, BlobError) as exc:
                raise ValueError("サービスの項目が不正です") from exc
            self._validate(item)
            validated.append(item)

        with self._lock:
            for item in validated:
                self._items[item.key] = item
            if validated:
                self._save()
        return len(validated)

    def get(self, key: ServiceKey) -> Optional[ServiceMetadata]:
        with self._lock:
            return self._items.get(key)

    def remove(self, key: ServiceKey) -> None:
        with self._lock:
            if self._items.pop(key, None) is not None:
                self._save()


class GuideCache:
    """保存 blob を ETag 単位で解析して再利用する。"""

    def __init__(self, store: Store, metadata: MetadataStore) -> None:
        self._store = store
        self._metadata = metadata
        self._lock = threading.RLock()
        self._cache: dict[ServiceKey, tuple[str, Optional[epg_parser.EpgService], str]] = {}

    def invalidate(self, key: ServiceKey) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def get(
        self, key: ServiceKey
    ) -> Optional[tuple[Entry, Optional[epg_parser.EpgService], str]]:
        result = self._store.get_blob(key)
        if result is None:
            return None
        entry, blob = result

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached[0] == entry.etag:
                return entry, cached[1], cached[2]

        parsed: Optional[epg_parser.EpgService]
        error = ""
        try:
            parsed = epg_parser.parse_service(blob)
        except epg_parser.EpgParseError as exc:
            parsed = None
            error = str(exc)
            LOG.warning("%s の番組表データを解析できません: %s", key, exc)

        with self._lock:
            self._cache[key] = (entry.etag, parsed, error)
        return entry, parsed, error

    def build_guide(self, first: datetime, last: datetime) -> dict[str, Any]:
        parsed_services: list[tuple[Entry, epg_parser.EpgService]] = []
        services: list[dict[str, Any]] = []

        entries = self._store.list_entries()
        entries.sort(key=self._sort_key)
        for entry in entries:
            result = self.get(entry.key)
            if result is None:
                continue
            current, parsed, error = result
            item: dict[str, Any] = {
                "nid": current.key.nid,
                "tsid": current.key.tsid,
                "sid": current.key.sid,
                "name": str(current.key),
                "etag": current.etag,
                "event_count": current.event_count,
                "network_type": normalize_network_type(None, current.key.nid),
                "events": [],
            }
            metadata = self._metadata.get(current.key)
            if metadata is not None:
                item.update(
                    {
                        "name": metadata.name,
                        "group": metadata.group,
                        "network_type": metadata.network_type,
                        "remote_control_key": metadata.remote_control_key,
                        "service_type": metadata.service_type,
                        "order": metadata.order,
                    }
                )
            if parsed is None:
                item["parse_error"] = error
            else:
                parsed_services.append((current, parsed))
            services.append(item)

        event_index: dict[tuple[int, int, int, int], epg_parser.EpgEvent] = {}
        for _entry, parsed in parsed_services:
            for event in parsed.events:
                event_index[(event.key.nid, event.key.tsid, event.key.sid, event.event_id)] = event

        item_by_key = {
            (item["nid"], item["tsid"], item["sid"]): item for item in services
        }
        for entry, parsed in parsed_services:
            item = item_by_key[(entry.key.nid, entry.key.tsid, entry.key.sid)]
            for event in parsed.events:
                if event.end <= first or event.start >= last:
                    continue
                data = epg_parser.event_to_dict(event)
                _fill_common_event(data, event, event_index)
                item["events"].append(data)

        return {
            "from": first.isoformat(),
            "to": last.isoformat(),
            "generated_at": datetime.now(epg_parser.JST).replace(microsecond=0).isoformat(),
            "services": services,
        }

    def _sort_key(self, entry: Entry) -> tuple[Any, ...]:
        metadata = self._metadata.get(entry.key)
        if metadata is None:
            return (1, 0, entry.key.nid, entry.key.tsid, entry.key.sid)
        return (0, metadata.order, entry.key.nid, entry.key.tsid, entry.key.sid)

    def get_event(
        self, key: ServiceKey, event_id: int
    ) -> Optional[tuple[Entry, epg_parser.EpgEvent, dict[str, Any]]]:
        result = self.get(key)
        if result is None or result[1] is None:
            return None
        entry, parsed, _error = result
        event = next((item for item in parsed.events if item.event_id == event_id), None)
        if event is None:
            return None

        index: dict[tuple[int, int, int, int], epg_parser.EpgEvent] = {}
        if event.common_event is not None:
            common_key = ServiceKey(key.nid, key.tsid, event.common_event.service_id)
            common_result = self.get(common_key)
            if common_result is not None and common_result[1] is not None:
                for candidate in common_result[1].events:
                    index[(key.nid, key.tsid, common_key.sid, candidate.event_id)] = candidate

        data = epg_parser.event_to_dict(event, include_details=True)
        _fill_common_event(data, event, index, include_details=True)
        return entry, event, data


def _fill_common_event(
    data: dict[str, Any],
    event: epg_parser.EpgEvent,
    index: dict[tuple[int, int, int, int], epg_parser.EpgEvent],
    include_details: bool = False,
) -> None:
    if not event.is_common_event or event.common_event is None:
        return
    target_key = (
        event.key.nid,
        event.key.tsid,
        event.common_event.service_id,
        event.common_event.event_id,
    )
    data["common_event"] = {
        "sid": event.common_event.service_id,
        "event_id": event.common_event.event_id,
    }
    target = index.get(target_key)
    if target is None:
        return
    common = epg_parser.event_to_dict(target, include_details=include_details)
    if not data.get("title"):
        data["title"] = common["title"]
    if not data.get("text"):
        data["text"] = common["text"]
    if not data.get("genres"):
        data["genres"] = common["genres"]
    if include_details and not data.get("extended_text"):
        data["extended_text"] = common.get("extended_text", [])


class Context:
    def __init__(self, store: Store, bus: EventBus, token: str) -> None:
        self.store = store
        self.bus = bus
        self.token = token
        self.metadata = MetadataStore(store.data_dir)
        self.guide = GuideCache(store, self.metadata)
        self.started_at = utcnow()


SERVICE_PATH_RE = re.compile(r"^/api/service/(\d+)/(\d+)/(\d+)$")
GUIDE_EVENT_PATH_RE = re.compile(r"^/api/guide/event/(\d+)/(\d+)/(\d+)/(\d+)$")
STATIC_PATH_RE = re.compile(r"^/static/(guide(?:-layout)?\.js|guide\.css)$")


def parse_guide_range(query: str) -> tuple[datetime, datetime]:
    """番組表 API の date または from / hours を JST の範囲へ変換する。"""
    params = parse_qs(query, keep_blank_values=True)
    hours_text = params.get("hours", ["24"])[-1]
    try:
        hours = int(hours_text)
    except ValueError as exc:
        raise ValueError("hours は整数で指定してください") from exc
    if not 1 <= hours <= 48:
        raise ValueError("hours は 1 から 48 の範囲で指定してください")

    if "from" in params:
        value = params["from"][-1]
        try:
            first = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("from の日時形式が不正です") from exc
        if first.tzinfo is None:
            first = first.replace(tzinfo=epg_parser.JST)
        else:
            first = first.astimezone(epg_parser.JST)
    else:
        date_text = params.get("date", [datetime.now(epg_parser.JST).date().isoformat()])[-1]
        try:
            day = datetime.strptime(date_text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("date は YYYY-MM-DD 形式で指定してください") from exc
        # TVTest の既定に近い朝4時区切り。UI 側は from を指定して変更できる。
        first = day.replace(hour=4, tzinfo=epg_parser.JST)

    return first, first + timedelta(hours=hours)


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
                self._handle_app(prefix)
                return
            if method == "GET" and path == "/status":
                self._handle_status(prefix)
                return
            static = STATIC_PATH_RE.match(path)
            if method == "GET" and static:
                self._handle_static(static.group(1))
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
            if method == "GET" and path == "/api/guide":
                self._handle_guide(query)
                return
            if method == "PUT" and path == "/api/service-metadata":
                self._handle_put_metadata()
                return

            guide_event = GUIDE_EVENT_PATH_RE.match(path)
            if method == "GET" and guide_event:
                try:
                    key = ServiceKey(
                        int(guide_event.group(1)),
                        int(guide_event.group(2)),
                        int(guide_event.group(3)),
                    )
                    event_id = int(guide_event.group(4))
                except BlobError as e:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, str(e))
                    return
                if not 0 <= event_id <= 0xFFFF:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "番組 ID の範囲が不正です")
                    return
                self._handle_guide_event(key, event_id)
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

    def _handle_guide(self, query: str) -> None:
        try:
            first, last = parse_guide_range(query)
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._send_json(HTTPStatus.OK, self.context.guide.build_guide(first, last))

    def _handle_guide_event(self, key: ServiceKey, event_id: int) -> None:
        result = self.context.guide.get_event(key, event_id)
        if result is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "番組がありません")
            return
        entry, _event, data = result
        data.update({"nid": key.nid, "tsid": key.tsid, "sid": key.sid})
        self._send_json(HTTPStatus.OK, {"event": data}, {"ETag": entry.etag})

    def _handle_put_metadata(self) -> None:
        body = self._read_body()
        if body is None:
            return
        try:
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("本文はオブジェクトで指定してください")
            count = self.context.metadata.update(
                payload.get("services"), self._source_name()
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return

        LOG.info("%s から %d サービスの局情報を受信しました。", self._source_name(), count)
        self.context.bus.publish({"type": "metadata", "count": count})
        self._send_json(HTTPStatus.OK, {"result": "stored", "count": count})

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
            self.context.guide.invalidate(key)
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
        self.context.guide.invalidate(key)
        self.context.metadata.remove(key)
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

    def _handle_app(self, prefix: str) -> None:
        path = os.path.join(APP_DIR, "static", "index.html")
        try:
            with open(path, "r", encoding="utf-8") as file:
                template = file.read()
        except OSError:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "画面を読み込めません")
            return

        base_json = json.dumps(prefix, ensure_ascii=False)
        # script 要素を閉じられないよう JSON 内の HTML 記号をエスケープする
        base_json = base_json.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        body = (
            template.replace("__BASE_PATH__", escape(prefix))
            .replace("__BASE_JSON__", base_json)
            .encode("utf-8")
        )
        self._send(HTTPStatus.OK, body, "text/html; charset=utf-8")

    def _handle_static(self, name: str) -> None:
        path = os.path.join(APP_DIR, "static", name)
        try:
            with open(path, "rb") as file:
                body = file.read()
        except OSError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "ファイルがありません")
            return
        content_type = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
        self._send(HTTPStatus.OK, body, content_type)

    def _handle_status(self, prefix: str) -> None:
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
