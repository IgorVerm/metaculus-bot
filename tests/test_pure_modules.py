"""Tests for the standard-library modules in bot/. Run: python3 -m unittest discover -s tests"""

import asyncio
import io
import unittest
from datetime import datetime, timedelta, timezone

from bot import config, credits, researcher, slots, timebudget

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


class SoonestFirstTest(unittest.TestCase):
    class Question:
        def __init__(self, name, close_time):
            self.name = name
            self.close_time = close_time

    def names(self, questions):
        return [question.name for question in timebudget.soonest_first(questions)]

    def test_soonest_first_and_unknown_last(self):
        Question = self.Question
        questions = [
            Question("weeks", NOW + timedelta(days=20)),
            Question("unknown", None),
            Question("hours", NOW + timedelta(hours=2)),
            Question("days", NOW + timedelta(days=2)),
        ]
        self.assertEqual(self.names(questions), ["hours", "days", "weeks", "unknown"])
        self.assertEqual([q.name for q in questions][0], "weeks")  # the input is not changed

    def test_equal_and_unknown_close_times_keep_their_order(self):
        Question = self.Question
        same = NOW + timedelta(days=1)
        questions = [
            Question("u1", None),
            Question("b", same),
            Question("u2", None),
            Question("a", same),
            Question("first", NOW),
        ]
        self.assertEqual(self.names(questions), ["first", "b", "a", "u1", "u2"])
        self.assertEqual(timebudget.soonest_first([]), [])

    def test_naive_close_time_is_read_as_utc(self):
        Question = self.Question
        naive = (NOW + timedelta(hours=1)).replace(tzinfo=None)
        questions = [Question("aware", NOW + timedelta(hours=2)), Question("naive", naive)]
        self.assertEqual(self.names(questions), ["naive", "aware"])


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
        names.append(config.SEARCH_MODEL)
        for name in names:
            self.assertTrue(name.startswith("openrouter/"), name)

    def test_no_google_model(self):
        names = [spec["model"] for spec in config.FORECASTERS]
        names += [config.PARSER_MODEL, config.RESEARCHER_WITHOUT_ASKNEWS, config.SEARCH_MODEL]
        for name in names:
            self.assertNotIn("google", name)
            self.assertNotIn("gemini", name)

    def test_two_models_from_two_vendors_at_high_effort(self):
        vendors = [spec["model"].split("/")[1] for spec in config.FORECASTERS]
        self.assertEqual(vendors, ["openai", "anthropic"])
        for spec in config.FORECASTERS:
            self.assertEqual(spec["reasoning"], {"effort": "high"})

    def test_three_forecasts_from_two_vendors(self):
        # The question types outside our method: three plain forecasts, the first vendor twice.
        lineup = [config.FORECASTERS[slot] for slot in config.PLAIN_FORECAST_SLOTS]
        vendors = [spec["model"].split("/")[1] for spec in lineup]
        self.assertEqual(len(lineup), 3)
        self.assertEqual(len(set(vendors)), 2)
        self.assertEqual(vendors, ["openai", "anthropic", "openai"])

    def test_research_without_asknews_uses_the_search_model(self):
        self.assertEqual(config.RESEARCHER_WITHOUT_ASKNEWS, config.SEARCH_MODEL)

    def test_search_model_searches_and_is_from_a_vendor_the_key_serves(self):
        self.assertTrue(config.SEARCH_MODEL.endswith(":online"))
        self.assertIn(config.SEARCH_MODEL.split("/")[1], ("openai", "anthropic"))


class ResearcherTest(unittest.TestCase):
    def test_only_openrouter_asknews_and_no_research_are_allowed(self):
        for name in (
            "openrouter/openai/gpt-6-luna:online",
            config.RESEARCHER_WITHOUT_ASKNEWS,
            config.RESEARCHER_WITH_ASKNEWS,
            config.SEARCH_MODEL,
            "asknews/deep-research/low-depth",
            "no_research",
        ):
            self.assertTrue(researcher.allowed(name), name)
        for name in (
            "metaculus/x",  # the framework would put the Metaculus token into published settings
            "exa/x",  # likewise an API key
            "smart-searcher/openrouter/x",
            "",
            None,
            "None",
            "No_Research",
            "no_research ",
            " openrouter/openai/x",
            "OpenRouter/openai/x",
            "openrouter",
            "openai/gpt-6-luna",
            "perplexity/sonar",
            "metaculus/openrouter/x",
            5,
        ):
            self.assertFalse(researcher.allowed(name), repr(name))

    def test_only_openrouter_names_are_built_as_model_objects(self):
        self.assertTrue(researcher.is_openrouter_model("openrouter/openai/gpt-6-luna:online"))
        for name in ("asknews/news-summaries", "no_research", "metaculus/x", "exa/x", "", None):
            self.assertFalse(researcher.is_openrouter_model(name), repr(name))

    def test_the_error_text_names_the_allowed_forms(self):
        for form in ("openrouter/", "asknews/", "no_research"):
            self.assertIn(form, researcher.ALLOWED_FORMS)


if __name__ == "__main__":
    unittest.main()
