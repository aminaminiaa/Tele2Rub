import os
import re
import json
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import Message
import asyncio
import time
from urllib.parse import urlparse
from pyrogram import idle

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
QUEUE_DIR = BASE_DIR / "queue"
QUEUE_FILE = QUEUE_DIR / "tasks.jsonl"
STATUS_FILE = QUEUE_DIR / "status.jsonl"
SETTINGS_FILE = QUEUE_DIR / "settings.json"
DELETED_FILE = QUEUE_DIR / "deleted.jsonl"
CANCEL_FILE = QUEUE_DIR / "cancelled.jsonl"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Please set API_ID, API_HASH and BOT_TOKEN in .env")

app = Client(
    "tel2rub",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


def safe_filename(name: Optional[str]) -> str:
    name = (name or "file.bin").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    name = name.rstrip(". ")
    return name[:200] or "file.bin"


def split_name(filename: str) -> tuple[str, str]:
    path = Path(filename)
    return path.stem, path.suffix


def get_media(message: Message):
    media_types = [
        ("document", message.document),
        ("video", message.video),
        ("audio", message.audio),
        ("voice", message.voice),
        ("photo", message.photo),
        ("animation", message.animation),
        ("video_note", message.video_note),
        ("sticker", message.sticker),
    ]

    for media_type, media in media_types:
        if media:
            return media_type, media

    return None, None


def build_download_filename(message: Message, media_type: str, media) -> str:
    original_name = getattr(media, "file_name", None)

    if not original_name:
        file_unique_id = getattr(media, "file_unique_id", None) or "file"

        default_extensions = {
            "document": ".bin",
            "video": ".mp4",
            "audio": ".mp3",
            "voice": ".ogg",
            "photo": ".jpg",
            "animation": ".mp4",
            "video_note": ".mp4",
            "sticker": ".webp",
        }

        original_name = f"{file_unique_id}{default_extensions.get(media_type, '.bin')}"

    original_name = safe_filename(original_name)
    stem, suffix = split_name(original_name)

    unique_name = f"{stem}_{message.id}{suffix or '.bin'}"
    return safe_filename(unique_name)

waiting_for_zip_password = False

class QueueManager:
    def __init__(self):
        self._cache = None
        self._mtime = 0

    def all(self):
        mtime = QUEUE_FILE.stat().st_mtime if QUEUE_FILE.exists() else 0
        if mtime == self._mtime and self._cache is not None:
            return self._cache
        self._cache = []
        if QUEUE_FILE.exists():
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                self._cache = [json.loads(l) for l in f if l.strip()]
        self._mtime = mtime
        return self._cache

    def push(self, task):
        task.setdefault("job_id", str(int(time.time() * 1000)))
        with open(QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
        self._cache = None

    def remove(self, job_id=None, message_id=None):
        tasks = self.all()
        kept, removed = [], None
        for t in tasks:
            if (job_id and str(t.get("job_id")) == str(job_id)) or \
               (message_id and int(t.get("status_message_id", 0)) == message_id):
                removed = t
            else:
                kept.append(t)
        if removed:
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                f.writelines(json.dumps(t, ensure_ascii=False) + "\n" for t in kept)
            self._cache = None
        return removed


queue = QueueManager()

def mark_deleted(task: dict):
    with open(DELETED_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(task, ensure_ascii=False) + "\n")

def mark_cancelled(task: dict):
    with open(CANCEL_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(task, ensure_ascii=False) + "\n")

def cancel_job(job_id: str):
    with open(CANCEL_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"job_id": str(job_id)}, ensure_ascii=False) + "\n")

def was_deleted(job_id=None, message_id=None) -> bool:
    if not DELETED_FILE.exists():
        return False
    with open(DELETED_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            if job_id and str(item.get("job_id")) == str(job_id):
                return True
            if message_id and int(item.get("status_message_id", 0)) == message_id:
                return True
    return False

def load_settings() -> dict:
    default_settings = {"safe_mode": False, "zip_password": "", "caption_mode": True}
    try:
        if SETTINGS_FILE.exists():
            loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            default_settings.update(loaded)
    except Exception:
        pass
    return default_settings

def save_settings(data: dict):
    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def is_direct_url(text: str) -> bool:
    if not text:
        return False

    url = extract_first_url(text)
    if not url:
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def extract_first_url(text: str) -> Optional[str]:
    if not text:
        return None

    match = re.search(r"https?://\S+", text)
    return match.group(0) if match else None


def progress_bar(percent: float, length: int = 12) -> str:
    filled = int(length * percent / 100)
    return "█" * filled + "░" * (length - filled)


def pretty_size(size) -> str:
    size = float(size or 0)
    units = ["B", "KB", "MB", "GB"]

    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1

    return f"{size:.2f} {units[index]}"


def eta_text(seconds) -> str:
    if not seconds or seconds <= 0:
        return "نامشخص"

    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


async def download_progress(current, total, status_message, file_name, started_at, state):
    now = time.time()

    if now - state.get("last_update", 0) < 3 and current < total:
        return

    state["last_update"] = now

    percent = current * 100 / total if total else 0
    elapsed = max(now - started_at, 1)
    speed = current / elapsed
    eta = (total - current) / speed if speed else None

    text = (
        f"📥 در حال دریافت فایل از تلگرام\n\n"
        f"فایل: `{file_name}`\n"
        f"حجم: `{pretty_size(total)}`\n"
        f"پیشرفت: `{percent:.1f}%`\n"
        f"`{progress_bar(percent)}`\n"
        f"سرعت: `{pretty_size(speed)}/s`\n"
        f"زمان باقی‌مانده: `{eta_text(eta)}`"
    )

    try:
        await status_message.edit_text(text)
    except Exception:
        pass

async def status_watcher():
    pos = 0
    while True:
        await asyncio.sleep(1)
        if not STATUS_FILE.exists():
            continue
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                f.seek(pos)
                lines = f.readlines()
                pos = f.tell()
            for line in lines:
                if not line.strip():
                    continue
                data = json.loads(line)
                chat_id = data.get("chat_id")
                msg_id = data.get("message_id")
                text = data.get("text", "")
                percent = data.get("percent")
                if not chat_id or not msg_id:
                    continue
                if percent is not None:
                    text += f"\n\n`{progress_bar(float(percent))}` `{float(percent):.1f}%`"
                try:
                    await app.edit_message_text(chat_id, msg_id, text)
                except Exception:
                    pass
        except Exception:
            pass

@app.on_message(filters.private & filters.command("start"))
async def start_handler(client: Client, message: Message):
    await message.reply_text(
        "سلام به ربات tele2rub خوش اومدی💙\n\n"
        "برای انتقال فایل از تلگرام به روبیکا، کافیه فایل رو برام فوروارد کنی.\n"
        "🌐 **لینک سایت:** اگه آدرس یک سایت رو بفرستی، کل قالب و فایل‌هاش رو برات استخراج و زیپ می‌کنم!\n"
        "📝 **متن:** اگه متنی بفرستی که لینک نداشته باشه، تبدیل به فایل `txt.` میشه و به روبیکا ارسال میشه.\n"
        "⚠️لطفا فایل‌ها رو حداکثر ۱۰ تا ۱۰ تا ارسال کن تا از سمت روبیکا به مشکل نخوره.\n\n"
        "برای دانلود از یوتیوب، اینستاگرام و... از این ربات استفاده کن: @Gozilla_bot\n"
        "بعد فایل رو اینجا بفرست تا توی روبیکا برات ارسال کنم.\n\n"
        "📌 راهنمای ربات:\n\n"
        "-حذف از صف:\n"
        "هر فایل وقتی تو صف قرار می‌گیره یه دستور لغو داره که با اون دستور می‌تونی حذفش کنی.\n"
        "⚠️اگر فایل در حال آپلود باشه، لغو بعد از پایان تلاش فعلی انجام میشه.\n\n"
        "-پاکسازی کل صف:\n"
        "/delall\n\n"
        "- حالت ارسال کپشن:\n"
        "به صورت پیش‌فرض تمام کپشن‌ها ارسال میشن.\n"
        "برای خاموش/روشن کردن:\n"
        " /caption on\n"
        " /caption off\n\n"
        "-حالت Safe Mode:\n"
        "همه فایل‌ها با رمز دلخواهت به صورت ZIP رمزدار ارسال میشن.\n\n"
        "برای فعال/غیرفعال کردن:\n"
        " /safemode on\n"
        " /safemode off\n\n"
        "⚠️برای فایل‌های حجیم و ویدیوها بهتره Safe Mode خاموش باشه تا سریع‌تر آپلود بشن.\n\n"
        "@caffeinexz"
    )

@app.on_message(filters.private & filters.command("caption"))
async def caption_handler(client: Client, message: Message):
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.reply_text("برای تغییر وضعیت ارسال کپشن از `/caption on` یا `/caption off` استفاده کن.")
        return

    action = args[1].strip().lower()
    settings = load_settings()

    if action == "on":
        settings["caption_mode"] = True
        save_settings(settings)
        await message.reply_text(
            "ارسال کپشن فعال شد.\n\n"
            "از این به بعد متون همراه فایل‌ها ارسال خواهند شد."
        )
        return

    if action == "off":
        settings["caption_mode"] = False
        save_settings(settings)
        await message.reply_text(
            "ارسال کپشن غیرفعال شد.\n\n"
            "از این به بعد فقط خود فایل ارسال می‌شود و متن‌ها نادیده گرفته می‌شوند."
        )
        return

    await message.reply_text("دستور نامعتبر است. از `/caption on` یا `/caption off` استفاده کن.")


@app.on_message(filters.private & filters.command("safemode"))
async def safemode_handler(client: Client, message: Message):
    global waiting_for_zip_password

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.reply_text("برای تغییر وضعیت Safe Mode از `/safemode on` یا `/safemode off` استفاده کن.")
        return

    action = args[1].strip().lower()
    settings = load_settings()

    if action == "on":
        settings["safe_mode"] = True
        save_settings(settings)
        waiting_for_zip_password = True

        await message.reply_text(
            "Safe Mode فعال شد.\n\n"
            "لطفا رمزی که می‌خواهید روی فایل‌های ZIP قرار بگیرد را ارسال کنید.\n"
            "از این به بعد فایل‌ها قبل از ارسال به روبیکا با همین رمز ZIP می‌شوند."
        )
        return

    if action == "off":
        settings["safe_mode"] = False
        settings["zip_password"] = ""
        save_settings(settings)
        waiting_for_zip_password = False

        await message.reply_text(
            "Safe Mode غیرفعال شد.\n\n"
            "از این به بعد فایل‌ها به‌صورت عادی ارسال می‌شوند."
        )
        return

    await message.reply_text("دستور نامعتبر است. از `/safemode on` یا `/safemode off` استفاده کن.")


@app.on_message(filters.private & filters.command("delall"))
async def clear_queue_handler(client: Client, message: Message):
    tasks = queue.all()

    if not tasks:
        await message.reply_text("صف خالی است.")
        return

    for task in tasks:
        mark_deleted(task)

        old_path = task.get("path")
        if old_path:
            try:
                path = Path(old_path)
                if path.exists():
                    path.unlink()
            except Exception:
                pass

        try:
            await client.edit_message_text(
                chat_id=task["chat_id"],
                message_id=task["status_message_id"],
                text="این مورد از صف حذف شد."
            )
        except Exception:
            pass

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        pass
    queue._cache = None
    queue._mtime = 0
    await message.reply_text("تمام موارد در صف پاک شد.")

@app.on_message(filters.private & filters.command("del"))
async def delete_one_handler(client: Client, message: Message):
    job_id = None
    reply_message_id = None

    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        job_id = parts[1].strip()

    if message.reply_to_message:
        reply_message_id = message.reply_to_message.id

    tasks = queue.all()

    if not tasks:
        if job_id and was_deleted(job_id=job_id):
            await message.reply_text("این مورد قبلاً از صف حذف شده است.")
            return

        if reply_message_id and was_deleted(message_id=reply_message_id):
            await message.reply_text("این مورد قبلاً از صف حذف شده است.")
            return

        if job_id:
            cancel_job(job_id)
            await message.reply_text(
                "لغو ثبت شد.\n\n"
            )
            return

        await message.reply_text("موردی برای حذف در صف پیدا نشد.")
        return

    removed = queue.remove(job_id=job_id, message_id=reply_message_id)

    if removed:
        mark_deleted(removed)

        old_path = removed.get("path")
        if old_path:
            try:
                path = Path(old_path)
                if path.exists():
                    path.unlink()
            except Exception:
                pass

        try:
            await client.edit_message_text(
                chat_id=removed["chat_id"],
                message_id=removed["status_message_id"],
                text="این مورد از صف حذف شد."
            )
        except Exception:
            pass

        await message.reply_text("از صف حذف شد.")
        return

    if job_id and was_deleted(job_id=job_id):
        await message.reply_text("این مورد قبلاً از صف حذف شده است.")
        return

    if reply_message_id and was_deleted(message_id=reply_message_id):
        await message.reply_text("این مورد قبلاً از صف حذف شده است.")
        return

    if job_id:
        cancel_job(job_id)
        await message.reply_text("دستور لغو ثبت شد.") 
        return


@app.on_message(filters.private & filters.text & ~filters.command(["start", "safemode", "caption", "del", "delall"]))
async def text_handler(client: Client, message: Message):
    global waiting_for_zip_password

    text = message.text or ""

    if waiting_for_zip_password:
        password = text.strip()

        if not password:
            await message.reply_text("رمز نمی‌تواند خالی باشد. لطفاً یک رمز معتبر ارسال کنید.")
            return

        settings = load_settings()
        settings["safe_mode"] = True
        settings["zip_password"] = password
        save_settings(settings)

        waiting_for_zip_password = False

        await message.reply_text(
            "رمز ذخیره شد.\n\n"
            "از این به بعد فایل‌ها قبل از ارسال به روبیکا به‌صورت ZIP رمزدار آماده می‌شوند."
        )
        return

    url = extract_first_url(text)
    settings = load_settings()

    # اگر پیام ارسالی شامل لینک اینترنتی نبود، به عنوان یک متن در نظر گرفته و به فایل txt تبدیل می‌شود
    if not url or not is_direct_url(url):
        txt_name = f"Text_Message_{message.id}.txt"
        txt_path = DOWNLOAD_DIR / txt_name
        
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
            
        status = await message.reply_text(
            "📝 متن دریافت شد.\n\n"
            "وضعیت: در حال آماده‌سازی فایل متنی..."
        )

        task = {
            "type": "local_file",
            "path": str(txt_path),
            "caption": "", # کپشن خالی است تا در روبیکا متن پیش‌فرض برایش گذاشته شود
            "chat_id": message.chat.id,
            "status_message_id": status.id,
            "file_name": txt_name,
            "file_size": txt_path.stat().st_size,
            "safe_mode": settings.get("safe_mode", False),
            "zip_password": settings.get("zip_password", ""),
        }

        queue.push(task)

        await status.edit_text(
            f"متن شما تبدیل به فایل txt شد و در صف قرار گرفت.\n\n"
            f"فایل: `{txt_name}`\n"
            f"شناسه: `{task['job_id']}`\n\n"
            f"برای حذف این مورد از صف:\n"
            f"`/del {task['job_id']}`"
        )
        return

    status = await message.reply_text(
        "لینک دریافت شد.\n\n"
        "وضعیت: در صف دانلود قرار گرفت."
    )

    task = {
        "type": "direct_url",
        "url": url,
        "chat_id": message.chat.id,
        "status_message_id": status.id,
        "safe_mode": settings.get("safe_mode", False),
        "zip_password": settings.get("zip_password", ""),
    }

    queue.push(task)

    await status.edit_text(
        f"لینک در صف قرار گرفت.\n\n"
        f"شناسه: `{task['job_id']}`\n"
        f"برای حذف این مورد از صف:\n"
        f"`/del {task['job_id']}`"
    )

    
@app.on_message(
    filters.private
    & (
        filters.document
        | filters.video
        | filters.audio
        | filters.voice
        | filters.photo
        | filters.animation
        | filters.video_note
        | filters.sticker
    )
)
async def media_handler(client: Client, message: Message):
    media_type, media = get_media(message)
    if not media:
        await message.reply_text("فایل قابل پردازش نیست.")
        return

    download_name = build_download_filename(message, media_type, media)
    download_path = DOWNLOAD_DIR / download_name

    status = await message.reply_text(
        "فایل دریافت شد.\n\n"
        "وضعیت: آماده‌سازی برای دانلود از تلگرام..."
    )

    try:
        started_at = time.time()
        progress_state = {"last_update": 0}

        downloaded = await client.download_media(
            message,
            file_name=str(download_path),
            progress=download_progress,
            progress_args=(status, download_name, started_at, progress_state),
        )

        if not downloaded:
            raise RuntimeError("Download failed.")

        downloaded_path = Path(downloaded)
        if not downloaded_path.exists():
            raise RuntimeError("Downloaded file not found.")

        file_size = downloaded_path.stat().st_size
        settings = load_settings()
        
        # بررسی وضعیت کپشن و تعیین متن
        raw_caption = message.caption or ""
        final_caption = raw_caption if settings.get("caption_mode", True) else ""

        task = {
            "type": "local_file",
            "path": str(downloaded_path),
            "caption": final_caption,
            "chat_id": message.chat.id,
            "status_message_id": status.id,
            "file_name": download_name,
            "file_size": file_size,
            "safe_mode": settings.get("safe_mode", False),
            "zip_password": settings.get("zip_password", ""),
        }

        queue.push(task)

        await status.edit_text(
            f"در صف قرار گرفت.\n\n"
            f"فایل: `{download_name}`\n"
            f"حجم: `{pretty_size(file_size)}`\n"
            f"شناسه: `{task['job_id']}`\n\n"
            f"برای حذف این مورد از صف:\n"
            f"`/del {task['job_id']}`"
        )

    except Exception as e:
        await status.edit_text(f"خطا: {str(e)}")

def clear_old_status():
    try:
        if STATUS_FILE.exists():
            STATUS_FILE.unlink()
    except Exception:
        pass

if __name__ == "__main__":
    clear_old_status()
    app.start()
    app.loop.create_task(status_watcher())
    idle()
    app.stop()