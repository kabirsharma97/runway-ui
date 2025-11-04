# app.py
# 🎬 RunwayML Text + Image → Video Generator (Stakeholder Demo Version)
# Author: Kabir Sharma | Streamlit UI for Sky AI Creative Automation MVP

import os, io, time, json, base64, mimetypes, requests
from PIL import Image
import streamlit as st

# ---------- CONFIG ----------
API_BASE = "https://api.dev.runwayml.com"
API_VERSION = "2024-11-06"
ASPECT_RATIOS = ["1280:720", "720:1280"]

MODEL_META = {
    "gen4_turbo":  {"durations": [5, 10], "credits_per_sec": 5, "endpoint": "image_to_video"},
    "veo3":        {"durations": [4, 6, 8], "credits_per_sec": 40, "endpoint": "image_to_video"},
    "veo3.1":      {"durations": [4, 6, 8], "credits_per_sec": 40, "endpoint": "image_to_video"},
    "veo3.1_fast": {"durations": [4, 6, 8], "credits_per_sec": 20, "endpoint": "image_to_video"},
}

# ---------- SECRET ----------
API_KEY = st.secrets.get("RUNWAY_API_KEY", os.getenv("RUNWAY_API_KEY", ""))
if not API_KEY:
    st.error("❌ Missing API key. Please add RUNWAY_API_KEY in Streamlit Secrets.")
    st.stop()

# ---------- HELPER FUNCTIONS ----------
def file_to_data_uri(file_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def ratio_to_float(ratio_str: str) -> float:
    w, h = ratio_str.split(":")
    return int(w) / int(h)

def normalize_to_ratio_pad(img: Image.Image, target_ratio: float, pad_color=(255,255,255)) -> Image.Image:
    w, h = img.size
    r = w / h
    if r > 2.0:
        new_h = int(round(w / 2.0))
        canvas = Image.new("RGB", (w, new_h), pad_color)
        canvas.paste(img, (0, (new_h - h)//2))
        img = canvas
    elif r < 0.5:
        new_w = int(round(h * 0.5))
        canvas = Image.new("RGB", (new_w, h), pad_color)
        canvas.paste(img, ((new_w - w)//2, 0))
        img = canvas
    return img

def start_task(model: str, ratio: str, duration: int, prompt_text: str, prompt_images):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": API_VERSION,
    }
    payload = {
        "model": model,
        "promptText": prompt_text,
        "ratio": ratio,
        "duration": duration
    }
    if prompt_images:
        if len(prompt_images) == 1:
            payload["promptImage"] = prompt_images[0]
        else:
            arr = [{"uri": prompt_images[0], "position": "first"}]
            for uri in prompt_images[1:]:
                arr.append({"uri": uri, "position": "last"})
            payload["promptImage"] = arr

    resp = requests.post(f"{API_BASE}/v1/image_to_video", headers=headers, json=payload, timeout=60)
    return resp

# ---------- UI SETUP ----------
st.set_page_config(page_title="🎬 Text-to-Video Generator", page_icon="🎬", layout="wide")

st.markdown(
    """
    <h1 style='color:#0078D7;'>🎬 Text + Image → Video Generator</h1>
    <p style='font-size:16px;color:#555;'>
    Generate AI-powered marketing videos using RunwayML diffusion models.<br>
    Choose a model, enter a prompt, and optionally add reference images (logos, characters).
    </p>
    <hr style="margin-top:10px;margin-bottom:20px;">
    """,
    unsafe_allow_html=True
)

# ---------- MAIN INPUTS ----------
col1, col2 = st.columns([2, 1], gap="large")

with col1:
    st.markdown("### ✏️ Prompt")
    prompt = st.text_area(
        "Describe your scene (e.g., stadium celebration, product demo, cinematic tone)",
        value="Ultra-realistic cinematic celebration in a packed stadium at night. "
              "Bright lights, confetti, and joyful energy. Include Sky Sports branding subtly.",
        height=140
    )

    st.markdown("### 🖼️ Upload Reference Images (Optional)")
    uploads = st.file_uploader(
        "Upload 1–3 reference images (fan, logo, product, etc.)",
        accept_multiple_files=True,
        type=["png", "jpg", "jpeg"]
    )

with col2:
    st.markdown("### ⚙️ Model Configuration")
    model = st.selectbox("Model ℹ️", list(MODEL_META.keys()), index=0, help="""
        **gen4_turbo:** Fast, image-guided video generation.\n
        **veo3 / veo3.1:** Text-only cinematic video generation (no image required).\n
        **veo3.1_fast:** Faster version of veo3.1 for demos.
    """)
    ratio = st.selectbox("Aspect Ratio ℹ️", ASPECT_RATIOS, index=0, help="Choose 16:9 (landscape) or 9:16 (portrait) output format.")
    duration = st.select_slider("Duration (seconds) ℹ️",
        options=MODEL_META[model]["durations"], value=MODEL_META[model]["durations"][-1],
        help="Shorter = faster, fewer credits. Longer = smoother motion, more realism."
    )
    st.caption(f"💰 Estimated cost: ~{MODEL_META[model]['credits_per_sec']} credits/sec × {duration}s")

generate = st.button("🚀 Generate Video", type="primary", use_container_width=True)

# ---------- GENERATION ----------
if generate:
    # Validation
    if model == "gen4_turbo" and not uploads:
        st.warning("⚠️ gen4_turbo requires at least one reference image.")
        st.stop()

    # Preprocess images
    prompt_images = []
    if uploads:
        target_ratio = ratio_to_float(ratio)
        with st.spinner("🪄 Preprocessing images..."):
            for f in uploads:
                mime = mimetypes.guess_type(f.name)[0] or "image/jpeg"
                img = Image.open(f).convert("RGB")
                img = normalize_to_ratio_pad(img, target_ratio)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                uri = file_to_data_uri(buf.getvalue(), "image/png")
                prompt_images.append(uri)

    with st.spinner("🚀 Submitting request to Runway..."):
        resp = start_task(model=model, ratio=ratio, duration=duration, prompt_text=prompt, prompt_images=prompt_images)
        st.code(f"HTTP {resp.status_code}\n{resp.text[:400]}", language="json")

    if resp.status_code != 200:
        st.error("❌ Failed to start task. Please review your ratio/duration/credits/images.")
        st.stop()

    task_id = resp.json().get("id")
    st.success(f"✅ Task started successfully (ID: {task_id})")

    progress = st.progress(0, text="⏳ Generating video… this may take a few minutes.")
    t0 = time.time()
    video_url = None
    while True:
        elapsed = int(time.time() - t0)
        progress.progress(min(100, (elapsed % 20) * 5), text="🎥 Rendering in progress…")
        poll = requests.get(f"{API_BASE}/v1/tasks/{task_id}",
                            headers={"Authorization": f"Bearer {API_KEY}", "X-Runway-Version": API_VERSION})
        js = poll.json()
        state = js.get("status") or js.get("state")
        if state in ("SUCCEEDED", "COMPLETED", "succeeded"):
            output = js.get("output") or js.get("result", {}).get("output") or []
            if output:
                video_url = output[0]
            break
        if state in ("FAILED", "ERROR", "CANCELLED"):
            st.error(f"❌ Task failed: {json.dumps(js, indent=2)}")
            st.stop()
        time.sleep(2)

    progress.empty()

    if video_url:
        st.video(video_url)
        st.download_button(
            "⬇️ Download MP4",
            data=requests.get(video_url).content,
            file_name=f"{model}_{ratio.replace(':','x')}_{duration}s.mp4",
            mime="video/mp4"
        )
        st.success("✅ Video generated successfully!")

# ---------- GUIDELINES ----------
st.markdown("---")
st.markdown("## 📘 Model Usage Guidelines")
st.markdown("""
| Model | Image Requirement | Recommended Use Case | Notes |
|--------|------------------|-----------------|--------|
| **gen4_turbo** | ✅ Required | Logo/character-driven shots | Fast, budget-friendly generation. |
| **veo3** | 🟡 Optional | Cinematic realism | Best for text-only creative ideation. |
| **veo3.1** | 🟡 Optional | High-quality brand visuals | Slower but highly consistent. |
| **veo3.1_fast** | 🟢 Optional | Rapid prototyping / Demos | Slightly reduced quality but faster. |
""", unsafe_allow_html=True)

st.info("""
💡 *Prompting Tips:*
- Keep prompts ≤ 800 characters.
- Describe visual tone (lighting, mood, camera motion).
- Avoid unsafe terms (violence, alcohol, politics, real faces).
""")

# ---------- NEXT VERSION ROADMAP ----------
# ---------- NEXT VERSION ROADMAP ----------
st.markdown("---")
st.markdown("## 🚀 Next Version (v2.0) – Planned Enhancements")

st.markdown("""
| Use case | Description | Status |
|---|---|---|
| **Video-to-Video Transformation** | Generate ad variants directly from a master campaign video — enabling quick localization and reuse of existing footage. | **In Progress** |
| **AI Product Advertisement Video Generation** | Automatically create short, on-brand product advertisement videos from any product webpage, designed to boost engagement and drive traffic back to the website. | **Exploration phase** |
""")
st.caption("🔧 These will form part of Phase 2 roadmap for AI Creative Automation initiative.")
