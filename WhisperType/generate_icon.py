"""
Generate whispertype.ico - a multi-size Windows icon for WhisperType.

Design: dark premium / tech-forward.
- Near-black slate background with a soft purple glow from centre-out
- Cyan/icy microphone that appears to glow (neon halo)
- Minimal, confident — distinct from the purple-gradient Apple-esque icon
  we started with

Exported as a multi-resolution .ico (16, 24, 32, 48, 64, 128, 256).
"""

import os
from PIL import Image, ImageDraw, ImageFilter


def lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(len(c1)))


def draw_icon(size):
    """Draw a WhisperType icon at the given size."""
    # Work at 4x for supersampling, then downscale with Lanczos.
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # --- Rounded-square base: near-black slate ---
    base = Image.new("RGBA", (s, s), (15, 23, 42, 255))  # slate-900

    # --- Purple radial glow bleeding out from centre ---
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gld = ImageDraw.Draw(glow)
    gld.ellipse(
        [int(s * 0.15), int(s * 0.15), int(s * 0.85), int(s * 0.85)],
        fill=(139, 92, 246, 180),  # violet-500 with opacity
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=s // 8))
    base = Image.alpha_composite(base, glow)

    # --- Rounded-square mask (22% corner radius) ---
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    radius = int(s * 0.22)
    md.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=255)

    bg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bg.paste(base, (0, 0), mask)
    img = Image.alpha_composite(img, bg)
    draw = ImageDraw.Draw(img)

    # --- Microphone dimensions ---
    cx = s // 2
    neon = (165, 243, 252)  # cyan-100 (icy white-cyan)
    halo_color = (34, 211, 238, 255)  # cyan-400 for the glow around it

    mic_w = int(s * 0.24)
    mic_h = int(s * 0.36)
    mic_x0 = cx - mic_w // 2
    mic_y0 = int(s * 0.22)
    mic_x1 = cx + mic_w // 2
    mic_y1 = mic_y0 + mic_h
    mic_radius = mic_w // 2

    # --- Neon halo / glow around the mic body ---
    halo = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    # Slightly larger-than-mic coloured shape that we then heavily blur
    pad = max(2, s // 80)
    hd.rounded_rectangle(
        [mic_x0 - pad, mic_y0 - pad, mic_x1 + pad, mic_y1 + pad],
        radius=mic_radius + pad,
        fill=halo_color,
    )
    halo = halo.filter(ImageFilter.GaussianBlur(radius=s // 40))
    img = Image.alpha_composite(img, halo)
    draw = ImageDraw.Draw(img)

    # --- Mic body (solid cyan-white) ---
    draw.rounded_rectangle(
        [mic_x0, mic_y0, mic_x1, mic_y1],
        radius=mic_radius,
        fill=neon + (255,),
    )

    # --- Mic stand: U-shape arc + vertical line + horizontal base ---
    stand_stroke = max(3, s // 28)
    stand_r_outer = int(s * 0.20)
    stand_cy = int(s * 0.60)

    # Halo glow for the stand too (keeps the neon consistency)
    stand_halo = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    shd = ImageDraw.Draw(stand_halo)
    shd.arc(
        [cx - stand_r_outer, stand_cy - stand_r_outer,
         cx + stand_r_outer, stand_cy + stand_r_outer],
        start=0, end=180,
        fill=halo_color,
        width=stand_stroke + 2,
    )
    line_top = stand_cy + stand_r_outer - stand_stroke // 3
    line_bottom = int(s * 0.82)
    shd.line(
        [cx, line_top, cx, line_bottom],
        fill=halo_color,
        width=stand_stroke + 2,
    )
    base_half = int(s * 0.11)
    shd.line(
        [cx - base_half, line_bottom, cx + base_half, line_bottom],
        fill=halo_color,
        width=stand_stroke + 2,
    )
    stand_halo = stand_halo.filter(ImageFilter.GaussianBlur(radius=s // 55))
    img = Image.alpha_composite(img, stand_halo)
    draw = ImageDraw.Draw(img)

    # Solid stand in neon colour
    draw.arc(
        [cx - stand_r_outer, stand_cy - stand_r_outer,
         cx + stand_r_outer, stand_cy + stand_r_outer],
        start=0, end=180,
        fill=neon + (255,),
        width=stand_stroke,
    )
    draw.line(
        [cx, line_top, cx, line_bottom],
        fill=neon + (255,),
        width=stand_stroke,
    )
    draw.line(
        [cx - base_half, line_bottom, cx + base_half, line_bottom],
        fill=neon + (255,),
        width=stand_stroke,
    )

    # --- Downscale for final output ---
    return img.resize((size, size), Image.LANCZOS)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(here, "whispertype.ico")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw_icon(s) for s in sizes]

    # Save as multi-size .ico — largest as base, PIL embeds the rest
    base = images[-1]
    base.save(
        out_path,
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=images[:-1],
    )

    # Also save a PNG preview for quick viewing
    preview_path = os.path.join(here, "whispertype_icon_preview.png")
    images[-1].save(preview_path, format="PNG")

    print(f"Wrote: {out_path}")
    print(f"Wrote: {preview_path}")


if __name__ == "__main__":
    main()
