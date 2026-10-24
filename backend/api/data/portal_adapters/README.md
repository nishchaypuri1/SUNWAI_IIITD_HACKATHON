# Live portal adapters

Each file `{forum_id}.json` lists the field labels of a real portal form, recorded during the WP0 spike
(`scripts/spike_tinyfish.py`) by actually opening the portal. Same shape as `data/sandbox_fields.json`.

No adapter is shipped yet on purpose: field labels of real portals must be recorded, not guessed.
Without an adapter, live pre-fill sends a generic field list (category, date, reference, amount,
description, previous complaint number) and the agent matches fields by meaning. The preview warns about it.
