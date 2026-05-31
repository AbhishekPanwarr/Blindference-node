#!/usr/bin/env python3
"""Generate Blindference Node architecture diagram PNG."""

from PIL import Image, ImageDraw, ImageFont
import os

# Canvas
WIDTH, HEIGHT = 1600, 1200
BG = "#0f0f1a"
ORANGE = "#f97316"
CYAN = "#22d3ee"
PURPLE = "#a855f7"
WHITE = "#ffffff"
GREY = "#64748b"
DARK_BOX = "#16213e"

img = Image.new("RGB", (WIDTH, HEIGHT), BG)
draw = ImageDraw.Draw(img)

# Try to load a font, fallback to default
try:
    font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
    font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
except:
    font_large = ImageFont.load_default()
    font_medium = font_large
    font_small = font_large

def draw_rounded_rect(draw, xy, fill, outline, width, radius=10):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

def draw_text_centered(draw, text, xy, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cx, cy = (xy[0] + xy[2]) // 2, (xy[1] + xy[3]) // 2
    draw.text((cx - tw // 2, cy - th // 2), text, font=font, fill=fill)

def draw_arrow(draw, start, end, color, label=None, font=None):
    draw.line([start, end], fill=color, width=2)
    # Arrowhead
    x1, y1 = end
    x0, y0 = start
    dx, dy = x1 - x0, y1 - y0
    length = (dx**2 + dy**2) ** 0.5
    if length > 0:
        dx, dy = dx / length * 10, dy / length * 10
        px, py = -dy, dx
        draw.polygon([(x1, y1), (int(x1 - dx + px), int(y1 - dy + py)), (int(x1 - dx - px), int(y1 - dy - py))], fill=color)
    if label and font:
        mx, my = (start[0] + end[0]) // 2, (start[1] + end[1]) // 2
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([mx - tw // 2 - 4, my - th // 2 - 2, mx + tw // 2 + 4, my + th // 2 + 2], fill=BG, outline=BG)
        draw.text((mx - tw // 2, my - th // 2), label, font=font, fill=color)

# Title
draw.text((WIDTH // 2 - 300, 20), "Blindference Node Architecture", font=font_large, fill=ORANGE)
draw.text((WIDTH // 2 - 250, 55), "Decentralized Confidential AI Execution on Arbitrum Sepolia", font=font_medium, fill=GREY)

# 1. User / Frontend (Top Left)
user_box = (50, 120, 280, 280)
draw_rounded_rect(draw, user_box, DARK_BOX, CYAN, 2)
draw.text((130, 135), "👤 User", font=font_medium, fill=CYAN)
draw.text((70, 170), "• MetaMask Wallet", font=font_small, fill=WHITE)
draw.text((70, 195), "• Blindference App", font=font_small, fill=WHITE)
draw.text((70, 220), "• Encrypted Prompt", font=font_small, fill=WHITE)
draw.text((70, 245), "• CoFHE Sharing Permit", font=font_small, fill=WHITE)

# 2. ICL (Top Center)
icl_box = (380, 120, 680, 280)
draw_rounded_rect(draw, icl_box, DARK_BOX, PURPLE, 2)
draw.text((490, 135), "🔷 ICL Coordinator", font=font_medium, fill=PURPLE)
draw.text((400, 170), "• Receives encrypted request", font=font_small, fill=WHITE)
draw.text((400, 195), "• Selects quorum (1L + 2V)", font=font_small, fill=WHITE)
draw.text((400, 220), "• Dispatches to nodes", font=font_small, fill=WHITE)
draw.text((400, 245), "• icl.blindference.xyz", font=font_small, fill=GREY)

# 3. Node (Center - Hero)
node_box = (300, 350, 1050, 750)
draw_rounded_rect(draw, node_box, "#1a1a2e", ORANGE, 4)
draw.text((620, 365), "🟠 Blindference Node", font=font_large, fill=ORANGE)
draw.text((610, 400), "Your Confidential Inference Worker", font=font_medium, fill=GREY)

# Node internal boxes
# Heartbeat
hb_box = (330, 450, 580, 540)
draw_rounded_rect(draw, hb_box, DARK_BOX, ORANGE, 1)
draw.text((370, 465), "💓 Heartbeat", font=font_medium, fill=ORANGE)
draw.text((345, 495), "POST /internal/heartbeat", font=font_small, fill=WHITE)
draw.text((345, 515), "Every 60 seconds", font=font_small, fill=GREY)

# Poller
poll_box = (620, 450, 870, 540)
draw_rounded_rect(draw, poll_box, DARK_BOX, ORANGE, 1)
draw.text((655, 465), "📡 Poller", font=font_medium, fill=ORANGE)
draw.text((635, 495), "GET /internal/assignments", font=font_small, fill=WHITE)
draw.text((635, 515), "Every 5 seconds", font=font_small, fill=GREY)

# CoFHE Bridge
cofhe_box = (330, 570, 580, 660)
draw_rounded_rect(draw, cofhe_box, DARK_BOX, ORANGE, 1)
draw.text((370, 585), "🔐 CoFHE Bridge", font=font_medium, fill=ORANGE)
draw.text((345, 615), "decryptForView()", font=font_small, fill=WHITE)
draw.text((345, 635), "Node.js subprocess", font=font_small, fill=GREY)

# Inference Worker
inf_box = (620, 570, 870, 660)
draw_rounded_rect(draw, inf_box, DARK_BOX, ORANGE, 1)
draw.text((650, 585), "🤖 Inference Worker", font=font_medium, fill=ORANGE)
draw.text((635, 615), "Groq / Gemini / vLLM", font=font_small, fill=WHITE)
draw.text((635, 635), "Pluggable backends", font=font_small, fill=GREY)

# IPFS Uploader
ipfs_box = (475, 690, 725, 740)
draw_rounded_rect(draw, ipfs_box, DARK_BOX, ORANGE, 1)
draw.text((520, 705), "📤 IPFS Upload — pinFileToIPFS", font=font_medium, fill=ORANGE)

# 4. External Services (Right)
ext_box = (1100, 120, 1550, 750)
draw_rounded_rect(draw, ext_box, DARK_BOX, CYAN, 2)
draw.text((1230, 135), "☁️ External Services", font=font_medium, fill=CYAN)

# CoFHE Network
draw_rounded_rect(draw, (1130, 180, 1520, 280), DARK_BOX, CYAN, 1)
draw.text((1200, 195), "🔐 CoFHE Network", font=font_medium, fill=CYAN)
draw.text((1145, 225), "Threshold FHE Decryption", font=font_small, fill=WHITE)
draw.text((1145, 245), "ACL-protected handles", font=font_small, fill=GREY)

# IPFS Gateway
draw_rounded_rect(draw, (1130, 310, 1520, 410), DARK_BOX, CYAN, 1)
draw.text((1220, 325), "📦 IPFS Gateway", font=font_medium, fill=CYAN)
draw.text((1145, 355), "Pinata / ipfs.io", font=font_small, fill=WHITE)
draw.text((1145, 375), "Encrypted prompt & output", font=font_small, fill=GREY)

# LLM Provider
draw_rounded_rect(draw, (1130, 440, 1520, 540), DARK_BOX, CYAN, 1)
draw.text((1210, 455), "🧠 LLM Provider", font=font_medium, fill=CYAN)
draw.text((1145, 485), "Groq / Gemini / Local vLLM", font=font_small, fill=WHITE)
draw.text((1145, 505), "Pluggable backend registry", font=font_small, fill=GREY)

# Arbitrum Sepolia
draw_rounded_rect(draw, (1130, 570, 1520, 670), DARK_BOX, CYAN, 1)
draw.text((1200, 585), "⛓ Arbitrum Sepolia", font=font_medium, fill=CYAN)
draw.text((1145, 615), "On-chain Registry & Staking", font=font_small, fill=WHITE)
draw.text((1145, 635), "Auto-payout rewards", font=font_small, fill=GREY)

# 5. Quorum Consensus (Bottom Center)
quorum_box = (300, 800, 1050, 920)
draw_rounded_rect(draw, quorum_box, DARK_BOX, CYAN, 2)
draw.text((610, 815), "✅ Quorum Consensus", font=font_medium, fill=CYAN)

# Leader
l_box = (350, 850, 550, 900)
draw_rounded_rect(draw, l_box, "#1a1a2e", ORANGE, 2)
draw.text((410, 865), "👑 Leader (60%)", font=font_medium, fill=ORANGE)

# Verifier 1
v1_box = (570, 850, 770, 900)
draw_rounded_rect(draw, v1_box, "#1a1a2e", CYAN, 1)
draw.text((620, 865), "🔍 Verifier 1 (20%)", font=font_medium, fill=CYAN)

# Verifier 2
v2_box = (790, 850, 990, 900)
draw_rounded_rect(draw, v2_box, "#1a1a2e", CYAN, 1)
draw.text((840, 865), "🔍 Verifier 2 (20%)", font=font_medium, fill=CYAN)

# 6. Dashboard (Bottom Right)
dash_box = (1100, 800, 1550, 920)
draw_rounded_rect(draw, dash_box, DARK_BOX, ORANGE, 2)
draw.text((1220, 815), "📊 Dashboard", font=font_medium, fill=ORANGE)
draw.text((1130, 850), "www.blindference.xyz", font=font_medium, fill=WHITE)
draw.text((1130, 880), "Track earnings, uptime, tier", font=font_small, fill=GREY)

# Arrows
# User -> ICL
draw_arrow(draw, (280, 200), (380, 200), CYAN, "1. Submit", font_small)
# ICL -> Node
draw_arrow(draw, (680, 200), (680, 350), PURPLE, "2. Dispatch", font_small)
# Node -> CoFHE
draw_arrow(draw, (1050, 600), (1130, 230), ORANGE, "3b. Decrypt", font_small)
# Node -> IPFS
draw_arrow(draw, (1050, 715), (1130, 360), ORANGE, "3c. Download / 3e. Upload", font_small)
# Node -> LLM
draw_arrow(draw, (1050, 615), (1130, 490), ORANGE, "3d. Inference", font_small)
# Node -> Chain
draw_arrow(draw, (1050, 715), (1130, 620), ORANGE, "3f. Heartbeat", font_small)
# Node -> Quorum
draw_arrow(draw, (675, 750), (675, 800), ORANGE, "4. Submit hash", font_small)
# Quorum -> ICL (implied)
draw_arrow(draw, (550, 800), (530, 280), CYAN, "5. Consensus", font_small)
# Chain -> Dashboard
draw_arrow(draw, (1520, 620), (1325, 800), ORANGE, "6. Rewards", font_small)

# Legend
legend_y = 980
draw.text((50, legend_y), "Legend:", font=font_medium, fill=WHITE)
draw.rectangle((150, legend_y, 170, legend_y + 15), fill=ORANGE)
draw.text((180, legend_y), "Node Process", font=font_small, fill=WHITE)
draw.rectangle((300, legend_y, 320, legend_y + 15), fill=CYAN)
draw.text((330, legend_y), "External / User", font=font_small, fill=WHITE)
draw.rectangle((470, legend_y, 490, legend_y + 15), fill=PURPLE)
draw.text((500, legend_y), "ICL Coordination", font=font_small, fill=WHITE)

# Save
out_path = "/home/abhieren/Drive/Projects/Buildathon/Fhenix/Blindference-node/docs/assets/architecture.png"
img.save(out_path, "PNG")
print(f"Generated: {out_path} ({WIDTH}x{HEIGHT})")
