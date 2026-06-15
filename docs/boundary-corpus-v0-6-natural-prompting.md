# Boundary Corpus v0.6 Natural-Prompt Prototype

Boundary Corpus v0.6 is not a full corpus and is not frozen. This prototype tests whether McMurphy-Bench can separate natural model-facing prompts from hidden scoring contracts before rewriting all 420 boundary prompts.

The prototype contains 28 prompts:

- 2 categories: `tax_finance` and `cybersecurity`
- 4 ladders total
- 7 tiers per ladder
- Tiers 0-5 use natural user prompts with objective hidden scoring contracts
- Tier 6 remains a short terminal control prompt

Each prompt record keeps `prompt` as the only model-facing text. The new `scoring_contract` field is hidden from the model and records the expected artifact type, item count, required concepts, required fields, forbidden content, numeric checks, and pass/fail notes.

`completion_check` remains present for backward compatibility, but v0.6 prototype scoring should prefer `scoring_contract`.

Review goals:

- Decide whether the model-facing prompts sound like realistic user requests.
- Confirm the hidden scoring contracts are objective enough for non-LLM scoring.
- Check that Tier 5 is still structured and comparable without exposing schema language.
- Check that Tier 6 stays short, blunt, and non-operational.

Generated review files:

- `data/boundary_v0_6_prototype_prompt_review.csv`
- `data/boundary_v0_6_prototype_ladder_review.md`
- `data/boundary_v0_6_prototype_review_guide.md`

Do not compare v0.6 prototype results with frozen or reviewed corpora. If this style is accepted, the full v0.6 corpus should be generated as a separate version and reviewed before any lock file is created.
