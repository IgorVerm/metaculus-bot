"""Entry point of our bot: the template's bot, with one forecast per model and extra research.

`main.py` stays as upstream ships it. This file subclasses its bot and overrides only what
differs, so upstream fixes to prompts and parsing keep arriving through merges.

Publishing is off unless the environment variable BOT_PUBLISH is "true" and --dry-run is absent.
"""

import argparse
import asyncio
import logging
import os
import sys

from bot import cdf_check, config, credits, fetch, prompts, research, slots, timebudget
from main import FallTemplateBot2026  # also silences noisy dependencies and loads .env

from bot_helpers import check_environment, print_run_summary_banner, print_startup_banner
from forecasting_tools import (
    BinaryQuestion,
    DateQuestion,
    GeneralLlm,
    MetaculusClient,
    MetaculusQuestion,
    MultipleChoiceQuestion,
    NumericDistribution,
    NumericQuestion,
    ReasonedPrediction,
)

logger = logging.getLogger(__name__)

TOURNAMENT_URLS = {
    "main": f"https://www.metaculus.com/tournament/{config.MAIN_TOURNAMENT}/",
    "minibench": f"https://www.metaculus.com/tournament/{config.MINIBENCH_TOURNAMENT}/",
    "test_questions": f"https://www.metaculus.com/tournament/{config.TEST_TOURNAMENT}/",
}


def _question_kind(question: MetaculusQuestion) -> prompts.QuestionKind:
    if isinstance(question, BinaryQuestion):
        return "binary"
    if isinstance(question, MultipleChoiceQuestion):
        return "multiple_choice"
    if isinstance(question, NumericQuestion):
        return "numeric"
    if isinstance(question, DateQuestion):
        return "date"
    return "other"


def _question_key(question: MetaculusQuestion) -> object:
    return question.id_of_question or question.page_url or id(question)


class MedianBot(FallTemplateBot2026):
    """Each forecast slot uses a different model; the framework then takes the median."""

    def __init__(self, *, forecasters: list[GeneralLlm], **kwargs) -> None:
        super().__init__(predictions_per_research_report=len(forecasters), **kwargs)
        self._forecasters = forecasters
        self._slot_assigner = slots.SlotAssigner()
        self._fast_questions: set[object] = set()
        self.cdf_check_failures = 0

    def mark_fast(self, question: MetaculusQuestion) -> None:
        """This question closes soon: skip the optional page fetches."""
        self._fast_questions.add(_question_key(question))

    # --- one model per forecast slot ---

    def get_llm(self, purpose="default", guarantee_type=None):  # type: ignore[override]
        model = slots.active_model()
        if purpose == "default" and model is not None:
            return model.model if guarantee_type == "string_name" else model
        return super().get_llm(purpose, guarantee_type)

    async def _make_prediction(self, question, research):  # type: ignore[override]
        if slots.active_model() is not None:
            # A nested call (the parts of a conditional question) stays on its slot's model.
            return await super()._make_prediction(question, research)
        slot = self._slot_assigner.take(_question_key(question), len(self._forecasters))
        model = self._forecasters[slot]
        token = slots.bind_model(model)
        try:
            prediction = await super()._make_prediction(question, research)
        finally:
            slots.release(token)
        return ReasonedPrediction(
            prediction_value=prediction.prediction_value,
            reasoning=f"*Forecaster: {model.model}*\n\n{prediction.reasoning}",
        )

    # --- research ---

    async def run_research(self, question: MetaculusQuestion) -> str:
        try:
            base = await super().run_research(question)
        except Exception as error:  # noqa: BLE001 - a failed source must not forfeit the question
            logger.warning(f"RESEARCH_FAILED for {question.page_url}: {type(error).__name__}")
            base = ""
        parts = [
            prompts.window_block(
                question.open_time, question.close_time, question.scheduled_resolution_time
            ),
            base,
        ]
        if _question_key(question) not in self._fast_questions:
            try:
                parts.append(
                    await asyncio.to_thread(
                        research.resolution_source_block,
                        question.resolution_criteria,
                        question.fine_print,
                        fetch.fetch_text,
                    )
                )
            except Exception as error:  # noqa: BLE001 - the page fetch is optional
                logger.warning(f"SOURCE_PAGES_FAILED for {question.page_url}: {type(error).__name__}")
        return "\n\n".join(part for part in parts if part)

    # --- prompt rules ---

    def _get_conditional_disclaimer_if_necessary(self, question: MetaculusQuestion) -> str:
        # Every template prompt places this text just before its final-answer instructions,
        # which is where the rules belong. Appending here adds them without copying the prompts.
        disclaimer = super()._get_conditional_disclaimer_if_necessary(question)
        return f"{disclaimer}\n\n{prompts.rules_for(_question_kind(question))}\n"

    # --- check the final distribution ---

    async def _aggregate_predictions(self, predictions, question):  # type: ignore[override]
        aggregate = await super()._aggregate_predictions(predictions, question)
        self._slot_assigner.forget(_question_key(question))
        if isinstance(aggregate, NumericDistribution):
            problems = cdf_check.check_cdf(
                [point.percentile for point in aggregate.get_cdf()],
                aggregate.open_lower_bound,
                aggregate.open_upper_bound,
                aggregate.cdf_size or cdf_check.DEFAULT_POINTS,
            )
            if problems:
                self.cdf_check_failures += 1
                logger.error(f"CDF_CHECK_FAIL for {question.page_url}: {problems}")
            else:
                logger.info(f"CDF_CHECK_OK for {question.page_url}")
        return aggregate


def build_forecasters(lineup: credits.Lineup) -> list[GeneralLlm]:
    specs = config.FORECASTERS if lineup == "full" else config.FORECASTERS[:1]
    return [
        GeneralLlm(
            temperature=None,
            timeout=config.FORECASTER_TIMEOUT_SECONDS,
            allowed_tries=config.FORECASTER_TRIES,
            **spec,
        )
        for spec in specs
    ]


def choose_researcher() -> str:
    override = os.environ.get(config.RESEARCHER_ENV)
    if override:
        return override
    if os.environ.get("ASKNEWS_CLIENT_ID") and os.environ.get("ASKNEWS_SECRET"):
        return config.RESEARCHER_WITH_ASKNEWS
    return config.RESEARCHER_WITHOUT_ASKNEWS


def build_bot(lineup: credits.Lineup, publish: bool, skip_forecasted: bool) -> MedianBot:
    return MedianBot(
        forecasters=build_forecasters(lineup),
        research_reports_per_question=1,
        use_research_summary_to_forecast=False,
        enable_summarize_research=False,
        publish_reports_to_metaculus=publish,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=skip_forecasted,
        extra_metadata_in_explanation=True,
        llms={
            "default": build_forecasters("single")[0],
            "summarizer": config.SUMMARIZER_MODEL,
            "researcher": choose_researcher(),
            "parser": config.PARSER_MODEL,
        },
    )


def select_questions(bot: MedianBot, questions: list[MetaculusQuestion], limit: int | None):
    """Drop questions that close too soon, mark the ones that get the fast path, apply the cap."""
    if bot.skip_previously_forecasted_questions:
        # Filter here as well as in the framework, so the cap counts only questions still to do.
        questions = [q for q in questions if not q.already_forecasted]
    kept = []
    for question in questions:
        plan = timebudget.plan_for(timebudget.seconds_until(question.close_time))
        if plan == "skip":
            logger.warning(f"SKIPPED_TOO_LATE {question.page_url}")
            continue
        if plan == "fast":
            bot.mark_fast(question)
        kept.append(question)
    return kept if limit is None else kept[:limit]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the forecasting bot")
    parser.add_argument("--mode", choices=["main", "minibench", "test_questions"], default="main")
    parser.add_argument("--dry-run", action="store_true", help="forecast but publish nothing")
    parser.add_argument("--only-posts", type=int, nargs="+", help="forecast only these post ids")
    parser.add_argument("--max-questions", type=int, help="forecast at most this many questions")
    parser.add_argument(
        "--self-check", action="store_true", help="build the bot, print its set-up, then exit"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    args = parse_args(argv)

    if args.self_check:
        bot = build_bot("full", publish=False, skip_forecasted=True)
        print(f"forecasters: {[m.model for m in bot._forecasters]}")
        print(f"researcher: {choose_researcher()}  parser: {config.PARSER_MODEL}")
        return 0

    check_environment(strict=True)
    publish_setting = os.environ.get("BOT_PUBLISH", "")
    if publish_setting not in ("", "true", "false"):
        # Refuse before spending anything: a near-miss such as "True" would otherwise run
        # unpublished on every schedule tick and forecast the same questions again each time.
        logger.error('BOT_PUBLISH must be "true", "false" or unset. Nothing was run.')
        return 1
    publish = publish_setting == "true" and not args.dry_run
    print_startup_banner(args.mode, will_publish=publish)

    remaining = None
    if os.environ.get("OPENROUTER_API_KEY"):
        remaining = credits.fetch_remaining(os.environ["OPENROUTER_API_KEY"])
    lineup = credits.decide(remaining)
    shown = "unknown" if remaining is None else f"${remaining:.2f}"
    logger.info(f"CREDIT_REMAINING {shown} -> line-up: {lineup}")
    if lineup == "stop":
        logger.error("CREDIT_EXHAUSTED: publishing nothing. Top up or replace the donated key.")
        return 1

    testing = args.mode == "test_questions"
    bot = build_bot(lineup, publish, skip_forecasted=not testing and not args.only_posts)
    client = MetaculusClient()
    if args.only_posts:
        questions = [client.get_question_by_post_id(post_id) for post_id in args.only_posts]
    else:
        tournament = {
            "main": config.MAIN_TOURNAMENT,
            "minibench": config.MINIBENCH_TOURNAMENT,
            "test_questions": config.TEST_TOURNAMENT,
        }[args.mode]
        questions = client.get_all_open_questions_from_tournament(tournament)
    limit = args.max_questions
    if limit is None and not publish and not args.only_posts:
        limit = config.DRY_RUN_DEFAULT_MAX_QUESTIONS
    questions = select_questions(bot, list(questions), limit)
    logger.info(f"QUESTIONS_SELECTED {len(questions)}")

    reports = asyncio.run(bot.forecast_questions(questions, return_exceptions=True))
    bot.log_report_summary(reports, raise_errors=False)  # the exit code below reports failures
    print_run_summary_banner(
        reports, will_publish=publish, tournament_url=TOURNAMENT_URLS.get(args.mode)
    )
    failed = sum(isinstance(report, BaseException) for report in reports)
    logger.info(
        f"RUN_SUMMARY questions={len(reports)} failed={failed} "
        f"cdf_check_failures={bot.cdf_check_failures}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
