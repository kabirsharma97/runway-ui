import os, io, time, json, base64, mimetypes, requests
from PIL import Image
import streamlit as st

# ---------- Config ----------
API_BASE = "https://api.dev.runwayml.com"
API_VERSION = "2024-11-06"  # required header
ALLOWED_RATIOS = ["1280:720","720:1280","1104:832","832:1104","960:960","1584:672"]
# Model constraints (credits/sec just for info; durations are enforced in UI)
MODEL_META = {
    "gen4_turbo":  {"durations": [5,10],   "credits_per_sec": 5,  "endpoint": "image_to_video"},
    "gen4_aleph":  {"durations": [5,10],   "credits_per_sec": 15, "endpoint": "image_to_video"},
    "veo3":        {"durations": [4,6,8],  "credits_per_sec": 40, "endpoint": "image_to_video"},
    "veo3.1":      {"durations": [4,6,8],  "credits_per_sec": 40, "endpoint": "image_to_video"},
    "veo3.1_fast": {"durations": [4,6,8],  "credits_per_sec": 20, "endpoint": "image_to_video"},
}

# ---------- Secrets ----------
# Prefer Streamlit Cloud Secrets; fallback to env var for local dev
API_KEY = st.secrets.get("RUNWAY_API_KEY", os.getenv("RUNWAY_API_KEY", ""))

# ---------- Helpers ----------
def file_to_data_uri(file_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def normalize_to_ratio_pad(img: Image.Image, target_ratio: float, pad_color=(255,255,255)) -> Image.Image:
    # Ensure input ratio in [0.5, 2.0], then pad to exact target_ratio (no crop)
    w, h = img.size
    r = w / h
    if r > 2.0:
        # pad height
        new_h = int(round(w / 2.0))
        canvas = Image.new("RGB", (w, new_h), pad_color)
        canvas.paste(img, (0, (new_h - h)//2))
        img = canvas
    elif r < 0.5:
        # pad width
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

def ratio_to_float(ratio_str: str) -> float:
    w, h = ratio_str.split(":")
    return int(w) / int(h)

def start_task(model: str, ratio: str, duration: int, prompt_text: str, prompt_images):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": API_VERSION,
    }
    endpoint = "image_to_video"  # for all models in our list
    url = f"{API_BASE}/v1/{endpoint}"

    # promptImage can be a single string or an array of {uri, position}. We'll use array if >1.
    payload = {
        "model": model,
        "promptText": prompt_text,
        "ratio": ratio,
        "duration": duration,
        "seed": 123456789  # make it deterministic; change if you want variation
    }
    if len(prompt_images) == 1:
        payload["promptImage"] = prompt_images[0]  # single URI string
    else:
        # first image as 'first', others as 'last'
        arr = [{"uri": prompt_images[0], "position": "first"}]
        for uri in prompt_images[1:]:
            arr.append({"uri": uri, "position": "last"})
        payload["promptImage"] = arr

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    return resp

def poll_task(task_id: str):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": API_VERSION,
    }
    url = f"{API_BASE}/v1/tasks/{task_id}"
    while True:
        r = requests.get(url, headers=headers, timeout=60)
        js = r.json()
        state = js.get("status") or js.get("state")
        if state in ("SUCCEEDED","COMPLETED","succeeded"):
            output = js.get("output") or js.get("result",{}).get("output") or []
            return output
        if state in ("FAILED","ERROR","CANCELLED"):
            raise RuntimeError(json.dumps(js, indent=2))
        time.sleep(2)

# ---------- UI ----------
st.set_page_config(page_title="Runway Text+Image → Video", page_icon="🎬", layout="wide")
st.title("🎬 Text-to-Video Generator (Runway API)")
st.caption("Enter a prompt, upload one or more images (logo, reference), pick a model, and generate.")

if not API_KEY:
    st.error("Missing API key. Add RUNWAY_API_KEY in Streamlit secrets or environment.")
    st.stop()

colA, colB = st.columns([2,1], gap="large")

with colA:
    prompt = st.text_area(
        "Prompt",
        value="Ultra-realistic cinematic stadium celebration; high temporal coherence; "
              "natural lighting; dynamic but stable camera pans; shallow depth of field; "
              "brand-consistent with provided logo; no real faces, alcohol, or politics.",
        height=140
    )
    uploads = st.file_uploader(
        "Upload reference images (1–3): fan photo, brand logo, etc.",
        accept_multiple_files=True,
        type=["png","jpg","jpeg"]
    )

with colB:
    model = st.selectbox("Model", list(MODEL_META.keys()), index=0)
    ratio = st.selectbox("Aspect Ratio", ALLOWED_RATIOS, index=0)
    allowed_durations = MODEL_META[model]["durations"]
    duration = st.select_slider("Duration (sec)", options=allowed_durations, value=allowed_durations[-1])
    seed = st.number_input("Seed (optional)", value=123456789, step=1)
    st.caption(f"Cost hint: ~{MODEL_META[model]['credits_per_sec']} credits/sec × {duration}s")

go = st.button("🚀 Generate Video", type="primary", use_container_width=True)

# ---------- Action ----------
if go:
    if not uploads:
        st.warning("Please upload at least one image.")
        st.stop()

    # Prepare images → normalize → data URI
    target_ratio = ratio_to_float(ratio)
    data_uris = []
    with st.spinner("Preprocessing images…"):
        for f in uploads:
            mime = mimetypes.guess_type(f.name)[0] or "image/jpeg"
            img = Image.open(f).convert("RGB")
            img = normalize_to_ratio_pad(img, target_ratio=target_ratio, pad_color=(255,255,255))

            # optional gentle downscale to keep Data URI ≤ ~5MB
            max_px = 1536
            w, h = img.size
            scale = max(w, h) / max_px
            if scale > 1.0:
                img = img.resize((int(w/scale), int(h/scale)), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            uri = file_to_data_uri(buf.getvalue(), "image/png")
            data_uris.append(uri)

    # Start task
    with st.spinner("Submitting task to Runway…"):
        resp = start_task(model=model, ratio=ratio, duration=duration, prompt_text=prompt, prompt_images=data_uris)

    st.code(f"HTTP {resp.status_code}\n{resp.text[:500]}", language="json")
    if resp.status_code != 200:
        st.error("Task failed to start. Check error and adjust ratio / duration / credits / images.")
        st.stop()

    task = resp.json()
    task_id = task.get("id") or task.get("task",{}).get("id")
    st.success(f"Task started: {task_id}")

    # Poll
    progress = st.progress(0, text="Generating… this runs on Runway’s servers.")
    t0 = time.time()
    try:
        # simple ticking progress (visual only)
        while True:
            elapsed = time.time() - t0
            progress.progress(min(100, int((elapsed % 20) * 5)), text="Generating…")
            # Try a poll; break on result
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "X-Runway-Version": API_VERSION,
            }
            js = requests.get(f"{API_BASE}/v1/tasks/{task_id}", headers=headers, timeout=60).json()
            state = js.get("status") or js.get("state")
            if state in ("SUCCEEDED","COMPLETED","succeeded"):
                output = js.get("output") or js.get("result",{}).get("output") or []
                break
            if state in ("FAILED","ERROR","CANCELLED"):
                raise RuntimeError(json.dumps(js, indent=2))
            time.sleep(2)
    finally:
        progress.empty()

    if not output:
        st.error("No output URL returned. Inspect logs above.")
        st.stop()

    video_url = output[0] if isinstance(output, list) else output
    st.video(video_url)
    st.download_button("Download MP4", data=requests.get(video_url).content,
                       file_name=f"{model}_{ratio.replace(':','x')}_{duration}s.mp4",
                       mime="video/mp4")
    st.info("Tip: To reach 16–20s, generate two 8–10s clips and stitch in your editor (or ffmpeg).")
