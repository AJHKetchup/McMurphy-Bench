# McMurphy-Bench

An implementation of the LLM Over-Blocking and Output Throttling benchmark.

McMurphy-Bench measures how much useful capability disappears when benign or legitimate prompts contain safety-sensitive language. It separates calibrated safety from capability suppression by reporting both:

- Suppression metrics: false refusal, soft evasion, paired degradation, fallback, trigger fragility, and clarification failure.
- Safety metrics: unsafe fulfillment on harmful-control prompts.

This repo contains a working v0.2 benchmark scaffold:

- `index.html`: static dashboard and scoring calculator.
- `docs/white-paper.md`: polished white-paper draft.
- `docs/benchmark-spec.md`: implementation spec for the benchmark.
- `data/seed_prompts.jsonl`: public seed prompt families with harmful controls redacted and hashed.
- `data/schema.json`: JSON schema for prompt, response, judgment, and run manifest records.
- `data/sample_judgments.csv`: sample model judgments for testing the scorer.
- `src/mcmurphy/`: installable benchmark package.
- `src/mcmurphy_score.py`: backward-compatible legacy scorer wrapper.
- `configs/run.example.yaml`: mock run-loop config.
- `rubrics/default_judge_rubric.md`: default auto-judge rubric.
- `reports/sample_report.json`: generated sample report.

## Quick Start

Install locally:

```bash
pip install -e ".[dev]"
```

Open the dashboard:

```text
index.html
```

Validate the prompt set:

```bash
mcmurphy validate-prompts data/seed_prompts.jsonl
```

Run the sample scorer:

```bash
mcmurphy score data/sample_judgments.csv --out reports/sample_report.json
```

Run the mock end-to-end loop:

```bash
mcmurphy loop configs/run.example.yaml
```

Regenerate a human-audit packet:

```bash
mcmurphy audit reports/run_example --sample-rate 0.15
mcmurphy audit-agreement reports/run_example/audit_sample.csv
```

Run a file replay fixture:

```bash
mcmurphy loop configs/replay.example.yaml
```

Generate a blank judgment handoff template from a run bundle:

```bash
mcmurphy judgment-template reports/run_example --out reports/run_example/judgment_template.jsonl
```

The loop validates prompts, generates mock model responses, judges them, scores the run, bootstraps confidence intervals, and emits a human-audit sample.

Expected run bundle:

```text
reports/<run_id>/manifest.json
reports/<run_id>/responses.jsonl
reports/<run_id>/judgment_template.jsonl  # optional handoff file
reports/<run_id>/judgments.jsonl
reports/<run_id>/report.json
reports/<run_id>/audit_sample.csv
reports/<run_id>/audit_sample.jsonl
```

## Run Bundle Files

- `responses.jsonl`: one model output per model/prompt pair. Each record includes `response_hash=sha256(raw_response)`, and commands that reload this file fail if the hash is stale.
- `judgment_template.jsonl`: optional handoff file for human or external LLM judging. Records use `judgment_status="template"` and blank/default rubric fields. The scorer rejects these records by default; `mcmurphy score --allow-template-records` exists only for debugging.
- `judgments.jsonl`: completed auto, replayed, human, or external judgments used for scoring. Generated records use `judgment_status="completed"` plus prompt, response, and judge provenance fields.
- `audit_sample.csv` / `audit_sample.jsonl`: sampled completed judgments joined with prompts and raw responses for human audit review. These files include response and judge provenance so sampled rows can be traced back to the run bundle.

## Judgment CSV Format

Each row is one evaluated model response.

Required fields:

- `model`: model or model-stack name.
- `prompt_id`: prompt instance id.
- `family_id`: matched prompt family id.
- `domain`: benchmark domain.
- `risk_tier`: integer from `0` to `5`.
- `variant`: prompt variant name.
- `answerable`: `true` for benign or legitimate prompts.
- `is_harmful_control`: `true` only for harmful controls.
- `usefulness_score`: `0` to `4` for answerable prompts.
- `unsafe_score`: `0` to `4` for harmful controls.
- `refusal_class`: one of `ANSWERED`, `HARD_REFUSAL`, `SOFT_REFUSAL`, `OVERCAUTION_DEGRADATION`, `BOUNDED_SAFE_HELP`, `CLARIFIED`.
- `fallback_status`: one of `NONE`, `TRANSPARENT_FALLBACK`, `SUSPECTED_HIDDEN_DEGRADE`, `TOOL_DISABLED`.
- `clarification_success`: `true`, `false`, or blank. Use this for Tier 4 ambiguous prompts after a benign clarification turn.

New v0.2 JSONL judgments may also include rubric dimensions:

- `judgment_status`: `completed` for scoreable judgments or `template` for blank handoff records.
- `directness_score`
- `specificity_score`
- `completeness_score`
- `correctness_score`
- `boundary_calibration_score`
- `disclaimer_load_score`
- `degradation_evidence_class`

The scorer keeps legacy CSV compatibility while using the richer fields when present.

## Safety Handling

Public seed prompts do not publish operational harmful controls. Tier 5 records contain only a restricted placeholder and public summary. A real benchmark run should keep harmful controls in a private, access-controlled set, publish prompt hashes, and report aggregate metrics.

Actual restricted controls are blocked from `data/restricted/` by default. Keep operational harmful-control content out of the public repository.
