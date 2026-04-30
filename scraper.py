import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
import pyzipper
import shutil

def sanitize_filename(name: str) -> str:
    """حذف کاراکترهای غیرمجاز برای اسم فایل‌ها"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    return name[:150] or "asset"

def download_webpage_as_zip(url: str, output_dir: Path, status_callback=None) -> Path:
    """
    دانلود سورس یک وب‌سایت به همراه فایل‌های استایل، عکس و اسکریپت‌ها 
    و فشرده‌سازی همه آن‌ها در یک فایل زیپ.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    
    if status_callback:
        status_callback("🌐 در حال دریافت ساختار اصلی وب‌سایت...")
        
    # دریافت کدهای HTML صفحه
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.text, "html.parser")
    
    # ساخت اسم امن از روی دامنه سایت
    domain = urlparse(url).netloc
    safe_domain = sanitize_filename(domain).replace("www.", "")
    timestamp = int(time.time())
    
    # ایجاد پوشه‌های موقت
    base_folder = output_dir / f"web_{safe_domain}_{timestamp}"
    assets_folder = base_folder / "assets"
    assets_folder.mkdir(parents=True, exist_ok=True)
    
    # تگ‌هایی که باید فایل‌هایشان دانلود شود
    tags_to_download = [
        ("img", "src"),
        ("link", "href"),
        ("script", "src")
    ]
    
    assets_found = []
    for tag_name, attr in tags_to_download:
        for tag in soup.find_all(tag_name):
            link = tag.get(attr)
            if not link:
                continue
            
            # برای تگ link فقط فایل‌های استایل (css) را می‌خواهیم
            if tag_name == "link" and "stylesheet" not in tag.get("rel", []):
                continue
            
            # تبدیل آدرس‌های نسبی (مثل /images/logo.png) به آدرس کامل وب
            asset_url = urljoin(url, link)
            
            # نادیده گرفتن فایل‌های Data URI (Base64)
            if asset_url.startswith("data:"):
                continue
                
            assets_found.append((tag, attr, asset_url))
            
    total_assets = len(assets_found)
    
    # دانلود تک‌تک فایل‌های سایت
    for i, (tag, attr, asset_url) in enumerate(assets_found, 1):
        if status_callback and i % 5 == 0:
            status_callback(f"⬇️ در حال دانلود فایل‌های سایت...\n\nفایل {i} از {total_assets}")
            
        try:
            asset_resp = requests.get(asset_url, headers=headers, timeout=10, stream=True)
            if asset_resp.status_code == 200:
                parsed_asset = urlparse(asset_url)
                asset_name = os.path.basename(parsed_asset.path)
                if not asset_name:
                    asset_name = f"asset_{i}"
                
                # جلوگیری از تداخل اسامی فایل‌های همنام
                asset_name = sanitize_filename(asset_name)
                asset_name = f"{i}_{asset_name}"
                
                asset_path = assets_folder / asset_name
                with open(asset_path, "wb") as f:
                    for chunk in asset_resp.iter_content(1024 * 64):
                        if chunk:
                            f.write(chunk)
                            
                # جایگزینی لینک وب با آدرس محلی در سورس HTML
                tag[attr] = f"assets/{asset_name}"
        except Exception:
            # در صورت خطای یک فایل (مثل 404) از آن رد می‌شویم
            pass 
            
    if status_callback:
        status_callback("📦 در حال فشرده‌سازی سایت در فایل زیپ...")
        
    # ذخیره کدهای HTML آپدیت‌شده
    html_path = base_folder / "index.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))
        
    # زیپ کردن پوشه قالب
    zip_path = output_dir / f"Website_{safe_domain}_{timestamp}.zip"
    with pyzipper.ZipFile(zip_path, "w", compression=pyzipper.ZIP_DEFLATED) as zipf:
        zipf.write(html_path, arcname="index.html")
        for root, dirs, files in os.walk(assets_folder):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.join("assets", file)
                zipf.write(file_path, arcname=arcname)
                
    # پاک کردن پوشه‌های موقت پس از زیپ
    shutil.rmtree(base_folder, ignore_errors=True)
    
    return zip_path