import yt_dlp
import os
import time
import glob

def download_media(url: str, quality: str, download_dir: str) -> str:
    """
    دانلود رسانه با سیستم هوشمند تشخیص کیفیت و فال‌بک خودکار
    """
    timestamp = int(time.time())
    base_name = f"media_{timestamp}"
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_file = os.path.join(current_dir, "cookies.txt")
    
    ydl_opts = {
        'outtmpl': os.path.join(download_dir, f"{base_name}.%(ext)s"),
        'quiet': False, 
        'no_warnings': True,
        'nocheckcertificate': True,
        'socket_timeout': 30,
        'retries': 5,
        'geo_bypass': True,
        'extractor_args': {
            'youtube': {'player_client': ['android', 'web']}
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    if os.path.exists(cookies_file):
        ydl_opts['cookiefile'] = cookies_file

    if quality == "audio":
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    elif quality in ["480", "720", "1080"]:
        # فرمت با فال‌بک هوشمند: ابتدا کیفیت دقیق، سپس نزدیک‌ترین، در نهایت هر چیزی
        ydl_opts['format'] = (
            f'bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/'
            f'bestvideo[height<={quality}]+bestaudio/'
            f'best[height<={quality}]/'
            'bestvideo+bestaudio/best'
        )
        ydl_opts['merge_output_format'] = 'mp4'
    else:
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
        ydl_opts['merge_output_format'] = 'mp4'

    def attempt_download(opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if 'requested_downloads' in info and len(info['requested_downloads']) > 0:
                return info['requested_downloads'][0]['filepath']
            if 'filepath' in info:
                return info['filepath']
            
            search_pattern = os.path.join(download_dir, f"{base_name}.*")
            downloaded_files = glob.glob(search_pattern)
            if downloaded_files:
                return downloaded_files[0]
        return None

    try:
        result = attempt_download(ydl_opts)
        if result: 
            return result
        
    except Exception as e:
        error_str = str(e).lower()
        
        if "requested format is not available" in error_str or "no video formats" in error_str:
            try:
                print("⚠️ فرمت درخواستی موجود نیست. در حال دانلود بهترین فرمت موجود...")
                ydl_opts['format'] = 'best'
                result = attempt_download(ydl_opts)
                if result: 
                    return result
            except Exception as fallback_err:
                raise Exception(f"شکست در دانلود فایل:\n{str(fallback_err)[:150]}")
        
        if "ffmpeg" in error_str and "is not installed" in error_str:
             raise Exception("نرم‌افزار FFmpeg روی سرور شما نصب نیست. لطفاً آن را نصب کنید.")
        
        if "sign in to confirm" in error_str:
             raise Exception("یوتیوب آی‌پی سرور را مسدود کرده! حتماً فایل cookies.txt را کنار فایل ربات قرار دهید.")
             
        raise Exception(f"خطا در دانلود:\n{str(e)[:150]}...")

    raise Exception("متأسفانه فایل مورد نظر پس از پردازش پیدا نشد.")
