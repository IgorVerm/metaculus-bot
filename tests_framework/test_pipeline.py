"""Our method run end to end with stand-in models. Needs the framework, so it runs in CI only:

    poetry run python -m unittest discover -s tests_framework -v

No test uses the network or a key. The models are stand-ins whose `invoke` returns fixed text,
and `structure_output` (which would call a parser model) is replaced by a stand-in that reads
the JSON line each fixed text ends with.
"""

import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import run_bot
from bot import config, framings
from forecasting_tools import (
    BinaryQuestion,
    ForecastBot,
    GeneralLlm,
    MetaculusQuestion,
    MultipleChoiceQuestion,
)

NOW = datetime.now(timezone.utc)
FRESH = NOW.date().isoformat()
OPTIONS = ["Red", "Blue", "Green"]


class StandInModel(GeneralLlm):
    """A model that answers from a function of the prompt and records what it was asked."""

    def __init__(self, name: str, responder) -> None:
        super().__init__(model=name)
        self.responder = responder
        self.prompts: list[str] = []

    async def invoke(self, prompt, system_prompt=None) -> str:  # type: ignore[override]
        self.prompts.append(prompt)
        await asyncio.sleep(0)  # let the concurrent calls interleave
        answer = self.responder(prompt)
        if isinstance(answer, BaseException):
            raise answer
        return answer


async def stand_in_structure_output(
    text_to_structure,
    output_type,
    model=None,
    num_validation_samples=1,
    allowed_tries=3,
    additional_instructions=None,
):
    lines = [line for line in text_to_structure.splitlines() if line.startswith("JSON: ")]
    if not lines:
        raise ValueError("the text holds no answer to parse")
    return output_type.model_validate(json.loads(lines[-1][len("JSON: ") :]))


def reply(text: str, payload: dict) -> str:
    return f"{text}\nJSON: {json.dumps(payload)}"


def binary(probability: float) -> str:
    return reply("Reasoning.", {"prediction_in_decimal": probability})


def structured(overall: float, statement: str = "A and B", split: dict | None = None) -> str:
    payload = {
        "events": [
            {"label": "A", "description": "the vote is held", "probability": 0.5},
            {"label": "B", "description": "the vote passes", "probability": 0.6},
        ],
        "statement": statement,
        "overall_probability": overall,
    }
    if split:
        payload["conditional_split"] = split
    return reply("Events and statement.", payload)


def option_list(probabilities: list[float]) -> str:
    return reply(
        "Reasoning.",
        {
            "predicted_options": [
                {"option_name": name, "probability": value}
                for name, value in zip(OPTIONS, probabilities)
            ]
        },
    )


def not_outcome(probabilities: list[float]) -> str:
    return reply(
        "Reasoning.",
        {
            "options": [
                {"option_name": name, "probability_not_outcome": value}
                for name, value in zip(OPTIONS, probabilities)
            ]
        },
    )


def forecaster(name: str, *, direct, reversed_, structured_=None, second_look=None) -> StandInModel:
    """A stand-in forecaster; each argument is the fixed text (or exception) for one framing."""

    def responder(prompt: str):
        if prompt.startswith(framings.SECOND_LOOK_TITLE):
            return second_look if second_look is not None else RuntimeError("no second look")
        if prompt.startswith(framings.REVERSED_TITLE):
            return reversed_
        if prompt.startswith(framings.REVERSED_OPTIONS_TITLE):
            return reversed_
        if prompt.startswith(framings.STRUCTURED_TITLE):
            return structured_
        return direct  # the template's own prompt

    return StandInModel(name, responder)


def searcher(evidence_date: str = FRESH, fail_on: str | None = None) -> StandInModel:
    def responder(prompt: str):
        if fail_on and prompt.startswith(fail_on):
            return TimeoutError("search failed")
        return (
            "Found at https://news.example.org/story?id=5 and https://www.example.com/a.\n"
            f"NEWEST_EVIDENCE_DATE: {evidence_date}"
        )

    return StandInModel("openrouter/stand-in/search:online", responder)


def build(forecasters, *, researcher=None, search=None, plain_slots=None) -> run_bot.MedianBot:
    return run_bot.MedianBot(
        forecasters=forecasters,
        plain_slots=plain_slots,
        search_model=search or searcher(),
        research_reports_per_question=1,
        use_research_summary_to_forecast=False,
        enable_summarize_research=False,
        publish_reports_to_metaculus=False,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=False,
        extra_metadata_in_explanation=True,
        llms={
            "default": forecasters[0],
            "summarizer": "openrouter/stand-in/summarizer",
            "researcher": researcher or searcher(),
            "parser": "openrouter/stand-in/parser",
        },
    )


def question_fields() -> dict:
    return dict(
        id_of_post=1,
        id_of_question=1,
        page_url="https://www.metaculus.com/questions/1/",
        background_info="A vote is planned.",
        resolution_criteria="Resolves as the official register shows.",
        fine_print="",
        open_time=NOW - timedelta(days=3),
        close_time=NOW + timedelta(days=30),
        scheduled_resolution_time=NOW + timedelta(days=60),
    )


def binary_question() -> BinaryQuestion:
    return BinaryQuestion(question_text="Will the law pass before 2027?", **question_fields())


def choice_question() -> MultipleChoiceQuestion:
    return MultipleChoiceQuestion(
        question_text="Which colour wins?", options=list(OPTIONS), **question_fields()
    )


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        for target in ("run_bot.structure_output", "main.structure_output"):
            patcher = mock.patch(target, stand_in_structure_output)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_method(self, bot, question):
        """Run our method for one question; returns the result and the log lines."""
        with self.assertLogs("run_bot", level="INFO") as captured:
            result = asyncio.run(bot._research_and_make_predictions(question))
        return result, [record.getMessage() for record in captured.records]

    @staticmethod
    def lines(log: list[str], word: str) -> list[str]:
        return [line for line in log if line.startswith(word + " ")]

    # --- yes/no ---

    def test_binary_with_one_contradiction(self):
        steady = forecaster(
            "openrouter/stand-in/steady",
            direct=binary(0.3),
            reversed_=binary(0.7),
            structured_=structured(0.3),
        )
        # Direct 0.9 lies outside the range 0.1 to 0.5 of "A and B" and far from 1 - 0.7.
        clashing = forecaster(
            "openrouter/stand-in/clashing",
            direct=binary(0.9),
            reversed_=binary(0.7),
            structured_=structured(0.3),
            second_look=binary(0.35),
        )
        research_model = searcher()
        search_model = searcher()
        bot = build([steady, clashing], researcher=research_model, search=search_model)
        result, log = self.run_method(bot, binary_question())

        values = [prediction.prediction_value for prediction in result.predictions]
        self.assertEqual(len(values), 6)
        for value, expected in zip(values, [0.3, 0.3, 0.3, 0.35, 0.3, 0.3]):
            self.assertAlmostEqual(value, expected)
        headers = [prediction.reasoning.splitlines()[0] for prediction in result.predictions]
        self.assertEqual(
            headers,
            [
                f"*Forecaster: {model.model}, framing: {framing}*"
                for model in (steady, clashing)
                for framing in config.FRAMINGS["binary"]
            ],
        )
        self.assertIn("Second look", result.predictions[3].reasoning)
        self.assertIn("probability of No 70%", result.predictions[1].reasoning)

        consistency = self.lines(log, "CONSISTENCY")
        self.assertEqual(len(consistency), 2)
        self.assertTrue(all("range=[0.10, 0.50]" in line for line in consistency))
        self.assertEqual(sum("contradicted=True" in line for line in consistency), 1)
        second_looks = self.lines(log, "SECOND_LOOK")
        self.assertEqual(len(second_looks), 1)
        self.assertIn("clashing", second_looks[0])
        self.assertIn("before=0.90 after=0.35", second_looks[0])
        self.assertEqual(self.lines(log, "FALLBACK"), [])
        self.assertEqual(result.errors, [])

        # One second look, for the clashing model only, showing it the contradiction.
        second_prompts = [p for p in clashing.prompts if p.startswith(framings.SECOND_LOOK_TITLE)]
        self.assertEqual(len(second_prompts), 1)
        self.assertIn("between 10% and 50%", second_prompts[0])
        self.assertIn("you answered 90%", second_prompts[0])
        self.assertFalse(any(p.startswith(framings.SECOND_LOOK_TITLE) for p in steady.prompts))
        self.assertEqual(len(steady.prompts), 3)
        self.assertEqual(len(clashing.prompts), 4)

        # Research: once per framing, shared by both models; fresh, so no retry.
        self.assertEqual(len(research_model.prompts), 1)
        self.assertIn("NEWEST_EVIDENCE_DATE", research_model.prompts[0])
        self.assertEqual(len(search_model.prompts), 2)
        self.assertTrue(search_model.prompts[0].startswith(framings.REVERSED_RESEARCH_TITLE))
        self.assertTrue(search_model.prompts[1].startswith(framings.STRUCTURED_RESEARCH_TITLE))
        self.assertEqual(len(self.lines(log, "FRESHNESS")), 3)
        self.assertTrue(all("retried=False" in line for line in self.lines(log, "FRESHNESS")))
        sources = self.lines(log, "SOURCES")
        self.assertEqual(len(sources), 1)
        self.assertIn("news.example.org", sources[0])
        self.assertIn("https://news.example.org/story'", sources[0])  # logged without its query
        self.assertNotIn("id=5", sources[0])
        # Every forecaster prompt carries the dates and the age of the newest evidence.
        for prompt in steady.prompts:
            self.assertIn("Dates. Today", prompt)
            self.assertIn("Age of this research", prompt)

        report = result.research_report
        self.assertTrue(report.startswith("## Consistency check"))
        self.assertIn("contradicted itself: yes; second look: yes", report)
        self.assertIn("contradicted itself: no; second look: no", report)
        for framing in config.FRAMINGS["binary"]:
            self.assertIn(f"## Research for the {framing} framing", report)

    def test_binary_fallbacks_keep_the_question(self):
        steady = forecaster(
            "openrouter/stand-in/steady",
            direct=binary(0.3),
            reversed_=binary(0.7),
            structured_="An answer with nothing to parse.",  # the parse fails
        )
        failing = forecaster(
            "openrouter/stand-in/failing",
            direct=binary(0.32),
            reversed_=TimeoutError("model timed out"),
            structured_=structured(0.3, statement="A and __import__('os')"),  # refused statement
        )
        search_model = searcher(fail_on=framings.REVERSED_RESEARCH_TITLE)
        bot = build([steady, failing], search=search_model)
        result, log = self.run_method(bot, binary_question())

        values = [prediction.prediction_value for prediction in result.predictions]
        self.assertEqual(len(values), 4)
        for value, expected in zip(values, [0.3, 0.3, 0.32, 0.3]):
            self.assertAlmostEqual(value, expected)
        fallbacks = self.lines(log, "FALLBACK")
        self.assertEqual(len(fallbacks), 3)
        self.assertTrue(any("research for the reversed framing" in line for line in fallbacks))
        self.assertTrue(any("structured answer" in line and "steady" in line for line in fallbacks))
        self.assertTrue(any("reversed answer" in line and "failing" in line for line in fallbacks))
        self.assertFalse(any("timed out" in line for line in fallbacks))  # the type, not the text
        self.assertEqual(len(result.errors), 3)
        # No range for either model, so nothing to contradict and no second look.
        self.assertTrue(all("range=none" in line for line in self.lines(log, "CONSISTENCY")))
        self.assertEqual(self.lines(log, "SECOND_LOOK"), [])
        # The reversed framing answered on the direct framing's research.
        reversed_prompt = next(p for p in steady.prompts if p.startswith(framings.REVERSED_TITLE))
        self.assertIn("Dates. Today", reversed_prompt)
        self.assertIn("No research of its own", result.research_report)

    def test_a_failed_second_look_keeps_the_first_answers(self):
        clashing = forecaster(
            "openrouter/stand-in/clashing",
            direct=binary(0.9),
            reversed_=binary(0.7),
            structured_=structured(0.3),
        )  # no second-look text: that call raises
        result, log = self.run_method(build([clashing]), binary_question())
        values = [prediction.prediction_value for prediction in result.predictions]
        for value, expected in zip(values, [0.9, 0.3, 0.3]):
            self.assertAlmostEqual(value, expected)
        self.assertEqual(len(values), 3)
        self.assertEqual(self.lines(log, "SECOND_LOOK"), [])
        self.assertEqual(len(self.lines(log, "FALLBACK")), 1)
        self.assertIn("second look: failed", result.research_report)

    def test_conditional_split_contradiction(self):
        # 0.5 * 0.9 + 0.5 * 0.5 = 0.7, against an overall answer of 0.3.
        split = {
            "event_label": "A",
            "probability_if_event_happens": 0.9,
            "probability_if_event_does_not_happen": 0.5,
        }
        model = forecaster(
            "openrouter/stand-in/split",
            direct=binary(0.3),
            reversed_=binary(0.7),
            structured_=structured(0.3, split=split),
            second_look=binary(0.31),
        )
        result, log = self.run_method(build([model]), binary_question())
        self.assertEqual(len(self.lines(log, "SECOND_LOOK")), 1)
        self.assertAlmostEqual(result.predictions[0].prediction_value, 0.31)
        second_prompt = next(p for p in model.prompts if p.startswith(framings.SECOND_LOOK_TITLE))
        self.assertIn("Together these give 70%", second_prompt)

    def test_stale_research_gets_one_retry(self):
        model = forecaster(
            "openrouter/stand-in/steady",
            direct=binary(0.3),
            reversed_=binary(0.7),
            structured_=structured(0.3),
        )
        research_model = searcher(evidence_date="2020-01-01")
        search_model = searcher()
        bot = build([model], researcher=research_model, search=search_model)
        result, log = self.run_method(bot, binary_question())
        retries = [
            p for p in search_model.prompts if p.startswith(framings.FRESHNESS_RESEARCH_TITLE)
        ]
        self.assertEqual(len(retries), 1)
        self.assertIn("since 2020-01-01", retries[0])
        direct_line = next(
            line for line in self.lines(log, "FRESHNESS") if "framing=direct" in line
        )
        self.assertIn("retried=True", direct_line)
        self.assertIn(f"newest={FRESH}", direct_line)
        self.assertIn("Later search", result.research_report)
        self.assertEqual(len(result.predictions), 3)

    def test_research_that_is_not_from_a_search_model_gets_no_retry(self):
        model = forecaster(
            "openrouter/stand-in/steady",
            direct=binary(0.3),
            reversed_=binary(0.7),
            structured_=structured(0.3),
        )
        search_model = searcher()
        bot = build([model], search=search_model)
        bot.set_llm("no_research", "researcher")
        result, log = self.run_method(bot, binary_question())
        self.assertEqual(len(search_model.prompts), 2)  # reversed and structured only
        self.assertEqual(len(result.predictions), 3)

    # --- multiple choice ---

    def test_multiple_choice_with_one_contradiction(self):
        # Converted reversed answers 0.65, 0.35, 0.10 sum to 1.10: inside the tolerances.
        steady = forecaster(
            "openrouter/stand-in/steady",
            direct=option_list([0.6, 0.3, 0.1]),
            reversed_=not_outcome([0.35, 0.65, 0.9]),
        )
        # Converted 0.3, 0.6, 0.1 against direct 0.6, 0.3, 0.1: two options clash.
        clashing = forecaster(
            "openrouter/stand-in/clashing",
            direct=option_list([0.6, 0.3, 0.1]),
            reversed_=not_outcome([0.7, 0.4, 0.9]),
            second_look=option_list([0.5, 0.4, 0.1]),
        )
        search_model = searcher()
        bot = build([steady, clashing], search=search_model)
        result, log = self.run_method(bot, choice_question())

        self.assertEqual(len(result.predictions), 4)
        answers = [prediction.prediction_value.to_dict() for prediction in result.predictions]
        for answer in answers:
            self.assertEqual(list(answer), OPTIONS)
            self.assertAlmostEqual(sum(answer.values()), 1.0)
            self.assertGreaterEqual(min(answer.values()), 0.01 - 1e-9)
        self.assertAlmostEqual(answers[0]["Red"], 0.6)
        self.assertAlmostEqual(answers[1]["Red"], 0.65 / 1.10)  # rescaled
        self.assertAlmostEqual(answers[2]["Red"], 0.5)  # the second look replaced the direct one
        self.assertAlmostEqual(answers[3]["Red"], 0.3)
        self.assertEqual(len(search_model.prompts), 1)  # reversed research only
        self.assertEqual(len(self.lines(log, "CONSISTENCY")), 2)
        self.assertEqual(len(self.lines(log, "SECOND_LOOK")), 1)
        self.assertEqual(self.lines(log, "FALLBACK"), [])
        second_prompt = next(
            p for p in clashing.prompts if p.startswith(framings.SECOND_LOOK_TITLE)
        )
        self.assertIn('For option "Red"', second_prompt)

        # The framework can combine them: the mean per option.
        from forecasting_tools.data_models.multiple_choice_report import MultipleChoiceReport

        combined = asyncio.run(
            MultipleChoiceReport.aggregate_predictions(
                [prediction.prediction_value for prediction in result.predictions],
                choice_question(),
            )
        )
        self.assertAlmostEqual(
            combined.to_dict()["Red"], (0.6 + 0.65 / 1.10 + 0.5 + 0.3) / 4, places=4
        )

    def test_multiple_choice_fallback_on_an_incomplete_reversed_answer(self):
        incomplete = reply(
            "Reasoning.", {"options": [{"option_name": "Red", "probability_not_outcome": 0.4}]}
        )
        model = forecaster(
            "openrouter/stand-in/steady", direct=option_list([0.6, 0.3, 0.1]), reversed_=incomplete
        )
        result, log = self.run_method(build([model]), choice_question())
        self.assertEqual(len(result.predictions), 1)
        self.assertEqual(len(self.lines(log, "FALLBACK")), 1)
        self.assertEqual(self.lines(log, "SECOND_LOOK"), [])

    def test_a_second_look_with_other_option_names_keeps_the_first_answers(self):
        wrong_names = reply(
            "Reasoning.",
            {
                "predicted_options": [
                    {"option_name": name, "probability": value}
                    for name, value in zip(["Rouge", "Bleu", "Vert"], [0.5, 0.4, 0.1])
                ]
            },
        )
        steady = forecaster(
            "openrouter/stand-in/steady",
            direct=option_list([0.6, 0.3, 0.1]),
            reversed_=not_outcome([0.35, 0.65, 0.9]),
        )
        clashing = forecaster(
            "openrouter/stand-in/clashing",
            direct=option_list([0.6, 0.3, 0.1]),
            reversed_=not_outcome([0.7, 0.4, 0.9]),
            second_look=wrong_names,
        )
        # The clashing model first: its second look must not become the reference names.
        result, log = self.run_method(build([clashing, steady]), choice_question())
        self.assertEqual(len(result.predictions), 4)
        for prediction in result.predictions:
            self.assertEqual(list(prediction.prediction_value.to_dict()), OPTIONS)
        self.assertAlmostEqual(result.predictions[0].prediction_value.to_dict()["Red"], 0.6)
        self.assertEqual(self.lines(log, "SECOND_LOOK"), [])
        fallbacks = self.lines(log, "FALLBACK")
        self.assertEqual(len(fallbacks), 1)
        self.assertIn("second look", fallbacks[0])
        self.assertIn("second look: failed", result.research_report)

    def test_the_questions_options_are_the_reference_names(self):
        other_names = reply(
            "Reasoning.",
            {
                "predicted_options": [
                    {"option_name": name, "probability": value}
                    for name, value in zip(["Rouge", "Bleu", "Vert"], [0.6, 0.3, 0.1])
                ]
            },
        )
        odd = forecaster(
            "openrouter/stand-in/odd", direct=other_names, reversed_=not_outcome([0.4, 0.7, 0.9])
        )
        steady = forecaster(
            "openrouter/stand-in/steady",
            direct=option_list([0.6, 0.3, 0.1]),
            reversed_=not_outcome([0.4, 0.7, 0.9]),
        )
        # The odd direct answer comes first and is the one left out; the three others combine.
        result, log = self.run_method(build([odd, steady]), choice_question())
        self.assertEqual(len(result.predictions), 3)
        for prediction in result.predictions:
            self.assertEqual(list(prediction.prediction_value.to_dict()), OPTIONS)
        fallbacks = self.lines(log, "FALLBACK")
        self.assertEqual(len(fallbacks), 1)
        self.assertIn("direct answer of openrouter/stand-in/odd", fallbacks[0])

        # When no answer names the question's options, the template's answers pass as they are.
        alone = forecaster(
            "openrouter/stand-in/odd", direct=other_names, reversed_=TimeoutError()
        )
        result, log = self.run_method(build([alone]), choice_question())
        self.assertEqual(len(result.predictions), 1)
        self.assertEqual(
            list(result.predictions[0].prediction_value.to_dict()), ["Rouge", "Bleu", "Vert"]
        )

    def test_the_researcher_gets_the_search_models_time_limit(self):
        asknews = ("ASKNEWS_CLIENT_ID", "ASKNEWS_SECRET", "ASKNEWS_API_KEY")
        clean = {k: v for k, v in os.environ.items() if k not in asknews + (config.RESEARCHER_ENV,)}
        with mock.patch.dict(os.environ, clean, clear=True):
            built = run_bot.build_researcher()
            self.assertIsInstance(built, GeneralLlm)
            self.assertEqual(built.model, config.SEARCH_MODEL)
            self.assertEqual(built.litellm_kwargs["timeout"], config.SEARCH_TIMEOUT_SECONDS)
            self.assertEqual(built.allowed_tries, config.SEARCH_TRIES)
            self.assertEqual(run_bot.choose_researcher(), config.SEARCH_MODEL)
            bot = run_bot.build_bot("full", publish=False, skip_forecasted=True)
            self.assertIsInstance(bot.get_llm("researcher"), GeneralLlm)
            self.assertEqual(
                bot.get_llm("researcher").litellm_kwargs["timeout"], config.SEARCH_TIMEOUT_SECONDS
            )
            plain_name = "openrouter/stand-in/x:online"
            with mock.patch.dict(os.environ, {config.RESEARCHER_ENV: plain_name}):
                override = run_bot.build_researcher()
                self.assertIsInstance(override, GeneralLlm)
                self.assertEqual(override.model, plain_name)
                self.assertEqual(override.litellm_kwargs["timeout"], config.SEARCH_TIMEOUT_SECONDS)
            for name in ("asknews/deep-research/low-depth", "smart-searcher/x", "no_research"):
                with mock.patch.dict(os.environ, {config.RESEARCHER_ENV: name}):
                    self.assertEqual(run_bot.build_researcher(), name)
            with mock.patch.dict(os.environ, {"ASKNEWS_API_KEY": "stand-in"}):
                self.assertEqual(run_bot.build_researcher(), config.RESEARCHER_WITH_ASKNEWS)

    # --- the framework around our method ---

    def test_whole_question_through_the_framework(self):
        steady = forecaster(
            "openrouter/stand-in/steady",
            direct=binary(0.3),
            reversed_=binary(0.7),
            structured_=structured(0.3),
        )
        clashing = forecaster(
            "openrouter/stand-in/clashing",
            direct=binary(0.9),
            reversed_=binary(0.6),
            structured_=structured(0.3),
            second_look=binary(0.35),
        )
        bot = build([steady, clashing], plain_slots=(0, 1, 0))
        report = asyncio.run(bot._run_individual_question(binary_question()))
        # The median of 0.3, 0.3, 0.3, 0.35, 0.4, 0.3.
        self.assertAlmostEqual(report.prediction, 0.3)
        self.assertIn("Consistency check", report.explanation)
        self.assertIn("framing: structured", report.explanation)
        self.assertEqual(report.errors, [])

    def test_one_surviving_answer_is_enough(self):
        lonely = forecaster(
            "openrouter/stand-in/lonely",
            direct=binary(0.4),
            reversed_=TimeoutError(),
            structured_=TimeoutError(),
        )
        silent = forecaster(
            "openrouter/stand-in/silent",
            direct=TimeoutError(),
            reversed_=TimeoutError(),
            structured_=TimeoutError(),
        )
        # Three plain forecasts are expected for other types; our method must not inherit that.
        bot = build([lonely, silent], plain_slots=(0, 1, 0))
        self.assertEqual(bot.expected_total_predictions, 3)
        report = asyncio.run(bot._run_individual_question(binary_question()))
        self.assertAlmostEqual(report.prediction, 0.4)
        self.assertEqual(len(report.errors), 5)
        self.assertEqual(bot.expected_total_predictions, 3)

    def test_no_answer_at_all_fails_the_question(self):
        silent = forecaster(
            "openrouter/stand-in/silent",
            direct=TimeoutError(),
            reversed_=TimeoutError(),
            structured_=TimeoutError(),
        )
        bot = build([silent])
        with self.assertLogs("run_bot", level="INFO"):
            with self.assertRaises(RuntimeError):
                asyncio.run(bot._research_and_make_predictions(binary_question()))
        with self.assertRaises(Exception):
            asyncio.run(bot._run_individual_question(binary_question()))

    def test_other_question_types_go_to_the_frameworks_method(self):
        first = forecaster("openrouter/stand-in/first", direct="", reversed_="")
        second = forecaster("openrouter/stand-in/second", direct="", reversed_="")
        bot = build([first, second], plain_slots=config.PLAIN_FORECAST_SLOTS)
        self.assertEqual(bot.predictions_per_research_report, 3)
        self.assertEqual(bot.research_reports_per_question, 1)
        self.assertEqual(
            [model.model for model in bot._plain_lineup], [first.model, second.model, first.model]
        )
        other = MetaculusQuestion(question_text="How many?", **question_fields())
        sentinel = object()
        with mock.patch.object(
            ForecastBot, "_research_and_make_predictions", mock.AsyncMock(return_value=sentinel)
        ) as framework_method:
            self.assertIs(asyncio.run(bot._research_and_make_predictions(other)), sentinel)
            framework_method.assert_awaited_once()
        self.assertEqual(first.prompts + second.prompts, [])

    def test_single_lineup_is_the_first_model_with_all_framings(self):
        self.assertEqual(len(run_bot.build_forecasters("single")), 1)
        self.assertEqual(
            run_bot.build_forecasters("single")[0].model, config.FORECASTERS[0]["model"]
        )
        self.assertEqual(run_bot.plain_slots("single"), (0,))
        self.assertEqual(run_bot.plain_slots("full"), config.PLAIN_FORECAST_SLOTS)
        self.assertEqual(len(run_bot.build_forecasters("full")), 2)
        self.assertEqual(run_bot.build_search_model().model, config.SEARCH_MODEL)
        model = forecaster(
            "openrouter/stand-in/only",
            direct=binary(0.3),
            reversed_=binary(0.7),
            structured_=structured(0.3),
        )
        result, _ = self.run_method(build([model]), binary_question())
        self.assertEqual(len(result.predictions), len(config.FRAMINGS["binary"]))


if __name__ == "__main__":
    unittest.main()
