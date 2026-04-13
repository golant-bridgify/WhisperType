"""
Generate whispertype.ico - a multi-size Windows icon for WhisperType.

Produces a modern microphone icon with a purple/blue gradient background,
exported as a multi-resolution .ico file (16, 32, 48, 64, 128, 256).
"""

import os
from PIL import Image, ImageDraw, ImageFilter


def lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(len(c1)))


def draw_icon(size):
    """Draw a WhisperType icon at the given size."""
    # Work at 4x for supersampling, then downscale
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # --- Rounded-square background with vertical gradient ---
    # Top color (lighter purple) -> bottom color (deeper purple)
    top_color = (124, 92, 255)      # #7C5CFF
    bot_color = (45, 27, 105)       # #2D1B69

    # Create gradient on a separate layer
    gradient = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    for y in range(s):
        t = y / (s - 1)
        color = lerp_color(top_color, bot_color, t) + (255,)
        gd.line([(0, y), (s, y)], fill=color)

    # Mask: rounded square
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    radius = int(s * 0.22)
    md.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=255)

    # Apply mask to gradient
    bg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bg.paste(gradient, (0, 0), mask)

    # Subtle inner glow on top edge
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gdl = ImageDraw.Draw(glow)
    gdl.rounded_rectangle(
        [int(s * 0.05), int(s * 0.05), int(s * 0.95), int(s * 0.5)],
        radius=radius,
        fill=(255, 255, 255, 28),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=s // 40))
    bg = Image.alpha_composite(bg, glow)

    img = Image.alpha_composite(img, bg)
    draw = ImageDraw.Draw(img)

    # --- Sound waves (arcs on each side of the microphone) ---
    cx, cy = s // 2, int(s * 0.48)
    wave_color = (255, 255, 255, 170)

    # Two arcs on each side
    arc_stroke = max(2, s // 48)
    for i, r in enumerate([int(s * 0.30), int(s * 0.38)]):
        # Left side
        draw.arc(
            [cx - r, cy - r, cx + r, cy + r],
            start=135,
            end=225,
            fill=wave_color,
            width=arc_stroke,
        )
        # Right side
        draw.arc(
            [cx - r, cy - r, cx + r, cy + r],
            start=-45,
            end=45,
            fill=wave_color,
            width=arc_stroke,
        )

    # --- Microphone body ---
    mic_w = int(s * 0.22)
    mic_h = int(s * 0.36)
    mic_x0 = cx - mic_w // 2
    mic_y0 = int(s * 0.22)
    mic_x1 = cx + mic_w // 2
    mic_y1 = mic_y0 + mic_h
    mic_radius = mic_w // 2

    # Soft shadow behind the mic
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    offset = max(2, s // 80)
    sd.rounded_rectangle(
        [mic_x0 + offset, mic_y0 + offset, mic_x1 + offset, mic_y1 + offset],
        radius=mic_radius,
        fill=(0, 0, 0, 90),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=s // 60))
    img = Image.alpha_composite(img, shadow)
    draw = ImageDraw.Draw(img)

    # Mic body (white)
    draw.rounded_rectangle(
        [mic_x0, mic_y0, mic_x1, mic_y1],
        radius=mic_radius,
        fill=(255, 255, 255, 255),
    )

    # --- Mic stand (U-shape + vertical line + base) ---
    stand_stroke = max(3, s // 28)
    stand_r_outer = int(s * 0.20)
    stand_cy = int(s * 0.58)
    draw.arc(
        [cx - stand_r_outer, stand_cy - stand_r_outer,
         cx + stand_r_outer, stand_cy + stand_r_outer],
        start=0,
        end=180,
        fill=(255, 255, 255, 255),
        width=stand_stroke,
    )

    # Vertical line from U down to base
    line_top = stand_cy + stand_r_outer - stand_stroke // 2
    line_bottom = int(s * 0.84)
    draw.line(
        [cx, line_top, cx, line_bottom],
        fill=(255, 255, 255, 255),
        width=stand_stroke,
    )

    # Base (horizontal line)
    base_half = int(s * 0.11)
    draw.line(
        [cx - base_half, line_bottom, cx + base_half, line_bottom],
        fill=(255, 255, 255, 255),
        width=stand_stroke,
    )

    # Downscale with high-quality Lanczos
    return img.resize((size, size), Image.LANCZOS)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(here, "whispertype.ico")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw_icon(s) for s in sizes]

    # Save as multi-size .ico (largest is the base, PIL embeds the rest)
    base = images[-1]
    base.save(
        out_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
    )

    # Also save a PNG preview for quick viewing
    preview_path = os.path.join(here, "whispertype_icon_preview.png")
    images[-1].save(preview_path, format="PNG")

    print(f"Wrote: {out_path}")
    print(f"Wrote: {preview_path}")


if __name__ == "__main__":
    main()
