# app.py
import os, io, time, json, base64, mimetypes, requests
from PIL import Image
import streamlit as st

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(page_title="Runway Text+Image → Video", page_icon="🎬", layout="wide")
st.title("🎬 Text-to-Video Generator (Runway API)")
st.caption("Use prompt-only or add images (logo/reference). Pick a model and generate your AI video.")

# =========================
# CONSTANTS
# =========================
API_BASE = "https://api.dev.runwayml.com"
API_VERSION = "2024-11-06"
ALLOWED_RATIOS = ["1280:720", "720:1280", "1104:832", "832:1104", "960:960", "1584:672"]

MODEL_META = {
    "gen4_turbo":  {"durations": [5,10], "credits_per_sec": 5, "note": "fastest & cheapest"},
    "gen4_aleph":  {"durations": [5,10], "credits_per_sec": 15, "note": "sharper than turbo"},
    "veo3":        {"durations": [4,6,8], "credits_per_sec": 40, "note": "high fidelity (prompt-only OK)"},
    "veo3.1":      {"durations": [4,6,8], "credits_per_sec": 40, "note": "latest fidelity"},
    "veo3.1_fast": {"durations": [4,6,8], "credits_per_sec": 20, "note": "balanced quality/speed"},
}

# =========================
# API KEY
# =========================
API_KEY = st.secrets.get("RUNWAY_API_KEY", os.getenv("RUNWAY_API_KEY", ""))
if not API_KEY:
    st.error("Missing API key. Add RUNWAY_API_KEY in Streamlit Cloud Secrets or .env (for local dev).")
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

    w, h = img.size
    curr = w/h
    if abs(curr - target_ratio) > 1e-3:
        if curr > target_ratio:
            target_h = int(round(w / target_ratio))
            canvas = Image.new("RGB", (w, target_h), pad_color)
            canvas.paste(img, (0, (target_h - h)//2))
            img = canvas
        else:
            target_w = int(round(h * target_ratio))
            canvas = Image.new("RGB", (target_w, h), pad_color)
            canvas.paste(img, ((target_w - w)//2, 0))
            img = canvas
    return img


def start_task(model: str, ratio: str, duration: int, prompt_text: str, prompt_images):
    """Switches endpoint dynamically: image_to_video vs text_to_video."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": API_VERSION,
    }

    use_images = len(prompt_images) > 0
    endpoint = "image_to_video" if use_images else "text_to_video"
    url = f"{API_BASE}/v1/{endpoint}"

    payload = {
        "model": model,
        "promptText": prompt_text,
        "ratio": ratio,
        "duration": duration,
        "seed": 123456789,
    }

    if use_images:
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
        "Prompt",
        value=("Ultra-realistic cinematic stadium celebration; natural lighting; dynamic camera pans; "
               "shallow depth of field; brand-consistent visuals; no real faces, alcohol, or politics."),
        height=140,
        help=("Describe the scene, lighting, motion, and tone. You can use this without images "
              "or upload 1–3 reference images (logo, person, or style cue).")
    )

    uploads = st.file_uploader(
        "(Optional) Upload reference images (1–3)",
        accept_multiple_files=True,
        type=["png","jpg","jpeg"],
        help=("Images are optional. The first acts as main reference; others as style cues. "
              "Leave empty for prompt-only generation.")
    )

with colB:
    model = st.selectbox(
        "Model",
        list(MODEL_META.keys()),
        index=2,
        help=("Choose a Runway model:\n"
              "• gen4_turbo — fast & cheap\n"
              "• gen4_aleph — sharper\n"
              "• veo3/3.1 — high fidelity (prompt-only OK)\n"
              "• veo3.1_fast — balanced quality/speed")
    )

    ratio = st.selectbox(
        "Aspect Ratio",
        ALLOWED_RATIOS,
        index=0,
        help=("Output frame shape (must match allowed ratios). "
              "Images are auto-padded to match selected ratio.")
    )

    allowed_durations = MODEL_META[model]["durations"]
    duration = st.select_slider(
        "Duration (sec)",
        options=allowed_durations,
        value=allowed_durations[-1],
        help=("Clip length allowed by chosen model (e.g., gen4: 5/10s, veo3.1: 4/6/8s). "
              "Longer = higher cost & render time.")
    )

    seed = st.number_input(
        "Seed (optional)",
        value=123456789,
        step=1,
        help=("Controls randomness. Same prompt + seed → identical result; "
              "change seed for variation.")
    )

    st.caption(f"~{MODEL_META[model]['credits_per_sec']} credits/sec × {duration}s ≈ cost estimate")

go = st.button("🚀 Generate Video", type="primary", use_container_width=True)

# =========================
# ACTION
# =========================
if go:
    target_ratio = ratio_to_float(ratio)
    data_uris = []

    if uploads:
        with st.status("Preprocessing images…"):
            for f in uploads:
                img = Image.open(f).convert("RGB")
                img = normalize_to_ratio_pad(img, target_ratio)
                max_px = 1024
                w, h = img.size
                scale = max(w, h) / max_px
                if scale > 1.0:
                    img = img.resize((int(w/scale), int(h/scale)), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=90)
                uri = file_to_data_uri(buf.getvalue(), "image/jpeg")
                data_uris.append(uri)
        st.info(f"{len(data_uris)} image(s) included as visual guidance.")
    else:
        st.info("No images uploaded — running prompt-only generation.")

    with st.status("Submitting task to Runway…"):
        resp = start_task(model, ratio, duration, prompt, data_uris)
        st.code(f"HTTP {resp.status_code}\n{resp.text[:500]}", language="json")

        if resp.status_code != 200:
            st.error("Task failed to start. Check response above and adjust ratio/duration/images/credits.")
            st.stop()

        task = resp.json()
        task_id = task.get("id") or task.get("task", {}).get("id")
        if not task_id:
            st.error("No task ID returned. Inspect logs above.")
            st.stop()

    with st.status("Generating video on Runway servers…"):
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "X-Runway-Version": API_VERSION,
        }
        t0 = time.time()
        while True:
            js = requests.get(f"{API_BASE}/v1/tasks/{task_id}", headers=headers, timeout=60).json()
            state = js.get("status") or js.get("state")
            if state in ("SUCCEEDED", "COMPLETED", "succeeded"):
                output = js.get("output") or js.get("result", {}).get("output") or []
                break
            if state in ("FAILED", "ERROR", "CANCELLED"):
                st.error(f"Generation failed:\n{json.dumps(js, indent=2)}")
                st.stop()
            elapsed = int(time.time() - t0)
            st.write(f"⏳ Generating… {elapsed}s elapsed")
            time.sleep(2)

    if not output:
        st.error("No output URL returned. Inspect logs above.")
        st.stop()

    video_url = output[0] if isinstance(output, list) else output
    st.subheader("✅ Result")
    st.video(video_url)

    try:
        bin_mp4 = requests.get(video_url, timeout=120).content
        st.download_button(
            "⬇️ Download MP4",
            data=bin_mp4,
            file_name=f"{model}_{ratio.replace(':','x')}_{duration}s.mp4",
            mime="video/mp4",
            use_container_width=True
        )
    except Exception:
        st.warning("Direct download may fail due to streaming response — use the video player’s save option.")

    st.info("To reach 16–20s, generate two 8–10s clips and stitch them together (ffmpeg or editor).")
