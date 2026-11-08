# normalize.py
from PIL import Image, ImageFilter

def normalize_product(
    input_path: str,
    output_path: str,
    canvas_size: int = 1024,
    scale_ratio: float = 0.55,
    bottom_margin: int = 174  # Pixels from bottom (1024 - 850)
):
    """
    Normalize product and bottom-anchor it on an RGBA canvas.
    Returns dict with pos and size for compositing/shadowing.
    """
    img = Image.open(input_path).convert("RGBA")

    # Trim transparent borders
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    # Slight sharpening for crisp edges
    img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))

    # Resize keeping aspect ratio
    max_dim = int(canvas_size * scale_ratio)
    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    # Create canvas and bottom-anchor product
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    x = (canvas_size - img.width) // 2

    anchor_y = canvas_size - bottom_margin   # product bottom target
    y = anchor_y - img.height

    # small forward offset so product sits slightly ON the floor (not behind seam)
    y += 6  # tweakable: increase to push forward, decrease to recede

    # clamp
    if y < 20:
        y = 20

    canvas.paste(img, (x, y), img)
    canvas.save(output_path, "PNG", optimize=True)

    return {
        "canvas_path": output_path,
        "pos": (x, y),
        "size": (img.width, img.height),
        "anchor_y": anchor_y
    }
