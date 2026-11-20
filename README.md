# AI Video Clipper Telegram Bot

Bot Telegram untuk membuat beberapa klip vertikal 9:16 dengan subtitle Bahasa Indonesia dari URL video yang dapat diakses.

## Status
Versi awal. Menggunakan FFmpeg, yt-dlp, dan faster-whisper lokal. Tidak semua platform atau URL selalu dapat diunduh. Gunakan hanya video yang Anda miliki atau punya izin untuk diproses.

## Konfigurasi
Buat environment secret `TELEGRAM_BOT_TOKEN` dari token BotFather. Jangan pernah memasukkan token ke file GitHub atau mengirimkannya di chat.

Opsional: `WHISPER_MODEL=tiny`, `MAX_CLIPS=3`, `CLIP_SECONDS=45`.

## Menjalankan dengan Docker
```bash
docker build -t ai-video-clipper .
docker run --rm -e TELEGRAM_BOT_TOKEN="TOKEN_ANDA" ai-video-clipper
```

Hosting gratis dapat memiliki batas CPU/RAM, waktu proses, ukuran file, dan waktu aktif. Bot video AI tidak bisa dijamin gratis tanpa batas.