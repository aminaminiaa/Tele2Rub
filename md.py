import yt_dlp
import os
import time
from pathlib import Path

def download_media(url: str, quality: str, download_dir: str) -> str:
    """
    دانلود رسانه با استفاده از yt-dlp بر اساس کیفیت درخواستی.
    quality می‌تواند شامل: audio, 480, 720, 1080 باشد.
    """
    timestamp = int(time.time())
    base_name = f"media_{timestamp}"
    
    # تنظیمات پایه برای جلوگیری از خطاهای متداول
    ydl_opts = {
        'outtmpl': os.path.join(download_dir, f"{base_name}.%(ext)s"),
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
    }

    # تخصیص فرمت‌ها بر اساس درخواست کاربر
    if quality == "audio":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    elif quality == "480":
        ydl_opts['format'] = 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
        ydl_opts['merge_output_format'] = 'mp4'
    elif quality == "720":
        ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
        ydl_opts['merge_output_format'] = 'mp4'
    elif quality == "1080":
        ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
        ydl_opts['merge_output_format'] = 'mp4'
    else:
        ydl_opts['format'] = 'best' # پیش‌فرض

    # شروع فرآیند دانلود
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        
        # پیدا کردن مسیر فایلی که در دیسک ذخیره شده است
        for file in os.listdir(download_dir):
            if file.startswith(base_name):
                return os.path.join(download_dir, file)

    raise Exception("متأسفانه فایل مورد نظر دانلود نشد.")