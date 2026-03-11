from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def extract_text_pdftotext(pdf_path: Path) -> tuple[str | None, str | None]:
    with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
        cmd = [
            "pdftotext",
            "-layout",
            str(pdf_path),
            tmp.name,
        ]

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return None, "pdftotext_not_installed"
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            return None, f"pdftotext_failed: {stderr}"
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

        text = Path(tmp.name).read_text(errors="ignore")

    text = text.replace("\x00", "")

    if not text.strip():
        return None, "pdftotext_empty_output"

    return text, None
