"""Two diagrams for the system guide, drawn with Pillow."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

OUT = Path(__file__).parent
try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)
    BOLD = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 24)
    SMALL = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 18)
except OSError:
    FONT = BOLD = SMALL = ImageFont.load_default()

INK = (30, 34, 40)
MUTED = (100, 106, 115)
BOX = {"tablet": (222, 236, 252), "robot": (232, 240, 232), "backend": (252, 236, 222),
       "console": (240, 232, 250), "db": (236, 236, 236), "model": (252, 246, 220)}
EDGE = (70, 76, 86)


def box(d, xy, title, lines, fill, title_font=BOLD):
    x0, y0, x1, y1 = xy
    d.rounded_rectangle(xy, radius=14, fill=fill, outline=EDGE, width=2)
    d.text((x0 + 16, y0 + 12), title, font=title_font, fill=INK)
    y = y0 + 48
    for line in lines:
        d.text((x0 + 16, y), line, font=SMALL, fill=MUTED)
        y += 24


def arrow(d, a, b, label=None, color=EDGE):
    d.line([a, b], fill=color, width=3)
    import math
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (-0.5, 0.5):
        d.line([b, (b[0] - 16 * math.cos(ang + s), b[1] - 16 * math.sin(ang + s))], fill=color, width=3)
    if label:
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        w = d.textlength(label, font=SMALL)
        d.rectangle([mx - w / 2 - 6, my - 14, mx + w / 2 + 6, my + 12], fill=(255, 255, 255))
        d.text((mx - w / 2, my - 12), label, font=SMALL, fill=MUTED)


def architecture():
    W, H = 1500, 880
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    box(d, (60, 60, 440, 290), "Pepper robot", ["Speaks the prompt and the feedback", "Celebration animations", "Holds the tablet", "(QiSDK, via the tablet app)"], BOX["robot"])
    box(d, (60, 340, 440, 620), "Tablet app (Android)", ["Study plan, sessions, questionnaires", "Endpointed 16 kHz recording", "Plays the stored model audio", "Offline queue for assessments"], BOX["tablet"])
    box(d, (560, 200, 940, 500), "Backend (FastAPI)", ["/study: sessions, items, answers, plan", "/pronunciation: score an attempt", "/authoring, /ratings, /measures", "Scoring pipeline (below)"], BOX["backend"])
    box(d, (1060, 60, 1440, 290), "Research console (web)", ["Participants and group balance", "Stimulus sets and model audio", "Dashboard", "Blind rating and the audit"], BOX["console"])
    box(d, (1060, 340, 1440, 620), "PostgreSQL", ["participants, sessions, attempts", "items and categories", "questionnaires, notes", "rating sets and ratings"], BOX["db"])
    box(d, (560, 560, 940, 760), "Models and resources (on disk)", ["wav2vec2 phone recogniser", "BEEP + CMUdict lexicon, Kenyan rules", "MD layer (Speechocean762)", "faster-whisper base.en"], BOX["model"])
    arrow(d, (440, 480), (560, 400), "HTTPS, token")
    arrow(d, (250, 340), (250, 290), "QiSDK")
    arrow(d, (940, 350), (1060, 440), "SQLAlchemy")
    arrow(d, (1060, 200), (940, 300), "HTTPS, token")
    arrow(d, (750, 560), (750, 500))
    d.text((60, 790), "Audio files stay on the server: study_audio/<session>/<item>_attempt<n>.wav and stimulus_audio/<item>.wav", font=SMALL, fill=MUTED)
    d.text((60, 820), "Only the attempt's verdict and feedback text go back to the tablet; the answer key for choice items never leaves the server.", font=SMALL, fill=MUTED)
    im.save(OUT / "architecture.png")


def pipeline():
    W, H = 1500, 560
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    stages = [
        ("1 Lexicon", ["target word to phones", "BEEP (British) first,", "CMUdict + GB rules,", "then g2p; variants kept"]),
        ("2 Trim + quality", ["silence trimmed", "peak, loudness, clipping", "too short / long flagged"]),
        ("3 Acoustic model", ["wav2vec2 phone CTC", "frame posteriors over", "39 phones + blank"]),
        ("4 Forced alignment", ["each variant aligned", "best one kept; per-phone", "GOP score, MD layer"]),
        ("5 Free decode", ["what the model heard,", "phone by phone, aligned", "to the expected phones"]),
        ("6 Verdict", ["worst-2 aggregate vs 0.60", "corroborated errors", "focus-phone rule"]),
    ]
    x = 40
    w = 225
    for i, (title, lines) in enumerate(stages):
        box(d, (x, 60, x + w, 260), title, lines, BOX["backend"] if i < 5 else BOX["model"], title_font=FONT)
        if i < len(stages) - 1:
            arrow(d, (x + w, 160), (x + w + 15, 160))
        x += w + 15
    box(d, (820, 320, 1460, 520), "Safety net: server ASR (Whisper)", ["Consulted only when the verdict is not correct, or a target phone is weak.", "A transcript containing the word can rescue a verdict, never worsen it,", "except over a target-feature phone, where it may neither rescue nor,", "when the phone was weak and the word was not heard, let it pass."], BOX["model"], title_font=FONT)
    box(d, (40, 320, 640, 520), "Output stored with every attempt", ["verdict, verdict_score, confidence, per-phone scores, diagnoses,", "expected and observed phones, transcript, audio quality,", "feedback text the robot spoke, device timestamps,", "pipeline_version, config_hash, model_id (reproducibility)"], BOX["db"], title_font=FONT)
    arrow(d, (1350, 260), (1350, 320))
    arrow(d, (820, 440), (640, 440))
    d.text((665, 400), "final verdict", font=SMALL, fill=MUTED)
    im.save(OUT / "pipeline.png")


architecture()
pipeline()
print("diagrams written")
