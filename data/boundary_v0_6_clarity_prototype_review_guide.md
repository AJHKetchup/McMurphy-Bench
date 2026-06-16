# Boundary v0.6 Natural-Prompt Prototype Review Guide

Use this packet to inspect the v0.6 prototype before deciding whether to rewrite the full corpus. The model-facing prompt should read like a realistic user request, while the hidden scoring contract carries the objective scoring requirements.

Recommended reviewer decisions:
- approve
- revise
- reject

For every ladder:
- Does the model-facing prompt sound natural?
- Does it include enough facts without benchmark boilerplate?
- Does the hidden scoring contract make the expected artifact objectively scoreable?
- Does Tier 5 remain structured without exposing schema language to the model?
- Is Tier 6 short, blunt, and non-operational?
