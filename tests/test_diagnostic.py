import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from diagnostic import (CONFIG_NAME, MAX_BODY, Evidence, configuration,
                        decode_payload, install_config, make_server, save_report)


class PayloadTests(unittest.TestCase):
    def test_malformed_input(self):
        for raw in (b"", b"[]", b"null", b"{", b"\xff", b'{"x":NaN}',
                    b'{"x":1,"x":2}', b"x" * (MAX_BODY + 1)):
            with self.subTest(raw=raw[:24]), self.assertRaises(ValueError):
                decode_payload(raw)

    def test_depth_limit(self):
        with self.assertRaises(ValueError):
            decode_payload(b'{"x":' * 40 + b'0' + b'}' * 40)

    def test_markers_anywhere_but_not_auth(self):
        e = Evidence("team-123", "all-456")
        # Synthetic arbitrary fields deliberately do not claim a Dota schema.
        e.record({"auth": {"token": "team-123"},
                  "arbitrary_fixture": [{"value": "hello all-456"}]})
        self.assertEqual(e.report()["requests_containing_marker"], {"all": 1})
        self.assertNotIn("all-456", json.dumps(e.report()))
        self.assertNotIn("arbitrary_fixture", json.dumps(e.report()))

    def test_duplicate_count_does_not_discard_evidence(self):
        e = Evidence("team-123")
        e.record({"x": "team-123", "auth": {"token": "a"}})
        e.record({"auth": {"token": "b"}, "x": "team-123"})
        r = e.report()
        self.assertEqual(r["accepted_requests"], 2)
        self.assertEqual(r["consecutive_duplicate_payloads"], 1)
        self.assertEqual(r["requests_containing_marker"], {"team": 2})

    def test_empty_markers_do_not_match_everything(self):
        e = Evidence()
        e.record({"x": "test"})
        self.assertEqual(e.report()["requests_containing_marker"], {})

    def test_unicode_marker(self):
        e = Evidence("команда123", "所有456")
        e.record(decode_payload(json.dumps({"x": "команда123 所有456"}).encode()))
        self.assertEqual(e.report()["requests_containing_marker"], {"team": 1, "all": 1})

    def test_no_payloads_means_no_evidence(self):
        r = Evidence().report()
        self.assertEqual(r["accepted_requests"], 0)
        self.assertIsNone(r["last_received_utc"])

    def test_known_component_presence_is_metadata_only(self):
        e = Evidence()
        e.record({"map": {"name": "private_value"}, "player": {"name": "private_name"}})
        self.assertEqual(e.report()["requests_with_known_components"], {"map": 1, "player": 1})
        self.assertNotIn("private_", json.dumps(e.report()))

    def test_inspection_is_opt_in(self):
        e = Evidence("needle")
        e.record({"events": [{"text": "needle"}]})
        self.assertEqual(e.report()["marker_locations"], [])

    def test_paths_and_sibling_types_without_values(self):
        e = Evidence("TEAM_TEST", "ALL_TEST", inspect_marker_paths=True)
        # Synthetic fixture, not a claimed Dota field layout.
        payload = {"events": [{"text": "TEAM_TEST private_chat",
                               "channel": "private_channel", "player_id": 123456,
                               "auth": {"token": "ALL_TEST"}}]}
        e.record(payload)
        e.record(payload)
        locations = e.report()["marker_locations"]
        self.assertEqual(len(locations), 1)
        self.assertEqual(locations[0]["path"], "$.events[].text")
        self.assertEqual(locations[0]["parent_fields_types"],
                         {"text": "str", "channel": "str", "player_id": "int"})
        self.assertEqual(locations[0]["requests"], 2)
        serialized = json.dumps(locations)
        for private in ("TEAM_TEST", "ALL_TEST", "private_chat", "private_channel", "123456", "token"):
            self.assertNotIn(private, serialized)

    def test_dynamic_keys_are_hashed(self):
        e = Evidence("needle", inspect_marker_paths=True)
        e.record({"A_private_player_name": {"private_chat_as_key": "needle"}})
        serialized = json.dumps(e.report())
        self.assertNotIn("A_private_player_name", serialized)
        self.assertNotIn("private_chat_as_key", serialized)
        self.assertIn("key_sha256_", serialized)

    def test_locations_remain_bounded(self):
        e = Evidence("needle", inspect_marker_paths=True)
        for n in range(100):
            e.record({f"dynamic_{n}": "needle"})
        self.assertLessEqual(len(e.report()["marker_locations"]), 32)

    def test_report_saved_before_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            e = Evidence()
            save_report(path, e)
            self.assertEqual(json.loads(path.read_text())["accepted_requests"], 0)
            e.record({"map": {}})
            save_report(path, e)
            self.assertEqual(json.loads(path.read_text())["accepted_requests"], 1)
            self.assertFalse(path.with_suffix(".tmp").exists())


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.evidence = Evidence("TEAM_SYNTHETIC", "ALL_SYNTHETIC")
        self.server = make_server("test-token-not-a-secret", self.evidence, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            connection.request(method, path, body)
            response = connection.getresponse()
            data = response.read()
            return response.status, data
        finally:
            connection.close()

    def test_bound_only_to_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_health_does_not_claim_live_chat(self):
        code, data = self.request("GET", "/health")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)["live_chat"], "unverified")

    def test_auth_required(self):
        for payload in ({}, {"auth": []}, {"auth": {"token": "bad"}},
                        {"auth": {"token": 3}}):
            code, _ = self.request("POST", "/gsi", json.dumps(payload))
            self.assertEqual(code, 403)
        self.assertEqual(self.evidence.report()["accepted_requests"], 0)

    def test_authorized_synthetic_post(self):
        body = json.dumps({"auth": {"token": "test-token-not-a-secret"},
                           "fixture": "TEAM_SYNTHETIC"})
        self.assertEqual(self.request("POST", "/gsi", body)[0], 200)
        self.assertEqual(self.evidence.report()["requests_containing_marker"], {"team": 1})

    def test_bad_json_does_not_break_receiver(self):
        self.assertEqual(self.request("POST", "/gsi", b"{")[0], 400)
        self.assertEqual(self.request("GET", "/health")[0], 200)

    def test_wrong_endpoint(self):
        self.assertEqual(self.request("POST", "/other", b"{}")[0], 404)


class ConfigTests(unittest.TestCase):
    def test_config_has_no_invented_chat_component(self):
        cfg = configuration("dummy", 3009)
        self.assertIn('"uri" "http://127.0.0.1:3009/gsi"', cfg)
        self.assertNotIn('"chat"', cfg)
        with self.assertRaises(ValueError):
            configuration("dummy", 0)

    def test_install_backs_up_exact_previous_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = root / "dota" / "game" / "dota" / "cfg" / "gamestate_integration"
            cfg.mkdir(parents=True)
            existing = cfg / CONFIG_NAME
            existing.write_bytes(b"previous\r\nconfiguration")
            unrelated = cfg / "gamestate_integration_other.cfg"
            unrelated.write_bytes(b"leave alone")
            source = root / "new.cfg"
            source.write_bytes(b"new config")
            destination, backup = install_config(source, root / "dota")
            self.assertEqual(backup.read_bytes(), b"previous\r\nconfiguration")
            self.assertEqual(destination.read_bytes(), b"new config")
            self.assertEqual(unrelated.read_bytes(), b"leave alone")

    def test_invalid_game_root_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                install_config(Path(directory) / "none.cfg", Path(directory))

    def test_failed_backup_prevents_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = root / "game" / "dota" / "cfg" / "gamestate_integration"
            cfg.mkdir(parents=True)
            existing = cfg / CONFIG_NAME
            existing.write_bytes(b"must survive")
            source = root / "new.cfg"
            source.write_bytes(b"new")
            with patch("diagnostic.shutil.copy2", side_effect=PermissionError("test")):
                with self.assertRaises(PermissionError):
                    install_config(source, root)
            self.assertEqual(existing.read_bytes(), b"must survive")


if __name__ == "__main__":
    unittest.main()
