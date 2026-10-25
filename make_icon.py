"""
make_icon.py — Convert the source image -> icon.ico for the Windows app.
Run before PyInstaller:  python make_icon.py

Self-contained: reads a local image next to this script (no machine-specific paths).
"""
import os
from PIL import Image

# Local source images, in priority order (first existing one wins).
src_candidates = ["vedantu.jpg", "icon_src.jpg"]
src = next((c for c in src_candidates if os.path.exists(c)), None)
if not src:
    raise FileNotFoundError("No source icon found (expected vedantu.jpg or icon_src.jpg).")

dst = "icon.ico"
img = Image.open(src).convert("RGBA")

# All standard Windows icon sizes
sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
img_256 = img.resize((256, 256), Image.LANCZOS)
img_256.save(dst, format="ICO", sizes=sizes)

print(f"Saved {dst} ({os.path.getsize(dst) // 1024} KB) from {src}")
