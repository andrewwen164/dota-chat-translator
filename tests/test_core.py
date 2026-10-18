import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest

from translator.core import (ApiFailure, Cache, Duplicates, Engine, Job, Message,
                             Worker, parse_translation, valid_text)


class NeverEnglish:
    def is_english(self, text):
        return False


class FakeApi:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    async def translate(self, text, target):
        self.calls += 1
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self):
        pass


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = Cache(":memory:", limit=2)

    def tearDown(self):
        self.cache.close()

    def test_key_separates_all_dimensions(self):
        self.cache.put("тп", "English", "a", "TP")
        self.assertEqual(self.cache.get("тп", "English", "a"), "TP")
        for source, target, model, version in (("тп!", "English", "a", "dota-translate-1"),
                ("тп", "Spanish", "a", "dota-translate-1"),
                ("тп", "English", "b", "dota-translate-1"), ("тп", "English", "a", "v2")):
            self.assertIsNone(self.cache.get(source, target, model, version))

    def test_persists_across_connections(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "cache.sqlite"
            c = Cache(path)
            c.put("hola", "English", "a", "hello")
            c.close()
            c = Cache(path)
            self.assertEqual(c.get("hola", "English", "a"), "hello")
            c.close()

    def test_prunes_and_clears(self):
        for i in range(3):
            self.cache.put(str(i), "English", "a", "value")
        self.assertIsNone(self.cache.get("0", "English", "a"))
        self.assertEqual(self.cache.db.execute("SELECT count(*) FROM translations").fetchone()[0], 2)
        self.cache.clear()
        self.assertIsNone(self.cache.get("2", "English", "a"))

    def test_invalid_translation_not_cached(self):
        with self.assertRaises(ValueError):
            self.cache.put("hola", "English", "a", "")


class ParsingTests(unittest.TestCase):
    def test_valid_unicode(self):
        raw = json.dumps({"translation": "Use BKB, damn it!", "source_language": "ru"})
        self.assertEqual(parse_translation(raw), "Use BKB, damn it!")

    def test_rejects_bad_shapes_and_empty(self):
        for raw in (None, "", "not json", '[]', '{"translation": "hello"}',
                    '{"translation": null, "source_language":"es"}',
                    '{"translation":"", "source_language":"es"}',
                    '{"translation":"hello", "source_language":"xx"}',
                    '{"translation":"hello", "translation":"bad", "source_language":"es"}',
                    '{"translation":"hello", "source_language":"es", "command":"send"}'):
            with self.subTest(raw=raw), self.assertRaises((ValueError, TypeError)):
                parse_translation(raw)

    def test_input_bounds(self):
        for text in (None, 4, "", " " * 4, "a" * 2001, "hello\x00", "\ud800"):
            self.assertFalse(valid_text(text))
        self.assertTrue(valid_text("使用 BKB!"))


class DuplicateTests(unittest.TestCase):
    def test_persistent_snapshot_refreshes_presence(self):
        now = [0]
        d = Duplicates(seconds=10, clock=lambda: now[0])
        m = Message("hola", origin="gsi")
        d.add(m)
        now[0] = 9
        self.assertTrue(d.contains(m))
        now[0] = 18
        self.assertTrue(d.contains(m))
        now[0] = 30
        self.assertFalse(d.contains(m))

    def test_event_ids_preserve_repeated_text(self):
        d = Duplicates()
        d.add(Message("hola", event_id="1", origin="gsi"))
        self.assertFalse(d.contains(Message("hola", event_id="2", origin="gsi")))
        self.assertTrue(d.contains(Message("hola", event_id="1", origin="gsi")))

    def test_queue_overflow_does_not_mark_unscheduled_message_seen(self):
        w = Worker(Path("unused"), FakeApi([]), lambda r: None, capacity=1)
        one, two = Job(Message("hola", origin="gsi")), Job(Message("你好", origin="gsi"))
        self.assertEqual(w.submit(one), "queued")
        self.assertEqual(w.submit(two), "queue full")
        self.assertEqual(w.submit(one), "duplicate")
        w.jobs.get_nowait()
        self.assertEqual(w.submit(two), "queued")

    def test_expired_duplicate_is_not_refreshed_before_enqueue(self):
        now = [0]
        d = Duplicates(seconds=10, clock=lambda: now[0])
        m = Message("hola", origin="gsi")
        d.add(m)
        now[0] = 11
        self.assertFalse(d.contains(m))
        self.assertFalse(d.contains(m))

    def test_worker_shutdown_cancels_inflight_request(self):
        entered = threading.Event()
        class Waiting(FakeApi):
            async def translate(self, text, target):
                entered.set()
                await asyncio.sleep(60)
        with tempfile.TemporaryDirectory() as directory:
            worker = Worker(Path(directory) / "cache.sqlite", Waiting([]), lambda r: None)
            worker.submit(Job(Message("Привет")))
            worker.start()
            self.assertTrue(entered.wait(3))
            worker.stop()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(worker.error, "")


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cache = Cache(":memory:")
        self.now = 0
        self.delays = []

    async def asyncTearDown(self):
        self.cache.close()

    async def sleep(self, seconds):
        self.delays.append(seconds)
        self.now += seconds

    def engine(self, outcomes, **kwargs):
        return Engine(FakeApi(outcomes), self.cache, detector=NeverEnglish(),
                      clock=lambda: self.now, sleep=self.sleep, **kwargs)

    async def test_success_then_cache_no_second_request(self):
        e = self.engine(["hello"])
        job = Job(Message("hola"))
        self.assertEqual((await e.process(job)).status, "translated")
        self.assertEqual((await e.process(job)).status, "cached")
        self.assertEqual(e.api.calls, 1)

    async def test_failure_shows_original_not_cached(self):
        e = self.engine([ApiFailure(), "hello"])
        job = Job(Message("hola"))
        self.assertEqual((await e.process(job)).translation, "hola")
        self.assertEqual((await e.process(job)).translation, "hello")
        self.assertEqual(e.api.calls, 2)

    async def test_transient_retry_capped_and_rate_limited(self):
        e = self.engine([ApiFailure(True)] * 3, attempts=2, rpm=20)
        result = await e.process(Job(Message("hola")))
        self.assertTrue(result.status.startswith("failed"))
        self.assertEqual(e.api.calls, 2)
        self.assertGreaterEqual(sum(self.delays), 3)

    async def test_permanent_failure_not_retried(self):
        e = self.engine([ApiFailure(False)], attempts=3)
        await e.process(Job(Message("hola")))
        self.assertEqual(e.api.calls, 1)

    async def test_safe_error_reason_and_code_in_result_and_metrics(self):
        e = self.engine([ApiFailure(reason="model_unavailable", http_status=404)])
        r = await e.process(Job(Message("hola")))
        self.assertEqual(r.translation, "hola")
        self.assertEqual(r.error_reason, "model_unavailable")
        self.assertEqual(r.http_status, 404)
        self.assertIn("model unavailable", r.status)
        self.assertEqual(e.metrics["last_error_reason"], "model_unavailable")
        self.assertEqual(e.metrics["last_http_status"], 404)

    async def test_timeout(self):
        class Slow(FakeApi):
            async def translate(self, text, target):
                await asyncio.sleep(1)
        e = self.engine([], attempts=1, timeout=0.01)
        e.api = Slow([])
        result = await e.process(Job(Message("hola")))
        self.assertEqual(result.translation, "hola")
        self.assertEqual(e.metrics["failures"], 1)

    async def test_identifiable_chatwheel_skipped(self):
        e = self.engine([])
        r = await e.process(Job(Message("Отходим!", chatwheel=True)))
        self.assertEqual(r.status, "skipped")
        self.assertEqual(e.api.calls, 0)

    async def test_known_english_skipped_without_api_call(self):
        from translator.core import EnglishDetector
        e = self.engine([])
        e.detector = EnglishDetector()
        result = await e.process(Job(Message("gg wp")))
        self.assertEqual(result.status, "skipped")
        self.assertEqual(e.api.calls, 0)

    async def test_outgoing_uses_same_pipeline_with_target_key(self):
        e = self.engine(["привет"])
        r = await e.process(Job(Message("hello"), "Russian", outgoing=True))
        self.assertEqual(r.translation, "привет")
        self.assertEqual(self.cache.get("hello", "Russian", e.model), "привет")

    async def test_malformed_input_no_request(self):
        e = self.engine([])
        r = await e.process(Job(Message("")))
        self.assertEqual(r.status, "invalid input")
        self.assertEqual(e.api.calls, 0)
