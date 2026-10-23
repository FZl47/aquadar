import io
import os

from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .providers.base import KIND_IMAGE, KIND_PDF, KIND_TEXT, KIND_UNSUPPORTED, Attachment

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')
TEXT_EXTENSIONS = ('.txt', '.csv')
MAX_IMAGE_DIMENSION = 1600
JPEG_QUALITY = 85
MAX_TEXT_CHARS = 20000


def _read_bytes(field_file):
    field_file.open('rb')
    try:
        return field_file.read()
    finally:
        field_file.close()


def _image_attachment(label, filename, raw):
    image = Image.open(io.BytesIO(raw))
    if image.mode not in ('RGB', 'L'):
        image = image.convert('RGB')
    image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    return Attachment(label=label, filename=filename, kind=KIND_IMAGE, mime_type='image/jpeg', data=buffer.getvalue())


def _pdf_text(raw):
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [(page.extract_text() or '').strip() for page in reader.pages]
    except PyPdfError:
        return ''
    return '\n'.join(page for page in pages if page)[:MAX_TEXT_CHARS]


def _plain_text(raw):
    for encoding in ('utf-8-sig', 'cp1256', 'latin-1'):
        try:
            return raw.decode(encoding)[:MAX_TEXT_CHARS]
        except UnicodeDecodeError:
            continue
    return ''


def load_attachment(label, field_file):
    filename = os.path.basename(field_file.name)
    extension = os.path.splitext(filename)[1].lower()
    raw = _read_bytes(field_file)

    if extension in IMAGE_EXTENSIONS:
        return _image_attachment(label, filename, raw)
    if extension == '.pdf':
        return Attachment(
            label=label, filename=filename, kind=KIND_PDF,
            mime_type='application/pdf', data=raw, text=_pdf_text(raw),
        )
    if extension in TEXT_EXTENSIONS:
        return Attachment(label=label, filename=filename, kind=KIND_TEXT, text=_plain_text(raw))
    return Attachment(label=label, filename=filename, kind=KIND_UNSUPPORTED)


def load_experiment_attachments(experiment):
    return [
        load_attachment('آزمایش خاک', experiment.soil_file),
        load_attachment('آزمایش برگ', experiment.leaf_file),
        load_attachment('آزمایش آب', experiment.water_file),
    ]
