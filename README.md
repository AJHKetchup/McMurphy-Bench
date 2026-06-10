# McMurphy-Bench

An implementation of the LLM Over-Blocking and Output Throttling benchmark.

McMurphy-Bench measures how much useful capability disappears when benign or legitimate prompts contain safety-sensitive language. It separates calibrated safety from capability suppression by reporting both:

- Suppression metrics: false refusal, soft evasion, paired degradation, fallback, trigger fragility, and clarification failure.
- Safety metrics: unsafe fulfillment on harmful-control prompts.

This folder contains a working v0 scaffold:

- `index.html`: static dashboard and scoring calculator.
- `docs/white-paper.md`: polished white-paper draft.
- `docs/benchmark-spec.md`: implementation spec for the benchmark.
- `data/seed_prompts.jsonl`: public seed prompt families with harmful controls redacted.
- `data/schema.json`: JSON schema for prompt and judgment records.
- `data/sample_judgments.csv`: sample model judgments for testing the scorer.
- `src/mcmurphy_score.py`: dependency-free CLI scorer.
- `reports/sample_report.json`: generated sample report.

## Quick Start

Open the dashboard:

```text
index.html
```

Run the sample scorer:

```bash
python src/mcmurphy_score.py data/sample_judgments.csv --out reports/sample_report.json
```

The scorer prints a leaderboard and writes a JSON report that can be loaded into the dashboard.

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

## Safety Handling

Public seed prompts do not publish operational harmful controls. Tier 5 records contain only a restricted placeholder and public summary. A real benchmark run should keep harmful controls in a private, access-controlled set, publish prompt hashes, and report aggregate metrics.
