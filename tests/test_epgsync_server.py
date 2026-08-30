"""TVTest EPG Sync のサーバのテスト

TVTest 側の LibISDB が生成した実データがあれば、環境変数 EPGSYNC_TEST_BLOB に
そのファイルを指定すると、ヘッダ解釈の相互運用も検証する。
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from tests.test_epgsync_parser import event_blob, service_blob

# 他のアドオンにも app/server.py があるため、"server" という名前で取り込むと
# 先に読み込まれたほうが sys.modules に残り、取り違えが起きる。
# パスを指定して、このアドオン専用の名前で読み込む。
_APP = (
    pathlib.Path(__file__).resolve().parent.parent
    / "tvtest_epg_sync"
    / "app"
    / "server.py"
)
_SPEC = importlib.util.spec_from_file_location("tvtest_epg_sync_server", _APP)
server = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def make_blob(nid=4, tsid=0x4010, sid=0xE4, version=1000, event_count=2, body=b"\x01\x00\x00\x00\x00"):
    """テスト用の EPG-SVC1 blob を作る(本体はサーバから見ると不透明)"""
    header = server.HEADER_STRUCT.pack(
        server.HEADER_MAGIC, 1, nid, tsid, sid, 0, event_count, version
    )
    return header + body


class ServerFixture(unittest.TestCase):
    """サーバを1個起動する土台(それ自体はテストを持たない)"""

    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="epgsync-test-")
        self.store = server.Store(self.data_dir)
        self.context = server.Context(self.store, server.EventBus(), token="secret")
        self.httpd = server.make_server(0, self.context, require_token=True)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.data_dir, ignore_errors=True)

    # -- 補助 --------------------------------------------------------------

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def request(self, method, path, data=None, headers=None, token="secret"):
        req = urllib.request.Request(self.url(path), data=data, method=method)
        if token:
            req.add_header("X-EPG-Token", token)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, dict(res.headers), res.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def put(self, blob, path=None, **kwargs):
        if path is None:
            key, _, _ = server.parse_header(blob)
            path = f"/api/service/{key.nid}/{key.tsid}/{key.sid}"
        return self.request("PUT", path, data=blob, **kwargs)


class ServerTestCase(ServerFixture):
    # -- ヘッダ解釈 --------------------------------------------------------

    def test_header_size_is_32(self):
        self.assertEqual(server.HEADER_SIZE, 32)

    def test_parse_header(self):
        blob = make_blob(nid=4, tsid=0x4010, sid=0xE4, version=12345, event_count=7)
        key, version, count = server.parse_header(blob)
        self.assertEqual((key.nid, key.tsid, key.sid), (4, 0x4010, 0xE4))
        self.assertEqual(version, 12345)
        self.assertEqual(count, 7)

    def test_parse_header_rejects_garbage(self):
        with self.assertRaises(server.BlobError):
            server.parse_header(b"short")
        with self.assertRaises(server.BlobError):
            server.parse_header(b"XPG-SVC1" + bytes(24))
        future = struct.pack("<8sIHHHHIQ", server.HEADER_MAGIC, 99, 0, 0, 0, 0, 0, 0)
        with self.assertRaises(server.BlobError):
            server.parse_header(future)

    # -- 認証 --------------------------------------------------------------

    def test_token_required(self):
        status, _, _ = self.request("GET", "/api/services", token=None)
        self.assertEqual(status, 401)

        status, _, _ = self.request("GET", "/api/services", token="wrong")
        self.assertEqual(status, 401)

        status, _, _ = self.request("GET", "/api/services")
        self.assertEqual(status, 200)

    def test_health_needs_no_token(self):
        status, _, body = self.request("GET", "/api/health", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

    # -- 保存と取得 --------------------------------------------------------

    def test_put_and_get(self):
        blob = make_blob(version=1000)

        status, headers, body = self.put(blob)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"], "stored")
        etag = headers["ETag"]

        status, headers, got = self.request("GET", "/api/service/4/16400/228")
        self.assertEqual(status, 200)
        self.assertEqual(got, blob)
        self.assertEqual(headers["ETag"], etag)
        self.assertEqual(headers["X-EPG-Version"], "1000")

        status, _, body = self.request("GET", "/api/services")
        services = json.loads(body)["services"]
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["version"], 1000)
        self.assertEqual(services[0]["sid"], 0xE4)

    def test_get_missing_service(self):
        status, _, _ = self.request("GET", "/api/service/1/2/3")
        self.assertEqual(status, 404)

    def test_if_none_match(self):
        blob = make_blob()
        _, headers, _ = self.put(blob)
        etag = headers["ETag"]

        status, _, _ = self.request(
            "GET", "/api/service/4/16400/228", headers={"If-None-Match": etag}
        )
        self.assertEqual(status, 304)

    def test_put_rejects_mismatched_path(self):
        blob = make_blob(sid=0xE4)
        status, _, body = self.put(blob, path="/api/service/4/16400/999")
        self.assertEqual(status, 400)
        self.assertIn("一致しません", json.loads(body)["error"])

    def test_put_rejects_garbage(self):
        status, _, _ = self.put(b"not an epg blob", path="/api/service/4/16400/228")
        self.assertEqual(status, 400)

    # -- バージョン管理 ----------------------------------------------------

    def test_identical_put_is_unchanged(self):
        blob = make_blob()
        self.put(blob)
        status, _, body = self.put(blob)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"], "unchanged")

    def test_older_version_is_rejected(self):
        self.put(make_blob(version=2000, body=b"\x02"))

        status, _, body = self.put(make_blob(version=1000, body=b"\x01"))
        self.assertEqual(status, 409)
        payload = json.loads(body)
        self.assertEqual(payload["result"], "stale")
        self.assertEqual(payload["current"]["version"], 2000)

        # force を付ければ通る
        status, _, body = self.put(
            make_blob(version=1000, body=b"\x01"),
            path="/api/service/4/16400/228?force=1",
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"], "stored")

    def test_newer_version_is_accepted(self):
        self.put(make_blob(version=1000, body=b"\x01"))
        status, _, body = self.put(make_blob(version=2000, body=b"\x02"))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"], "stored")

    def test_if_match_conflict(self):
        _, headers, _ = self.put(make_blob(version=1000, body=b"\x01"))
        stale_etag = headers["ETag"]

        # 別のクライアントが先に更新した
        self.put(make_blob(version=2000, body=b"\x02"))

        status, _, body = self.put(
            make_blob(version=3000, body=b"\x03"), headers={"If-Match": stale_etag}
        )
        self.assertEqual(status, 412)
        self.assertEqual(json.loads(body)["result"], "conflict")

        # 現在の ETag なら通る
        _, headers, _ = self.request("GET", "/api/service/4/16400/228")
        status, _, body = self.put(
            make_blob(version=3000, body=b"\x03"),
            headers={"If-Match": headers["ETag"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"], "stored")

    # -- 削除と永続化 ------------------------------------------------------

    def test_delete(self):
        self.put(make_blob())
        status, _, _ = self.request("DELETE", "/api/service/4/16400/228")
        self.assertEqual(status, 200)
        status, _, _ = self.request("GET", "/api/service/4/16400/228")
        self.assertEqual(status, 404)

    def test_index_survives_restart(self):
        self.put(make_blob(version=4242))

        reopened = server.Store(self.data_dir)
        entries = reopened.list_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].version, 4242)

    def test_index_rebuild_from_blobs(self):
        self.put(make_blob(version=4242))
        os.remove(os.path.join(self.data_dir, "index.json"))

        # 索引が失われても blob から復旧できる
        reopened = server.Store(self.data_dir)
        entries = reopened.list_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].version, 4242)

    def test_index_rebuild_from_corrupt_file(self):
        self.put(make_blob(version=4242))
        with open(os.path.join(self.data_dir, "index.json"), "w") as f:
            f.write("{ broken json")

        reopened = server.Store(self.data_dir)
        entries = reopened.list_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].version, 4242)

    # -- SSE ---------------------------------------------------------------

    def test_events_stream(self):
        received = []
        ready = threading.Event()
        done = threading.Event()

        def listen():
            req = urllib.request.Request(self.url("/api/events"))
            req.add_header("X-EPG-Token", "secret")
            with urllib.request.urlopen(req, timeout=15) as res:
                ready.set()
                for raw in res:
                    line = raw.decode("utf-8").strip()
                    if line.startswith("data: "):
                        received.append(json.loads(line[6:]))
                        done.set()
                        return

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        self.assertTrue(ready.wait(10), "SSE に接続できませんでした")

        # 購読が登録されるまで待つ
        for _ in range(100):
            if self.context.bus.subscriber_count() > 0:
                break
            threading.Event().wait(0.05)

        self.put(make_blob(version=777), headers={"X-EPG-Source": "test-pc"})

        self.assertTrue(done.wait(10), "更新通知が届きませんでした")
        self.assertEqual(received[0]["type"], "updated")
        self.assertEqual(received[0]["version"], 777)
        self.assertEqual(received[0]["source"], "test-pc")

    # -- 行指向形式(TVTest 向け) ----------------------------------------

    def test_services_text_format(self):
        self.put(make_blob(nid=4, tsid=0x4010, sid=0xE4, version=1000, event_count=5))
        self.put(make_blob(nid=4, tsid=0x4010, sid=0xE5, version=2000, event_count=7,
                           body=b"\x02"))

        status, headers, body = self.request("GET", "/api/services?format=text")
        self.assertEqual(status, 200)
        self.assertIn("text/plain", headers["Content-Type"])

        lines = body.decode("utf-8").splitlines()
        self.assertEqual(len(lines), 2)

        fields = lines[0].split(" ")
        self.assertEqual(len(fields), 6)
        self.assertEqual(fields[:5], ["4", "16400", "228", "1000", "5"])
        self.assertEqual(len(fields[5]), 32)  # etag

    def test_services_text_format_when_empty(self):
        status, _, body = self.request("GET", "/api/services?format=text")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    def test_format_event_text(self):
        line = server.format_event_text(
            {"type": "updated", "nid": 4, "tsid": 16400, "sid": 228,
             "version": 1000, "event_count": 5, "etag": "abc", "source": "living pc"}
        )
        self.assertEqual(line, "updated 4 16400 228 1000 5 abc living pc")

        line = server.format_event_text(
            {"type": "deleted", "nid": 4, "tsid": 16400, "sid": 228}
        )
        self.assertEqual(line, "deleted 4 16400 228")

    def test_events_text_stream(self):
        received = []
        ready = threading.Event()
        done = threading.Event()

        def listen():
            req = urllib.request.Request(self.url("/api/events?format=text"))
            req.add_header("X-EPG-Token", "secret")
            with urllib.request.urlopen(req, timeout=15) as res:
                ready.set()
                for raw in res:
                    line = raw.decode("utf-8").strip()
                    if line.startswith("data: "):
                        received.append(line[6:])
                        done.set()
                        return

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        self.assertTrue(ready.wait(10), "SSE に接続できませんでした")

        for _ in range(100):
            if self.context.bus.subscriber_count() > 0:
                break
            threading.Event().wait(0.05)

        self.put(make_blob(version=555, event_count=3), headers={"X-EPG-Source": "tv1"})

        self.assertTrue(done.wait(10), "更新通知が届きませんでした")
        fields = received[0].split(" ")
        self.assertEqual(fields[0], "updated")
        self.assertEqual(fields[1:6], ["4", "16400", "228", "555", "3"])
        self.assertEqual(fields[7], "tv1")

    # -- 切断の扱い --------------------------------------------------------

    def test_connection_reset_is_not_logged_as_error(self):
        """クライアントが接続を切っただけならトレースバックを出さない"""
        import logging

        records = []

        class Collector(logging.Handler):
            def emit(self, record):
                records.append(record)

        collector = Collector()
        server.LOG.addHandler(collector)
        try:
            self.httpd.handle_error(None, ("127.0.0.1", 12345))  # 例外は発生していない
            try:
                raise ConnectionResetError(10054, "強制的に切断されました")
            except ConnectionResetError:
                self.httpd.handle_error(None, ("127.0.0.1", 12345))
        finally:
            server.LOG.removeHandler(collector)

        self.assertFalse(
            [r for r in records if r.levelno >= logging.ERROR],
            "接続断で ERROR が記録されました",
        )

    def test_real_exception_is_still_logged(self):
        import logging

        records = []

        class Collector(logging.Handler):
            def emit(self, record):
                records.append(record)

        collector = Collector()
        server.LOG.addHandler(collector)
        try:
            try:
                raise ValueError("本物の不具合")
            except ValueError:
                self.httpd.handle_error(None, ("127.0.0.1", 12345))
        finally:
            server.LOG.removeHandler(collector)

        self.assertTrue([r for r in records if r.levelno >= logging.ERROR])

    def test_abrupt_disconnect_keeps_server_alive(self):
        """接続を途中で切っても、その後の要求が通ること"""
        import socket

        self.put(make_blob())

        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(b"GET /api/health HTTP/1.1\r\nHost: x\r\n\r\n")
        s.recv(64)
        # キープアライブで待機中の接続を RST で落とす
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        s.close()

        status, _, body = self.request("GET", "/api/services")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["services"]), 1)

    # -- 状態画面 ----------------------------------------------------------

    def test_index_page(self):
        self.put(make_blob())
        status, headers, body = self.request("GET", "/", token=None)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])

        html = body.decode("utf-8")
        self.assertIn("TVTest EPG Sync", html)
        self.assertIn("番組表", html)
        self.assertIn("同期状態", html)
        self.assertIn('/static/guide.css', html)
        self.assertIn('/static/guide-layout.js', html)
        self.assertIn('/static/guide.js', html)

    def test_static_guide_assets(self):
        status, headers, body = self.request("GET", "/static/guide.css", token=None)
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers["Content-Type"])
        self.assertIn(b"event-card", body)

        status, headers, body = self.request("GET", "/static/guide.js", token=None)
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", headers["Content-Type"])
        self.assertIn(b"EventSource", body)
        self.assertIn(b"/api/events?ui=1", body)

        status, headers, body = self.request("GET", "/static/guide-layout.js", token=None)
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", headers["Content-Type"])
        self.assertIn(b"variableTimeline", body)

    def test_fallback_status_page(self):
        self.put(make_blob())
        status, headers, body = self.request("GET", "/status", token=None)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        html = body.decode("utf-8")
        self.assertIn("0004/4010/00E4", html)
        self.assertIn("EventSource", html)

    def test_services_json_has_summary(self):
        status, _, body = self.request("GET", "/api/services")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["summary"]["subscribers"], 0)

    # -- 番組表 API -------------------------------------------------------

    def test_guide_api_filters_time_range(self):
        self.put(service_blob(event_blob(hour=2), event_blob(event_id=0x1001, hour=21)))

        status, _, body = self.request("GET", "/api/guide?date=2026-08-29")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["from"], "2026-08-29T04:00:00+09:00")
        self.assertEqual(payload["to"], "2026-08-30T04:00:00+09:00")
        events = payload["services"][0]["events"]
        self.assertEqual(payload["services"][0]["network_type"], "bs")
        self.assertEqual([item["event_id"] for item in events], [0x1001])
        self.assertEqual(events[0]["title"], "テスト番組『表題』")

    def test_guide_api_accepts_explicit_range(self):
        self.put(service_blob(event_blob(hour=21)))
        status, _, body = self.request(
            "GET", "/api/guide?from=2026-08-29T12:00:00%2B00:00&hours=2"
        )
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["from"], "2026-08-29T21:00:00+09:00")
        self.assertEqual(len(payload["services"][0]["events"]), 1)

    def test_guide_api_rejects_bad_range(self):
        status, _, body = self.request("GET", "/api/guide?date=bad")
        self.assertEqual(status, 400)
        self.assertIn("YYYY-MM-DD", json.loads(body)["error"])

        status, _, body = self.request("GET", "/api/guide?date=2026-08-29&hours=100")
        self.assertEqual(status, 400)
        self.assertIn("1 から 48", json.loads(body)["error"])

    def test_guide_event_details(self):
        self.put(service_blob(event_blob()))
        status, headers, body = self.request(
            "GET", "/api/guide/event/4/16400/228/4096"
        )
        self.assertEqual(status, 200)
        self.assertIn("ETag", headers)
        event = json.loads(body)["event"]
        self.assertEqual(event["title"], "テスト番組『表題』")
        self.assertEqual(event["extended_text"][0]["description"], "出演者")
        self.assertEqual(event["audio"][0]["text"], "主音声")

    def test_guide_cache_follows_service_etag(self):
        self.put(service_blob(event_blob(name="更新前")))
        _, _, body = self.request("GET", "/api/guide?date=2026-08-29")
        self.assertEqual(json.loads(body)["services"][0]["events"][0]["title"], "更新前")

        self.put(service_blob(event_blob(updated_time=3000, name="更新後")))
        _, _, body = self.request("GET", "/api/guide?date=2026-08-29")
        self.assertEqual(json.loads(body)["services"][0]["events"][0]["title"], "更新後")

    def test_malformed_body_does_not_break_whole_guide(self):
        self.put(make_blob(body=b"\x04\xff\xff\xff\x7f"))
        status, _, body = self.request("GET", "/api/guide?date=2026-08-29")
        self.assertEqual(status, 200)
        service = json.loads(body)["services"][0]
        self.assertEqual(service["events"], [])
        self.assertTrue(service["parse_error"])

    # -- 局メタデータ ------------------------------------------------------

    def test_service_metadata_names_and_orders_guide(self):
        self.put(service_blob(event_blob(name="一局目"), sid=0xE4))
        self.put(service_blob(event_blob(name="二局目"), sid=0xE5))
        metadata = {
            "services": [
                {
                    "nid": 4, "tsid": 0x4010, "sid": 0xE4,
                    "name": "総合テレビ", "group": "地デジ",
                    "network_type": "terrestrial",
                    "remote_control_key": 1, "service_type": 1, "order": 20,
                },
                {
                    "nid": 4, "tsid": 0x4010, "sid": 0xE5,
                    "name": "教育テレビ", "group": "地デジ",
                    "network_type": "terrestrial",
                    "remote_control_key": 2, "service_type": 1, "order": 10,
                },
            ]
        }
        status, _, body = self.request(
            "PUT", "/api/service-metadata",
            data=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-EPG-Source": "living-pc"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["count"], 2)

        status, _, body = self.request("GET", "/api/guide?date=2026-08-29")
        self.assertEqual(status, 200)
        services = json.loads(body)["services"]
        self.assertEqual([item["name"] for item in services], ["教育テレビ", "総合テレビ"])
        self.assertEqual(services[0]["group"], "地デジ")
        self.assertEqual(services[0]["network_type"], "terrestrial")
        self.assertEqual(services[0]["remote_control_key"], 2)

    def test_service_metadata_requires_token_and_valid_data(self):
        payload = json.dumps({"services": []}).encode("utf-8")
        status, _, _ = self.request(
            "PUT", "/api/service-metadata", data=payload, token=None
        )
        self.assertEqual(status, 401)

        status, _, body = self.request(
            "PUT", "/api/service-metadata", data=b'{"services":[{"nid":4}]}'
        )
        self.assertEqual(status, 400)
        self.assertTrue(json.loads(body)["error"])

        invalid = json.dumps({"services": [{
            "nid": 4, "tsid": 0x4010, "sid": 0xE4,
            "name": "不正局", "network_type": "cable",
        }]}).encode("utf-8")
        status, _, _ = self.request("PUT", "/api/service-metadata", data=invalid)
        self.assertEqual(status, 400)

    def test_service_metadata_survives_restart(self):
        metadata = {
            "services": [{
                "nid": 4, "tsid": 0x4010, "sid": 0xE4,
                "name": "保存局", "order": 1,
            }]
        }
        status, _, _ = self.request(
            "PUT", "/api/service-metadata",
            data=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200)

        reopened_store = server.Store(self.data_dir)
        reopened = server.Context(reopened_store, server.EventBus(), token="secret")
        item = reopened.metadata.get(server.ServiceKey(4, 0x4010, 0xE4))
        self.assertIsNotNone(item)
        self.assertEqual(item.name, "保存局")
        self.assertEqual(item.network_type, "bs")

    def test_known_satellite_networks_are_classified_and_migrated(self):
        self.assertEqual(server.normalize_network_type(None, 0x000B), "bs")
        self.assertEqual(server.normalize_network_type("terrestrial", 0x000B), "bs")
        self.assertEqual(server.normalize_network_type(None, 0x000A), "other")
        self.assertEqual(server.normalize_network_type("cs", 0x000A), "other")
        self.assertEqual(server.normalize_network_type(None, 0x0006), "cs")

        metadata = {
            "saved_at": "2026-08-30T00:00:00Z",
            "services": [
                {
                    "nid": 0x000B, "tsid": 1, "sid": 101,
                    "name": "BS 4K", "network_type": "terrestrial",
                },
                {
                    "nid": 0x000A, "tsid": 2, "sid": 102,
                    "name": "プレミアム", "network_type": "cs",
                },
            ],
        }
        with open(os.path.join(self.data_dir, "metadata.json"), "w", encoding="utf-8") as file:
            json.dump(metadata, file)

        reopened = server.MetadataStore(self.data_dir)
        self.assertEqual(
            reopened.get(server.ServiceKey(0x000B, 1, 101)).network_type,
            "bs",
        )
        self.assertEqual(
            reopened.get(server.ServiceKey(0x000A, 2, 102)).network_type,
            "other",
        )

    def test_ui_subscriber_is_not_counted(self):
        ready = threading.Event()
        stop = threading.Event()

        def listen(query):
            req = urllib.request.Request(self.url("/api/events" + query))
            req.add_header("X-EPG-Token", "secret")
            with urllib.request.urlopen(req, timeout=15) as res:
                ready.set()
                while not stop.is_set():
                    if not res.readline():
                        return

        t = threading.Thread(target=listen, args=("?ui=1",), daemon=True)
        t.start()
        self.assertTrue(ready.wait(10))

        # 状態画面からの購読が登録されるのを待つ
        for _ in range(100):
            if len(self.context.bus._subscribers) > 0:
                break
            threading.Event().wait(0.05)

        # ui=1 はクライアント数に数えない
        self.assertEqual(self.context.bus.subscriber_count(), 0)

        status, _, body = self.request("GET", "/api/services")
        self.assertEqual(json.loads(body)["summary"]["subscribers"], 0)

        stop.set()

    def test_ingress_path_prefix(self):
        status, _, body = self.request(
            "GET", "/api/health", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

        prefix = "/api/hassio_ingress/abc"
        status, _, body = self.request(
            "GET", prefix + "/", headers={"X-Ingress-Path": prefix}, token=None
        )
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn(prefix + "/static/guide.css", html)
        self.assertIn('window.EPGSYNC_BASE = "' + prefix + '"', html)


class RealBlobTestCase(ServerFixture):
    """TVTest / LibISDB が実際に生成した blob との相互運用

    EPGSYNC_TEST_BLOB に EPGDataSerializer が出力したファイルを指定して実行する。
    """

    def setUp(self):
        path = os.environ.get("EPGSYNC_TEST_BLOB")
        if not path or not os.path.exists(path):
            self.skipTest("EPGSYNC_TEST_BLOB が指定されていません")
        with open(path, "rb") as f:
            self.blob = f.read()
        super().setUp()

    def test_parses_real_blob(self):
        key, version, event_count = server.parse_header(self.blob)
        self.assertGreater(event_count, 0)
        self.assertGreater(version, 0)
        self.assertLessEqual(key.nid, 0xFFFF)
        print(
            f"\n  実データ: {key} version={version} events={event_count} "
            f"size={len(self.blob)} バイト"
        )

    def test_real_blob_round_trip_through_server(self):
        key, version, event_count = server.parse_header(self.blob)
        path = f"/api/service/{key.nid}/{key.tsid}/{key.sid}"

        status, headers, body = self.put(self.blob)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["result"], "stored")
        self.assertEqual(headers["X-EPG-Version"], str(version))
        self.assertEqual(json.loads(body)["current"]["event_count"], event_count)

        status, _, got = self.request("GET", path)
        self.assertEqual(status, 200)
        # サーバを経由してもバイト単位で変化しないこと
        self.assertEqual(got, self.blob)
