import os, re, shutil, subprocess, tempfile
from pathlib import Path
from telegram import Bot
from yt_dlp import YoutubeDL
from faster_whisper import WhisperModel

TOKEN=os.environ["TELEGRAM_BOT_TOKEN"]
URL=os.environ["VIDEO_URL"]
CHAT=int(os.environ["CHAT_ID"])
MAX_CLIPS=3
CLIP_SECONDS=45

def run(cmd):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if p.returncode: raise RuntimeError((p.stderr or "FFmpeg gagal")[-1000:])
    return p.stdout

def duration(path):
    return float(run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)]).strip())

def stamp(t):
    ms=int(max(0,t)*1000); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); s,ms=divmod(ms,1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

async def main():
    bot=Bot(TOKEN)
    await bot.send_message(CHAT,"⏳ Video masuk antrean. Sedang diunduh dan dianalisis.")
    with tempfile.TemporaryDirectory() as td:
        folder=Path(td)
        opts={"format":"bestvideo[height<=1080]+bestaudio/best[height<=1080]/best","merge_output_format":"mp4","outtmpl":str(folder/"input.%(ext)s"),"noplaylist":True,"max_filesize":700*1024*1024,"quiet":True}
        with YoutubeDL(opts) as ydl:
            info=ydl.extract_info(URL,download=True)
            candidate=Path(ydl.prepare_filename(info))
            if not candidate.exists():
                found=list(folder.glob("input.*"))
                if not found: raise RuntimeError("Unduhan gagal.")
                candidate=found[0]
            source=folder/"source.mp4"; shutil.copyfile(candidate,source)
        dur=duration(source)
        if dur<15: raise RuntimeError("Video terlalu pendek (minimal 15 detik).")
        await bot.send_message(CHAT,"🧠 Menganalisis ucapan untuk memilih momen.")
        model=WhisperModel("tiny",device="cpu",compute_type="int8")
        segs,_=model.transcribe(str(source),language="id",vad_filter=True)
        segs=list(segs)
        ranked=[]
        for s in segs:
            a=max(0,float(s.start)); b=min(dur,a+CLIP_SECONDS)
            if b-a<12: continue
            score=len((s.text or "").split())/max(1,b-a)
            if not any(abs(a,x[0])<CLIP_SECONDS*.7 for x in ranked): ranked.append((a,b,score))
        ranked.sort(key=lambda x:x[2],reverse=True)
        chosen=sorted(ranked[:MAX_CLIPS],key=lambda x:x[0])
        if not chosen: chosen=[(0,min(dur,CLIP_SECONDS),0)]
        for i,(a,b,_) in enumerate(chosen,1):
            srt=folder/f"{i}.srt"; out=folder/f"{i}.mp4"
            rows=[]; n=1
            for s in segs:
                x=max(a,s.start); y=min(b,s.end); txt=(s.text or "").strip()
                if y>x and txt:
                    rows.extend([str(n),f"{stamp(x-a)} --> {stamp(y-a)}",txt,""]); n+=1
            srt.write_text("\n".join(rows),encoding="utf-8")
            sub=str(srt).replace("\\","\\\\").replace(":","\\:")
            vf=f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles='{sub}':force_style='FontName=DejaVu Sans,FontSize=18,Outline=2,Alignment=2,MarginV=100'"
            run(["ffmpeg","-y","-ss",str(a),"-i",str(source),"-t",str(b-a),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","26","-c:a","aac","-b:a","128k","-movflags","+faststart",str(out)])
            if out.stat().st_size<49*1024*1024:
                with out.open("rb") as f: await bot.send_video(CHAT,video=f,caption=f"Klip {i}/{len(chosen)}",supports_streaming=True,read_timeout=180,write_timeout=180)
            else: await bot.send_message(CHAT,f"Klip {i} terlalu besar untuk dikirim.")
    await bot.send_message(CHAT,"✅ Selesai. Kirim URL lain untuk membuat klip lagi.")

if __name__=="__main__":
    import asyncio
    try: asyncio.run(main())
    except Exception as e:
        import asyncio
        async def report():
            await Bot(TOKEN).send_message(CHAT,"❌ Gagal memproses: "+str(e)[:700])
        asyncio.run(report())
