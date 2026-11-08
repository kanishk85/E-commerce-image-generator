"""Stability AI image-to-image masking integration."""

import base64
import os

import requests
from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

STABILITY_KEY = os.getenv("STABILITY_API_KEY", "")
STABILITY_URL = (
    "https://api.stability.ai/v1/generation/"
    "stable-diffusion-xl-1024-v1-0/image-to-image/masking"
)


def stability_generate(
    init_image_path: str,
    mask_path: str,
    prompt: str,
    negative_prompt: str,
    out_path: str,
    cfg_scale: float = 7.0,
    steps: int = 30,
    timeout: int = 120,
) -> bool:
    """Generate a masked image with Stability AI and save it to ``out_path``."""
    if not STABILITY_KEY:
        raise RuntimeError("STABILITY_API_KEY is missing; set it in .env or the environment")

    headers = {
        "Authorization": f"Bearer {STABILITY_KEY}",
        "Accept": "application/json",
    }
    data = {
        "mask_source": "MASK_IMAGE_WHITE",
        "text_prompts[0][text]": prompt,
        "text_prompts[0][weight]": 1.0,
        "text_prompts[1][text]": negative_prompt,
        "text_prompts[1][weight]": -1.0,
        "cfg_scale": cfg_scale,
        "steps": steps,
        "samples": 1,
    }

    with open(init_image_path, "rb") as init_image, open(mask_path, "rb") as mask_image:
        files = {"init_image": init_image, "mask_image": mask_image}
        response = requests.post(
            STABILITY_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=timeout,
        )

    if not response.ok:
        raise RuntimeError(f"Stability API error {response.status_code}: {response.text}")

    try:
        artifacts = response.json().get("artifacts", [])
        image_data = base64.b64decode(artifacts[0]["base64"], validate=True)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Stability API returned an invalid image response") from exc

    with open(out_path, "wb") as output_file:
        output_file.write(image_data)
    return True
