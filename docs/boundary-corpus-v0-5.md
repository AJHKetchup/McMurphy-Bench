# Boundary Corpus v0.5

Boundary Corpus v0.5 is a draft seven-tier naturalistic corpus for manual review before any lock file or live benchmarking run.

v0.5 keeps the v0.4 categories and ladder IDs, but changes the ladder shape from six tiers to seven:

- Tier 0: benign objective task
- Tier 1: ordinary lawful real-world help
- Tier 2: aggressive but defensible help
- Tier 3: gray-zone analysis
- Tier 4: edge-seeking but still plausibly defensible
- Tier 5: structured unsupported or disallowed request
- Tier 6: terminal harmful-control prompt

The main purpose of v0.5 is to separate two jobs that v0.4 combined in Tier 5. Tier 5 is now structurally comparable with Tiers 0-4: it includes the scenario facts, forbids follow-up questions, and requires an objective JSON artifact. Tier 6 is the short terminal control prompt and is reported separately.

Boundary scoring should read v0.5 reports with two measures:

- `structured_boundary_depth` uses Tiers 0-5 only.
- `terminal_control_outcome` uses Tier 6 only.

The legacy `boundary_depth` field remains as an alias for `structured_boundary_depth` for compatibility.

v0.5 is not frozen. Do not compare pilot results across different corpus hashes, and do not create a v0.5 lock file until the prompt review packet has been inspected and accepted. If prompt text changes after review, regenerate the inventory and review packet before any future freeze.

Review files:

- `data/boundary_v0_5_prompt_review.csv`
- `data/boundary_v0_5_ladder_review.md`
- `data/boundary_v0_5_review_guide.md`
- `data/boundary_v0_5_review_status.json`
