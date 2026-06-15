# Boundary Corpus v0.4 Naturalistic

Boundary Corpus v0.4 Naturalistic is a draft successor to the frozen v0.3 corpus. It keeps the same benchmark shape while rewriting user-facing prompt text to sound less like a benchmark template and more like realistic user requests.

## Shape

- 360 prompts
- 12 categories
- 60 ladders
- 6 tiers per ladder
- 60 prompts per tier
- Same category set and ladder IDs as v0.3

## What Changed From v0.3

v0.3 was structurally correct but too benchmark-aware in user-facing text. v0.4 removes safety-line telegraphing such as "explicit illegal or harmful request", "boundary memo", "what crosses the line", and "corpus" from prompt text.

Tier 0-4 prompts still provide all needed facts, require no follow-up questions, and specify objective JSON output contracts. Tier 5 prompts are direct disallowed user requests, but are no longer meta-labeled as harmful controls and do not include operational detail.

## Current Quality Targets

The v0.4 inventory tracks naturalism checks:

- `safety_telegraph_count`
- `meta_boundary_language_count`
- `duplicate_scenario_count`
- `over_similar_ladder_count`

The draft target before human review is:

- `safety_telegraph_count = 0`
- `meta_boundary_language_count = 0`
- `likely_template_prompt_count = 0`
- `weak_tier4_count = 0`
- `missing_concrete_facts_count = 0`
- `weak_completion_check_count = 0`

## Review Workflow

Generate the review packet:

```bash
mcmurphy export-review-packet data/boundary_v0_4_prompts.jsonl --out-dir data
```

Review:

- `data/boundary_v0_4_prompt_review.csv`
- `data/boundary_v0_4_ladder_review.md`
- `data/boundary_v0_4_review_guide.md`

Do not freeze v0.4 until manual review is complete. A future freeze should create `data/boundary_v0_4_lock.json` only after reviewer decisions are resolved.
