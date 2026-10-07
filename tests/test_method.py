"""Tests for our method's pure modules: the checker, the framings and the freshness gate.

Run: python3 -m unittest discover -s tests
"""

import itertools
import random
import unittest
from datetime import date

from bot import config, formal, framings, freshness, limits

TODAY = date(2026, 10, 6)
SETTINGS = dict(range_tolerance=0.05, pair_tolerance=0.10, max_events=6)


def random_statement(rng: random.Random, labels: list[str], depth: int = 0):
    """A random statement as text, with brackets around every compound part."""
    roll = rng.random()
    if depth >= 3 or roll < 0.3:
        return rng.choice(labels)
    if roll < 0.45:
        return f"not {random_statement(rng, labels, depth + 1)}"
    word = rng.choice(["and", "or"])
    parts = [random_statement(rng, labels, depth + 1) for _ in range(rng.randint(2, 4))]
    return "(" + f" {word} ".join(parts) + ")"


class ParserTest(unittest.TestCase):
    def test_precedence_and_brackets(self):
        self.assertEqual(
            formal.parse("A or B and not C"),
            ("or", [("var", "A"), ("and", [("var", "B"), ("not", ("var", "C"))])]),
        )
        self.assertEqual(
            formal.parse("(A or B) and C"),
            ("and", [("or", [("var", "A"), ("var", "B")]), ("var", "C")]),
        )
        self.assertEqual(formal.parse("A AND B"), formal.parse("A and B"))
        self.assertEqual(formal.parse("not not A"), ("not", ("not", ("var", "A"))))
        self.assertEqual(formal.parse("A and B and C")[0], "and")
        self.assertEqual(len(formal.parse("A and B and C")[1]), 3)
        self.assertEqual(formal.labels_in(formal.parse("(A or F) and not A")), {"A", "F"})

    def test_everything_outside_the_token_set_is_refused(self):
        refused = [
            "",
            "   ",
            "G",  # only A to F
            "a and B",  # labels are capitals
            "A and",
            "and A",
            "A B",
            "(A or B",
            "A or B)",
            "()",
            "A & B",
            "A || B",
            "A and not",
            "A xor B",
            "A and 1",
            "A if B else C",
            "__import__('os').system('true')",
            "A.__class__",
            "A; B",
            "A\nor\x00B",
            "AB",
            "A or (B and (C or D)) or print",
            "A" + " and A" * 200,  # too long
            None,
            5,
        ]
        for statement in refused:
            with self.assertRaises(formal.StatementError, msg=repr(statement)):
                formal.parse(statement)

    def test_evaluate(self):
        tree = formal.parse("A and (B or not C)")
        self.assertTrue(formal.evaluate(tree, {"A": True, "B": False, "C": False}))
        self.assertFalse(formal.evaluate(tree, {"A": True, "B": False, "C": True}))
        self.assertFalse(formal.evaluate(tree, {"A": False, "B": True, "C": True}))


class BoundsTest(unittest.TestCase):
    def test_rules_as_specified(self):
        p = {"A": 0.7, "B": 0.6, "C": 0.2}
        self.assertEqual(formal.bounds(formal.parse("A"), p), (0.7, 0.7))
        low, high = formal.bounds(formal.parse("not A"), p)
        self.assertAlmostEqual(low, 0.3)
        self.assertAlmostEqual(high, 0.3)
        low, high = formal.bounds(formal.parse("A and B"), p)
        self.assertAlmostEqual(low, 0.3)  # 0.7 + 0.6 - 1
        self.assertAlmostEqual(high, 0.6)
        low, high = formal.bounds(formal.parse("A and B and C"), p)
        self.assertAlmostEqual(low, 0.0)  # max(0, 1.5 - 2)
        self.assertAlmostEqual(high, 0.2)
        low, high = formal.bounds(formal.parse("B or C"), p)
        self.assertAlmostEqual(low, 0.6)
        self.assertAlmostEqual(high, 0.8)
        low, high = formal.bounds(formal.parse("A or B or C"), p)
        self.assertAlmostEqual(low, 0.7)
        self.assertAlmostEqual(high, 1.0)  # min(1, 1.5)
        low, high = formal.bounds(formal.parse("not (A and B)"), p)
        self.assertAlmostEqual(low, 0.4)
        self.assertAlmostEqual(high, 0.7)

    def test_bounds_hold_for_any_dependence_between_events(self):
        # Random joint distributions over all truth assignments: the events' exact marginals go
        # into the bounds, and the statement's exact probability must lie inside them.
        rng = random.Random(20261006)
        checked = 0
        for _ in range(3000):
            labels = list(formal.LABELS[: rng.randint(1, 6)])
            assignments = list(itertools.product([False, True], repeat=len(labels)))
            style = rng.random()
            if style < 0.4:  # mass on a few assignments: strong dependence
                weights = [0.0] * len(assignments)
                count = min(len(assignments), rng.randint(1, 3))
                for index in rng.sample(range(len(assignments)), count):
                    weights[index] = rng.random() + 1e-6
            elif style < 0.7:  # uneven weights
                weights = [rng.random() ** 4 for _ in assignments]
            else:
                weights = [rng.random() for _ in assignments]
            total = sum(weights)
            weights = [weight / total for weight in weights]
            marginals = {
                # min(): a sum of floats can land a hair above 1
                label: min(1.0, sum(w for w, a in zip(weights, assignments) if a[position]))
                for position, label in enumerate(labels)
            }
            text = random_statement(rng, labels)
            tree = formal.parse(text)
            exact = sum(
                weight
                for weight, assignment in zip(weights, assignments)
                if formal.evaluate(tree, dict(zip(labels, assignment)))
            )
            low, high = formal.bounds(tree, marginals)
            self.assertLessEqual(low - 1e-9, exact, text)
            self.assertLessEqual(exact, high + 1e-9, text)
            self.assertLessEqual(0.0, low + 1e-12)
            self.assertLessEqual(high, 1.0 + 1e-12)
            self.assertEqual(formal.statement_range(text, marginals, 6), (low, high))
            checked += 1
        self.assertEqual(checked, 3000)

    def test_statement_range_refuses_unusable_events(self):
        with self.assertRaises(formal.StatementError):
            formal.statement_range("A and B", {"A": 0.5}, 6)  # B was not named
        with self.assertRaises(formal.StatementError):
            formal.statement_range("A", {}, 6)
        with self.assertRaises(formal.StatementError):
            formal.statement_range("A", {"A": 1.2}, 6)
        with self.assertRaises(formal.StatementError):
            formal.statement_range("A", {"A": None}, 6)
        with self.assertRaises(formal.StatementError):
            formal.statement_range("A", {"A": 0.5, "G": 0.5}, 6)
        with self.assertRaises(formal.StatementError):
            formal.statement_range("A", {"A": 0.5, "B": 0.5, "C": 0.5}, 2)  # too many events
        with self.assertRaises(formal.StatementError):
            formal.events_from_pairs([("A", 0.5), ("a ", 0.4)])  # the same label twice
        self.assertEqual(formal.events_from_pairs([(" a", 0.5), ("B", 0.4)]), {"A": 0.5, "B": 0.4})


def structured(events, statement, overall, split=None):
    return {"events": events, "statement": statement, "overall": overall, "split": split}


class BinaryContradictionTest(unittest.TestCase):
    def test_consistent_answers(self):
        answer = structured([("A", 0.5), ("B", 0.6)], "A and B", 0.3)
        result = formal.check_binary(0.32, 0.28, answer, **SETTINGS)
        self.assertEqual(result.value_range, (0.10000000000000009, 0.5))
        self.assertFalse(result.contradicted)
        self.assertEqual(result.skipped, [])

    def test_each_answer_outside_the_range(self):
        answer = structured([("A", 0.5), ("B", 0.6)], "A and B", 0.3)  # range 0.1 to 0.5
        self.assertEqual(len(formal.check_binary(0.8, None, answer, **SETTINGS).findings), 1)
        self.assertEqual(len(formal.check_binary(None, 0.02, answer, **SETTINGS).findings), 1)
        outside = structured([("A", 0.5), ("B", 0.6)], "A and B", 0.7)
        result = formal.check_binary(None, None, outside, **SETTINGS)
        self.assertEqual(len(result.findings), 1)
        self.assertIn("between 10% and 50%", result.findings[0])
        self.assertIn("A and B", result.findings[0])

    def test_range_tolerance_is_a_threshold(self):
        answer = structured([("A", 0.5)], "A", 0.5)
        self.assertFalse(formal.check_binary(0.55, None, answer, **SETTINGS).contradicted)
        self.assertFalse(formal.check_binary(0.45, None, answer, **SETTINGS).contradicted)
        self.assertTrue(formal.check_binary(0.56, None, answer, **SETTINGS).contradicted)
        self.assertTrue(formal.check_binary(0.44, None, answer, **SETTINGS).contradicted)

    def test_direct_against_reversed(self):
        self.assertFalse(formal.check_binary(0.6, 0.5, None, **SETTINGS).contradicted)
        self.assertFalse(formal.check_binary(0.3, 0.2, None, **SETTINGS).contradicted)
        result = formal.check_binary(0.62, 0.5, None, **SETTINGS)
        self.assertTrue(result.contradicted)
        self.assertIn("62%", result.findings[0])
        self.assertIn("50%", result.findings[0])
        self.assertIsNone(result.value_range)

    def test_conditional_split(self):
        split = {"event": "A", "if_yes": 0.8, "if_no": 0.1}  # 0.5 * 0.8 + 0.5 * 0.1 = 0.45
        self.assertAlmostEqual(formal.split_implied(0.5, 0.8, 0.1), 0.45)
        fits = structured([("A", 0.5), ("B", 0.9)], "A or B", 0.9, None)
        self.assertFalse(formal.check_binary(None, None, fits, **SETTINGS).contradicted)
        agrees = structured([("A", 0.5)], "A or not A", 0.47, split)
        self.assertFalse(formal.check_binary(None, None, agrees, **SETTINGS).contradicted)
        differs = structured([("A", 0.5)], "A or not A", 0.6, split)
        result = formal.check_binary(None, None, differs, **SETTINGS)
        self.assertEqual(len(result.findings), 1)
        self.assertIn("45%", result.findings[0])

    def test_a_checker_that_cannot_run_reports_nothing(self):
        # These decide the fallback: no finding means no second look.
        unusable = [
            structured([("A", 0.5)], "A and import os", 0.9),
            structured([("A", 0.5)], "A and B", 0.9),
            structured([("A", 0.5), ("A", 0.2)], "A", 0.9),
            structured([("A", 7)], "A", 0.9),
            structured([], "A", 0.9),
            structured([("A", 0.5)], None, 0.9),
            structured([(label, 0.5) for label in "ABCDEFG"], "A", 0.9),
        ]
        for answer in unusable:
            result = formal.check_binary(0.1, None, answer, **SETTINGS)
            self.assertIsNone(result.value_range, answer)
            self.assertFalse(result.contradicted, answer)
            self.assertTrue(result.skipped, answer)
        nothing = formal.check_binary(0.4, None, None, **SETTINGS)
        self.assertFalse(nothing.contradicted)
        self.assertTrue(nothing.skipped)

    def test_a_broken_split_is_skipped_and_the_pair_test_still_runs(self):
        for split in (
            {"event": "D", "if_yes": 0.8, "if_no": 0.1},
            {"event": "A", "if_yes": None, "if_no": 0.1},
            {"event": "A", "if_yes": 1.8, "if_no": 0.1},
        ):
            answer = structured([("A", 0.5)], "A", 0.5, split)
            result = formal.check_binary(0.5, 0.5, answer, **SETTINGS)
            self.assertFalse(result.contradicted)
            self.assertTrue(result.skipped)
        unparsed = structured([("A", 0.5)], "A plus B", 0.5)
        self.assertTrue(formal.check_binary(0.9, 0.2, unparsed, **SETTINGS).contradicted)

    def test_describe_numbers_the_findings(self):
        self.assertEqual(formal.describe(["first", "second"]), "1. first\n2. second")


class MultipleChoiceTest(unittest.TestCase):
    SETTINGS = dict(pair_tolerance=0.10, sum_tolerance=0.15)

    def test_conversion_uses_the_questions_names_and_order(self):
        converted = framings.convert_reversed_options(
            {"blue ": 0.7, "Red": 0.4, "GREEN": 0.9}, ["Red", "Blue", "Green"]
        )
        self.assertEqual(list(converted), ["Red", "Blue", "Green"])
        for value, expected in zip(converted.values(), [0.6, 0.3, 0.1]):
            self.assertAlmostEqual(value, expected)

    def test_conversion_refuses_incomplete_or_foreign_answers(self):
        options = ["Red", "Blue"]
        for answer in (
            {"Red": 0.4},
            {"Red": 0.4, "Blue": 0.5, "Green": 0.9},
            {"Red": 0.4, "Bleu": 0.5},
            {"Red": 0.4, "red": 0.5},
            {"Red": 1.4, "Blue": 0.5},
            {},
        ):
            with self.assertRaises(ValueError, msg=answer):
                framings.convert_reversed_options(answer, options)

    def test_sum_test(self):
        direct = {"Red": 0.6, "Blue": 0.3, "Green": 0.1}
        fine = {"Red": 0.65, "Blue": 0.35, "Green": 0.15}  # sums to 1.15
        self.assertFalse(formal.check_multiple_choice(direct, fine, **self.SETTINGS).contradicted)
        high = {"Red": 0.66, "Blue": 0.36, "Green": 0.16}  # sums to 1.18
        result = formal.check_multiple_choice(direct, high, **self.SETTINGS)
        self.assertEqual(len(result.findings), 1)
        self.assertIn("118%", result.findings[0])
        low = {"Red": 0.5, "Blue": 0.2, "Green": 0.1}  # sums to 0.8
        self.assertTrue(formal.check_multiple_choice(None, low, **self.SETTINGS).contradicted)

    def test_pair_test_per_option(self):
        direct = {"Red": 0.6, "Blue": 0.3, "Green": 0.1}
        swapped = {"Red": 0.3, "Blue": 0.6, "Green": 0.1}
        result = formal.check_multiple_choice(direct, swapped, **self.SETTINGS)
        self.assertEqual(len(result.findings), 2)
        self.assertIn("Red", result.findings[0])
        at_tolerance = {"Red": 0.5, "Blue": 0.4, "Green": 0.1}
        self.assertFalse(
            formal.check_multiple_choice(direct, at_tolerance, **self.SETTINGS).contradicted
        )

    def test_missing_answers_skip_the_check(self):
        direct = {"Red": 0.6, "Blue": 0.4}
        nothing = formal.check_multiple_choice(direct, None, **self.SETTINGS)
        self.assertFalse(nothing.contradicted)
        self.assertTrue(nothing.skipped)
        other_names = formal.check_multiple_choice({"Rouge": 0.6}, direct, **self.SETTINGS)
        self.assertFalse(other_names.contradicted)
        self.assertEqual(len(other_names.skipped), 2)

    def test_rescale(self):
        scaled = framings.rescale({"Red": 0.6, "Blue": 0.6})
        self.assertEqual(scaled, {"Red": 0.5, "Blue": 0.5})
        with self.assertRaises(ValueError):
            framings.rescale({"Red": 0.0, "Blue": 0.0})

    def test_floor_and_renormalise(self):
        result = framings.floor_and_renormalise({"Red": 0.9, "Blue": 0.3, "Green": 0.0}, 0.01)
        self.assertAlmostEqual(sum(result.values()), 1.0)
        self.assertAlmostEqual(result["Green"], 0.01)
        self.assertAlmostEqual(result["Red"] / result["Blue"], 3.0)
        # A second option falls under the floor only after the first was raised to it.
        cascade = framings.floor_and_renormalise(
            {"a": 0.9799, "b": 0.0101, "c": 0.0, "d": 0.01}, 0.01
        )
        self.assertAlmostEqual(sum(cascade.values()), 1.0)
        self.assertGreaterEqual(min(cascade.values()), 0.01 - 1e-12)
        rng = random.Random(7)
        for _ in range(500):
            values = {str(i): rng.random() ** 6 for i in range(rng.randint(2, 12))}
            floored = framings.floor_and_renormalise(values, config.MIN_OPTION_PROBABILITY)
            self.assertAlmostEqual(sum(floored.values()), 1.0)
            self.assertGreaterEqual(min(floored.values()), config.MIN_OPTION_PROBABILITY - 1e-12)
            self.assertLessEqual(max(floored.values()), 0.99 + 1e-12)
        with self.assertRaises(ValueError):
            framings.floor_and_renormalise({str(i): 1.0 for i in range(101)}, 0.01)


class ConversionTest(unittest.TestCase):
    def test_complement_and_clamp(self):
        self.assertAlmostEqual(framings.complement(0.3), 0.7)
        self.assertEqual(framings.clamp(framings.complement(0.999), 0.01, 0.99), 0.01)
        self.assertEqual(framings.clamp(framings.complement(0.0), 0.01, 0.99), 0.99)
        self.assertEqual(framings.clamp(0.4, 0.01, 0.99), 0.4)


class PromptTest(unittest.TestCase):
    QUESTION = framings.QuestionText(
        text="Will the bridge open before 2027?",
        background="It is being built.",
        criteria="Resolves Yes if the operator announces the opening.",
        fine_print="",
        options=(),
    )
    OPTIONS = framings.QuestionText(text="Which colour wins?", options=("Red", "Blue"))

    def test_every_research_request_carries_the_requirements(self):
        requirements = framings.research_requirements(TODAY, date(2026, 12, 1), ("bad.example",))
        for wanted in (
            "Today is 2026-10-06",
            "closes on 2026-12-01",
            "newest developments first",
            "publication date",
            "resolution criteria name",
            "bad.example",
            "NEWEST_EVIDENCE_DATE: YYYY-MM-DD",
            "NEWEST_EVIDENCE_DATE: unknown",
        ):
            self.assertIn(wanted, requirements)
        self.assertNotIn("Do not rely", framings.research_requirements(TODAY, None, ()))
        requests = [
            framings.reversed_research_request(self.QUESTION, requirements),
            framings.structured_research_request(self.QUESTION, requirements),
            framings.freshness_research_request(self.QUESTION, date(2026, 9, 1), requirements),
            framings.reversed_research_request(self.OPTIONS, requirements),
        ]
        for request in requests:
            self.assertIn(requirements, request)
        self.assertIn(self.QUESTION.criteria, requests[0])
        self.assertIn("since 2026-09-01", requests[2])
        self.assertIn("['Red', 'Blue']", requests[3])

    def test_the_question_is_passed_unchanged(self):
        prompts = [
            framings.reversed_binary_prompt(self.QUESTION, "R", TODAY),
            framings.structured_binary_prompt(self.QUESTION, "R", TODAY, 6),
            framings.second_look_binary_prompt(self.QUESTION, "R", TODAY, "said", "1. clash"),
        ]
        for prompt in prompts:
            self.assertIn(self.QUESTION.text, prompt)
            self.assertIn(self.QUESTION.criteria, prompt)
            self.assertIn("2026-10-06", prompt)
        self.assertTrue(prompts[0].startswith(framings.REVERSED_TITLE))
        self.assertIn("Probability of No: ZZ%", prompts[0])
        self.assertTrue(prompts[1].startswith(framings.STRUCTURED_TITLE))
        self.assertIn("A, B, C, D, E, F", prompts[1])
        self.assertIn("1. clash", prompts[2])
        self.assertIn('"Probability: ZZ%"', prompts[2])
        options = framings.reversed_options_prompt(self.OPTIONS, "", TODAY)
        self.assertIn("NOT the outcome", options)
        self.assertIn("(no research available)", options)
        second = framings.second_look_options_prompt(self.OPTIONS, "R", TODAY, "said", "1. clash")
        self.assertIn("Option_A: Probability_A", second)

    def test_research_as_read_and_as_published(self):
        dates = framings.dates_block(TODAY, date(2026, 9, 1), None, date(2027, 1, 2))
        self.assertIn("Today: 2026-10-06", dates)
        self.assertIn("closes for forecasts: not stated", dates)
        note = framings.age_note(date(2026, 10, 1), 5)
        self.assertIn("5 days before today", note)
        self.assertIn("unknown", framings.age_note(None, None))
        read = framings.for_forecaster(dates, note, "the research")
        self.assertEqual(read, f"{dates}\n{note}\n\nthe research")
        self.assertEqual(
            framings.for_forecaster(dates, "", ""), f"{dates}\n\n(no research available)"
        )
        published = framings.for_comment("# Title\n#tag\nbody " + "x" * 50, 20)
        self.assertNotIn("#", published)
        self.assertTrue(published.startswith("Title\ntag\nbody"))
        self.assertIn("shortened", published)
        self.assertEqual(framings.for_comment("short", 20), "short")


class FreshnessTest(unittest.TestCase):
    def test_reading_the_evidence_line(self):
        read = freshness.newest_evidence_date
        self.assertEqual(read("text\nNEWEST_EVIDENCE_DATE: 2026-10-01"), date(2026, 10, 1))
        self.assertEqual(read("**NEWEST_EVIDENCE_DATE:** 2026-10-01\n"), date(2026, 10, 1))
        self.assertEqual(read("newest_evidence_date:2026-09-30."), date(2026, 9, 30))
        # A joined text carries two lines; the last one is the retry's.
        self.assertEqual(
            read("NEWEST_EVIDENCE_DATE: 2026-08-01\nmore\nNEWEST_EVIDENCE_DATE: 2026-10-05"),
            date(2026, 10, 5),
        )
        for text in (
            "",
            None,
            "no line here",
            "NEWEST_EVIDENCE_DATE: unknown",
            "NEWEST_EVIDENCE_DATE: 2026-13-45",
            "NEWEST_EVIDENCE_DATE: last week",
        ):
            self.assertIsNone(read(text), text)

    def test_age(self):
        self.assertEqual(freshness.age_in_days(date(2026, 10, 1), TODAY), 5)
        self.assertEqual(freshness.age_in_days(TODAY, TODAY), 0)
        self.assertEqual(freshness.age_in_days(date(2026, 10, 7), TODAY), 0)  # a later time zone
        self.assertIsNone(freshness.age_in_days(date(2026, 10, 20), TODAY))  # not believable
        self.assertIsNone(freshness.age_in_days(None, TODAY))

    def test_retry_decision(self):
        limit = config.FRESHNESS_MAX_AGE_DAYS
        decide = freshness.needs_retry
        self.assertFalse(decide(limit, limit, from_search=True, already_retried=False))
        self.assertTrue(decide(limit + 1, limit, from_search=True, already_retried=False))
        self.assertTrue(decide(None, limit, from_search=True, already_retried=False))
        self.assertFalse(decide(None, limit, from_search=True, already_retried=True))
        self.assertFalse(decide(None, limit, from_search=False, already_retried=False))
        self.assertFalse(decide(0, limit, from_search=True, already_retried=False))

    def test_retry_asks_from_the_known_date_or_the_threshold(self):
        self.assertEqual(freshness.retry_since(date(2026, 8, 1), TODAY, 7), date(2026, 8, 1))
        self.assertEqual(freshness.retry_since(None, TODAY, 7), date(2026, 9, 29))
        self.assertEqual(freshness.retry_since(date(2027, 1, 1), TODAY, 7), date(2026, 9, 29))
        self.assertEqual(
            freshness.newest_of(None, date(2026, 1, 1), date(2026, 2, 1)), date(2026, 2, 1)
        )
        self.assertIsNone(freshness.newest_of(None, None))

    def test_which_research_sources_are_search_models(self):
        self.assertTrue(freshness.from_search_model(config.RESEARCHER_WITHOUT_ASKNEWS))
        self.assertTrue(freshness.from_search_model(config.SEARCH_MODEL))
        self.assertFalse(freshness.from_search_model(config.RESEARCHER_WITH_ASKNEWS))
        self.assertFalse(freshness.from_search_model("asknews/deep-research/low-depth"))
        self.assertFalse(freshness.from_search_model("smart-searcher/openrouter/x"))
        for name in ("", None, "None", "no_research"):
            self.assertFalse(freshness.from_search_model(name))

    def test_addresses_are_extracted_in_order_without_duplicates(self):
        text = (
            "See https://www.Example.org/a/b?x=1, and (http://news.example.com/story).\n"
            "[link](https://example.org/a/b?x=1) again https://www.Example.org/a/b?x=1 "
            "and <https://sub.data.example.net:8443/p#frag>; not ftp://old.example or example.com."
        )
        urls = freshness.extract_urls(text)
        self.assertEqual(
            urls,
            [
                "https://www.Example.org/a/b?x=1",
                "http://news.example.com/story",
                "https://example.org/a/b?x=1",
                "https://sub.data.example.net:8443/p#frag",
            ],
        )
        self.assertEqual(
            freshness.domains(urls), ["example.org", "news.example.com", "sub.data.example.net"]
        )
        self.assertEqual(freshness.extract_urls(None), [])
        self.assertEqual(freshness.extract_urls("no addresses"), [])

    def test_logged_addresses_carry_no_query(self):
        self.assertEqual(
            freshness.without_query("https://example.org/a?token=secret#x"), "https://example.org/a"
        )
        self.assertEqual(freshness.without_query("https://example.org/a"), "https://example.org/a")

    def test_blocked_domains(self):
        found = ["example.org", "news.bad.example", "notbad.example", "bad.example"]
        self.assertEqual(
            freshness.blocked_among(found, ("bad.example",)), ["news.bad.example", "bad.example"]
        )
        self.assertEqual(freshness.blocked_among(found, config.BLOCKED_DOMAINS), [])
        self.assertIsNone(freshness.domain_of("not an address"))
        self.assertIsNone(freshness.domain_of("http://[broken"))


class LimitsTest(unittest.TestCase):
    def test_short_text_is_untouched(self):
        self.assertEqual(limits.cap_text("short", 100), "short")
        self.assertEqual(limits.cap_text("x" * 100, 100), "x" * 100)
        self.assertEqual(limits.cap_text(None, 100), "")
        self.assertEqual(limits.cap_text("", 100), "")

    def test_long_text_is_cut_to_the_limit_and_says_so(self):
        for size in (101, 5000, 10**6):
            cut = limits.cap_text("x" * size, 100)
            self.assertEqual(len(cut), 100)
            self.assertTrue(cut.endswith(limits.CUT_MARKER))
            self.assertTrue(cut.startswith("x" * (100 - len(limits.CUT_MARKER))))
        self.assertEqual(limits.cap_text("abcdefgh", 3), "abc")  # no room for the marker
        self.assertEqual(limits.cap_text("abcdefgh", 0), "")
        self.assertEqual(limits.cap_text("abcdefgh", -5), "")
        once = limits.cap_text("y" * 50000, config.RESEARCH_MAX_CHARS)
        self.assertEqual(len(once), config.RESEARCH_MAX_CHARS)
        self.assertEqual(limits.cap_text(once, config.RESEARCH_MAX_CHARS), once)

    def test_run_cap(self):
        self.assertEqual(limits.split_for_run([1, 2, 3], 5), ([1, 2, 3], []))
        self.assertEqual(limits.split_for_run([1, 2, 3], 3), ([1, 2, 3], []))
        self.assertEqual(limits.split_for_run([1, 2, 3], 2), ([1, 2], [3]))
        self.assertEqual(limits.split_for_run([], 2), ([], []))
        self.assertEqual(limits.split_for_run([1, 2], 0), ([], [1, 2]))
        self.assertEqual(limits.split_for_run([1, 2], -1), ([], [1, 2]))
        kept, left = limits.split_for_run(list(range(40)), config.MAX_QUESTIONS_PER_RUN)
        self.assertEqual(len(kept), config.MAX_QUESTIONS_PER_RUN)
        self.assertEqual(len(left), 40 - config.MAX_QUESTIONS_PER_RUN)

    def test_limits_as_set_by_the_owner(self):
        self.assertEqual(config.FORECASTER_MAX_OUTPUT_TOKENS, 12000)
        self.assertEqual(config.SEARCH_MAX_OUTPUT_TOKENS, 6000)
        self.assertEqual(config.HELPER_MAX_OUTPUT_TOKENS, 4000)
        self.assertEqual(config.RESEARCH_MAX_CHARS, 16000)
        self.assertEqual(config.QUOTED_ANSWER_MAX_CHARS, 4000)
        self.assertEqual(config.MAX_QUESTIONS_PER_RUN, 5)
        self.assertEqual(config.RUN_COST_CEILING_USD, 25)
        self.assertLess(config.RESEARCH_RETRY_MAX_CHARS, config.RESEARCH_MAX_CHARS - 100)

    def test_worst_case_call_counts(self):
        self.assertEqual(
            limits.worst_case_calls("binary"),
            {"flagship": 8, "second_looks": 2, "search": 4, "parser": 14},
        )
        self.assertEqual(
            limits.worst_case_calls("multiple_choice"),
            {"flagship": 6, "second_looks": 2, "search": 3, "parser": 12},
        )
        self.assertEqual(limits.worst_case_calls("plain")["flagship"], 3)
        self.assertEqual(limits.worst_case_calls("conditional")["flagship"], 12)
        self.assertEqual(limits.worst_case_calls("conditional")["parser"], 24)
        with self.assertRaises(ValueError):
            limits.worst_case_calls("other")

    def test_every_model_has_a_price(self):
        names = [spec["model"] for spec in config.FORECASTERS]
        names += [config.SEARCH_MODEL, config.PARSER_MODEL, config.SUMMARIZER_MODEL]
        names.append(config.RESEARCHER_WITHOUT_ASKNEWS)
        for name in names:
            price_in, price_out = limits.price_per_million(name)
            self.assertGreater(price_in, 0)
            self.assertGreater(price_out, price_in)
        self.assertEqual(limits.price_per_million("openrouter/openai/gpt-6.1-sol"), (2.0, 10.0))
        self.assertEqual(
            limits.price_per_million("openrouter/anthropic/claude-opus-5.5"), (4.0, 20.0)
        )
        self.assertEqual(limits.price_per_million(config.SEARCH_MODEL), (0.10, 0.50))
        self.assertAlmostEqual(limits.call_cost_usd(config.SEARCH_MODEL, 1e6, 1e6), 0.60)
        with self.assertRaises(KeyError):
            limits.price_per_million("openrouter/other/model")

    def test_the_bound_by_hand(self):
        # A yes/no question at the limits, written out. Input per call: 16000 / 4 + 3000.
        research_in = 7000
        second_look_in = (16000 + 4 * 4000) / 4 + 3000
        self.assertEqual(limits.prompt_tokens(config.RESEARCH_MAX_CHARS), research_in)
        flagship = 0.0
        for price_in, price_out in ((2.0, 10.0), (4.0, 20.0)):  # four calls on each model
            tokens_in = 3 * research_in + second_look_in
            flagship += 2 * (tokens_in * price_in + 4 * 12000 * price_out) / 1e6  # two tries
        search = 4 * 2 * (research_in * 0.10 + 6000 * 0.50) / 1e6
        parser = 14 * 3 * 2 * ((12000 + 3000) * 0.10 + 4000 * 0.50) / 1e6
        by_hand = flagship + search + parser
        self.assertAlmostEqual(limits.worst_case_question_cost_usd(), by_hand)
        self.assertAlmostEqual(limits.worst_case_question_cost_usd("binary"), by_hand)
        self.assertAlmostEqual(
            limits.worst_case_run_cost_usd(), config.MAX_QUESTIONS_PER_RUN * by_hand
        )

    def test_conditional_bound_by_hand(self):
        # Three forecasts (two on the first model) of four parts; part k reads the research and
        # k earlier parts, each at most 4000 characters of reasoning and 2000 of frame.
        self.assertEqual(config.APPENDED_REASONING_MAX_CHARS, 4000)
        self.assertEqual(limits.template_research_max_chars(), 16000 + 3 * 6000)
        tokens_in = sum((16000 + earlier * 6000) / 4 + 3000 for earlier in range(4))
        flagship = 0.0
        for forecasts, (price_in, price_out) in ((2, (2.0, 10.0)), (1, (4.0, 20.0))):
            flagship += forecasts * 2 * (tokens_in * price_in + 4 * 12000 * price_out) / 1e6
        search = 1 * 2 * (7000 * 0.10 + 6000 * 0.50) / 1e6
        parser = 24 * 3 * 2 * ((12000 + 3000) * 0.10 + 4000 * 0.50) / 1e6
        self.assertAlmostEqual(
            limits.worst_case_question_cost_usd("conditional"), flagship + search + parser
        )
        self.assertGreater(
            limits.worst_case_question_cost_usd("conditional"),
            4 * limits.worst_case_question_cost_usd("plain"),
        )

    def test_a_run_stays_under_the_cost_ceiling(self):
        # A config change that lifts the bound over the ceiling fails here.
        self.assertEqual(
            set(limits.KINDS), {"binary", "multiple_choice", "plain", "conditional"}
        )
        for kind in limits.KINDS:
            bound = limits.worst_case_run_cost_usd(kind)
            self.assertLess(bound, config.RUN_COST_CEILING_USD, kind)
            self.assertGreater(bound, 0, kind)
        self.assertEqual(config.RUN_COST_CEILING_USD, 25)
        for kind in ("multiple_choice", "plain"):
            self.assertLess(
                limits.worst_case_run_cost_usd(kind), limits.worst_case_run_cost_usd()
            )


class MethodSettingsTest(unittest.TestCase):
    def test_settings_as_specified(self):
        self.assertEqual(config.RANGE_TOLERANCE, 0.05)
        self.assertEqual(config.PAIR_TOLERANCE, 0.10)
        self.assertEqual(config.SUM_TOLERANCE, 0.15)
        self.assertEqual(config.MAX_EVENTS, 6)
        self.assertEqual(config.FRESHNESS_MAX_AGE_DAYS, 7)
        self.assertEqual(config.BLOCKED_DOMAINS, ())
        self.assertEqual((config.MIN_PROBABILITY, config.MAX_PROBABILITY), (0.01, 0.99))
        self.assertEqual(len(formal.LABELS), config.MAX_EVENTS)

    def test_framings_per_question_type(self):
        self.assertEqual(
            config.FRAMINGS["binary"], (framings.DIRECT, framings.REVERSED, framings.STRUCTURED)
        )
        self.assertEqual(config.FRAMINGS["multiple_choice"], (framings.DIRECT, framings.REVERSED))


if __name__ == "__main__":
    unittest.main()
