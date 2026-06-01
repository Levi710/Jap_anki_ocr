from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.__main__ import main
from app.profiling import compute_document_fingerprint, create_profiling_run


class ProfilingTests(unittest.TestCase):
    def test_compute_document_fingerprint_uses_pdf_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "book.pdf"
            pdf_bytes = b"%PDF-1.4\n%scanned\n"
            pdf_path.write_bytes(pdf_bytes)

            fingerprint = compute_document_fingerprint(pdf_path)

            self.assertEqual(fingerprint["sha256"], hashlib.sha256(pdf_bytes).hexdigest())
            self.assertEqual(fingerprint["metadata"]["filename"], "book.pdf")
            self.assertEqual(fingerprint["metadata"]["size_bytes"], len(pdf_bytes))

    def test_create_profiling_run_writes_profile_json_in_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "book.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            run_dir = create_profiling_run(pdf_path=pdf_path, runs_root=tmp_path / "runs")

            self.assertTrue(run_dir.exists())
            self.assertEqual(run_dir.parent.name, "runs")
            profile_json = run_dir / "profile.json"
            self.assertTrue(profile_json.exists())

            profile_data = json.loads(profile_json.read_text(encoding="utf-8"))
            self.assertEqual(profile_data["command"], "profile")
            self.assertEqual(profile_data["source_pdf"], str(pdf_path.resolve()))
            self.assertEqual(profile_data["stubs"]["ocr"], "not_implemented")

    def test_cli_profile_command_creates_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "book.pdf"
            runs_dir = tmp_path / "runs"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            with patch("builtins.print") as print_mock:
                exit_code = main(["profile", str(pdf_path), "--runs-dir", str(runs_dir)])

            self.assertEqual(exit_code, 0)
            self.assertTrue(runs_dir.exists())
            self.assertEqual(len(list(runs_dir.iterdir())), 1)
            print_mock.assert_called_once()
            printed_message = print_mock.call_args.args[0]
            self.assertIn("Profiling run created:", printed_message)


if __name__ == "__main__":
    unittest.main()
