from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

PHASE_VERSION = "1.5"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_document_fingerprint(pdf_path: Path) -> dict:
    pdf_bytes = pdf_path.read_bytes()
    if b"%PDF-" not in pdf_bytes[:1024]:
        raise ValueError(f"Input is not a PDF file: {pdf_path}")

    stat = pdf_path.stat()
    return {
        "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "metadata": {
            "filename": pdf_path.name,
            "size_bytes": stat.st_size,
            "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        },
    }


def create_profiling_run(pdf_path: Path, runs_root: Path = Path("runs")) -> Path:
    fingerprint = compute_document_fingerprint(pdf_path)
    created_at = _utc_now()
    run_id = f"{created_at.strftime('%Y%m%dT%H%M%SZ')}_{pdf_path.stem}_{fingerprint['sha256'][:8]}"
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    profile_data = {
        "phase": PHASE_VERSION,
        "command": "profile",
        "created_at_utc": created_at.isoformat(),
        "source_pdf": str(pdf_path.resolve()),
        "fingerprint": fingerprint,
        "stubs": {
            "ocr": "not_implemented",
            "extraction": "not_implemented",
            "validation": "not_implemented",
        },
    }

    (run_dir / "profile.json").write_text(
        json.dumps(profile_data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return run_dir
