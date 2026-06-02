# Jap_anki_ocr

Phase 1 scaffolding for a generic document intelligence platform.

## Profiling engine (Phase 2)

Run:

```bash
python -m app profile book.pdf
```

This command currently:

- Ingests the PDF as raw bytes
- Computes a document fingerprint (`sha256` + basic file metadata)
- Creates a profiling run directory under `runs/` with `profile.json`
- Generates page features, layout clusters, structure candidates, and ranked profiles
- Emits `profile_report.md` with the recommended profile

OCR, extraction, and validation are intentionally stubbed and not implemented yet.
