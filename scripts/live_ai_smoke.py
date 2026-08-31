"""Explicitly opt-in live smoke check for configured inference boundaries."""

from __future__ import annotations

import argparse
import os

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
            "Buy milk", projects=[]
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
