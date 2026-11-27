"""Idempotently provision the simulation datasets and evaluators.

Reads every dataset definition under tests/simulation/datasets and mirrors it
to the configured observability platforms:

- Langfuse: creates/updates datasets and items, plus the server-side
  LLM-as-Judge setup so results appear in the Evaluations section (an LLM
  connection for the judge model, one 'simulation_llm_as_judge' evaluator,
  and one evaluation rule per dataset targeting its experiment runs).
- LangWatch: syncs all definitions into a single consolidated 'simulations'
  dataset (free-plan limit of 3 datasets per project), appending missing
  entries matched by item_id.

Safe to re-run: everything is upserted or skipped when already present, and
the evaluator (plus its rules) is recreated when the judge model config
drifts from the SIMULATION_JUDGE_* environment variables. Platforms without
credentials are skipped.

Usage:
    uv run python scripts/setup_simulation_evals.py

The simulation make targets run this script before every suite execution.

Langfuse needs LANGFUSE_BASE_URL (or LANGFUSE_HOST), LANGFUSE_PUBLIC_KEY and
LANGFUSE_SECRET_KEY; LangWatch needs LANGWATCH_ENDPOINT and LANGWATCH_API_KEY.
The judge model follows SIMULATION_JUDGE_MODEL / SIMULATION_JUDGE_API_BASE /
SIMULATION_JUDGE_API_KEY.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langfuse import Langfuse  # noqa: E402
from langfuse.api.llm_connections import LlmAdapter  # noqa: E402
from langfuse.api.evaluation_commons import (  # noqa: E402
    EvaluationRuleFilter_StringOptions,
    EvaluationRuleOptionsFilterOperator,
    EvaluatorOutputDefinition_Numeric,
    PromptVariableMappingInput,
    PromptVariableMappingSource,
)
from langfuse.api.evaluation_rules import (  # noqa: E402
    EvaluationRuleEvaluatorAssignmentInput,
)
from langfuse.api.evaluators import (  # noqa: E402
    CreateEvaluatorRequest_LlmAsJudge,
    EvaluatorModelConfig,
)

from tests.simulation.common.config import (  # noqa: E402
    JUDGE_API_BASE,
    JUDGE_API_KEY,
    JUDGE_MODEL,
)
from tests.simulation.common.datasets import (  # noqa: E402
    DATASETS_DIR,
    load_definition,
)
from tests.simulation.langfuse.runner import sync_dataset  # noqa: E402
from tests.simulation.langwatch.runner import sync_dataset_entries  # noqa: E402

EVALUATOR_NAME = "simulation_llm_as_judge"

# evaluator/rule creation preflights a live judge-model call server-side
PREFLIGHT_REQUEST_OPTIONS = {"timeout_in_seconds": 120}

EVALUATOR_PROMPT = """You are an impartial judge evaluating the response of an LLM agent.

User message:
{{input}}

Agent response:
{{output}}

Evaluation criteria:
{{expected_output}}

Rate between 0.0 and 1.0 how well the agent response satisfies all evaluation criteria.
"""


def parse_judge_model() -> tuple[str, str]:
    if "/" in JUDGE_MODEL:
        provider, model = JUDGE_MODEL.split("/", 1)
    else:
        provider, model = "openai", JUDGE_MODEL
    return provider, model


def sync_llm_connection(langfuse: Langfuse) -> bool:
    provider, model = parse_judge_model()
    secret_key = JUDGE_API_KEY or os.getenv(f"{provider.upper()}_API_KEY")
    if not secret_key:
        print(f"No API key found for judge provider '{provider}', skipping evaluators")
        return False

    adapter = LlmAdapter.ANTHROPIC if provider == "anthropic" else LlmAdapter.OPEN_AI
    kwargs = {"base_url": JUDGE_API_BASE} if JUDGE_API_BASE else {}
    langfuse.api.llm_connections.upsert(
        provider=provider,
        adapter=adapter,
        secret_key=secret_key,
        custom_models=[model],
        **kwargs,
    )
    print(f"Synced LLM connection '{provider}' (model '{model}')")
    return True


def ensure_evaluator(langfuse: Langfuse, dataset_names: list) -> str:
    provider, model = parse_judge_model()
    existing = None
    for evaluator in langfuse.api.evaluators.list(limit=100).data:
        if evaluator.name == EVALUATOR_NAME:
            existing = evaluator
            break

    if existing is not None:
        config = existing.model_config_
        if config is None:
            config = langfuse.api.evaluators.get(existing.id).model_config_
        if config is not None and config.provider == provider and config.model == model:
            print(f"Evaluator '{EVALUATOR_NAME}' already up to date")
            return existing.id
        # judge model drifted: rules reference the evaluator, recreate both
        rule_names = {f"{name}_judge" for name in dataset_names}
        for rule in langfuse.api.evaluation_rules.list().data:
            if rule.name in rule_names:
                langfuse.api.evaluation_rules.delete(rule.id)
                print(f"Deleted evaluation rule '{rule.name}' (judge model changed)")
        langfuse.api.evaluators.delete(existing.id)
        print(f"Deleted evaluator '{EVALUATOR_NAME}' (judge model changed)")

    created = langfuse.api.evaluators.create(
        request=CreateEvaluatorRequest_LlmAsJudge(
            name=EVALUATOR_NAME,
            prompt=EVALUATOR_PROMPT,
            output_definition=EvaluatorOutputDefinition_Numeric(
                min_value=0.0,
                max_value=1.0,
                score_reasoning_instructions="Explain why the score was assigned.",
                score_value_instructions="Score between 0.0 and 1.0 rating how "
                "well the response meets all criteria.",
            ),
            model_config_=EvaluatorModelConfig(provider=provider, model=model),
        ),
        request_options=PREFLIGHT_REQUEST_OPTIONS,
    )
    print(f"Created evaluator '{EVALUATOR_NAME}'")
    return created.id


def ensure_evaluation_rules(
    langfuse: Langfuse, dataset_names: list, evaluator_id: str
) -> None:
    existing = {rule.name for rule in langfuse.api.evaluation_rules.list().data}
    for dataset_name in dataset_names:
        rule_name = f"{dataset_name}_judge"
        if rule_name in existing:
            print(f"Evaluation rule '{rule_name}' already exists")
            continue
        dataset = langfuse.api.datasets.get(dataset_name)
        langfuse.api.evaluation_rules.create(
            name=rule_name,
            enabled=True,
            sampling=1.0,
            filter=[
                EvaluationRuleFilter_StringOptions(
                    column="datasetId",
                    operator=EvaluationRuleOptionsFilterOperator.ANY_OF,
                    value=[dataset.id],
                )
            ],
            evaluator_assignments=[
                EvaluationRuleEvaluatorAssignmentInput(
                    evaluator_id=evaluator_id,
                    variable_mapping=[
                        PromptVariableMappingInput(
                            variable="input",
                            source=PromptVariableMappingSource.INPUT,
                        ),
                        PromptVariableMappingInput(
                            variable="output",
                            source=PromptVariableMappingSource.OUTPUT,
                        ),
                        PromptVariableMappingInput(
                            variable="expected_output",
                            source=PromptVariableMappingSource.EXPECTED_OUTPUT,
                        ),
                    ],
                )
            ],
            request_options=PREFLIGHT_REQUEST_OPTIONS,
        )
        print(f"Created evaluation rule '{rule_name}'")


def sync_langfuse() -> None:
    langfuse = Langfuse()
    dataset_names = []
    for path in sorted(DATASETS_DIR.glob("*.json")):
        definition = load_definition(path.stem)
        sync_dataset(langfuse, definition)
        dataset_names.append(definition["name"])
        print(
            f"Synced Langfuse dataset '{definition['name']}' "
            f"({len(definition['items'])} items)"
        )

    if sync_llm_connection(langfuse):
        evaluator_id = ensure_evaluator(langfuse, dataset_names)
        ensure_evaluation_rules(langfuse, dataset_names, evaluator_id)

    langfuse.flush()


def sync_langwatch() -> None:
    for path in sorted(DATASETS_DIR.glob("*.json")):
        definition = load_definition(path.stem)
        try:
            sync_dataset_entries(definition)
            print(f"Synced LangWatch dataset '{definition['name']}'")
        except Exception as error:
            print(f"LangWatch sync failed for '{definition['name']}': {error}")


def main() -> int:
    langfuse_configured = bool(
        (os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST"))
        and os.getenv("LANGFUSE_PUBLIC_KEY")
        and os.getenv("LANGFUSE_SECRET_KEY")
    )
    langwatch_configured = bool(
        os.getenv("LANGWATCH_ENDPOINT") and os.getenv("LANGWATCH_API_KEY")
    )
    if not langfuse_configured and not langwatch_configured:
        print(
            "No platform credentials found. Set LANGFUSE_BASE_URL (or "
            "LANGFUSE_HOST) + LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY and/or "
            "LANGWATCH_ENDPOINT + LANGWATCH_API_KEY."
        )
        return 1

    if langfuse_configured:
        sync_langfuse()
    else:
        print("Langfuse credentials not set, skipping Langfuse sync")

    if langwatch_configured:
        sync_langwatch()
    else:
        print("LangWatch credentials not set, skipping LangWatch sync")

    return 0


if __name__ == "__main__":
    sys.exit(main())
