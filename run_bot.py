"""Entry point of our bot: the template's bot, with our method on top.

`main.py` stays as upstream ships it. This file subclasses its bot and overrides only what
differs, so upstream fixes to prompts and parsing keep arriving through merges.

Yes/no and multiple-choice questions are answered by two models in several framings, each with
its own research, and checked for contradictions (`docs/design/bot.md`). Every other question
type gets the template's method with one forecast per slot.

Publishing is off unless the environment variable BOT_PUBLISH is "true" and --dry-run is absent.
"""

import argparse
import asyncio
import logging
import os
import sys
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from bot import config, credits, formal, framings, freshness, slots, timebudget
from main import FallTemplateBot2026  # also silences noisy dependencies and loads .env

from bot_helpers import check_environment, print_run_summary_banner, print_startup_banner
from forecasting_tools import (
    BinaryPrediction,
    BinaryQuestion,
    GeneralLlm,
    MetaculusClient,
    MetaculusQuestion,
    MultipleChoiceQuestion,
    PredictedOption,
    PredictedOptionList,
    ReasonedPrediction,
    structure_output,
)
from forecasting_tools.data_models.forecast_report import ResearchWithPredictions
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TOURNAMENT_URLS = {
    "main": f"https://www.metaculus.com/tournament/{config.MAIN_TOURNAMENT}/",
    "minibench": f"https://www.metaculus.com/tournament/{config.MINIBENCH_TOURNAMENT}/",
    "test_questions": f"https://www.metaculus.com/tournament/{config.TEST_TOURNAMENT}/",
}

BINARY = "binary"
MULTIPLE_CHOICE = "multiple_choice"

# True while the current task works on a question that our own method answers.
_own_method: ContextVar[bool] = ContextVar("own_method_question", default=False)


def _question_key(question: MetaculusQuestion) -> object:
    return question.id_of_question or question.page_url or id(question)


def _kind_of(question: MetaculusQuestion) -> str | None:
    """Which of our pipelines answers this question; None for the template's plain method."""
    if isinstance(question, BinaryQuestion):
        return BINARY
    if isinstance(question, MultipleChoiceQuestion):
        return MULTIPLE_CHOICE
    return None


def _day(moment: datetime | None) -> date | None:
    return moment.date() if moment else None


# --- what the parser model returns for our own framings ---


class EventEstimate(BaseModel):
    label: str
    description: str = ""
    probability: float = Field(ge=0, le=1)


class ConditionalSplit(BaseModel):
    event_label: str
    probability_if_event_happens: float = Field(ge=0, le=1)
    probability_if_event_does_not_happen: float = Field(ge=0, le=1)


class StructuredAnswer(BaseModel):
    events: list[EventEstimate]
    statement: str
    conditional_split: ConditionalSplit | None = None
    overall_probability: float = Field(ge=0, le=1)


class NotOutcome(BaseModel):
    option_name: str
    probability_not_outcome: float = Field(ge=0, le=1)


class NotOutcomeList(BaseModel):
    options: list[NotOutcome]


# --- one question's passage through our method ---


@dataclass
class _Research:
    framing: str
    text: str = ""  # what the source returned; empty when it failed
    for_models: str = ""  # what the forecasters read
    failed: bool = False


@dataclass
class _Answer:
    model: Any
    framing: str
    prediction: ReasonedPrediction  # the value that joins the other answers
    checked: Any  # what the checker compares: a probability of Yes, or {option: probability}
    shown: str  # the answer in plain words, for the second look and the summary
    structured: dict | None = None  # the checker's input from the structured framing
    second_look: bool = False


@dataclass
class _Run:
    question: Any
    kind: str
    today: date
    text: framings.QuestionText
    errors: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return str(self.question.page_url)


class MedianBot(FallTemplateBot2026):
    """Our method for yes/no and multiple choice; one model per forecast slot for the rest."""

    def __init__(
        self,
        *,
        forecasters: list[GeneralLlm],
        plain_slots: tuple[int, ...] | None = None,
        search_model: GeneralLlm | None = None,
        **kwargs,
    ) -> None:
        if plain_slots is None:
            plain_slots = tuple(range(len(forecasters)))
        super().__init__(predictions_per_research_report=len(plain_slots), **kwargs)
        self._forecasters = forecasters
        self._plain_lineup = [forecasters[index] for index in plain_slots]
        self._search_model = search_model
        self._slot_assigner = slots.SlotAssigner()

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
        slot = self._slot_assigner.take(_question_key(question), len(self._plain_lineup))
        model = self._plain_lineup[slot]
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
            return await super().run_research(question)
        except Exception as error:  # noqa: BLE001 - a failed source must not forfeit the question
            logger.warning(f"RESEARCH_FAILED for {question.page_url}: {type(error).__name__}")
            return ""

    @staticmethod
    def _get_research_prompt(question, researcher) -> str:  # type: ignore[override]
        prompt = FallTemplateBot2026._get_research_prompt(question, researcher)
        if _own_method.get() and freshness.from_search_model(GeneralLlm.to_model_name(researcher)):
            # Our method asks every search model for dated, sourced, newest-first evidence.
            today = datetime.now(timezone.utc).date()
            prompt += "\n\n" + framings.research_requirements(
                today, _day(question.close_time), config.BLOCKED_DOMAINS
            )
        return prompt

    async def _aggregate_predictions(self, predictions, question):  # type: ignore[override]
        self._slot_assigner.forget(_question_key(question))
        return await super()._aggregate_predictions(predictions, question)

    # --- our method: where it hooks into the framework ---

    async def _run_individual_question(self, question):  # type: ignore[override]
        token = _own_method.set(_kind_of(question) is not None)
        try:
            return await super()._run_individual_question(question)
        finally:
            _own_method.reset(token)

    @property
    def expected_total_predictions(self) -> int:  # type: ignore[override]
        # The framework fails a question that has fewer than half of this many answers. Our
        # method returns however many answers survived, and one is enough to publish.
        if _own_method.get():
            return 1
        return super().expected_total_predictions

    async def _research_and_make_predictions(self, question):  # type: ignore[override]
        kind = _kind_of(question)
        if kind is None:
            return await super()._research_and_make_predictions(question)
        token = _own_method.set(True)
        try:
            return await self._run_own_method(question, kind)
        finally:
            _own_method.reset(token)

    def _fallback(self, run: _Run, part: str, error: BaseException | str) -> None:
        """A part of our method failed; the question continues without it."""
        reason = error if isinstance(error, str) else type(error).__name__
        logger.warning(f"FALLBACK {run.url} part={part} reason={reason}")
        run.errors.append(f"Skipped {part}: {reason}")

    async def _run_own_method(self, question, kind: str) -> ResearchWithPredictions:
        run = _Run(
            question=question,
            kind=kind,
            today=datetime.now(timezone.utc).date(),
            text=framings.QuestionText(
                text=question.question_text,
                background=question.background_info or "",
                criteria=question.resolution_criteria or "",
                fine_print=question.fine_print or "",
                options=tuple(getattr(question, "options", None) or ()),
            ),
        )
        framing_names = config.FRAMINGS[kind]

        research = await self._research_all_framings(run, framing_names)
        answers = await self._answer_all(run, framing_names, research)
        if not answers:
            raise RuntimeError(f"No model produced an answer for {run.url}")

        direct_research = research[framings.DIRECT].for_models
        outcomes = await asyncio.gather(
            *(
                self._check_model(run, model, answers, direct_research)
                for model in self._forecasters
            ),
            return_exceptions=True,
        )
        summary_lines = []
        for model, outcome in zip(self._forecasters, outcomes):
            if isinstance(outcome, BaseException):
                self._fallback(run, f"consistency check of {model.model}", outcome)
                summary_lines.append(f"- {model.model}: the consistency check could not run.")
            else:
                summary_lines.append(outcome)

        answers = self._drop_mismatched_options(run, answers)
        predictions = [
            ReasonedPrediction(
                prediction_value=answer.prediction.prediction_value,
                reasoning=(
                    f"*Forecaster: {answer.model.model}, framing: {answer.framing}*\n\n"
                    f"{answer.prediction.reasoning}"
                ),
            )
            for answer in answers
        ]
        report = self._research_report(summary_lines, framing_names, research)
        return ResearchWithPredictions(
            research_report=report,
            summary_report=await self.summarize_research(question, report),
            errors=run.errors,
            predictions=predictions,
        )

    # --- our method: research per framing ---

    async def _research_all_framings(self, run: _Run, framing_names) -> dict[str, _Research]:
        results = await asyncio.gather(
            *(self._research_framing(run, framing) for framing in framing_names),
            return_exceptions=True,
        )
        research: dict[str, _Research] = {}
        for framing, result in zip(framing_names, results):
            if isinstance(result, BaseException):
                self._fallback(run, f"research for the {framing} framing", result)
                result = _Research(framing=framing, failed=True)
            research[framing] = result
        research.setdefault(framings.DIRECT, _Research(framing=framings.DIRECT, failed=True))

        dates = framings.dates_block(
            run.today,
            _day(run.question.open_time),
            _day(run.question.close_time),
            _day(run.question.scheduled_resolution_time),
        )
        direct = research[framings.DIRECT]
        direct.for_models = framings.for_forecaster(dates, direct.for_models, direct.text)
        for item in research.values():
            if item is direct:
                continue
            if item.failed or not item.text.strip():
                # The framing still answers, on the direct framing's research.
                item.for_models = direct.for_models
            else:
                item.for_models = framings.for_forecaster(dates, item.for_models, item.text)

        urls = freshness.extract_urls("\n".join(item.text for item in research.values()))
        found_domains = freshness.domains(urls)
        shown = [freshness.without_query(url) for url in urls[: config.MAX_LOGGED_SOURCES]]
        logger.info(
            f"SOURCES {run.url} count={len(urls)} domains={found_domains} "
            f"blocked={freshness.blocked_among(found_domains, config.BLOCKED_DOMAINS)} "
            f"addresses={shown}"
        )
        return research

    async def _research_framing(self, run: _Run, framing: str) -> _Research:
        """One framing's research. `for_models` carries the age note until the caller builds it."""
        requirements = framings.research_requirements(
            run.today, _day(run.question.close_time), config.BLOCKED_DOMAINS
        )
        retried = False
        if framing == framings.DIRECT:
            # The template's research; its semaphore is taken and released inside this call.
            text = await FallTemplateBot2026.run_research(self, run.question)
            try:
                researcher = GeneralLlm.to_model_name(self.get_llm("researcher"))
            except Exception:  # noqa: BLE001 - no researcher configured
                researcher = ""
            from_search = freshness.from_search_model(researcher) and bool((text or "").strip())
        else:
            if self._search_model is None:
                raise RuntimeError("no search model configured")
            if framing == framings.REVERSED:
                request = framings.reversed_research_request(run.text, requirements)
            else:
                request = framings.structured_research_request(run.text, requirements)
            text = await self._search_model.invoke(request)
            from_search = True
        text = text or ""

        newest = freshness.newest_evidence_date(text)
        age = freshness.age_in_days(newest, run.today)
        if framing == framings.DIRECT and self._search_model is not None:
            if freshness.needs_retry(
                age, config.FRESHNESS_MAX_AGE_DAYS, from_search=from_search, already_retried=False
            ):
                retried = True
                since = freshness.retry_since(newest, run.today, config.FRESHNESS_MAX_AGE_DAYS)
                try:
                    later = await self._search_model.invoke(
                        framings.freshness_research_request(run.text, since, requirements)
                    )
                    text = framings.join_research(text, later or "")
                    later_newest = freshness.newest_evidence_date(later)
                    if freshness.age_in_days(later_newest, run.today) is not None:
                        dated = newest if age is not None else None
                        newest = freshness.newest_of(dated, later_newest)
                        age = freshness.age_in_days(newest, run.today)
                except Exception as error:  # noqa: BLE001 - the first research still stands
                    self._fallback(run, "freshness retry", error)
        if age is None:
            newest = None
        logger.info(
            f"FRESHNESS {run.url} framing={framing} search_model={from_search} "
            f"newest={newest.isoformat() if newest else 'unknown'} "
            f"age_days={age if age is not None else 'unknown'} retried={retried}"
        )
        note = framings.age_note(newest, age) if from_search else ""
        return _Research(framing=framing, text=text, for_models=note)

    def _research_report(self, summary_lines, framing_names, research) -> str:
        """The research text of the published comment: the check's summary, then each framing."""
        parts = [
            "## Consistency check\n"
            "Each model answers in several framings; a model whose answers contradict each "
            "other under the rules of probability answers once more.\n" + "\n".join(summary_lines)
        ]
        for framing in framing_names:
            item = research[framing]
            if item.failed or not item.text.strip():
                body = "No research of its own; the forecasters used the direct framing's research."
                if framing == framings.DIRECT:
                    body = "No research was available."
            else:
                body = framings.for_comment(item.text, config.RESEARCH_CHARS_IN_COMMENT)
            parts.append(f"## Research for the {framing} framing\n{body}")
        return "\n\n".join(parts)

    # --- our method: the answers ---

    async def _answer_all(self, run: _Run, framing_names, research) -> list[_Answer]:
        jobs = [(model, framing) for model in self._forecasters for framing in framing_names]
        results = await asyncio.gather(
            *(
                self._answer(run, model, framing, research[framing].for_models)
                for model, framing in jobs
            ),
            return_exceptions=True,
        )
        answers = []
        for (model, framing), result in zip(jobs, results):
            if isinstance(result, BaseException):
                self._fallback(run, f"{framing} answer of {model.model}", result)
            else:
                answers.append(result)
        return answers

    async def _answer(self, run: _Run, model, framing: str, research: str) -> _Answer:
        # Runs as its own task, so the binding is seen by this answer alone.
        token = slots.bind_model(model)
        try:
            if run.kind == BINARY:
                if framing == framings.DIRECT:
                    return await self._binary_direct(run, model, research)
                if framing == framings.REVERSED:
                    return await self._binary_reversed(run, model, research)
                return await self._binary_structured(run, model, research)
            if framing == framings.DIRECT:
                return await self._options_direct(run, model, research)
            return await self._options_reversed(run, model, research)
        finally:
            slots.release(token)

    @staticmethod
    def _clamp(probability: float) -> float:
        return framings.clamp(probability, config.MIN_PROBABILITY, config.MAX_PROBABILITY)

    async def _binary_direct(self, run: _Run, model, research: str) -> _Answer:
        prediction = await self._run_forecast_on_binary(run.question, research)
        value = self._clamp(prediction.prediction_value)
        return _Answer(
            model=model,
            framing=framings.DIRECT,
            prediction=ReasonedPrediction(prediction_value=value, reasoning=prediction.reasoning),
            checked=value,
            shown=(
                "Asked directly for the probability of Yes, you answered "
                f"{framings.percent(value)}."
            ),
        )

    async def _binary_reversed(self, run: _Run, model, research: str) -> _Answer:
        reasoning = await model.invoke(
            framings.reversed_binary_prompt(run.text, research, run.today)
        )
        parsed: BinaryPrediction = await structure_output(
            reasoning,
            BinaryPrediction,
            model=self.get_llm("parser", "llm"),
            num_validation_samples=self._structure_output_validation_samples,
            additional_instructions=(
                framings.REVERSED_PARSING + "\n" + self._create_resolved_question_parsing_message()
            ),
        )
        stated_no = parsed.prediction_in_decimal
        value = self._clamp(framings.complement(stated_no))
        conversion = (
            f"Converted by our code: probability of No {framings.percent(stated_no)}, "
            f"so probability of Yes {framings.percent(value)}."
        )
        return _Answer(
            model=model,
            framing=framings.REVERSED,
            prediction=ReasonedPrediction(
                prediction_value=value, reasoning=f"{reasoning}\n\n{conversion}"
            ),
            checked=value,
            shown=(
                f"Asked for the probability of No, you answered {framings.percent(stated_no)}, "
                f"which means {framings.percent(value)} for Yes."
            ),
        )

    async def _binary_structured(self, run: _Run, model, research: str) -> _Answer:
        reasoning = await model.invoke(
            framings.structured_binary_prompt(run.text, research, run.today, config.MAX_EVENTS)
        )
        # One sample: the event descriptions are free text, so two parses rarely match exactly.
        parsed: StructuredAnswer = await structure_output(
            reasoning,
            StructuredAnswer,
            model=self.get_llm("parser", "llm"),
            num_validation_samples=1,
            additional_instructions=(
                framings.STRUCTURED_PARSING
                + "\n"
                + self._create_resolved_question_parsing_message()
            ),
        )
        value = self._clamp(parsed.overall_probability)
        split = parsed.conditional_split
        structured = {
            "events": [(event.label, event.probability) for event in parsed.events],
            "statement": parsed.statement,
            "overall": value,
            "split": None
            if split is None
            else {
                "event": split.event_label,
                "if_yes": split.probability_if_event_happens,
                "if_no": split.probability_if_event_does_not_happen,
            },
        }
        events_shown = "; ".join(
            f"{event.label} ({event.description[:200]}): {framings.percent(event.probability)}"
            for event in parsed.events
        )
        shown = (
            f"In the structured framing you named the events {events_shown}. You wrote the "
            f"resolution criteria as the statement \"{parsed.statement[:300]}\". "
        )
        if split is not None:
            shown += (
                f"You answered {framings.percent(split.probability_if_event_happens)} if event "
                f"{split.event_label} happens and "
                f"{framings.percent(split.probability_if_event_does_not_happen)} if it does not. "
            )
        shown += f"Your overall answer there was {framings.percent(value)}."
        return _Answer(
            model=model,
            framing=framings.STRUCTURED,
            prediction=ReasonedPrediction(prediction_value=value, reasoning=reasoning),
            checked=value,
            shown=shown,
            structured=structured,
        )

    async def _options_direct(self, run: _Run, model, research: str) -> _Answer:
        prediction = await self._run_forecast_on_multiple_choice(run.question, research)
        asked = "Asked directly for each option's probability"
        return self._options_answer(run, model, prediction, asked)

    def _options_answer(self, run: _Run, model, prediction, asked: str) -> _Answer:
        given = {
            option.option_name: option.probability
            for option in prediction.prediction_value.predicted_options
        }
        try:
            given = framings.match_options(given, list(run.text.options))
        except ValueError:
            pass  # kept as the template returned it; the check compares what it can
        return _Answer(
            model=model,
            framing=framings.DIRECT,
            prediction=prediction,
            checked=given,
            shown=f"{asked}, you answered: {framings.options_line(given)}.",
        )

    async def _options_reversed(self, run: _Run, model, research: str) -> _Answer:
        reasoning = await model.invoke(
            framings.reversed_options_prompt(run.text, research, run.today)
        )
        parsed: NotOutcomeList = await structure_output(
            reasoning,
            NotOutcomeList,
            model=self.get_llm("parser", "llm"),
            num_validation_samples=self._structure_output_validation_samples,
            additional_instructions=(
                framings.reversed_options_parsing(run.text.options)
                + "\n"
                + self._create_resolved_question_parsing_message()
            ),
        )
        if len({item.option_name for item in parsed.options}) != len(parsed.options):
            raise ValueError("an option was answered twice")
        stated = {item.option_name: item.probability_not_outcome for item in parsed.options}
        converted = framings.convert_reversed_options(stated, list(run.text.options))
        published = framings.floor_and_renormalise(converted, config.MIN_OPTION_PROBABILITY)
        option_list = PredictedOptionList(
            predicted_options=[
                PredictedOption(option_name=option, probability=min(1.0, max(0.0, value)))
                for option, value in published.items()
            ]
        )
        conversion = (
            "Converted by our code with 1 - q per option: "
            f"{framings.options_line(converted)} "
            f"(sum {framings.percent(sum(converted.values()))}). "
            f"Rescaled to sum to 100%: {framings.options_line(published)}."
        )
        return _Answer(
            model=model,
            framing=framings.REVERSED,
            prediction=ReasonedPrediction(
                prediction_value=option_list, reasoning=f"{reasoning}\n\n{conversion}"
            ),
            checked=converted,
            shown=(
                "Asked for the probability that each option is not the outcome, your answers "
                f"mean these probabilities: {framings.options_line(converted)}."
            ),
        )

    def _drop_mismatched_options(self, run: _Run, answers: list[_Answer]) -> list[_Answer]:
        """The framework combines multiple-choice answers only when all name the same options."""
        if run.kind != MULTIPLE_CHOICE:
            return answers

        def names(answer: _Answer) -> frozenset:
            options = answer.prediction.prediction_value.predicted_options
            return frozenset(option.option_name for option in options)

        directs = [answer for answer in answers if answer.framing == framings.DIRECT]
        reference = names(directs[0]) if directs else frozenset(run.text.options)
        kept = []
        for answer in answers:
            ours = answer.framing != framings.DIRECT or answer.second_look
            if ours and names(answer) != reference:
                self._fallback(
                    run, f"{answer.framing} answer of {answer.model.model}", "option names differ"
                )
                continue
            kept.append(answer)
        return kept

    # --- our method: the check and the second look ---

    async def _check_model(self, run: _Run, model, answers: list[_Answer], research: str) -> str:
        """Check one model's answers; on a contradiction, replace its direct answer in `answers`.

        Returns the model's line for the comment.
        """
        own = {answer.framing: answer for answer in answers if answer.model is model}
        if not own:
            return f"- {model.model}: no answer."
        direct = own.get(framings.DIRECT)
        reversed_answer = own.get(framings.REVERSED)
        structured = own.get(framings.STRUCTURED)

        if run.kind == BINARY:
            result = formal.check_binary(
                direct.checked if direct else None,
                reversed_answer.checked if reversed_answer else None,
                structured.structured if structured else None,
                range_tolerance=config.RANGE_TOLERANCE,
                pair_tolerance=config.PAIR_TOLERANCE,
                max_events=config.MAX_EVENTS,
            )
            values = " ".join(
                f"{name}={answer.checked:.2f}" if answer else f"{name}=none"
                for name, answer in (
                    ("direct", direct),
                    ("reversed", reversed_answer),
                    ("structured", structured),
                )
            )
            shown_range = (
                "none"
                if result.value_range is None
                else f"[{result.value_range[0]:.2f}, {result.value_range[1]:.2f}]"
            )
            logged = f"range={shown_range} {values}"
            line = f"- {model.model}: range {shown_range}; {values}"
        else:
            result = formal.check_multiple_choice(
                direct.checked if direct else None,
                reversed_answer.checked if reversed_answer else None,
                pair_tolerance=config.PAIR_TOLERANCE,
                sum_tolerance=config.SUM_TOLERANCE,
            )
            total = (
                f"{sum(reversed_answer.checked.values()):.2f}" if reversed_answer else "none"
            )
            logged = f"reversed_sum={total} direct={'yes' if direct else 'none'}"
            line = f"- {model.model}: sum of the converted reversed answers {total}"
        logger.info(
            f"CONSISTENCY {run.url} model={model.model} {logged} "
            f"contradicted={result.contradicted} findings={len(result.findings)} "
            f"checks_skipped={len(result.skipped)}"
        )
        line += f"; contradicted itself: {'yes' if result.contradicted else 'no'}"
        if not result.contradicted:
            return line + "; second look: no."

        try:
            second = await self._second_look(run, model, own, result.findings, research)
        except Exception as error:  # noqa: BLE001 - the first answers stand
            self._fallback(run, f"second look of {model.model}", error)
            return line + "; second look: failed, the first answers stand."
        before = "none" if direct is None else self._brief(direct)
        logger.info(
            f"SECOND_LOOK {run.url} model={model.model} before={before} after={self._brief(second)}"
        )
        # No await between here and the write, so the other model's check cannot interleave.
        position = next((i for i, answer in enumerate(answers) if answer is direct), None)
        if position is None:
            answers.append(second)
        else:
            answers[position] = second
        return line + f"; second look: yes, its direct answer became {self._brief(second)}."

    @staticmethod
    def _brief(answer: _Answer) -> str:
        if isinstance(answer.checked, dict):
            return "{" + ", ".join(f"{value:.2f}" for value in answer.checked.values()) + "}"
        return f"{answer.checked:.2f}"

    async def _second_look(self, run: _Run, model, own: dict, findings: list[str], research: str):
        said = "\n".join(
            f"- {own[framing].shown}" for framing in config.FRAMINGS[run.kind] if framing in own
        )
        contradictions = formal.describe(findings)
        note = (
            "*Second look: this model's first answers contradicted each other, so it was shown "
            "the contradiction and answered once more. This answer replaces its first direct "
            "answer.*"
        )
        token = slots.bind_model(model)
        try:
            if run.kind == BINARY:
                prompt = framings.second_look_binary_prompt(
                    run.text, research, run.today, said, contradictions
                )
                prediction = await self._binary_prompt_to_forecast(run.question, prompt)
                value = self._clamp(prediction.prediction_value)
                return _Answer(
                    model=model,
                    framing=framings.DIRECT,
                    prediction=ReasonedPrediction(
                        prediction_value=value, reasoning=f"{note}\n\n{prediction.reasoning}"
                    ),
                    checked=value,
                    shown=f"At the second look you answered {framings.percent(value)}.",
                    second_look=True,
                )
            prompt = framings.second_look_options_prompt(
                run.text, research, run.today, said, contradictions
            )
            prediction = await self._multiple_choice_prompt_to_forecast(run.question, prompt)
        finally:
            slots.release(token)
        answer = self._options_answer(
            run,
            model,
            ReasonedPrediction(
                prediction_value=prediction.prediction_value,
                reasoning=f"{note}\n\n{prediction.reasoning}",
            ),
            "At the second look",
        )
        answer.second_look = True
        return answer


def build_forecasters(lineup: credits.Lineup) -> list[GeneralLlm]:
    """The models of the line-up. "single" (credit is low) is the first model alone."""
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


def plain_slots(lineup: credits.Lineup) -> tuple[int, ...]:
    """Which model answers each plain forecast of the question types outside our method."""
    return config.PLAIN_FORECAST_SLOTS if lineup == "full" else (0,)


def build_search_model() -> GeneralLlm:
    return GeneralLlm(
        model=config.SEARCH_MODEL,
        temperature=None,
        timeout=config.SEARCH_TIMEOUT_SECONDS,
        allowed_tries=config.SEARCH_TRIES,
    )


def choose_researcher() -> str:
    override = os.environ.get(config.RESEARCHER_ENV)
    if override:
        return override
    has_pair = os.environ.get("ASKNEWS_CLIENT_ID") and os.environ.get("ASKNEWS_SECRET")
    if has_pair or os.environ.get("ASKNEWS_API_KEY"):
        return config.RESEARCHER_WITH_ASKNEWS
    return config.RESEARCHER_WITHOUT_ASKNEWS


def build_bot(lineup: credits.Lineup, publish: bool, skip_forecasted: bool) -> MedianBot:
    return MedianBot(
        forecasters=build_forecasters(lineup),
        plain_slots=plain_slots(lineup),
        search_model=build_search_model(),
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
    """Drop questions that close too soon to forecast, then apply the cap."""
    if bot.skip_previously_forecasted_questions:
        # Filter here as well as in the framework, so the cap counts only questions still to do.
        questions = [q for q in questions if not q.already_forecasted]
    kept = []
    for question in questions:
        if timebudget.too_late(timebudget.seconds_until(question.close_time)):
            logger.warning(f"SKIPPED_TOO_LATE {question.page_url}")
            continue
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
        print(f"plain forecasts: {[m.model for m in bot._plain_lineup]}")
        print(f"researcher: {choose_researcher()}  parser: {config.PARSER_MODEL}")
        print(f"search model: {config.SEARCH_MODEL}")
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
    logger.info(f"RUN_SUMMARY questions={len(reports)} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
