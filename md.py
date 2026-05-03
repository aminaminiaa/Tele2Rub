import yt_dlp
import os
import time

def download_media(url: str, quality: str, download_dir: str) -> str:
    """
    دانلود رسانه با استفاده از yt-dlp بر اساس کیفیت درخواستی.
    """
    timestamp = int(time.time())
    base_name = f"media_{timestamp}"
    
    # تنظیمات پایه بهینه شده برای جلوگیری از گیر کردن و بلاک شدن
    ydl_opts = {
        'outtmpl': os.path.join(download_dir, f"{base_name}.%(ext)s"),
        'quiet': False, # تغییر به False برای دیدن ارورهای احتمالی در کنسول
        'no_warnings': True,
        'nocheckcertificate': True,
        'socket_timeout': 30, # جلوگیری از گیر کردن تا ابد (بسیار مهم)
        'retries': 3,
        'geo_bypass': True,
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
        ydl_opts['format'] = 'best'

    # شروع فرآیند دانلود
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # تلاش برای دریافت مسیر دقیق فایل از خود yt-dlp
            if 'requested_downloads' in info and len(info['requested_downloads']) > 0:
                return info['requested_downloads'][0]['filepath']
            
            # در صورتی که مسیر در متغیر بالا نبود (مثل بعضی فایل‌های صوتی)، در پوشه می‌گردیم
            for file in os.listdir(download_dir):
                if file.startswith(base_name):
                    return os.path.join(download_dir, file)
                    
    except Exception as e:
        raise Exception(f"خطا از سمت سرور مرجع یا محدودیت دانلود:\n{str(e)[:200]}")

    raise Exception("متأسفانه فایل مورد نظر دانلود نشد.")