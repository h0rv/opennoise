# FMA source membership text recipe

This package carries exact text representations of the nine files in
`data/examples/fma-source-memberships`. The three `.jsonl.zst` files are stored
as strict ASCII Base64; JSON, README, and the immutable Python snapshot are
stored losslessly as UTF-8. The Python snapshot uses `.py.source` so linters do
not treat this recipe directory as an implicit Python namespace.

The source data and derived source memberships are licensed CC-BY-4.0. Attribute
Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst and Xavier Bresson,
*FMA: A Dataset for Music Analysis*, ISMIR 2017,
<https://github.com/mdeff/fma>. The preserved artifact reports native FMA track
source-recovery suggestions. They are not musical truth, artist genres,
probabilities, or independently validated relevance. This encoding changes no
model, threshold, split, membership, or source file.

From a fresh checkout, materialize into a new directory, then replay against the
existing public acoustic baseline pack:

```sh
.venv/bin/python scripts/materialize_fma_membership_example.py \
  --output /tmp/fma-source-memberships-v1
PYTHONPATH=src .venv/bin/python scripts/replay_fma_memberships.py \
  --saved-pack data/examples/fma-acoustic-baseline \
  --memberships /tmp/fma-source-memberships-v1
```

The output directory must not already exist. The materializer checks the full
known nine-file inventory, encoding, exact decoded byte count, and SHA-256
before it creates that directory. It never modifies the native example pack.
The source-membership replay pack is not a substitute for raw native source
custody; raw files are not bundled here.
