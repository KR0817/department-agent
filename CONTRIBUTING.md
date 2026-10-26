# Contributing

Use fictional or explicitly synthetic examples only. Do not attach clinical records, screenshots of real patients, private literature collections, credentials or deployment databases to issues or pull requests.

Install with `uv sync --frozen`. Prepare the synthetic prescription assets with `uv run --frozen python scripts/start.py --prepare-only`, then run the unit, smoke and release checks listed in the README. Changes to source evidence, human review, versioned persistence or authentication must include checks that detect the relevant failure.

Preserve the three module boundaries. Match the existing style and avoid unrelated formatting changes. Keep generated outputs and local runs in ignored `work/` directories. Do not weaken provenance or private-output guards to make tests pass.

Document changes to the public configuration, dependency lock, synthetic data origin and third-party notices. A generated result must remain distinguishable from a clinical observation or a published source. Do not invent references or performance numbers.

By contributing, you agree that your contribution can be distributed under this repository's applicable software license. Preserve any third-party copyright and license notices and identify separately licensed components.
