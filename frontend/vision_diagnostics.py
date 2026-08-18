"""
EcoPilot Frontend: Vision Diagnostics
=========================================
Detects fridge frost buildup, dirty AC filters, and dry/scaled cooler pads
from a user-submitted photo. No new hardware needed -- works with any
phone camera.

HONESTY NOTE (say this explicitly in the demo): this is a lightweight,
rule-based image-statistics analyzer -- genuinely analyzes whatever photo
you feed it (real pixel statistics, not a canned response), but it is NOT
a trained CNN. A production version would swap in a small fine-tuned
model (e.g. MobileNet) trained on a labeled photo dataset -- same
architecture slot, different backend.
"""

import numpy as np
from PIL import Image


def _load_rgb(image_input):
    if isinstance(image_input, Image.Image):
        img = image_input
    else:
        img = Image.open(image_input)
    img = img.convert("RGB")
    img.thumbnail((400, 400))
    return np.asarray(img).astype(float) / 255.0


def _to_hsv(rgb_arr):
    img = Image.fromarray((rgb_arr * 255).astype(np.uint8))
    hsv = np.asarray(img.convert("HSV")).astype(float) / 255.0
    return hsv


def analyze_fridge_frost(image_input):
    rgb = _load_rgb(image_input)
    hsv = _to_hsv(rgb)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    frost_mask = (v > 0.75) & (s < 0.18)
    frost_fraction = frost_mask.mean()

    if frost_fraction > 0.30:
        verdict, severity = "Heavy frost buildup detected", "high"
        action = "Defrost recommended now — significant ice coverage is reducing cooling efficiency and increasing compressor runtime."
    elif frost_fraction > 0.12:
        verdict, severity = "Moderate frost buildup detected", "medium"
        action = "Defrost within the next few days — frost is starting to accumulate on interior surfaces."
    else:
        verdict, severity = "No significant frost detected", "none"
        action = "No action needed — interior surfaces look clear."

    return {"verdict": verdict, "severity": severity, "metric_name": "Frost-like pixel coverage",
            "metric_value": f"{frost_fraction*100:.1f}%", "action": action}


def analyze_ac_filter(image_input):
    rgb = _load_rgb(image_input)
    hsv = _to_hsv(rgb)
    v = hsv[..., 2]
    brightness = v.mean()
    contrast = v.std()
    dirt_score = (1 - brightness) * 0.6 + (1 - min(contrast * 4, 1)) * 0.4

    if dirt_score > 0.55:
        verdict, severity = "Filter appears significantly dirty", "high"
        action = "Clean or replace the filter — buildup this heavy can cut AC efficiency noticeably and increase energy use."
    elif dirt_score > 0.35:
        verdict, severity = "Filter shows moderate dust buildup", "medium"
        action = "Clean the filter soon — moderate dust is starting to restrict airflow."
    else:
        verdict, severity = "Filter looks clean", "none"
        action = "No action needed — mesh pattern and brightness look consistent with a clean filter."

    return {"verdict": verdict, "severity": severity, "metric_name": "Dirt score (brightness + texture loss)",
            "metric_value": f"{dirt_score*100:.1f}/100", "action": action}


def analyze_cooler_pad(image_input):
    rgb = _load_rgb(image_input)
    hsv = _to_hsv(rgb)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    scale_mask = (v > 0.70) & (s < 0.22)
    scale_fraction = scale_mask.mean()
    avg_saturation = s.mean()

    if scale_fraction > 0.25 or avg_saturation < 0.15:
        verdict, severity = "Pad appears dry / scale buildup detected", "high"
        action = "Check water supply and pump — a dry or heavily scaled pad wastes fan electricity for little cooling effect and can be an early dry-run symptom."
    elif scale_fraction > 0.10:
        verdict, severity = "Pad shows some mineral scale buildup", "medium"
        action = "Consider descaling or rinsing the pad — moderate buildup is starting to reduce cooling efficiency."
    else:
        verdict, severity = "Pad appears adequately wet, minimal scale", "none"
        action = "No action needed."

    return {"verdict": verdict, "severity": severity, "metric_name": "Scale-like pixel coverage",
            "metric_value": f"{scale_fraction*100:.1f}%", "action": action}


ANALYZERS = {
    "fridge": ("Fridge Interior — Frost Check", analyze_fridge_frost),
    "ac_filter": ("AC Filter — Dirt Check", analyze_ac_filter),
    "cooler_pad": ("Cooler Pad — Dryness/Scale Check", analyze_cooler_pad),
}
