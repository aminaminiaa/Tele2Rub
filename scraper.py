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
    دانلود کامل سورس، قالب، تصاویر و فونت‌های وب‌سایت.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    if status_callback:
        status_callback("🌐 در حال دریافت ساختار اصلی وب‌سایت...")
        
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.text, "html.parser")
    domain = urlparse(url).netloc
    safe_domain = sanitize_filename(domain).replace("www.", "")
    timestamp = int(time.time())
    
    base_folder = output_dir / f"web_{safe_domain}_{timestamp}"
    assets_folder = base_folder / "assets"
    assets_folder.mkdir(parents=True, exist_ok=True)
    
    # اضافه شدن پشتیبانی از تصاویر، فونت‌ها و استایل‌ها
    tags_to_download = [
        ("img", "src"),
        ("link", "href"),
        ("script", "src"),
        ("source", "src")
    ]
    
    assets_found = []
    for tag_name, attr in tags_to_download:
        for tag in soup.find_all(tag_name):
            link = tag.get(attr)
            if not link:
                continue
            
            if tag_name == "link":
                rel = tag.get("rel", [])
                if isinstance(rel, str):
                    rel = [rel]
                # فقط استایل‌ها، فونت‌ها و آیکون‌ها
                if not any(r in rel for r in ["stylesheet", "icon", "shortcut icon", "preload"]):
                    continue
            
            asset_url = urljoin(url, link)
            if asset_url.startswith("data:") or asset_url.startswith("#"):
                continue
                
            assets_found.append((tag, attr, asset_url))
            
    total_assets = len(assets_found)
    global_counter = 0
    
    for i, (tag, attr, asset_url) in enumerate(assets_found, 1):
        if status_callback and i % 5 == 0:
            status_callback(f"⬇️ در حال دانلود فایل‌های سایت...\n\nفایل {i} از {total_assets}")
            
        try:
            asset_resp = requests.get(asset_url, headers=headers, timeout=15)
            if asset_resp.status_code == 200:
                global_counter += 1
                parsed_asset = urlparse(asset_url)
                asset_name = os.path.basename(parsed_asset.path)
                asset_name = sanitize_filename(asset_name) or f"asset_{global_counter}"
                asset_name = f"{global_counter}_{asset_name}"
                
                content_type = asset_resp.headers.get("Content-Type", "")
                asset_content = asset_resp.content
                
                # رفع مشکل فونت‌ها: استخراج فایل‌های داخل CSS (فونت‌ها و عکس‌های پس‌زمینه)
                if "text/css" in content_type or asset_name.endswith(".css"):
                    try:
                        css_text = asset_resp.text
                        # پیدا کردن تمام آدرس‌های فونت و عکس در فایل استایل
                        css_urls = re.findall(r'url\(\s*[\'"]?([^\'"()]+)[\'"]?\s*\)', css_text)
                        
                        for inner_url in css_urls:
                            if inner_url.startswith("data:") or inner_url.startswith("#"):
                                continue
                                
                            inner_full_url = urljoin(asset_url, inner_url.strip())
                            try:
                                inner_resp = requests.get(inner_full_url, headers=headers, timeout=10)
                                if inner_resp.status_code == 200:
                                    global_counter += 1
                                    inner_parsed = urlparse(inner_full_url)
                                    inner_name = os.path.basename(inner_parsed.path)
                                    inner_name = sanitize_filename(inner_name) or f"font_{global_counter}"
                                    inner_name = f"{global_counter}_{inner_name}"
                                    
                                    with open(assets_folder / inner_name, "wb") as f:
                                        f.write(inner_resp.content)
                                        
                                    # جایگزینی مسیر در فایل CSS (چون فایل‌ها در یک پوشه هستند، فقط اسم کافیست)
                                    css_text = css_text.replace(inner_url, inner_name)
                            except Exception:
                                pass
                        
                        asset_content = css_text.encode("utf-8")
                    except Exception:
                        pass # اگر CSS قابل دیکود نبود نادیده می‌گیریم
                
                with open(assets_folder / asset_name, "wb") as f:
                    f.write(asset_content)
                            
                tag[attr] = f"assets/{asset_name}"
        except Exception:
            pass 
            
    if status_callback:
        status_callback("📦 در حال فشرده‌سازی سایت در فایل زیپ...")
        
    html_path = base_folder / "index.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))
        
    zip_path = output_dir / f"Website_{safe_domain}_{timestamp}.zip"
    with pyzipper.ZipFile(zip_path, "w", compression=pyzipper.ZIP_DEFLATED) as zipf:
        zipf.write(html_path, arcname="index.html")
        for root, dirs, files in os.walk(assets_folder):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.join("assets", file)
                zipf.write(file_path, arcname=arcname)
                
    shutil.rmtree(base_folder, ignore_errors=True)
    return zip_path