from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.responses import Response
from tempfile import TemporaryDirectory
import io, logging, os, random, time
from functools import lru_cache

from normalize import normalize_product
from generate import stability_generate
from PIL import Image, ImageDraw, ImageFilter

app = FastAPI()
logger = logging.getLogger("uvicorn.error")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------
# 1. THE BRAIN: TEMPLATE LIBRARY
# ---------------------------
# To add a new style, you just add one entry here.
TEMPLATES = {
    # --- INFINITE FLOORS ---
    "wood": {
        "type": "infinite",
        "prompt": "rustic wooden table surface, rich wood texture, seamless, clean studio lighting",
        "floor_color": (139, 69, 19, 255),
        "wall_tone": (210, 190, 170),
        "cfg": 9.0
    },
    "marble": {
        "type": "infinite",
        "prompt": "clean white marble surface texture, subtle veining, seamless, no objects",
        "floor_color": (240, 240, 240, 255),
        "wall_tone": (230, 230, 235),
        "cfg": 10.0
    },
    
    # --- WATER ---
    "water": {
        "type": "prop_ripples",
        "prompt": "product standing on water surface, blue water ripples, reflection, ocean horizon, fresh aquatic background",
        "floor_color": (100, 150, 255, 255), # Blue
        "wall_tone": (180, 220, 255),        # Sky Blue
        "cfg": 9.0
    }
}

# ---------------------------
# 2. LAYER 3: BACKGROUND GENERATOR (The Wall)
# ---------------------------
def generate_bokeh_wall(width, height, base_color):
    """Generates Layer 3: The blurry background wall"""
    wall = Image.new("RGBA", (width, height), base_color + (255,))
    draw = ImageDraw.Draw(wall)
    # Draw random lights
    for _ in range(25):
        x = random.randint(0, width)
        y = random.randint(0, height)
        radius = random.randint(40, 120)
        opacity = random.randint(15, 45)
        # Light is brighter than base
        light_color = tuple(min(255, c + 50) for c in base_color) + (opacity,)
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=light_color)
    return wall.filter(ImageFilter.GaussianBlur(35)) # Heavy blur for depth

# ---------------------------
# 3. LAYER 2: BASE GENERATOR (The Prop/Floor)
# ---------------------------
def draw_base_layer(draw, tpl_type, x, y, w, h, floor_y, canvas_w, canvas_h, color):
    """
    Draws Layer 2 based on the template type.
    x, y, w, h = Product dimensions/location.
    """
    
    # A. INFINITE FLOOR (Wood, Marble)
    if tpl_type == "infinite":
        # Just a flat block from horizon to bottom
        draw.rectangle([(0, floor_y), (canvas_w, canvas_h)], fill=color)

    # B. WATER (Ripples)
    elif tpl_type == "prop_ripples":
        # Draw Water Surface
        draw.rectangle([(0, floor_y), (canvas_w, canvas_h)], fill=color)
        
        # Draw Concentric Ellipses (Ripples)
        center_y = y + 20
        for i in range(3):
            r_w = int(w * (1.2 + i*0.5))
            r_h = int(w * (0.3 + i*0.1))
            draw.ellipse(
                [x - r_w//2, center_y - r_h//2, x + r_w//2, center_y + r_h//2],
                outline=(200, 230, 255, 150), width=3
            )


@app.get("/", response_class=HTMLResponse)
def home():
    index_path = os.path.join(BASE_DIR, "index.html")
    if not os.path.exists(index_path): return HTMLResponse("Index not found", 500)
    with open(index_path, "r", encoding="utf-8") as f: return f.read()


@app.head("/", include_in_schema=False)
def home_head():
    return Response(status_code=200)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@lru_cache(maxsize=1)
def get_rembg_session():
    from rembg import new_session

    started = time.perf_counter()
    logger.info("Loading the rembg model session")
    session = new_session()
    logger.info("rembg model session ready in %.1f seconds", time.perf_counter() - started)
    return session

def create_product_image(input_bytes: bytes, template: str, bg_style: str) -> bytes:
    """Create an image using temporary files that are removed on return."""
    canvas_size = 1024
    floor_y = 860
    tpl = TEMPLATES[template]

    with TemporaryDirectory(prefix="product-image-") as temp_dir:
        input_path = os.path.join(temp_dir, "upload")
        with open(input_path, "wb") as input_file:
            input_file.write(input_bytes)

        from rembg import remove

        removed_path = os.path.join(temp_dir, "removed.png")
        removal_started = time.perf_counter()
        logger.info("Removing the uploaded image background")
        with open(input_path, "rb") as input_file:
            removed_bytes = remove(input_file.read(), session=get_rembg_session())
        logger.info("Background removal finished in %.1f seconds", time.perf_counter() - removal_started)
        with open(removed_path, "wb") as removed_file:
            removed_file.write(removed_bytes)

        norm_path = os.path.join(temp_dir, "normalized.png")
        info = normalize_product(
            removed_path,
            norm_path,
            canvas_size=canvas_size,
            scale_ratio=0.55,
            bottom_margin=140,
        )
        px, py = info["pos"]
        pw, ph = info["size"]
        feet_cx = px + pw // 2
        feet_cy = py + ph

        scene = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        if bg_style == "white":
            wall_img = Image.new("RGBA", (canvas_size, floor_y), (255, 255, 255, 255))
        else:
            wall_img = generate_bokeh_wall(canvas_size, floor_y, tpl["wall_tone"])
        scene.paste(wall_img, (0, 0))

        draw = ImageDraw.Draw(scene)
        draw_base_layer(
            draw, tpl["type"], feet_cx, feet_cy, pw, ph,
            floor_y, canvas_size, canvas_size, tpl["floor_color"]
        )
        init_path = os.path.join(temp_dir, "scene.png")
        scene.save(init_path)

        mask = Image.new("L", (canvas_size, canvas_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rectangle([(0, floor_y + 5), (canvas_size, canvas_size)], fill=255)
        mask_path = os.path.join(temp_dir, "mask.png")
        mask.filter(ImageFilter.GaussianBlur(5)).save(mask_path)

        ai_path = os.path.join(temp_dir, "generated-background.png")
        try:
            generation_started = time.perf_counter()
            logger.info("Requesting a background from Stability AI")
            stability_generate(
                init_image_path=init_path,
                mask_path=mask_path,
                prompt=tpl["prompt"],
                negative_prompt="clutter, messy, text, watermark, bad anatomy, duplicate",
                out_path=ai_path,
                cfg_scale=tpl["cfg"],
                steps=30,
            )
            logger.info("Stability AI finished in %.1f seconds", time.perf_counter() - generation_started)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Image generation failed: {exc}") from exc

        with Image.open(ai_path) as generated_background:
            composed = generated_background.convert("RGBA")
        with Image.open(norm_path) as normalized_product:
            product = normalized_product.convert("RGBA")

        shadow = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.ellipse(
            [px + pw * 0.1, feet_cy - 15, px + pw * 0.9, feet_cy + 15],
            fill=(0, 0, 0, 160),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(10))
        composed = Image.alpha_composite(composed, shadow)
        composed.alpha_composite(product, dest=(0, 0))

        output = io.BytesIO()
        composed.convert("RGB").save(output, "JPEG", quality=95)
        return output.getvalue()


@app.post("/generate")
async def generate(
    file: UploadFile = File(...),
    template: str = Form("wood"),
    bg_style: str = Form("match"),
):
    if template not in TEMPLATES:
        return JSONResponse({"status": "error", "message": "Invalid template"}, status_code=400)
    if bg_style not in {"match", "white"}:
        return JSONResponse({"status": "error", "message": "Invalid wall style"}, status_code=400)

    try:
        image_bytes = await file.read()
        result_bytes = create_product_image(image_bytes, template, bg_style)
    finally:
        await file.close()

    return Response(content=result_bytes, media_type="image/jpeg")
