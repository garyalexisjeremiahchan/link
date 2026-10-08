import io
import os
from pathlib import Path
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask
from PIL import Image
import segno

BRAND_LOGO_SVG_PATH = Path("static/brand/fcc-dove-light.svg")
BRAND_LOGO_1C_SVG_PATH = Path("static/brand/fcc-dove-1c-ink.svg")

def generate_qr_svg(url: str, dark_color: str = "#14161A", light_color: str = "#FFFFFF") -> str:
    """Generate clean vector SVG QR Code using segno."""
    qr = segno.make(url, error="h")
    buffer = io.BytesIO()
    qr.save(
        buffer,
        kind="svg",
        dark=dark_color,
        light=light_color,
        scale=10,
        border=2,
    )
    return buffer.getvalue().decode("utf-8")

def generate_qr_png(
    url: str,
    dark_color: tuple = (20, 22, 26),      # ink-950 #14161A
    light_color: tuple = (255, 255, 255),  # white
    embed_logo: bool = True
) -> bytes:
    """Generate high-resolution PNG with centered FCC Dove emblem."""
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
        # Check if we have raster logo or draw emblem
        # Create a clean circular badge with FCC Dove in the center
        badge_size = int(img.size[0] * 0.24)
        badge = Image.new("RGBA", (badge_size, badge_size), (255, 255, 255, 255))
        
        # Draw soft rounded boundary for badge
        from PIL import ImageDraw
        mask = Image.new("L", (badge_size, badge_size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, badge_size, badge_size), fill=255)
        
        # Add a subtle border
        border_draw = ImageDraw.Draw(badge)
        border_draw.ellipse((0, 0, badge_size - 1, badge_size - 1), outline=dark_color, width=2)
        
        # If we have a PNG icon or raster, paste it; otherwise render dove silhouette
        # Let's draw an elegant Dove Gold dot or load fcc-app-icon if rendered
        # We can draw stylized wings/cross or paste
        logo_png_path = Path("static/brand/fcc-dove.png")
        if logo_png_path.exists():
            logo = Image.open(logo_png_path).convert("RGBA")
            inner_size = int(badge_size * 0.75)
            logo = logo.resize((inner_size, inner_size), Image.Resampling.LANCZOS)
            offset = ((badge_size - inner_size) // 2, (badge_size - inner_size) // 2)
            badge.paste(logo, offset, logo)
        else:
            # Stylized Dove Gold core emblem
            gold = (248, 220, 41, 255)  # Dove Gold #F8DC29
            teal = (28, 118, 120, 255)  # Teal #1C7678
            d_size = int(badge_size * 0.6)
            d_offset = (badge_size - d_size) // 2
            border_draw.ellipse(
                (d_offset, d_offset, d_offset + d_size, d_offset + d_size),
                fill=gold,
                outline=teal,
                width=2
            )

        pos = ((img.size[0] - badge_size) // 2, (img.size[1] - badge_size) // 2)
        img.paste(badge, pos, mask)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
