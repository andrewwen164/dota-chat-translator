from dataclasses import asdict
import unittest

from translator.ingest import Mapping, checked_path, discover_strings


class MappingTests(unittest.TestCase):
    def test_no_default_schema_assumption(self):
        self.assertEqual(Mapping().extract({"chat": "hola"}), [])

    def test_user_mapped_fields_only(self):
        mapping = Mapping(enabled=True, records=["fixture", "*"], text=["body"],
                          sender=["who"], channel=["where"], event_id=["id"])
        result = mapping.extract({"fixture": [{"body": "hola", "who": "actual name",
                                   "where": "raw channel", "id": 3}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].sender, "actual name")
        self.assertEqual(result[0].channel, "raw channel")
        self.assertEqual(result[0].hero, "")
        self.assertEqual(result[0].event_id, "3")

    def test_malformed_records_skipped(self):
        mapping = Mapping(enabled=True, records=["fixture", "*"], text=["body"])
        self.assertEqual(mapping.extract({"fixture": [None, 4, {}, {"body": 7}, {"body": ""}]}), [])

    def test_unmapped_identity_unknown(self):
        result = Mapping(enabled=True, text=["body"]).extract({"body": "hola", "name": "not mapped"})
        self.assertEqual(result[0].sender, "")
        self.assertEqual(result[0].channel, "")

    def test_auth_never_a_selectable_field(self):
        with self.assertRaises(ValueError):
            checked_path(["auth", "token"])
        found = list(discover_strings({"auth": {"token": "secret"}, "x": "hola"}))
        self.assertEqual(found, [(["x"], "hola")])

    def test_paths_roundtrip_and_validation(self):
        m = Mapping(enabled=True, records=["fixture", "*"], text=["body"])
        self.assertEqual(Mapping.from_dict(asdict(m)), m)
        for path in ("$.x", [False], [-1], ["auth"], ["x"] * 33):
            with self.assertRaises(ValueError):
                checked_path(path)

    def test_chatwheel_only_explicit_true(self):
        m = Mapping(enabled=True, records=["fixture", "*"], text=["body"], chatwheel=["wheel"])
        records = [{"body": "hola", "wheel": True}, {"body": "hola", "wheel": "true"}]
        self.assertEqual([x.chatwheel for x in m.extract({"fixture": records})], [True, False])
