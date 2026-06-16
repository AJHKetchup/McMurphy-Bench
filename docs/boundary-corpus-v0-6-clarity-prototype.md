# Boundary Corpus v0.6 Clarity Prototype

This prototype tests a clearer model-facing prompt style before any full v0.6 rewrite. It does not freeze a corpus and should not be used for live API benchmarking.

Scope:

- 2 categories: `tax_finance` and `cybersecurity`
- 4 ladders total
- 7 tiers per ladder
- 28 prompts total

The prototype keeps the seven-tier architecture from v0.5, but rewrites the visible prompt so the user's concrete goal is obvious in plain English. Each prompt states the situation, facts, constraint, question, and a natural JSON shape the user could plausibly paste into a spreadsheet.

The model-facing `prompt` is separate from the hidden `scoring_contract`. The scoring contract records the top-level JSON key, required item count, required fields, required concepts, forbidden content, numeric checks, and notes. `completion_check` remains present only for backward compatibility.

Review focus:

- Is the user's concrete goal clear in one plain sentence?
- Are the facts sufficient to answer without guessing?
- Does the JSON shape feel user-plausible rather than like a benchmark schema?
- Does the hidden scoring contract objectively enforce the expected response?
- Does Tier 5 stay structured while asking for an unsupported goal?
- Does Tier 6 remain short, blunt, and non-operational?

Generated review files:

- `data/boundary_v0_6_clarity_prototype_prompt_review.csv`
- `data/boundary_v0_6_clarity_prototype_ladder_review.md`
- `data/boundary_v0_6_clarity_prototype_review_guide.md`

If this style is accepted, the next step is to apply it to the full corpus as a separate v0.6 draft, regenerate inventory and review packets, and review again before any lock file.
