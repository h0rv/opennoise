# Reconstructed FMA descriptor map

The retained October 13 catalog exports had no attached descriptor map. The
October 15 restoration uses the existing `fma-fresh-descriptor-pca-v1` producer
and exporter, with a new declaration bound to the retained reconstruction.
Historical map, model, split, and feature pins remain unchanged. No baseline
model was trained again and no held-out results selected parameters.

The map retains 164 genre and 16,916 artist identities. It positions 158 genres
and 16,109 artists; the remaining identities stay in the searchable list with
missing coordinates. The covariance uses 92,270 finite original-training rows.
Genre centroids use original-training source positives. Artist positions summarize
associated finite descriptors for browsing and do not assert genre membership.
PC1 and PC2 summarize numeric descriptor variance; they do not establish musical
similarity or recover Every Noise's musical axis meanings.

The guarded build took 1.457 seconds with 146,460,672 peak RSS bytes. Exact
producer replay passed in 1.680 seconds with 156,348,416 peak RSS bytes. A separate
implementation recomputed all 44 eigenvalues, both axes, every coordinate and
abstention, and all eight component-bucket sensitivity fits. Its largest coordinate
difference was 1.07e-14, within floating-point tolerance, in 3.58 seconds and about
313 MB. Both used the unchanged 120-second and 1 GB limits.

A fresh native catalog can attach the map using `--descriptor-map`. The root
Genre families page offers a full-catalog map link only when its manifest,
shards, metadata identity, native genre scope, and bounded file inventory verify.
This opens a separate document and stops the root player; the UI says so. Inside
the full catalog, explicit map excerpt controls reuse its persistent player.
No map view or restored URL starts audio automatically.

## Reproduce from retained reconstruction inputs

The exact input aliases, digests, producer hashes and limits are recorded in
[`fma-descriptor-map-restoration-v1.json`](../../data/recipes/fma-descriptor-map-restoration-v1.json).
The aliases adapt the retained `baseline44` directory and independent audit names
to the existing producer's input layout. Use a fresh destination; do not rename,
replace or modify the retained capture or prior map declarations.

```sh
poe sync
```

Prepare the input layout with Python, setting `source` and `output` to the retained
reconstruction and a fresh destination respectively:

```python
import hashlib
import json
import shutil
from pathlib import Path

source = Path("/workspace/opennoise-rebuild-20261013")
output = Path("/workspace/fma-descriptor-restoration-replay/inputs")
recipe = json.loads(Path("data/recipes/fma-descriptor-map-restoration-v1.json").read_text())
output.mkdir(parents=True)

for relative, binding in recipe["inputs"].items():
    original = source / binding["reconstruction_path"]
    assert not any(path.is_symlink() for path in (original, *original.parents))
    body = original.read_bytes()
    assert len(body) == binding["bytes"]
    assert hashlib.sha256(body).hexdigest() == binding["sha256"]
    destination = output / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(original, destination)
```

Then invoke the existing bounded stages:

```sh
PYTHONPATH=src .venv/bin/python scripts/build_fma_fresh_map.py freeze \
  --source-root /workspace/fma-descriptor-restoration-replay/inputs \
  --declaration /workspace/fma-descriptor-restoration-replay/declaration.json
PYTHONPATH=src .venv/bin/python scripts/build_fma_fresh_map.py build \
  --source-root /workspace/fma-descriptor-restoration-replay/inputs \
  --declaration /workspace/fma-descriptor-restoration-replay/declaration.json \
  --output /workspace/fma-descriptor-restoration-replay/map
PYTHONPATH=src .venv/bin/python scripts/build_fma_fresh_map.py verify \
  --source-root /workspace/fma-descriptor-restoration-replay/inputs \
  --output /workspace/fma-descriptor-restoration-replay/map
```

Pass that map directory as `--descriptor-map` when creating a **fresh** native
catalog using `scripts/build_fma_static_catalog.py`, alongside the existing
metadata source/projection, verified audio, and optional neighbor attachments.
The static exporter enforces 200 KB per shard and a 3 MB map budget. Rebuild the
listening home and root discovery index afterward; their receipts bind the new
catalog bytes. No audio or native metadata changes are needed.

The restoration evidence is retained under
`/workspace/fma-descriptor-restore-20261015`: declaration, map, input layout,
build/replay resource evidence, independent audit script/report, and browser logs.
The actual browser contract exercises all genre identities, artist scope and
missingness, lazy shards, source-bound map navigation, selection, playback,
mobile resizing and silent reload. Numerical replay establishes computational
correctness only; no human musical judgments were collected.
