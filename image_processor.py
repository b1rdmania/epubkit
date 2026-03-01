"""
Image processor for Xteink X4 EPUB Optimizer.
Handles: baseline JPEG conversion, resize, 4-level grayscale quantization,
contrast boost, Light Novel mode.

X4 specs (SSD1677 controller):
  - Display: 800x480, 4-level grayscale (black, dark gray, light gray, white)
  - Max image: 1024x1024
  - RAM: 380KB — smaller images = faster rendering
"""

import io
from pathlib import Path
from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageOps, ImageDraw, ImageFont


# X4 screen dimensions (800x480 landscape panel)
X4_WIDTH = 800
X4_HEIGHT = 480

# Hard limit per X4 JPEG spec
MAX_IMAGE_DIMENSION = 1024

# SSD1677 supports 4-level grayscale: black, dark gray, light gray, white
EINK_PALETTE_LEVELS = [0, 85, 170, 255]

SUPPORTED_EXTENSIONS = {'.png', '.gif', '.webp', '.bmp', '.jpeg', '.jpg', '.tif', '.tiff'}


@dataclass
class ImageOptions:
    grayscale: bool = True
    contrast_boost: bool = True
    contrast_factor: float = 1.5  # Higher default for 4-level display
    quality: int = 70
    max_width: int = X4_WIDTH
    max_height: int = X4_HEIGHT
    eink_quantize: bool = True  # Quantize to 4 gray levels (SSD1677)
    light_novel_mode: bool = False
    light_novel_rotate_left: bool = True


@dataclass
class ImageResult:
    output_bytes: bytes
    new_filename: str
    original_size: int
    new_size: int
    was_converted: bool
    details: str


def should_process(filename: str) -> bool:
    """Check if a file is a processable image based on extension."""
    return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS


def is_progressive_jpeg(image_bytes: bytes) -> bool:
    """Check if JPEG data is progressive/interlaced."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.format != 'JPEG':
            return False
        return img.info.get('progressive', False) or img.info.get('progression', False)
    except Exception:
        return False


def _quantize_to_4_levels(img: Image.Image) -> Image.Image:
    """
    Quantize grayscale image to 4 e-ink levels with Floyd-Steinberg dithering.
    Maps to: black (0), dark gray (85), light gray (170), white (255).
    Uses PIL's built-in quantize with a custom 4-color palette for speed.
    """
    # Build a 4-color grayscale palette image
    palette_img = Image.new('P', (1, 1))
    palette = []
    for level in EINK_PALETTE_LEVELS:
        palette.extend([level, level, level])
    # Pad palette to 256 entries (required by PIL)
    palette.extend([0, 0, 0] * (256 - len(EINK_PALETTE_LEVELS)))
    palette_img.putpalette(palette)

    # Quantize with Floyd-Steinberg dithering
    rgb = img.convert('RGB')
    quantized = rgb.quantize(colors=len(EINK_PALETTE_LEVELS),
                             palette=palette_img,
                             dither=Image.Dither.FLOYDSTEINBERG)
    return quantized.convert('L')


def _handle_transparency(img: Image.Image) -> Image.Image:
    """Composite transparent images onto white background."""
    if img.mode in ('RGBA', 'LA', 'PA'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'PA':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1])
        return background
    if img.mode == 'P':
        if 'transparency' in img.info:
            img = img.convert('RGBA')
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            return background
        return img.convert('RGB')
    return img


def _handle_light_novel(img: Image.Image, rotate_left: bool) -> list[Image.Image]:
    """
    Light Novel mode: if image is landscape (wider than tall),
    rotate and optionally split for vertical e-reader viewing.
    """
    width, height = img.size

    if width <= height:
        return [img]

    aspect = width / height

    if aspect > 1.8:
        # Double-page spread — split into two portrait pages
        mid = width // 2
        right_half = img.crop((mid, 0, width, height))
        left_half = img.crop((0, 0, mid, height))
        return [right_half, left_half]
    else:
        angle = 90 if rotate_left else -90
        rotated = img.rotate(angle, expand=True)
        return [rotated]


def process_image(image_bytes: bytes, filename: str, options: ImageOptions = None) -> list[ImageResult]:
    """
    Process a single image for X4 optimization.
    Returns a list of ImageResult (usually 1, but Light Novel mode may split into 2).
    """
    if options is None:
        options = ImageOptions()

    original_size = len(image_bytes)
    original_ext = Path(filename).suffix.lower()
    stem = Path(filename).stem

    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        return [ImageResult(
            output_bytes=image_bytes,
            new_filename=filename,
            original_size=original_size,
            new_size=original_size,
            was_converted=False,
            details=f"Skipped (corrupt: {e})"
        )]

    # Handle animated GIFs — take first frame
    if getattr(img, 'is_animated', False):
        img.seek(0)

    # Handle CMYK
    if img.mode == 'CMYK':
        img = img.convert('RGB')

    # Handle 1-bit images
    if img.mode == '1':
        img = img.convert('L')

    # Handle transparency
    img = _handle_transparency(img)

    # Ensure RGB mode
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    # Light Novel mode — handle landscape images
    if options.light_novel_mode:
        images = _handle_light_novel(img, options.light_novel_rotate_left)
    else:
        images = [img]

    results = []
    for i, current_img in enumerate(images):
        details_parts = []

        # Track format conversion
        if original_ext != '.jpg' and original_ext != '.jpeg':
            details_parts.append(f"{original_ext.upper().strip('.')}→JPEG")

        orig_w, orig_h = current_img.size

        # Enforce 1024x1024 hard limit (X4 JPEG spec)
        if orig_w > MAX_IMAGE_DIMENSION or orig_h > MAX_IMAGE_DIMENSION:
            current_img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
                                  Image.Resampling.LANCZOS)
            clamped_w, clamped_h = current_img.size
            details_parts.append(f"clamped {orig_w}x{orig_h}→{clamped_w}x{clamped_h}")
            orig_w, orig_h = clamped_w, clamped_h

        # Resize to fit X4 screen
        if orig_w > options.max_width or orig_h > options.max_height:
            current_img.thumbnail((options.max_width, options.max_height),
                                  Image.Resampling.LANCZOS)
            new_w, new_h = current_img.size
            details_parts.append(f"resized {orig_w}x{orig_h}→{new_w}x{new_h}")

        # Convert to grayscale
        if options.grayscale:
            current_img = current_img.convert('L')

            # Contrast enhancement (before quantization for best results)
            if options.contrast_boost:
                if options.eink_quantize:
                    # Auto-stretch histogram first for better 4-level mapping
                    current_img = ImageOps.autocontrast(current_img, cutoff=1)
                enhancer = ImageEnhance.Contrast(current_img)
                current_img = enhancer.enhance(options.contrast_factor)

            # Quantize to 4 e-ink levels with dithering
            if options.eink_quantize:
                current_img = _quantize_to_4_levels(current_img)
                details_parts.append("4-level grayscale")
            else:
                details_parts.append("grayscale")

            if options.contrast_boost:
                details_parts.append(f"contrast {options.contrast_factor}x")

            # Convert back to RGB for JPEG compatibility
            current_img = current_img.convert('RGB')

        elif options.contrast_boost:
            # Contrast without grayscale
            enhancer = ImageEnhance.Contrast(current_img)
            current_img = enhancer.enhance(options.contrast_factor)
            details_parts.append(f"contrast {options.contrast_factor}x")

        # Save as baseline JPEG
        buffer = io.BytesIO()
        current_img.save(
            buffer,
            format='JPEG',
            quality=options.quality,
            progressive=False,
            optimize=True,
            # 4:2:0 for grayscale (all 3 channels identical, saves ~15-20%)
            # 4:4:4 for color images
            subsampling=2 if options.grayscale else 0
        )
        output_bytes = buffer.getvalue()

        # Build filename
        if len(images) > 1:
            new_filename = f"{stem}_part{i + 1}.jpg"
            details_parts.insert(0, f"split part {i + 1}/{len(images)}")
        else:
            new_filename = f"{stem}.jpg"

        results.append(ImageResult(
            output_bytes=output_bytes,
            new_filename=new_filename,
            original_size=original_size if i == 0 else 0,
            new_size=len(output_bytes),
            was_converted=True,
            details=", ".join(details_parts) if details_parts else "baseline JPEG"
        ))

    return results


def generate_cover_image(title: str, author: str,
                         width: int = X4_WIDTH, height: int = X4_HEIGHT) -> bytes:
    """Generate a simple cover image from title and author text."""
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    title_size = 36
    author_size = 24

    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", title_size)
        author_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", author_size)
    except (OSError, IOError):
        try:
            title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", title_size)
            author_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", author_size)
        except (OSError, IOError):
            title_font = ImageFont.load_default()
            author_font = ImageFont.load_default()

    border = 20
    draw.rectangle(
        [border, border, width - border, height - border],
        outline=(180, 180, 180),
        width=2
    )

    padding = 40
    max_text_width = width - (padding * 2)

    def wrap_text(text, font, max_w):
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_w:
                current_line = test
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    title_lines = wrap_text(title, title_font, max_text_width)
    title_y = height // 3
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        line_w = bbox[2] - bbox[0]
        x = (width - line_w) // 2
        draw.text((x, title_y), line, fill=(30, 30, 30), font=title_font)
        title_y += bbox[3] - bbox[1] + 8

    if author:
        author_lines = wrap_text(author, author_font, max_text_width)
        author_y = title_y + 40
        for line in author_lines:
            bbox = draw.textbbox((0, 0), line, font=author_font)
            line_w = bbox[2] - bbox[0]
            x = (width - line_w) // 2
            draw.text((x, author_y), line, fill=(100, 100, 100), font=author_font)
            author_y += bbox[3] - bbox[1] + 6

    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=85, progressive=False, optimize=True)
    return buffer.getvalue()
