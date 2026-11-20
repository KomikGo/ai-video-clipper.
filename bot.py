import logging, os, re, shutil, subprocess, tempfile
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from yt_dlp import YoutubeDL
from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clipper")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MODEL_NAME = os.getenv("WHISPER_MODEL", "tiny")
MAX_CLIPS = max(1, min(int(os.getenv("MAX_CLIPS", "3")), 5))
CLIP_SECONDS = max(15, min(int(os.getenv("CLIP_SECONDS", "45")), 90))
URL_RE = re.compile(r"https?://\S+", re.I)
model = None

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError((p.stderr or "FFmpeg gagal")[-1200:])
    return p.stdout

def duration_of(path):
    return float(run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)]).strip())

def choose_segments(segs, duration):
    ranked = []
    for s in segs:
        a = max(0.0, float(s.start)); b = min(duration, a + CLIP_SECONDS)
        if b-a < 12: continue
        score = len((s.text or "").split()) / max(1, b-a)
        if not any(abs(a-x[0]) < CLIP_SECONDS*0.7 for x in ranked):
            ranked.append((a,b,score))
    ranked.sort(key=lambda x:x[2], reverse=True)
    chosen = sorted(ranked[:MAX_CLIPS], key=lambda x:x[0])
    if not chosen:
        n = min(MAX_CLIPS, max(1, int(duration//CLIP_SECONDS)))
        chosen = [(max(0,min(duration-12,(duration-CLIP_SECONDS)*i/max(1,n-1))),
                   min(duration,max(0,min(duration-12,(duration-CLIP_SECONDS)*i/max(1,n-1)))+CLIP_SECONDS),0) for i in range(n)]
    return chosen

def srt_time(t):
    ms=int(max(0,t)*1000); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); s,ms=divmod(ms,1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def write_srt(segs,a,b,path):
    rows=[]; idx=1
    for s in segs:
        x=max(a,s.start); y=min(b,s.end); txt=(s.text or "").strip()
        if y>x and txt:
            rows += [str(idx),f"{srt_time(x-a)} --> {srt_time(y-a)}",txt,""]; idx+=1
    Path(path).write_text("\n".join(rows),encoding="utf-8")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Kirim URL video yang Anda miliki atau berhak gunakan. Saya akan mencoba membuat klip vertikal dengan subtitle Bahasa Indonesia. Tidak semua situs didukung.")

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global model
    match=URL_RE.search(update.message.text or "")
    if not match:
        await update.message.reply_text("Kirim URL video yang valid."); return
    status=await update.message.reply_text("⏳ Mengunduh video...")
    with tempfile.TemporaryDirectory(prefix="clipper_") as td:
        folder=Path(td)
        try:
            opts={"format":"bestvideo[height<=1080]+bestaudio/best[height<=1080]/best","merge_output_format":"mp4","outtmpl":str(folder/"input.%(ext)s"),"noplaylist":True,"max_filesize":700*1024*1024,"quiet":True}
            with YoutubeDL(opts) as ydl:
                info=ydl.extract_info(match.group(0).rstrip(".,)"),download=True)
                candidate=Path(ydl.prepare_filename(info))
                if not candidate.exists():
                    found=list(folder.glob("input.*"))
                    if not found: raise RuntimeError("Unduhan tidak menghasilkan file.")
                    candidate=found[0]
                source=folder/"source.mp4"; shutil.copyfile(candidate,source)
            dur=duration_of(source)
            if dur<15: raise RuntimeError("Video terlalu pendek (minimal 15 detik).")
            await status.edit_text("🧠 Menganalisis ucapan...")
            if model is None: model=WhisperModel(MODEL_NAME,device="cpu",compute_type="int8")
            iterator,_=model.transcribe(str(source),language="id",vad_filter=True)
            segs=list(iterator); clips=choose_segments(segs,dur)
            await status.edit_text(f"✂️ Membuat {len(clips)} klip...")
            for i,(a,b,_) in enumerate(clips,1):
                srt=folder/f"{i}.srt"; out=folder/f"{i}.mp4"; write_srt(segs,a,b,srt)
                sub=str(srt).replace("\\\\","\\\\\\\\").replace(":","\\\\:")
                vf=f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles='{sub}':force_style='FontName=DejaVu Sans,FontSize=18,Outline=2,Shadow=1,Alignment=2,MarginV=100'"
                run(["ffmpeg","-y","-ss",str(a),"-i",str(source),"-t",str(b-a),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","26","-c:a","aac","-b:a","128k","-movflags","+faststart",str(out)])
                if out.stat().st_size>49*1024*1024:
                    await update.message.reply_text(f"Klip {i} terlalu besar untuk dikirim oleh bot, dilewati."); continue
                with out.open("rb") as f:
                    await update.message.reply_video(video=f,caption=f"Klip {i}/{len(clips)} · {int(a)}–{int(b)} detik",supports_streaming=True,read_timeout=120,write_timeout=120)
            await status.edit_text("✅ Selesai. Kirim URL berikutnya jika ingin membuat klip lagi.")
        except Exception as e:
            log.exception("Pemrosesan gagal")
            await status.edit_text("❌ Gagal memproses video. Platform mungkin membatasi akses atau server kehabisan sumber daya.\n\n"+str(e)[-800:])

def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN belum diatur sebagai environment secret.")
    public_url = os.getenv("WEBHOOK_URL", "").rstrip("/")
    webhook_path = os.getenv("WEBHOOK_PATH", "telegram-webhook")
    secret = os.getenv("WEBHOOK_SECRET_TOKEN", "")
    if not public_url.startswith("https://"):
        raise SystemExit("WEBHOOK_URL harus berupa URL https:// dari Render.")
    if not secret:
        raise SystemExit("WEBHOOK_SECRET_TOKEN belum diatur sebagai environment secret.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        url_path=webhook_path,
        webhook_url=f"{public_url}/{webhook_path}",
        secret_token=secret,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
