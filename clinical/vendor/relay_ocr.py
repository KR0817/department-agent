"""Local-only OCR client for synthetic laboratory-report images."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class LocalOcrUnavailable(RuntimeError):
    """Raised when the local Tesseract executable or language data is unavailable."""


class LocalOcrFailed(RuntimeError):
    """Raised when local Tesseract cannot process an image."""


MAX_OCR_OUTPUT_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class OcrExtraction:
    text: str
    engine_version: str


@dataclass(frozen=True)
class OcrTsvExtraction:
    tsv: str
    engine_version: str


class LocalTesseractOcr:
    """Runs Tesseract locally; it never sends an image or OCR text to a remote service."""

    def __init__(
        self,
        executable: Path | None = None,
        language: str = "eng",
        tessdata_dir: Path | None = None,
    ) -> None:
        self.executable = executable or self._default_executable()
        self.language = language
        self.tessdata_dir = tessdata_dir

    @classmethod
    def from_environment(cls) -> "LocalTesseractOcr":
        configured_path = os.getenv("TESSERACT_EXECUTABLE")
        executable = Path(configured_path) if configured_path else None
        configured_tessdata = os.getenv("TESSERACT_TESSDATA_DIR")
        project_tessdata = Path(__file__).resolve().parent.parent / "vendor" / "tessdata_fast"
        if configured_tessdata:
            tessdata_dir = Path(configured_tessdata)
        elif all((project_tessdata / f"{language}.traineddata").is_file() for language in ("chi_sim", "eng")):
            tessdata_dir = project_tessdata
        else:
            tessdata_dir = None
        default_language = "chi_sim+eng" if tessdata_dir == project_tessdata else "eng"
        return cls(
            executable=executable,
            language=os.getenv("TESSERACT_LANGUAGE", default_language),
            tessdata_dir=tessdata_dir,
        )

    @staticmethod
    def _default_executable() -> Path:
        discovered = shutil.which("tesseract")
        if discovered:
            return Path(discovered)
        program_files = os.getenv("ProgramFiles")
        if program_files:
            return Path(program_files) / "Tesseract-OCR" / "tesseract.exe"
        return Path("tesseract")

    def _extract_output(
        self,
        image_path: Path,
        output_format: str | None = None,
        psm: int = 6,
    ) -> tuple[str, str]:
        if not self.executable.is_file():
            raise LocalOcrUnavailable("local_tesseract_not_available")
        if self.tessdata_dir is not None and not self.tessdata_dir.is_dir():
            raise LocalOcrUnavailable("local_tessdata_not_available")
        if not image_path.is_file():
            raise LocalOcrFailed("synthetic_upload_not_found")
        extraction_command = [str(self.executable), str(image_path), "stdout"]
        if self.tessdata_dir is not None:
            extraction_command.extend(["--tessdata-dir", str(self.tessdata_dir)])
        extraction_command.extend(["--psm", str(psm), "-l", self.language])
        if output_format == "tsv":
            extraction_command.extend(["-c", "tessedit_create_tsv=1"])
        try:
            version_process = subprocess.run(
                [str(self.executable), "--version"],
                capture_output=True,
                check=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            with tempfile.TemporaryFile() as output_file:
                subprocess.run(
                    extraction_command,
                    stdout=output_file,
                    stderr=subprocess.DEVNULL,
                    check=True,
                    timeout=45,
                )
                output_file.seek(0, os.SEEK_END)
                if output_file.tell() > MAX_OCR_OUTPUT_BYTES:
                    raise LocalOcrFailed("local_ocr_output_too_large")
                output_file.seek(0)
                extraction_output = output_file.read().decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired as error:
            raise LocalOcrFailed("local_ocr_timeout") from error
        except subprocess.CalledProcessError as error:
            raise LocalOcrFailed("local_ocr_failed") from error
        engine_version = version_process.stdout.splitlines()[0].strip() if version_process.stdout else "tesseract"
        return extraction_output, f"{engine_version};lang={self.language}"

    def extract(self, image_path: Path) -> OcrExtraction:
        text, engine_version = self._extract_output(image_path)
        return OcrExtraction(
            text=text,
            engine_version=engine_version,
        )

    def extract_tsv(self, image_path: Path, psm: int = 6) -> OcrTsvExtraction:
        tsv, engine_version = self._extract_output(image_path, "tsv", psm=psm)
        return OcrTsvExtraction(
            tsv=tsv,
            engine_version=engine_version,
        )
