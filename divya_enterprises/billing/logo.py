"""Shop logo validation and normalisation (Business Profile upload).

The logo is stored in the database, not on disk, so pg_dump backups carry
it. Every upload is decoded with Pillow and re-encoded:

* at most MAX_UPLOAD_BYTES (2 MB) as uploaded;
* the decoded format must be PNG or JPEG (the file's real content, never its
  name or the browser's content type); SVG, GIF, WebP and anything else are
  rejected;
* decompression bombs are refused before any pixel is decoded
  (width x height above MAX_PIXELS, or Pillow's own bomb error);
* EXIF orientation applied, converted to RGB/RGBA, scaled so the longest
  side is at most MAX_SIDE px, saved as PNG (which drops all metadata).
"""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_SIDE = 600
ALLOWED_FORMATS = {"PNG", "JPEG"}
STORED_CONTENT_TYPE = "image/png"


class LogoError(ValueError):
    """A logo upload that cannot be accepted; the message is shown to the user."""


def normalize_logo(data):
    """Validate an uploaded logo and return the PNG bytes to store."""
    if not data:
        raise LogoError("The logo file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise LogoError("The logo must be 2 MB or smaller.")
    try:
        image = Image.open(BytesIO(data))
        image_format = image.format
        width, height = image.size
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise LogoError("The logo must be a PNG or JPEG image.") from None
    if image_format not in ALLOWED_FORMATS:
        raise LogoError(f"The logo must be a PNG or JPEG image (this file is {image_format}).")
    if width * height > MAX_PIXELS:
        raise LogoError("The logo image is too large to process; use one under 25 megapixels.")
    try:
        image.load()
        image = ImageOps.exif_transpose(image)
    except (Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise LogoError("The logo image could not be read; it may be damaged.") from None

    has_alpha = image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha else "RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()
