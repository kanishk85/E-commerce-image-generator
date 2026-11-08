# E commerce image generator

A small FastAPI web app that removes the background from a product photo, creates a styled scene, and composites the product into the generated image.

## Features

- Lightweight product cutout using `rembg`'s `u2netp` model
- Three scene styles: wood, marble, and water, with wall and floor treatments
- White studio or matching textured wall
- Stability AI image-to-image inpainting for scene generation

## Requirements

- Python 3.10 or newer
- A Stability AI API key

## Run locally

1. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Set your Stability API key in the local `.env` file (which is ignored by Git):

   ```powershell
   STABILITY_API_KEY=your-stability-api-key
   ```

   Or set it in PowerShell before starting the server:

   ```powershell
   $env:STABILITY_API_KEY = "your-stability-api-key"
   ```

4. Start the app:

   ```powershell
   uvicorn main:app --reload
   ```

5. Open <http://127.0.0.1:8000>.

Uploads and intermediate images are processed in a temporary directory and deleted after each request. The generated result is returned directly to the browser instead of being saved on the server.
