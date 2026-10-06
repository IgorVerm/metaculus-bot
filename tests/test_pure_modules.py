"""Tests for the standard-library modules in bot/. Run: python3 -m unittest discover -s tests"""

import asyncio
import io
import unittest
from datetime import datetime, timedelta, timezone

from bot import config, credits, slots, timebudget

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


class TimeBudgetTest(unittest.TestCase):
    def test_unknown_close_time_is_not_too_late(self):
        self.assertIsNone(timebudget.seconds_until(None, NOW))
        self.assertFalse(timebudget.too_late(None))

    def test_threshold(self):
        self.assertFalse(timebudget.too_late(config.SKIP_BELOW_SECONDS))
        self.assertTrue(timebudget.too_late(config.SKIP_BELOW_SECONDS - 1))
        self.assertTrue(timebudget.too_late(-10))

    def test_naive_close_time_is_read_as_utc(self):
        naive = (NOW + timedelta(hours=1)).replace(tzinfo=None)
        self.assertEqual(timebudget.seconds_until(naive, NOW), 3600)


class CreditsTest(unittest.TestCase):
    def test_remaining_from_payload(self):
        self.assertEqual(credits.remaining_from_payload({"data": {"limit_remaining": 12.5}}), 12.5)
        self.assertEqual(credits.remaining_from_payload({"data": {"limit": 100, "usage": 97}}), 3.0)
        self.assertIsNone(credits.remaining_from_payload({"data": {"limit": None, "usage": 4}}))
        self.assertIsNone(credits.remaining_from_payload({}))

    def test_decide(self):
        self.assertEqual(credits.decide(None), "full")
        self.assertEqual(credits.decide(config.FULL_LINEUP_MIN_USD), "full")
        self.assertEqual(credits.decide(config.FULL_LINEUP_MIN_USD - 0.01), "single")
        self.assertEqual(credits.decide(config.STOP_BELOW_USD), "single")
        self.assertEqual(credits.decide(config.STOP_BELOW_USD - 0.01), "stop")

    def test_fetch_remaining_reads_reply_and_sends_the_key_as_a_header(self):
        seen = {}

        class Reply(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def opener(request, timeout):
            seen["auth"] = request.get_header("Authorization")
            seen["url"] = request.full_url
            return Reply(b'{"data": {"limit_remaining": 42}}')

        self.assertEqual(credits.fetch_remaining("k", opener=opener), 42.0)
        self.assertEqual(seen["auth"], "Bearer k")
        self.assertEqual(seen["url"], credits.KEY_STATUS_URL)  # the key is not in the URL

    def test_fetch_remaining_failure_reads_as_unknown(self):
        def opener(request, timeout):
            raise OSError("down")

        self.assertIsNone(credits.fetch_remaining("k", opener=opener))


class SlotsTest(unittest.TestCase):
    def test_slots_cycle_per_question(self):
        assigner = slots.SlotAssigner()
        self.assertEqual([assigner.take("q1", 3) for _ in range(4)], [0, 1, 2, 0])
        self.assertEqual(assigner.take("q2", 3), 0)
        assigner.forget("q1")
        self.assertEqual(assigner.take("q1", 3), 0)

    def test_concurrent_tasks_each_keep_their_own_model(self):
        assigner = slots.SlotAssigner()
        lineup = ["a", "b", "c"]

        async def forecast():
            token = slots.bind_model(lineup[assigner.take("q", len(lineup))])
            try:
                await asyncio.sleep(0)  # let the other tasks run in between
                return slots.active_model()
            finally:
                slots.release(token)

        async def run():
            return await asyncio.gather(forecast(), forecast(), forecast())

        self.assertEqual(sorted(asyncio.run(run())), lineup)
        self.assertIsNone(slots.active_model())


class ConfigTest(unittest.TestCase):
    def test_models_go_through_openrouter_only(self):
        # Another route (for example the framework's Metaculus proxy) would put its
        # credential into the model settings that the bot publishes with each forecast.
        names = [spec["model"] for spec in config.FORECASTERS]
        names += [config.PARSER_MODEL, config.SUMMARIZER_MODEL, config.RESEARCHER_WITHOUT_ASKNEWS]
        for name in names:
            self.assertTrue(name.startswith("openrouter/"), name)

    def test_no_google_model(self):
        for spec in config.FORECASTERS:
            self.assertNotIn("google", spec["model"])

    def test_three_forecasts_from_two_vendors(self):
        vendors = {spec["model"].split("/")[1] for spec in config.FORECASTERS}
        self.assertEqual(len(config.FORECASTERS), 3)
        self.assertEqual(len(vendors), 2)


if __name__ == "__main__":
    unittest.main()
