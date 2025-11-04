import os, io, time, json, base64, mimetypes, requests
from PIL import Image
import streamlit as st

# =========================
# CONFIG & CONSTANTS
# =========================
st.set_page_config(
    page_title="Text+Image → Video",
    page_icon="🎬",
    layout="wide",
)

# ---- Custom CSS (cards, buttons, typography)
st.markdown("""
<style>
/* Page width */
.main .block-container {max-width: 1200px; padding-top: 1.5rem;}

/* Header bar */
.app-header {
  padding: 14px 18px; border-radius: 14px;
  background: linear-gradient(135deg, #0a1627 0%, #152c55 100%);
  color: #ffffff; margin-bottom: 16px; border: 1px solid rgba(255,255,255,0.08);
  display:flex; align-items:center; gap:14px;
}
.app-title {font-size: 1.25rem; font-weight: 700; letter-spacing: .2px;}
.app-sub {opacity: .85; font-size: 0.92rem}

/* Cards */
.card {
  background: #0e1117;
  border: 1px solid rgba(250,250,250,0.08);
  border-radius: 14px; padding: 16px;
}
.light .card { background: #ffffff; border: 1px solid #e8e8e8; }

/* Labels/Badges */
.badge {display:inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600;}
.badge-ok {background:#e6ffed; color:#007a34; border:1px solid #b7f7c7;}
.badge-warn {background:#fff6e6; color:#8a4b00; border:1px solid #ffd79a;}
.badge-info {background:#e6f3ff; color:#004a99; border:1px solid #b8dbff;}

/* Buttons */
.stButton>button {border-radius: 10px; padding: 10px 14px; font-weight: 700;}
</style>
""", unsafe_allow_html=True)

# ---- Header
st.markdown("""
<div class="app-header">
  <div style="display:flex;align-items:center;gap:10px;">
    <span style="font-size:22px;">🎬</span>
    <div>
      <div class="app-title">Text + Image → Video (Runway API)</div>
      <div class="app-sub">Prompt, upload refs/logos, select model & generate stakeholder-ready shots.</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ---- Model metadata
ALLOWED_RATIOS = ["1280:720","720:1280","1104:832","832:1104","960:960","1584:672"]
MODEL_META = {
    "gen4_turbo":  {"durations": [5,10],  "cps": 5,  "endpoint": "image_to_video", "note":"fast + cheapest"},
    "gen4_aleph":  {"durations": [5,10],  "cps": 15, "endpoint": "image_to_video", "note":"sharper than turbo"},
    "veo3":        {"durations": [4,6,8], "cps": 40, "endpoint": "image_to_video", "note":"higher quality"},
    "veo3.1":      {"durations": [4,6,8], "cps": 40, "endpoint": "image_to_video", "note":"newer fidelity"},
    "veo3.1_fast": {"durations": [4,6,8], "cps": 20, "endpoint": "image_to_video", "note":"balanced speed/quality"},
}

API_BASE = "https://api.dev.runwayml.com"
API_VERSION = "2024-11-06"
API_KEY = st.secrets.get("RUNWAY_API_KEY", os.getenv("RUNWAY_API_KEY", ""))

if not API_KEY:
    st.error("Missing API key. Add `RUNWAY_API_KEY` in Streamlit Secrets or env.")
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
    # clamp aspect to [0.5, 2.0] via padding
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

    # pad to exact target_ratio
    w, h = img.size
    curr = w/h
    if abs(curr - target_ratio) > 1e-3:
        if curr > target_ratio:   # need more height
            target_h = int(round(w / target_ratio))
            canvas = Image.new("RGB", (w, target_h), pad_color)
            canvas.paste(img, (0, (target_h - h)//2))
            img = canvas
        else:                     # need more width
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
        "seed": 123456789
    }
    if len(prompt_images) == 1:
        payload["promptImage"] = prompt_images[0]
    else:
        # first image as primary, others as trailing conditioning
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

# =========================
# LAYOUT
# =========================
left, right = st.columns([1.6, 1.0])

with left:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("🔤 Prompt")
    prompt = st.text_area(
        label="",
        value=("Ultra-realistic cinematic stadium celebration; high temporal coherence; "
               "natural lighting; dynamic but stable camera pans; shallow depth of field; "
               "brand-consistent with provided logo; no real faces, alcohol, politics."),
        height=120,
        placeholder="Describe the shot you want…"
    )

    st.markdown("**📸 Reference Images (1–3)** — e.g., person still + brand logo")
    uploads = st.file_uploader(
        label="",
        accept_multiple_files=True,
        type=["png", "jpg", "jpeg"]
    )
    if uploads:
        thumbs = st.columns(min(len(uploads),3))
        for i, f in enumerate(uploads[:3]):
            with thumbs[i]:
                st.image(f, caption=f.name, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("⚙️ Generation Settings")

    model = st.selectbox(
        "Model",
        options=list(MODEL_META.keys()),
        index=0,
        help="Choose a Runway model."
    )
    ratio = st.selectbox("Aspect Ratio", ALLOWED_RATIOS, index=0)
    allowed = MODEL_META[model]["durations"]
    duration = st.select_slider("Duration (sec)", options=allowed, value=allowed[-1])
    cps = MODEL_META[model]["cps"]
    est_cost = cps * duration
    st.markdown(f"**Estimated Cost:** `{cps} credits/s × {duration}s = {est_cost} credits`")

    with st.expander("Advanced"):
        seed = st.number_input("Seed", value=123456789, step=1, help="Change for variation.")
        pad_color = st.color_picker("Letterbox Color", "#FFFFFF")

    go = st.button("🚀 Generate", type="primary", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# =========================
# ACTION
# =========================
if go:
    if not uploads:
        st.warning("Upload at least one reference image (logo/person).")
        st.stop()

    # Preprocess refs → normalize + optional downscale → data URIs
    target_ratio = ratio_to_float(ratio)
    data_uris = []
    with st.status("Preprocessing images…", expanded=False) as s:
        for f in uploads:
            mime = mimetypes.guess_type(f.name)[0] or "image/jpeg"
            img = Image.open(f).convert("RGB")
            img = normalize_to_ratio_pad(img, target_ratio, pad_color=Image.new("RGB",(1,1),pad_color).getpixel((0,0)))

            # Gentle downscale to keep URI smaller (<~5MB)
            max_px = 1536
            w, h = img.size
            scale = max(w, h) / max_px
            if scale > 1.0:
                img = img.resize((int(w/scale), int(h/scale)), Image.LANCZOS)

            buf = io.BytesIO(); img.save(buf, format="PNG")
            uri = file_to_data_uri(buf.getvalue(), "image/png")
            data_uris.append(uri)
        s.update(label="Images ready.", state="complete")

    with st.status("Submitting to Runway…", expanded=False) as s:
        try:
            resp = start_task(model=model, ratio=ratio, duration=duration, prompt_text=prompt, prompt_images=data_uris)
            st.code(f"HTTP {resp.status_code}\n{resp.text[:500]}", language="json")
            if resp.status_code != 200:
                st.error("Task failed to start. Check ratio/duration/credits/image size.")
                st.stop()
            task = resp.json()
            task_id = task.get("id") or task.get("task",{}).get("id")
            s.update(label=f"Started task: {task_id}", state="running")
        except Exception as e:
            st.error(f"Request error: {e}")
            st.stop()

    with st.status("Generating on Runway servers…", expanded=False) as s:
        t0 = time.time()
        try:
            # Poll
            while True:
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
                # Pretty tick in the status line
                elapsed = int(time.time()-t0)
                s.update(label=f"Generating… {elapsed}s", state="running")
                time.sleep(2)
            s.update(label="Generation complete.", state="complete")
        except Exception as e:
            st.error(f"Task error: {e}")
            st.stop()

    # Output card
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("✅ Result")
    if not output:
        st.error("No output URL returned. Inspect logs above.")
        st.stop()

    video_url = output[0] if isinstance(output, list) else output
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
    except Exception as e:
        st.warning(f"Download streamed from URL only (direct fetch failed): {e}")
    # Tips
    st.markdown(
        '<span class="badge badge-info">Tip</span> Generate two 8–10s clips for ~16–20s and stitch in your editor.',
        unsafe_allow_html=True
    )
    st.markdown('</div>', unsafe_allow_html=True)
