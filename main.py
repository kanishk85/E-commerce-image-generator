from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os, shutil, uuid, random

from normalize import normalize_product
from generate import stability_generate
from PIL import Image, ImageDraw, ImageFilter

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")

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

@app.post("/generate")
async def generate(
    file: UploadFile = File(...),
    template: str = Form("wood"),
    bg_style: str = Form("match")
):
    if template not in TEMPLATES: return JSONResponse({"status": "error", "message": "Invalid template"})
    if bg_style not in {"match", "white"}:
        return JSONResponse({"status": "error", "message": "Invalid wall style"}, status_code=400)

    task_id = uuid.uuid4().hex
    canvas_size = 1024
    tpl = TEMPLATES[template]
    
    # Standard Horizon for infinite floors, but adjustable
    floor_y = 860 

    # 1. Setup Files
    filename = os.path.basename(file.filename or "upload")
    input_path = os.path.join(UPLOAD_DIR, f"{task_id}_{filename}")
    with open(input_path, "wb") as f: shutil.copyfileobj(file.file, f)

    from rembg import remove
    with open(input_path, "rb") as f: removed_bytes = remove(f.read())
    removed_path = os.path.join(OUTPUT_DIR, f"removed_{task_id}.png")
    with open(removed_path, "wb") as f: f.write(removed_bytes)

    # 2. Normalize (Layer 1)
    margin = 140
    norm_path = os.path.join(OUTPUT_DIR, f"norm_{task_id}.png")
    info = normalize_product(removed_path, norm_path, canvas_size=1024, scale_ratio=0.55, bottom_margin=margin)
    
    # Get Product Info
    px, py = info["pos"]
    pw, ph = info["size"]
    feet_cx = px + pw // 2
    feet_cy = py + ph

    # 3. BUILD THE SCENE (Layer 3 + Layer 2)
    scene = Image.new("RGBA", (canvas_size, canvas_size), (0,0,0,0))
    
    # --- LAYER 3: BACKGROUND (Wall) ---
    if bg_style == "white":
        wall_img = Image.new("RGBA", (canvas_size, floor_y), (255, 255, 255, 255))
    else:
        wall_img = generate_bokeh_wall(canvas_size, floor_y, tpl["wall_tone"])
    scene.paste(wall_img, (0, 0))

    # --- LAYER 2: BASE (Prop/Floor) ---
    # We draw this directly onto the scene
    draw = ImageDraw.Draw(scene)
    draw_base_layer(draw, tpl["type"], feet_cx, feet_cy, pw, ph, floor_y, canvas_size, canvas_size, tpl["floor_color"])

    # Save Guide
    init_path = os.path.join(OUTPUT_DIR, f"init_{task_id}.png")
    scene.save(init_path)

    # 4. SMART MASKING
    # We must mask ONLY the area we want the AI to texture.
    # 1. Wall is Protected (Black)
    # 2. Floor is Generated (White)
    mask = Image.new("L", (canvas_size, canvas_size), 0)
    mdraw = ImageDraw.Draw(mask)

    # Unmask Floor
    mdraw.rectangle([(0, floor_y + 5), (canvas_size, canvas_size)], fill=255)
    
    mask_path = os.path.join(OUTPUT_DIR, f"mask_{task_id}.png")
    mask.filter(ImageFilter.GaussianBlur(5)).save(mask_path)

    # 5. AI Generation
    ai_path = os.path.join(OUTPUT_DIR, f"bg_{task_id}.png")
    try:
        stability_generate(
            init_image_path=init_path,
            mask_path=mask_path,
            prompt=tpl["prompt"],
            negative_prompt="clutter, messy, text, watermark, bad anatomy, duplicate",
            out_path=ai_path,
            cfg_scale=tpl["cfg"],
            steps=30
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Image generation failed: {exc}") from exc

    # 6. COMPOSITE (Layer 1 on Top)
    bg = Image.open(ai_path).convert("RGBA")
    prod = Image.open(norm_path).convert("RGBA")
    composed = bg.copy()

    # Dynamic Shadow
    shadow = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    
    # Shadow logic varies by prop type
    sdraw.ellipse([px+pw*0.1, feet_cy-15, px+pw*0.9, feet_cy+15], fill=(0,0,0,160))
        
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    composed = Image.alpha_composite(composed, shadow)
    
    # Paste Product
    composed.alpha_composite(prod, dest=(0, 0))

    final_path = os.path.join(OUTPUT_DIR, f"final_{task_id}.jpg")
    composed.convert("RGB").save(final_path, "JPEG", quality=95)

    return {"status": "success", "final_image_url": f"/outputs/{os.path.basename(final_path)}"}
