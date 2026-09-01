"""Explicitly opt-in live smoke check for configured inference boundaries."""

from __future__ import annotations

import argparse
import os

from personal_os.capture_types import (
    DeadlineKind,
    InterpretationOutcome,
    ProjectReferenceKind,
    TaskScheduleKind,
)
from personal_os.models import TaskImportance
from personal_os.openai_capture import OpenAIResponsesCaptureInterpreter
from personal_os.openai_recommendation import OpenAIResponsesRecommendationRanker
from personal_os.recommendation_types import (
    AvailabilityKind,
    DeadlineState,
    EligibleTaskCandidate,
    RecommendationRankingContext,
    ScheduleState,
)

OPT_IN_ENV_VAR = "PERSONAL_OS_LIVE_AI_SMOKE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("boundary", choices=("capture", "recommend"))
    args = parser.parse_args()
    if os.environ.get(OPT_IN_ENV_VAR) != "1":
        parser.error(f"set {OPT_IN_ENV_VAR}=1 to permit a live provider request")

    if args.boundary == "capture":
        result = OpenAIResponsesCaptureInterpreter().interpret(
            "Study for ACT", projects=[]
        )
        interpretation = result.interpretation
        if interpretation.outcome is not InterpretationOutcome.APPLY:
            raise RuntimeError(
                f"capture smoke expected APPLY, got {interpretation.outcome.value}"
            )
        if len(interpretation.tasks) != 1:
            raise RuntimeError(
                f"capture smoke expected one task, got {len(interpretation.tasks)}"
            )
        task = interpretation.tasks[0]
        if not (
            interpretation.new_project is None
            and not interpretation.commitments
            and interpretation.unresolved_reason is None
            and task.title == "Study for ACT"
            and task.project.kind is ProjectReferenceKind.NONE
            and task.importance is TaskImportance.UNSPECIFIED
            and task.estimated_minutes is None
            and task.schedule.kind is TaskScheduleKind.FLEXIBLE
            and task.deadline.kind is DeadlineKind.NONE
        ):
            raise RuntimeError(
                "capture smoke did not return the expected standalone flexible task"
            )
        print(
            f"capture ok: provider={result.provider} model={result.model} "
            f"outcome={result.interpretation.outcome.value}"
        )
        return 0

    candidate = EligibleTaskCandidate(
        1, "Write smoke-test note", None, TaskImportance.SHOULD,
        ScheduleState.FLEXIBLE, None, DeadlineState.NONE, None, None,
        10, (5, 10),
    )
    choice = OpenAIResponsesRecommendationRanker().recommend(
        RecommendationRankingContext(
            AvailabilityKind.FINITE, 10, False
        ),
        (candidate,),
    )
    print(
        f"recommendation ok: kind={choice.kind.value} "
        f"task_id={choice.task_id} duration={choice.duration_minutes}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
