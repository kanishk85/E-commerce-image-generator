"""Run a local normalization check using the bundled sample product image."""

from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from normalize import normalize_product


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_image = temp_path / "sample.png"
        output_image = temp_path / "normalized.png"
        Image.new("RGB", (320, 240), "white").save(input_image)
        normalize_product(str(input_image), str(output_image))
        if not output_image.is_file():
            raise RuntimeError("Normalization did not create an output image")
        print("Normalization succeeded")


if __name__ == "__main__":
    main()
