# app.py
import os, io, time, json, base64, mimetypes, requests
from PIL import Image
import streamlit as st

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(page_title="Runway Text+Image → Video", page_icon="🎬", layout="wide")

st.title("🎬 Text-to-Video Generator")
st.caption("Enter a prompt, upload one or more images (logo, reference), pick a model, and generate.")

# =========================
# CONSTANTS
# =========================
API_BASE = "https://api.dev.runwayml.com"
API_VERSION = "2024-11-06"  # required header version
ALLOWED_RATIOS = ["1280:720","720:1280","1104:832","832:1104","960:960","1584:672"]

# Model constraints (credits/sec shown for info; durations enforced in UI)
MODEL_META = {
    "gen4_turbo":  {"durations": [5,10],  "credits_per_sec": 5,  "endpoint": "image_to_video", "note":"fastest + cheapest"},
    "gen4_aleph":  {"durations":[5,10],   "credits_per_sec": 15, "endpoint": "image_to_video", "note":"sharper than turbo"},
    "veo3":        {"durations":[4,6,8],  "credits_per_sec": 40, "endpoint": "image_to_video", "note":"higher fidelity"},
    "veo3.1":      {"durations":[4,6,8],  "credits_per_sec": 40, "endpoint": "image_to_video", "note":"newer fidelity"},
    "veo3.1_fast": {"durations":[4,6,8],  "credits_per_sec": 20, "endpoint": "image_to_video", "note":"balanced speed/quality"},
}

# Secrets (prefer Streamlit Cloud Secrets; fallback to env var)
API_KEY = st.secrets.get("RUNWAY_API_KEY", os.getenv("RUNWAY_API_KEY", ""))

if not API_KEY:
    st.error("Missing API key. Add RUNWAY_API_KEY in `.streamlit/secrets.toml` or environment.")
    st.stop()

# =========================
# HELPERS
# =========================
def ratio_to_float(ratio_str: str) -> float:
    w, h = ratio_str.split(":")
    return int(w) / int(h)

def file_to_data_uri(file_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def normalize_to_ratio_pad(img: Image.Image, target_ratio: float, pad_color=(255,255,255)) -> Image.Image:
    """
    Step 1: Ensure input aspect within [0.5, 2.0] via padding (Runway input requirement).
    Step 2: Pad to the exact target output ratio (no crop).
    """
    w, h = img.size
    r = w / h
    # Clamp to [0.5, 2.0]
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

    # Pad to exact target ratio
    w, h = img.size
    curr = w/h
    if abs(curr - target_ratio) > 1e-3:
        if curr > target_ratio:  # need more height
            target_h = int(round(w / target_ratio))
            canvas = Image.new("RGB", (w, target_h), pad_color)
            canvas.paste(img, (0, (target_h - h)//2))
            img = canvas
        else:                    # need more width
            target_w = int(round(h * target_ratio))
            canvas = Image.new("RGB", (target_w, h), pad_color)
            canvas.paste(img, ((target_w - w)//2, 0))
            img = canvas
    return img

def start_task(model: str, ratio: str, duration: int, prompt_text: str, prompt_images):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": API_VERSION,
    }
    url = f"{API_BASE}/v1/image_to_video"
    payload = {
        "model": model,
        "promptText": prompt_text,
        "ratio": ratio,
        "duration": duration,
        "seed": 123456789  # deterministic; change for variation
    }
    # promptImage can be a single string or an array of {uri, position}
    if len(prompt_images) == 1:
        payload["promptImage"] = prompt_images[0]
    else:
        arr = [{"uri": prompt_images[0], "position": "first"}]
        for uri in prompt_images[1:]:
            arr.append({"uri": uri, "position": "last"})
        payload["promptImage"] = arr

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    return resp

# =========================
# UI
# =========================
colA, colB = st.columns([2,1], gap="large")

with colA:
    prompt = st.text_area(
        label="Prompt",
        value=(
            "Ultra-realistic cinematic stadium celebration; high temporal coherence; "
            "natural lighting; dynamic but stable camera pans; shallow depth of field; "
            "brand-consistent with provided logo; no real faces, alcohol, or politics."
        ),
        height=140,
        help=(
            "Describe the shot, story beats, camera/motion, lighting, mood, and constraints.\n"
            "Mention brand cues (logo/color) and safety limits. Uploaded images act as visual guidance."
        ),
        placeholder="Describe the scene you want to generate…"
    )

    uploads = st.file_uploader(
        label="Upload reference images (1–3): fan photo, brand logo, etc.",
        accept_multiple_files=True,
        type=["png","jpg","jpeg"],
        help=(
            "1–3 PNG/JPG images. The first image is treated as the primary reference; "
            "others act as auxiliary style/branding cues. Large images are padded to the selected aspect."
        )
    )

with colB:
    model = st.selectbox(
        "Model",
        list(MODEL_META.keys()),
        index=0,
        help=(
            "Choose a Runway model:\n"
            "• gen4_turbo — fastest & cheapest\n"
            "• gen4_aleph — sharper than turbo\n"
            "• veo3 / veo3.1 — higher fidelity\n"
            "• veo3.1_fast — balanced speed/quality"
        )
    )

    ratio = st.selectbox(
        "Aspect Ratio",
        ALLOWED_RATIOS,
        index=0,
        help=(
            "Output frame shape. Must be one of the allowed ratios.\n"
            "Uploaded images are auto-padded to match:\n"
            "• 1280:720 (landscape) • 720:1280 (vertical) • 960:960 (square)"
        )
    )

    allowed_durations = MODEL_META[model]["durations"]
    duration = st.select_slider(
        "Duration (sec)",
        options=allowed_durations,
        value=allowed_durations[-1],
        help=(
            "Clip length allowed by the chosen model (e.g., gen4: 5/10s, veo3.1: 4/6/8s).\n"
            "Longer = more credits & render time."
        )
    )

    seed = st.number_input(
        "Seed (optional)",
        value=123456789,
        step=1,
        help=(
            "Controls randomness. Same prompt + same seed → repeatable results.\n"
            "Change the seed to get a different take."
        )
    )

    st.caption(f"Cost hint: ~{MODEL_META[model]['credits_per_sec']} credits/sec × {duration}s")

st.caption("Click **Generate** to submit your prompt and images to Runway’s servers. Rendering happens remotely.")
go = st.button("🚀 Generate Video", type="primary", use_container_width=True)

# =========================
# ACTION
# =========================
if go:
    if not uploads:
        st.warning("Please upload at least one image (logo, reference, or still).")
        st.stop()

    target_ratio = ratio_to_float(ratio)
    data_uris = []
    too_big = False

    # Preprocess images → normalize → downscale → JPEG (to avoid blob deletion) → Data URI
    with st.status("Preprocessing images…", expanded=False) as s:
        for f in uploads:
            mime_guess = mimetypes.guess_type(f.name)[0] or "image/jpeg"
            img = Image.open(f).convert("RGB")

            # Normalize aspect to be valid & match target ratio
            img = normalize_to_ratio_pad(img, target_ratio=target_ratio, pad_color=(255,255,255))

            # Gentle downscale to keep Data URI small (reduce blob failures)
            max_px = 1024  # smaller than 1536 to be extra safe
            w, h = img.size
            scale = max(w, h) / max_px
            if scale > 1.0:
                img = img.resize((int(w/scale), int(h/scale)), Image.LANCZOS)

            # Encode as JPEG (smaller than PNG)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            file_bytes = buf.getvalue()
            if len(file_bytes) > 5 * 1024 * 1024:  # ~5MB
                too_big = True

            uri = file_to_data_uri(file_bytes, "image/jpeg")
            data_uris.append(uri)
        s.update(label="Images ready.", state="complete")

    if too_big:
        st.warning("One or more images are still large (>5MB after compression). Consider uploading smaller images.")

    # Start task
    with st.status("Submitting task to Runway…", expanded=False) as s:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "X-Runway-Version": API_VERSION,
        }
        try:
            resp = start_task(model=model, ratio=ratio, duration=duration, prompt_text=prompt, prompt_images=data_uris)
        except Exception as e:
            st.error(f"Request failed: {e}")
            st.stop()

        st.code(f"HTTP {resp.status_code}\n{resp.text[:500]}", language="json")

        if resp.status_code != 200:
            # Friendly guidance for common cases
            txt = resp.text
            if "not enough credits" in txt.lower():
                st.error("Runway says you do not have enough credits for this run. Try a shorter duration or cheaper model.")
            elif "ratio" in txt.lower():
                st.error("The selected aspect ratio is not allowed. Pick one from the dropdown only.")
            else:
                st.error("Task failed to start. Adjust ratio/duration/credits/images and retry.")
            st.stop()

        task = resp.json()
        task_id = task.get("id") or task.get("task",{}).get("id")
        if not task_id:
            st.error("No task id returned. Inspect the response above.")
            st.stop()
        s.update(label=f"Task started: {task_id}", state="complete")

    # Poll
    with st.status("Generating on Runway servers…", expanded=False) as s:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "X-Runway-Version": API_VERSION,
        }
        t0 = time.time()
        while True:
            js = requests.get(f"{API_BASE}/v1/tasks/{task_id}", headers=headers, timeout=60).json()
            state = js.get("status") or js.get("state")
            if state in ("SUCCEEDED","COMPLETED","succeeded"):
                output = js.get("output") or js.get("result",{}).get("output") or []
                break
            if state in ("FAILED","ERROR","CANCELLED"):
                # Show useful details from server
                st.error(f"Generation failed:\n{json.dumps(js, indent=2)}")
                # Common helpful tips:
                st.info("Tips: Use smaller JPEGs, shorter duration, allowed ratio, and neutralize brand/team names if moderation flags.")
                st.stop()
            elapsed = int(time.time() - t0)
            s.update(label=f"Generating… {elapsed}s", state="running")
            time.sleep(2)
        s.update(label="Generation complete.", state="complete")

    # Output card
    if not output:
        st.error("No output URL returned. Inspect logs above.")
        st.stop()

    video_url = output[0] if isinstance(output, list) else output
    st.subheader("✅ Result")
    st.video(video_url)

    # Download
    try:
        bin_mp4 = requests.get(video_url, timeout=120).content
        st.download_button(
            "⬇️ Download MP4",
            data=bin_mp4,
            file_name=f"{model}_{ratio.replace(':','x')}_{duration}s.mp4",
            mime="video/mp4",
            use_container_width=True
        )
    except Exception as e:
        st.warning(f"Direct download failed (served as streaming only). You can still save from the player: {e}")

    st.info("Tip: To reach 16–20s, generate two 8–10s clips and stitch in an editor (or with ffmpeg).")
