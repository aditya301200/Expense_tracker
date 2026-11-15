import os
import json
from PIL import Image, ImageDraw, ImageFont

# ==============================================================================
# ⚙️ CONFIGURATION: PASTE YOUR LIVE STREAMLIT APP URL BELOW
# ==============================================================================
STREAMLIT_APP_URL = "https://das-family-tracker.streamlit.app"  # <-- Replace with your actual .streamlit.app URL!
APP_NAME = "Das Family Expense & Loan Tracker"
APP_SHORT_NAME = "Das Tracker"

DOCS_DIR = "docs"
os.makedirs(DOCS_DIR, exist_ok=True)


def create_rupee_icon(size=512):
    """Generates a sleek dark-emerald & navy app icon with glowing gold bars and ₹ symbol."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Rounded Square Background (Deep Navy / Emerald Gradient Effect)
    bg = Image.new("RGBA", (size, size), (11, 25, 44, 255))
    bg_draw = ImageDraw.Draw(bg)
    for y in range(size):
        # Subtle vertical gradient from dark teal-emerald at top to deep navy at bottom
        r = int(10 + (18 - 10) * (1 - y / size))
        g = int(22 + (68 - 22) * (1 - y / size))
        b = int(42 + (65 - 42) * (1 - y / size))
        bg_draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    # Apply rounded corners mask
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    corner_radius = int(size * 0.22)
    mask_draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=corner_radius, fill=255)
    img.paste(bg, (0, 0), mask)

    draw = ImageDraw.Draw(img)

    # 2. Subtle Gold Inner Border
    pad = int(size * 0.045)
    draw.rounded_rectangle(
        [(pad, pad), (size - pad - 1, size - pad - 1)],
        radius=int(corner_radius * 0.82),
        outline=(212, 175, 55, 110),
        width=max(2, int(size * 0.012))
    )

    # 3. Rising Financial Growth Bars (Emerald Green & Gold)
    bar_configs = [
        (0.20, 0.78, 0.29, 0.86, (46, 204, 113, 150)),
        (0.35, 0.66, 0.44, 0.86, (46, 204, 113, 185)),
        (0.50, 0.52, 0.59, 0.86, (46, 204, 113, 220)),
        (0.65, 0.36, 0.74, 0.86, (241, 196, 15, 240)),
    ]
    for x1_r, y1_r, x2_r, y2_r, color in bar_configs:
        draw.rounded_rectangle(
            [(int(size * x1_r), int(size * y1_r)), (int(size * x2_r), int(size * y2_r))],
            radius=max(3, int(size * 0.02)),
            fill=color
        )

    # Base line under bars
    draw.line(
        [(int(size * 0.15), int(size * 0.86)), (int(size * 0.82), int(size * 0.86))],
        fill=(46, 204, 113, 200),
        width=max(2, int(size * 0.01))
    )

    # 4. Upward Growth Arrow
    pts = [
        (int(size * 0.22), int(size * 0.64)),
        (int(size * 0.42), int(size * 0.48)),
        (int(size * 0.55), int(size * 0.53)),
        (int(size * 0.75), int(size * 0.24)),
    ]
    draw.line(pts, fill=(88, 245, 165, 255), width=max(4, int(size * 0.028)), joint="curve")

    # Arrowhead
    ax, ay = pts[-1]
    ah = int(size * 0.06)
    draw.polygon(
        [(ax, ay), (ax - ah, ay + int(ah * 0.25)), (ax - int(ah * 0.25), ay + ah)],
        fill=(88, 245, 165, 255)
    )

    # 5. Bold Golden Indian Rupee (₹) Symbol in Center
    font_size = int(size * 0.54)
    font = None
    # Try Windows fonts that support the Indian Rupee ₹ glyph
    for font_candidate in ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/calibrib.ttf", "C:/Windows/Fonts/seguiemj.ttf", "arial.ttf"]:
        if os.path.exists(font_candidate):
            try:
                font = ImageFont.truetype(font_candidate, font_size)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    symbol = "₹"
    bbox = draw.textbbox((0, 0), symbol, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - int(size * 0.04)
    ty = (size - th) // 2 - bbox[1] - int(size * 0.02)

    # Drop shadow for depth
    shadow_offset = max(2, int(size * 0.015))
    draw.text((tx + shadow_offset, ty + shadow_offset), symbol, font=font, fill=(0, 0, 0, 180))
    # Main Gold Symbol
    draw.text((tx, ty), symbol, font=font, fill=(255, 215, 0, 255))

    return img


def build_pwa_files():
    # 1. Generate Icons (512x512, 192x192, and root app_icon.png for Streamlit)
    icon_512 = create_rupee_icon(512)
    icon_192 = icon_512.resize((192, 192), Image.Resampling.LANCZOS)

    icon_512.save("app_icon.png", "PNG")
    icon_512.save(os.path.join(DOCS_DIR, "icon-512.png"), "PNG")
    icon_192.save(os.path.join(DOCS_DIR, "icon-192.png"), "PNG")
    print("✅ Created app_icon.png, docs/icon-192.png, and docs/icon-512.png")

    # 2. Generate docs/manifest.json
    manifest_data = {
        "name": APP_NAME,
        "short_name": APP_SHORT_NAME,
        "description": "Das Family Monthly Expense, Income & Loan Tracker",
        "start_url": "./index.html",
        "scope": "./",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#0E1117",
        "theme_color": "#0B192C",
        "icons": [
            {
                "src": "./icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "./icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }
    with open(os.path.join(DOCS_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    print("✅ Created docs/manifest.json")

    # 3. Generate docs/sw.js (Service Worker required by Android Chrome for Full-Screen PWA Install)
    sw_code = """const CACHE_NAME = 'das-tracker-pwa-v1';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
"""
    with open(os.path.join(DOCS_DIR, "sw.js"), "w", encoding="utf-8") as f:
        f.write(sw_code)
    print("✅ Created docs/sw.js")

    # 4. Generate docs/index.html (Full-Screen Zero-Margin Iframe Wrapper with ?embed=true)
    clean_url = STREAMLIT_APP_URL.rstrip("/")
    embed_url = f"{clean_url}/?embed=true"

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover" />
  <title>{APP_NAME}</title>

  <!-- PWA Manifest & Theme Colors -->
  <link rel="manifest" href="./manifest.json" />
  <meta name="theme-color" content="#0B192C" />
  <meta name="mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <meta name="apple-mobile-web-app-title" content="{APP_SHORT_NAME}" />

  <!-- App Icons -->
  <link rel="icon" type="image/png" sizes="192x192" href="./icon-192.png" />
  <link rel="apple-touch-icon" href="./icon-192.png" />

  <style>
    * {{
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }}
    html, body {{
      width: 100%;
      height: 100%;
      overflow: hidden;
      background-color: #0E1117;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}
    .iframe-container {{
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      width: 100vw;
      height: 100dvh;
      border: none;
    }}
    iframe {{
      width: 100%;
      height: 100%;
      border: none;
      display: block;
    }}
  </style>
</head>
<body>
  <div class="iframe-container">
    <iframe
      src="{embed_url}"
      allow="clipboard-read; clipboard-write; fullscreen"
      title="{APP_NAME}">
    </iframe>
  </div>

  <script>
    if ('serviceWorker' in navigator) {{
      window.addEventListener('load', () => {{
        navigator.serviceWorker.register('./sw.js').catch((err) => {{
          console.log('ServiceWorker registration failed:', err);
        }});
      }});
    }}
  </script>
</body>
</html>
"""
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"✅ Created docs/index.html (Wrapping: {embed_url})")


if __name__ == "__main__":
    build_pwa_files()
    print("\n🎉 Done! Next: Push to GitHub and enable GitHub Pages on the '/docs' folder.")