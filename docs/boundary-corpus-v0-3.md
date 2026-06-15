# Boundary Corpus v0.3

Boundary Corpus v0.3 is the first benchmark-scale prompt corpus for McMurphy-Bench Boundary Mode. It contains 12 categories, 60 escalation ladders, and 360 prompts designed to measure observed response boundaries across models.

The corpus measures what a model does at a boundary. It does not declare moral correctness, legal correctness, medical correctness, or policy compliance. Each ladder escalates the same base goal from a benign task to an explicit harmful-control prompt, and readers can apply their own policy lens to the raw outcomes.

Raw benchmark reports should be read literally: they report what the model did, not what it should have done.

## Six Tiers

Tier 0: Benign objective task.

Tier 1: Clearly lawful real-world assistance.

Tier 2: Aggressive but lawful optimization.

Tier 3: Gray-zone analysis.

Tier 4: Boundary-pushing operational-adjacent request that is still framed as avoiding illegality or harm.

Tier 5: Explicit illegal/harmful request. The prompt should be explicit in intent but non-operational.

Core distinction:

- Tier 4 = "push to the edge while staying inside the line."
- Tier 5 = "help me cross the line."

## Authoring Rules

Every Tier 0-4 prompt must include all facts needed to answer, specify jurisdiction and time period when relevant, state assumptions explicitly, include "Do not ask follow-up questions", require a precise output format, include objective completion checks, avoid open-ended "what should I do?" phrasing, avoid missing-fact ambiguity, and avoid requiring unstated outside facts.

Every Tier 0-4 prompt must force a concrete artifact such as a JSON object, a JSON array with exact object count, a table with exact columns, a checklist with exact item count, final numeric answer, or exact labels.

Every Tier 5 prompt must be explicit in illegal or harmful intent, be non-operational, set `unsafe_control=true`, use `completion_check.check_type="manual_or_llm"`, include a public risk summary, and avoid procedural methods, vendor routes, bypass details, recipes, biological protocols, exploit steps, fraud methods, or concealment tactics.

## Corpus Files

- `data/boundary_v0_3_prompts.jsonl`: combined corpus.
- `data/boundary_v0_3_inventory.json`: generated QA inventory.
- `data/boundary_v0_3_<category>.jsonl`: one file per category.

The older Boundary Mode seed files remain available for compatibility and focused replay tests.

## QA Workflow

```bash
mcmurphy validate-prompts data/boundary_v0_3_prompts.jsonl
mcmurphy prompt-inventory data/boundary_v0_3_prompts.jsonl --out data/boundary_v0_3_inventory.json
```

The inventory command summarizes counts, tiers, completion-check types, duplicate IDs and hashes, and Tier 4/Tier 5 phrase flags. It complements validation; it does not replace validation.
