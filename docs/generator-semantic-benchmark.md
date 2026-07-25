# Generator semantic benchmark

The learned-audio path is an optional, evidence-gated addition to the existing
Librosa descriptors. Descriptor-only generation remains available while analyzer
v2 backfills the existing v1 records. Genre/style metadata is never passed to the
grouping algorithm.

## Candidate model

- Model: `Xenova/clap-htsat-unfused`, audio-only ONNX export.
- Source revision: `7fe18129b081a8cd2a0aba45e858b5b114c03a6b`.
- Asset: `onnx/audio_model.onnx`.
- Size: `117528416` bytes.
- SHA-256: `a1c2b43c44f71e0fa841a4b86700886c199bf87699ea45632c4d831bc6c88957`.
- Output: 512 dimensions.
- Runtime dependency: `onnxruntime`; preprocessing uses the existing
  `librosa`/NumPy stack and does not require PyTorch or Transformers.
- Licence: the source model card declares Apache-2.0. The asset is not bundled
  into the repository or application image.

The deployment must install the model into the durable app-data mount explicitly:

```bash
python -m app.sonic.model_assets \
  --destination /data/models/clap-htsat-unfused-audio.onnx
```

The installer downloads only when invoked, writes to a temporary sibling file,
checks the exact byte size and SHA-256, then atomically replaces the destination.
Runtime loading is local-only and checksum-verified once per worker process.

Set both variables to enable semantic extraction:

```bash
SONIC_SEMANTIC_ENABLED=true
SONIC_SEMANTIC_MODEL_PATH=/data/models/clap-htsat-unfused-audio.onnx
```

Missing assets, runtime failures, or semantic coverage below 65% produce explicit
descriptor-only evidence. They do not make compatible v1 tracks disappear.

## Representative benchmark

The aggregate benchmark is in the application package so it is runnable inside
the production image:

```bash
python -m app.sonic.benchmark --sample-limit 72
```

If v2 embeddings have not yet reached the sample coverage gate, compute them
in-memory without writing the database:

```bash
SONIC_SEMANTIC_ENABLED=true \
SONIC_SEMANTIC_MODEL_PATH=/data/models/clap-htsat-unfused-audio.onnx \
python -m app.sonic.benchmark \
  --sample-limit 72 \
  --compute-missing-semantic \
  --output /data/exports/sonic-generator-benchmark.json
```

The benchmark:

- reads the database and local media without persisting features or runs;
- selects a deterministic tempo-stratified sample of 48–96 tracks;
- emits no track identifiers, titles, or paths;
- compares descriptor-only and hybrid cohesion, separation, boundary stability,
  runtime, and memory;
- uses specific tag agreement only as an evaluation signal;
- exercises missing-model/embedding fallback;
- records cold and warm inference separately when it computes embeddings.

Hybrid selection is deliberately not based on model reputation. The emitted
`selection_gate.hybrid_selected` requires semantic evidence to be usable and
requires at least 48 sampled tracks, a scale-independent
separation-to-cohesion ratio, boundary stability, and specific-tag agreement not
to regress materially. Product judgment should also inspect playlist membership,
boundary items, and musical usefulness before enabling the hybrid weight in
production.

## Production-data result (2026-07-25)

The read-only benchmark ran against 72 deterministically sampled tracks from
1,361 production-ready tracks, evenly stratified across four tempo ranges.
All 72 CLAP embeddings completed, with a 15.018-second cold inference and a
0.943-second warm mean on the production host. Descriptor-only grouping had a
1.301 separation-to-cohesion ratio and stable boundaries.

Four hybrid weights were measured:

| Semantic weight | Acoustic weight | Separation/cohesion | Boundary stability |
| --- | --- | --- | --- |
| 15% | 85% | 0.789 | 1.0 |
| 25% | 75% | 0.800 | 1.0 |
| 35% | 65% | 0.748 | 1.0 |
| 50% | 50% | 0.692 | 1.0 |

None met the non-regression gate of 90% of the descriptor-only ratio. The
learned representation therefore ships available but disabled by default:
descriptor-only remains the production grouping path, analyzer v1 records remain
eligible, and missing-model fallback is verified. An explicit future experiment
can choose `semantic_mode=auto`; its conservative starting weight is 15%, while
the production default remains `off` until a later representative benchmark
passes.

## Local implementation smoke

The pinned ONNX asset was verified locally on Python 3.12/x86-compatible ONNX
Runtime:

- checksum verification: 0.044 seconds;
- cold session load: 0.458 seconds;
- deterministic 10-second preprocessing output: `[1, 1, 1001, 64]` float32;
- model output: `[1, 512]`;
- first full-file embedding, including decode, session load, preprocessing, and
  three windows: 1.355 seconds;
- warm full-file embedding: 0.073 seconds;
- final embedding: 512 dimensions, three windows, L2 norm `1.0`, bit-for-bit
  deterministic across the two runs.

These figures prove the inference contract, not representative generator quality.
The production-data benchmark above remains the enablement gate.
