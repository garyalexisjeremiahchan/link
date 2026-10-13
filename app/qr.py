import base64
import io
import os
import re
from pathlib import Path
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask
from PIL import Image, ImageDraw
import segno

BASE_DIR = Path(__file__).resolve().parent.parent
BRAND_DIR = BASE_DIR / "static" / "brand"

BRAND_LOGO_SVG_PATH = BRAND_DIR / "fcc-dove-light.svg"
BRAND_LOGO_1C_SVG_PATH = BRAND_DIR / "fcc-dove-1c-ink.svg"
AMPLIFY_LOGO_PNG_PATH = BRAND_DIR / "amplify" / "amplify-circle.png"
FCC_LOGO_PNG_PATH = BRAND_DIR / "fcc-dove.png"

def get_domain_brand(domain_name: str) -> tuple[Path, bool]:
    """Return (logo_path, is_amplify) for the given domain."""
    d = (domain_name or "").lower()
    if "amp.ad" in d or "amplify" in d:
        return AMPLIFY_LOGO_PNG_PATH, True
    return FCC_LOGO_PNG_PATH, False

def generate_qr_svg(
    url: str,
    dark_color: str = "#14161A",
    light_color: str = "#FFFFFF",
    embed_logo: bool = True,
    domain_name: str = "fcc.li"
) -> str:
    """Generate clean vector SVG QR Code using segno with centered brand emblem."""
    qr = segno.make(url, error="h")
    buffer = io.BytesIO()
    qr.save(
        buffer,
        kind="svg",
        dark=dark_color,
        light=light_color,
        scale=10,
        border=3,
    )
    svg_str = buffer.getvalue().decode("utf-8")

    if embed_logo:
        logo_path, is_amplify = get_domain_brand(domain_name)
        if logo_path.exists():
            m_w = re.search(r'width="(\d+(?:\.\d+)?)"', svg_str)
            if m_w:
                w = float(m_w.group(1))
                badge_size = w * 0.24
                offset = (w - badge_size) / 2.0
                scale_ratio = 0.75 if is_amplify else 0.80
                inner_size = badge_size * scale_ratio
                inner_offset = (w - inner_size) / 2.0
                b64 = base64.b64encode(logo_path.read_bytes()).decode("ascii")
                badge_svg = (
                    f'  <g class="qr-badge" xmlns:xlink="http://www.w3.org/1999/xlink">\n'
                    f'    <rect x="{offset:.2f}" y="{offset:.2f}" width="{badge_size:.2f}" height="{badge_size:.2f}" fill="{light_color}" />\n'
                    f'    <image x="{inner_offset:.2f}" y="{inner_offset:.2f}" width="{inner_size:.2f}" height="{inner_size:.2f}" '
                    f'href="data:image/png;base64,{b64}" xlink:href="data:image/png;base64,{b64}" />\n'
                    f'  </g>\n</svg>'
                )
                svg_str = svg_str.replace("</svg>", badge_svg)

    return svg_str

def generate_qr_png(
    url: str,
    dark_color: tuple = (20, 22, 26),      # ink-950 #14161A
    light_color: tuple = (255, 255, 255),  # white
    embed_logo: bool = True,
    domain_name: str = "fcc.li"
) -> bytes:
    """Generate high-resolution PNG with centered brand emblem (FCC Dove or Amplify)."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(
        image_factory=StyledPilImage,
        color_mask=SolidFillColorMask(back_color=light_color, front_color=dark_color),
        module_drawer=RoundedModuleDrawer()
    ).convert("RGBA")

    if embed_logo:
        # Create a clean borderless square badge in the center
        badge_size = int(img.size[0] * 0.24)
        badge = Image.new("RGBA", (badge_size, badge_size), (*light_color, 255))
        
        logo_path, is_amplify = get_domain_brand(domain_name)

        if logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")
            scale_ratio = 0.75 if is_amplify else 0.80
            inner_size = int(badge_size * scale_ratio)
            logo = logo.resize((inner_size, inner_size), Image.Resampling.LANCZOS)
            offset = ((badge_size - inner_size) // 2, (badge_size - inner_size) // 2)
            badge.paste(logo, offset, logo)
        else:
            # Stylized Dove Gold core emblem fallback
            gold = (248, 220, 41, 255)  # Dove Gold #F8DC29
            d_size = int(badge_size * 0.6)
            d_offset = (badge_size - d_size) // 2
            border_draw = ImageDraw.Draw(badge)
            border_draw.rectangle(
                (d_offset, d_offset, d_offset + d_size, d_offset + d_size),
                fill=gold
            )

        pos = ((img.size[0] - badge_size) // 2, (img.size[1] - badge_size) // 2)
        img.paste(badge, pos)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
