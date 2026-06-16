# Boundary Corpus v0.6 Clarity Prototype

This prototype tests a clearer model-facing prompt style before any full v0.6 rewrite. It does not freeze a corpus and should not be used for live API benchmarking.

Scope:

- 2 categories: `tax_finance` and `cybersecurity`
- 4 ladders total
- 8 tiers per ladder, numbered 0 through 7
- 32 prompts total

The prototype extends the v0.5 seven-tier architecture with a Tier 7 terminal-pressure row. Tiers 0 through 7 preserve the same scenario, facts, requested artifact, output shape, row count, and column names within each ladder; only the risk pressure changes.

The model-facing `prompt` is separate from the hidden `scoring_contract`. The scoring contract records the top-level JSON key, required item count, required fields, required concepts, forbidden content, numeric checks, and notes. `completion_check` remains present only for backward compatibility.

Review focus:

- Is the user's concrete goal clear in one plain sentence?
- Are the facts sufficient to answer without guessing?
- Does the JSON shape feel user-plausible rather than like a benchmark schema?
- Does the hidden scoring contract objectively enforce the expected response?
- Does Tier 5 stay structured as a bounded completion task?
- Does Tier 6 preserve the same worksheet while refusing the unsafe part and giving a safe substitute?
- Does Tier 7 preserve Tier 6 structure while applying terminal unsafe pressure?
- Are provider blocks, empty safety responses, and structured refusals distinguishable from unsafe fulfillment?

Generated review files:

- `data/boundary_v0_6_clarity_prototype_prompt_review.csv`
- `data/boundary_v0_6_clarity_prototype_ladder_review.md`
- `data/boundary_v0_6_clarity_prototype_review_guide.md`

If this style is accepted, the next step is to apply it to the full corpus as a separate v0.6 draft, regenerate inventory and review packets, and review again before any lock file.
