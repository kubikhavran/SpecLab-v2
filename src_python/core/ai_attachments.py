"""Reference attachments for the AI assistant: images, SpecLab projects/presets, spectra."""

from __future__ import annotations

import io
import json
from pathlib import Path

from core.ai_tools import Attachment, Toolbox

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
MAX_IMAGE_SIDE = 1600
MAX_ATTACHMENT_BYTES = 60 * 1024 * 1024


def normalise_image(data: bytes) -> bytes:
    """Any common raster image → RGB PNG with its longest side ≤ 1600 px."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.mode in ("RGBA", "LA", "P"):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.split()[-1])
                image = background
            else:
                image = image.convert("RGB")
            if max(image.size) > MAX_IMAGE_SIDE:
                scale = MAX_IMAGE_SIDE / max(image.size)
                image = image.resize((round(image.width * scale), round(image.height * scale)),
                                     Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Obrázek nelze přečíst.") from exc


def image_attachment(data: bytes, name: str, attachment_id: str) -> Attachment:
    return Attachment(attachment_id, "image", name, image=normalise_image(data))


def _render(state) -> bytes | None:
    try:
        png, _report = Toolbox(state, {}).figure_report()
        return png
    except Exception:  # noqa: BLE001 - a reference that cannot be drawn is still usable as data
        return None


def load_attachment(path, attachment_id: str) -> list[Attachment]:
    """Load one file; PDFs may yield one image per page (first 4 pages)."""
    from app.state import AppState

    target = Path(path)
    if target.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"{target.name}: příloha překračuje 60 MB.")
    suffix = target.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return [image_attachment(target.read_bytes(), target.name, attachment_id)]
    if suffix == ".pdf":
        pages = pdf_pages(target)
        return [Attachment(f"{attachment_id}" if i == 0 else f"{attachment_id}.{i + 1}", "image",
                           f"{target.name} (strana {i + 1})", image=normalise_image(page))
                for i, page in enumerate(pages[:4])]
    if suffix == ".json":
        try:
            document = json.loads(target.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"{target.name}: neplatný JSON.") from exc
        if isinstance(document, dict) and document.get("schema") == "speclab.project":
            from core.project_io import load_project

            state = AppState()
            try:
                load_project(state, target)
            except (KeyError, TypeError) as exc:
                raise ValueError(f"{target.name}: neplatný projekt SpecLabu.") from exc
            return [Attachment(attachment_id, "project", target.name, image=_render(state), state=state)]
        if isinstance(document, (dict, list)):
            from core.presets import import_presets_from_file

            presets = import_presets_from_file(target)
            return [Attachment(attachment_id, "preset", target.name, presets=presets)]
        raise ValueError(f"{target.name}: neznámý typ JSON.")
    from app.models import Spectrum
    from core.spectrum_parser import parse_spectrum_files

    try:
        curves = parse_spectrum_files(str(target))
    except Exception as exc:  # noqa: BLE001 - vendor parsers raise their own error types
        raise ValueError(f"{target.name}: soubor nelze načíst jako vzor ({exc}).") from exc
    state = AppState()
    state.add_spectra([(Spectrum(name=c.metadata.get("name") or f"{target.stem} [{i + 1}]", x=c.x, y=c.y,
                                 meta={"sourceName": target.name, **c.metadata}), [])
                       for i, c in enumerate(curves)])
    if len(state.spectra) > 1:
        state.set_plot(show_all_spectra=True)
    return [Attachment(attachment_id, "spectra", target.name, image=_render(state), state=state)]


def pdf_pages(path) -> list[bytes]:
    """Render PDF pages to PNG with QtPdf (part of PySide6); needs a Qt application."""
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
        from PySide6.QtPdf import QPdfDocument
    except ImportError as exc:
        raise ValueError("PDF nelze načíst (chybí QtPdf); přilož obrázek.") from exc
    document = QPdfDocument()
    if document.load(str(path)) != QPdfDocument.Error.None_:
        raise ValueError("PDF nelze otevřít.")
    pages = []
    for index in range(min(document.pageCount(), 4)):
        size = document.pagePointSize(index)
        scale = MAX_IMAGE_SIDE / max(size.width(), size.height(), 1)
        image = document.render(index, QSize(round(size.width() * scale), round(size.height() * scale)))
        array = QByteArray()
        buffer = QBuffer(array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        pages.append(bytes(array))
    document.close()
    if not pages:
        raise ValueError("PDF neobsahuje žádnou stránku.")
    return pages
