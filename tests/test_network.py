import json
import tempfile
import unittest
from pathlib import Path

from meta_sonata.network import (
    ExternalServiceError,
    NetworkClient,
    RateLimiter,
    ResponseCache,
)


class FakeHeaders:
    def __init__(self, content_type="application/json; charset=utf-8"):
        self.content_type = content_type

    def get(self, name, default=None):
        return self.content_type if name.lower() == "content-type" else default


class FakeResponse:
    def __init__(self, payload, content_type="application/json; charset=utf-8"):
        self.payload = payload
        self.headers = FakeHeaders(content_type)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class FakeClock:
    def __init__(self):
        self.value = 100.0
        self.sleeps = []

    def now(self):
        return self.value

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.value += delay


class NetworkTest(unittest.TestCase):
    def test_musicbrainz_rate_limit_is_never_bypassed(self):
        clock = FakeClock()
        calls = []

        def opener(request, *, timeout):
            calls.append((request.full_url, timeout))
            return FakeResponse(b'{"ok": true}')

        with tempfile.TemporaryDirectory() as tmp:
            client = NetworkClient(
                cache=ResponseCache(Path(tmp) / "cache.sqlite3"),
                opener=opener,
                musicbrainz_limiter=RateLimiter(
                    1.0,
                    clock=clock.now,
                    sleeper=clock.sleep,
                ),
            )
            client.fetch_json("https://musicbrainz.org/ws/2/artist/a?fmt=json")
            client.fetch_json("https://musicbrainz.org/ws/2/artist/b?fmt=json")

        self.assertEqual(len(calls), 2)
        self.assertEqual(clock.sleeps, [1.0])

    def test_musicbrainz_failure_still_reserves_the_rate_limit_slot(self):
        clock = FakeClock()
        attempts = 0

        def opener(request, *, timeout):
            nonlocal attempts
            del request, timeout
            attempts += 1
            raise TimeoutError("offline")

        with tempfile.TemporaryDirectory() as tmp:
            client = NetworkClient(
                cache=ResponseCache(Path(tmp) / "cache.sqlite3"),
                opener=opener,
                musicbrainz_limiter=RateLimiter(
                    1.0,
                    clock=clock.now,
                    sleeper=clock.sleep,
                ),
            )
            for entity in ("a", "b"):
                with self.assertRaises(ExternalServiceError):
                    client.fetch_json(
                        f"https://musicbrainz.org/ws/2/artist/{entity}?fmt=json"
                    )

        self.assertEqual(attempts, 2)
        self.assertEqual(clock.sleeps, [1.0])

    def test_success_is_cached_and_stale_cache_is_a_failure_fallback(self):
        calls = 0

        def success(request, *, timeout):
            nonlocal calls
            del request, timeout
            calls += 1
            return FakeResponse(json.dumps({"value": 1}).encode())

        with tempfile.TemporaryDirectory() as tmp:
            cache = ResponseCache(Path(tmp) / "cache.sqlite3")
            client = NetworkClient(cache=cache, opener=success)
            url = "https://example.test/data"

            self.assertEqual(client.fetch_json(url, cache_ttl=0), {"value": 1})

            def failing(request, *, timeout):
                del request, timeout
                raise TimeoutError("offline")

            offline = NetworkClient(cache=cache, opener=failing)
            self.assertEqual(offline.fetch_json(url), {"value": 1})

        self.assertEqual(calls, 1)

    def test_non_musicbrainz_hosts_are_not_artificially_delayed(self):
        clock = FakeClock()

        def opener(request, *, timeout):
            del request, timeout
            return FakeResponse(b'{"ok": true}')

        with tempfile.TemporaryDirectory() as tmp:
            client = NetworkClient(
                cache=ResponseCache(Path(tmp) / "cache.sqlite3"),
                opener=opener,
                musicbrainz_limiter=RateLimiter(
                    1.0,
                    clock=clock.now,
                    sleeper=clock.sleep,
                ),
            )
            client.fetch_json("https://itunes.apple.com/search?term=a")
            client.fetch_json("https://itunes.apple.com/search?term=b")

        self.assertEqual(clock.sleeps, [])

    def test_malformed_json_is_not_left_in_the_cache(self):
        payloads = [b"not-json", b'{"ok": true}']

        def opener(request, *, timeout):
            del request, timeout
            return FakeResponse(payloads.pop(0))

        with tempfile.TemporaryDirectory() as tmp:
            client = NetworkClient(
                cache=ResponseCache(Path(tmp) / "cache.sqlite3"),
                opener=opener,
            )
            url = "https://example.test/data"
            with self.assertRaises(ExternalServiceError):
                client.fetch_json(url)
            self.assertEqual(client.fetch_json(url), {"ok": True})

        self.assertEqual(payloads, [])


if __name__ == "__main__":
    unittest.main()
