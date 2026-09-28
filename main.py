# -*- coding: utf-8 -*-
"""
بات علوم 802 سید رضی - Bale Bot API
نسخه: 1.0

امکانات:
- پیوی: سؤالات متن / نمونه سؤال با دکمه‌های شیشه‌ای (Inline Keyboard)
- فهرست 15 فصل علوم هشتم و ارسال PDF هر فصل
- گروه: فعال‌سازی با «فعال»
- حذف لینک‌ها، استیکرها و GIF/Animation
- تشخیص فحش و پیام‌های تهاجمی و سکوت 5 روزه
- تشخیص درگیری دو نفره (heuristic) و سکوت هر دو نفر برای 5 روز
- گزارش تخلف به ادمین‌هایی که با /admin در پیوی ثبت شده‌اند
- ذخیره اطلاعات در data.json
- دریافت Update با getUpdates (Long Polling)

نیازمندی‌ها:
    pip install -r requirements.txt
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import aiohttp
from moderation import contains_profanity


# ============================================================
# تنظیمات
# ============================================================

TOKEN = os.getenv("BALE_TOKEN", "910778897:LmrqWY0tz23lwohVxW_-jKj9EWtXRRNHoS8")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"
BOT_NAME = "بات علوم 802 سید رضی"
ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
TEXT_PDF_DIR = ROOT / "pdfs" / "text"
SAMPLE_PDF_DIR = ROOT / "pdfs" / "samples"

MUTE_SECONDS = 5 * 24 * 60 * 60  # پنج روز
FIGHT_WINDOW = 120  # دو دقیقه برای تشخیص تعامل تهاجمی دو نفره
ADMIN_CACHE_TTL = 60

# 15 فصل علوم تجربی پایه هشتم
LESSONS = {
    1: ("فصل ۱ — مخلوط و جداسازی مواد", TEXT_PDF_DIR / "01.pdf"),
    2: ("فصل ۲ — تغییرهای شیمیایی در خدمت زندگی", TEXT_PDF_DIR / "02.pdf"),
    3: ("فصل ۳ — از درون اتم چه خبر", TEXT_PDF_DIR / "03.pdf"),
    4: ("فصل ۴ — تنظیم عصبی", TEXT_PDF_DIR / "04.pdf"),
    5: ("فصل ۵ — حس و حرکت", TEXT_PDF_DIR / "05.pdf"),
    6: ("فصل ۶ — تنظیم هورمونی", TEXT_PDF_DIR / "06.pdf"),
    7: ("فصل ۷ — الفبای زیست فناوری", TEXT_PDF_DIR / "07.pdf"),
    8: ("فصل ۸ — تولید مثل در جانداران", TEXT_PDF_DIR / "08.pdf"),
    9: ("فصل ۹ — الکتریسیته", TEXT_PDF_DIR / "09.pdf"),
    10: ("فصل ۱۰ — مغناطیس", TEXT_PDF_DIR / "10.pdf"),
    11: ("فصل ۱۱ — کانی‌ها", TEXT_PDF_DIR / "11.pdf"),
    12: ("فصل ۱۲ — سنگ‌ها", TEXT_PDF_DIR / "12.pdf"),
    13: ("فصل ۱۳ — هوازدگی", TEXT_PDF_DIR / "13.pdf"),
    14: ("فصل ۱۴ — نور و ویژگی‌های آن", TEXT_PDF_DIR / "14.pdf"),
    15: ("فصل ۱۵ — شکست نور", TEXT_PDF_DIR / "15.pdf"),
}

SAMPLES = {
    "first": ("نمونه سؤال نوبت اول", SAMPLE_PDF_DIR / "first_term.pdf"),
    "second": ("نمونه سؤال نوبت دوم", SAMPLE_PDF_DIR / "second_term.pdf"),
    "comprehensive": ("نمونه سؤال جامع", SAMPLE_PDF_DIR / "comprehensive.pdf"),
}

# توجه: این فهرست عمداً قابل ویرایش نگه داشته شده است.
# برای پوشش واژگان بیشتر می‌توانی موردهای جدید اضافه کنی.
# فیلتر چندزبانه از moderation.py استفاده می‌کند.
# فهرست واژه‌ها داخل سورس بات کپی نشده است.
FIGHT_WORDS = {
    "دعوا",
    "درگیری",
    "خفه شو",
    "گمشو",
    "می‌کشمت",
    "می کشمت",
    "بزن بریم",
    "بیا بیرون",
}

URL_RE = re.compile(
    r"(?i)(?:https?://|www\.|t\.me/|telegram\.me/|ble\.ir/|bale\.ai/|https?://ble\.ir|https?://bale\.ai)\S+"
)


# ============================================================
# ابزارهای عمومی
# ============================================================


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    text = text.replace("ۀ", "ه").replace("ة", "ه")
    text = text.replace("‌", " ")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def contains_any(text: str, words: set[str]) -> bool:
    normalized = normalize_text(text)
    # بررسی با فاصله/مرز تقریبی برای کاهش match اشتباه
    for word in words:
        w = normalize_text(word)
        if w and w in normalized:
            return True
    return False


def has_link(message: dict[str, Any]) -> bool:
    text = (message.get("text") or "") + "\n" + (message.get("caption") or "")
    return bool(URL_RE.search(text))


def user_display(user: dict[str, Any] | None) -> str:
    if not user:
        return "کاربر ناشناس"
    first = (user.get("first_name") or "").strip()
    last = (user.get("last_name") or "").strip()
    name = " ".join(x for x in (first, last) if x).strip() or "بدون نام"
    username = user.get("username")
    if username:
        return f"{name} (@{username})"
    return name


def user_id(user: dict[str, Any] | None) -> int | None:
    value = (user or {}).get("id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ============================================================
# ذخیره‌سازی JSON
# ============================================================

class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = asyncio.Lock()
        self.data: dict[str, Any] = {
            "admins": [],
            "active_groups": {},
        }

    def load(self) -> None:
        if not self.path.exists():
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.data, dict):
                raise ValueError("data.json is not an object")
            self.data.setdefault("admins", [])
            self.data.setdefault("active_groups", {})
        except Exception:
            # فایل خراب را از بین نمی‌بریم؛ یک ساختار سالم می‌سازیم.
            backup = self.path.with_suffix(".broken.json")
            try:
                self.path.replace(backup)
            except Exception:
                pass
            self.data = {"admins": [], "active_groups": {}}
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    async def save(self) -> None:
        async with self.lock:
            temp = self.path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp.replace(self.path)

    def is_admin(self, uid: int | None) -> bool:
        return uid is not None and int(uid) in {int(x) for x in self.data.get("admins", [])}

    def admins(self) -> list[int]:
        result: list[int] = []
        for x in self.data.get("admins", []):
            try:
                result.append(int(x))
            except (TypeError, ValueError):
                continue
        return result

    def is_active(self, chat_id: int | str) -> bool:
        return bool(self.data["active_groups"].get(str(chat_id), False))

    async def set_active(self, chat_id: int | str, active: bool) -> None:
        self.data["active_groups"][str(chat_id)] = bool(active)
        await self.save()

    async def add_admin(self, uid: int) -> None:
        ids = self.admins()
        if uid not in ids:
            ids.append(uid)
            self.data["admins"] = ids
            await self.save()


# ============================================================
# API بله
# ============================================================

class BaleAPI:
    def __init__(self, token: str):
        self.token = token
        self.base = f"https://tapi.bale.ai/bot{token}"
        self.file_base = f"https://tapi.bale.ai/file/bot{token}"
        self.session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        timeout = aiohttp.ClientTimeout(total=70)
        self.session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def call(self, method: str, data: dict[str, Any] | None = None) -> Any:
        if self.session is None:
            raise RuntimeError("HTTP session is not started")

        url = f"{self.base}/{method}"
        payload = data or {}
        last_error = None
        for attempt in range(3):
            try:
                async with self.session.post(url, json=payload) as resp:
                    raw = await resp.text()
                    try:
                        result = json.loads(raw)
                    except json.JSONDecodeError:
                        raise RuntimeError(f"Bale returned non-JSON: HTTP {resp.status} {raw[:300]}")
                    if not result.get("ok"):
                        raise RuntimeError(
                            f"Bale API error in {method}: {result.get('error_code')} {result.get('description')}"
                        )
                    return result.get("result")
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
                last_error = exc
                # خطاهای API را بی‌جهت سریع تکرار نکن.
                await asyncio.sleep(1.5 * (attempt + 1))
        raise last_error if last_error else RuntimeError(f"Unknown error calling {method}")

    async def call_multipart(self, method: str, form: aiohttp.FormData) -> Any:
        if self.session is None:
            raise RuntimeError("HTTP session is not started")
        url = f"{self.base}/{method}"
        async with self.session.post(url, data=form) as resp:
            raw = await resp.text()
            result = json.loads(raw)
            if not result.get("ok"):
                raise RuntimeError(
                    f"Bale API error in {method}: {result.get('error_code')} {result.get('description')}"
                )
            return result.get("result")

    async def get_updates(self, offset: int | None, timeout: int = 35) -> list[dict[str, Any]]:
        data: dict[str, Any] = {"limit": 100, "timeout": timeout}
        if offset is not None:
            data["offset"] = offset
        result = await self.call("getUpdates", data)
        return result if isinstance(result, list) else []

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> Any:
        data: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            data["reply_markup"] = reply_markup
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = reply_to_message_id
        return await self.call("sendMessage", data)

    async def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        data: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup is not None:
            data["reply_markup"] = reply_markup
        return await self.call("editMessageText", data)

    async def answer_callback(self, callback_id: str, text: str = "") -> Any:
        return await self.call(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": text},
        )

    async def delete_message(self, chat_id: int | str, message_id: int) -> Any:
        return await self.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    async def get_me(self) -> dict[str, Any]:
        return await self.call("getMe")

    async def delete_webhook(self) -> Any:
        return await self.call("deleteWebhook")

    async def get_chat_member(self, chat_id: int | str, uid: int) -> dict[str, Any]:
        return await self.call("getChatMember", {"chat_id": chat_id, "user_id": uid})

    async def get_chat_administrators(self, chat_id: int | str) -> list[dict[str, Any]]:
        result = await self.call("getChatAdministrators", {"chat_id": chat_id})
        return result if isinstance(result, list) else []

    async def restrict_chat_member(self, chat_id: int | str, uid: int, until_date: int | None = None) -> Any:
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "user_id": uid,
            "can_send_messages": False,
            "can_send_media_messages": False,
            "can_send_other_messages": False,
            "can_add_web_page_previews": False,
        }
        if until_date is not None:
            data["until_date"] = until_date
        return await self.call("restrictChatMember", data)

    async def send_document(
        self,
        chat_id: int | str,
        file_path: Path,
        caption: str | None = None,
    ) -> Any:
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(file_path)
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        if caption:
            form.add_field("caption", caption)
        with file_path.open("rb") as fh:
            form.add_field(
                "document",
                fh,
                filename=file_path.name,
                content_type="application/pdf",
            )
            # چون file handle داخل context باز است، خود درخواست همین جا انجام می‌شود.
            return await self.call_multipart("sendDocument", form)


# ============================================================
# کیبوردها
# ============================================================


def btn(text: str, callback_data: str) -> dict[str, str]:
    return {"text": text, "callback_data": callback_data}


def main_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [btn("📘 سؤالات متن", "text_questions")],
            [btn("📝 نمونه سؤال", "samples")],
        ]
    }


def lessons_keyboard() -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for number, (title, _) in LESSONS.items():
        row.append(btn(str(number), f"lesson:{number}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn("↩️ بازگشت", "home")])
    return {"inline_keyboard": rows}


def samples_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [btn("نوبت اول", "sample:first")],
            [btn("نوبت دوم", "sample:second")],
            [btn("جامع", "sample:comprehensive")],
            [btn("↩️ بازگشت", "home")],
        ]
    }


# ============================================================
# بات اصلی
# ============================================================

class ScienceBot:
    def __init__(self, api: BaleAPI, store: Store):
        self.api = api
        self.store = store
        self.bot_id: int | None = None
        self.bot_name = BOT_NAME
        self.admin_cache: dict[int, tuple[float, set[int]]] = {}
        # chat_id -> (last_user_id, timestamp, display)
        self.recent_aggressive: dict[int, tuple[int, float, str]] = {}

    async def startup(self) -> None:
        self.store.load()
        await self.api.start()
        await self.api.delete_webhook()
        me = await self.api.get_me()
        self.bot_id = user_id(me)
        self.bot_name = me.get("first_name") or BOT_NAME
        print(f"[{self.bot_name}] started | id={self.bot_id}")
        print(f"admins={self.store.admins()}")

    async def safe_send(self, chat_id: int | str, text: str, **kwargs: Any) -> None:
        try:
            await self.api.send_message(chat_id, text, **kwargs)
        except Exception as exc:
            print("send_message error:", exc)

    async def report(self, message: dict[str, Any], reason: str, extra: str = "") -> None:
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_title = chat.get("title") or chat.get("username") or str(chat.get("id"))
        uid = user_id(sender)
        suffix = f"\n{extra}" if extra else ""
        text = (
            "🚨 گزارش نظارت بات علوم 802 سید رضی\n\n"
            f"گروه: {chat_title}\n"
            f"کاربر: {user_display(sender)}\n"
            f"شناسه: {uid}\n"
            f"نوع تخلف: {reason}{suffix}"
        )
        for admin_id in self.store.admins():
            await self.safe_send(admin_id, text)

    async def get_group_admin_ids(self, chat_id: int) -> set[int]:
        now = time.time()
        cached = self.admin_cache.get(chat_id)
        if cached and now - cached[0] < ADMIN_CACHE_TTL:
            return cached[1]
        try:
            admins = await self.api.get_chat_administrators(chat_id)
        except Exception as exc:
            print("get_chat_administrators error:", exc)
            return set()
        ids = {uid for uid in (user_id(x.get("user")) for x in admins) if uid is not None}
        self.admin_cache[chat_id] = (now, ids)
        return ids

    async def bot_can_moderate(self, chat_id: int) -> tuple[bool, str]:
        if self.bot_id is None:
            return False, "شناسه بات مشخص نیست"
        try:
            member = await self.api.get_chat_member(chat_id, self.bot_id)
        except Exception as exc:
            return False, str(exc)
        status = member.get("status")
        if status not in {"administrator", "creator"}:
            return False, "بات ادمین گروه نیست."
        if status == "creator":
            return True, ""
        if member.get("can_delete_messages") is not True:
            return False, "دسترسی حذف پیام ندارد."
        if member.get("can_restrict_members") is not True:
            return False, "دسترسی محدود کردن اعضا ندارد."
        return True, ""

    async def activate_group(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        sender_id = user_id(message.get("from"))
        if chat.get("type") not in {"group", "supergroup"} or chat_id is None:
            return

        admins = await self.get_group_admin_ids(int(chat_id))
        if sender_id not in admins:
            await self.safe_send(chat_id, "❌ فقط مدیران گروه می‌توانند بات را فعال کنند.")
            return

        can_mod, reason = await self.bot_can_moderate(int(chat_id))
        if not can_mod:
            await self.safe_send(
                chat_id,
                "❌ برای فعال‌سازی، بات باید مدیر باشد و دسترسی حذف پیام و محدود کردن اعضا را داشته باشد.\n\n"
                f"دلیل: {reason}",
            )
            return

        await self.store.set_active(chat_id, True)
        await self.safe_send(chat_id, "✅ بات علوم 802 سید رضی فعال شد.\nنظارت گروه شروع شد.")

    async def handle_private_admin(self, message: dict[str, Any]) -> None:
        uid = user_id(message.get("from"))
        chat_id = (message.get("chat") or {}).get("id")
        if uid is None or chat_id is None:
            return

        admins = self.store.admins()
        if not admins:
            await self.store.add_admin(uid)
            await self.safe_send(
                chat_id,
                "✅ شما به‌عنوان ادمین اولیه بات ثبت شدید.\nاز این به بعد گزارش تخلفات گروه به این پیوی ارسال می‌شود.",
            )
            return

        if self.store.is_admin(uid):
            await self.safe_send(chat_id, "✅ شما از قبل به‌عنوان ادمین ثبت شده‌اید.")
        else:
            await self.safe_send(chat_id, "❌ این دستور فقط برای ادمین‌های ثبت‌شده فعال است.")

    async def handle_private_message(self, message: dict[str, Any]) -> None:
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None:
            return
        uid = user_id(message.get("from"))
        text = normalize_text(message.get("text"))

        if text == "/admin":
            await self.handle_private_admin(message)
            return

        if text.startswith("/start") or text in {"درود", "سلام", "شروع"}:
            await self.safe_send(
                chat_id,
                "درود 👋\n\nبرای دریافت فایل‌های علوم هشتم از گزینه‌های زیر اقدام فرمایید:",
                reply_markup=main_keyboard(),
            )
            return

        if text == "/status":
            await self.safe_send(
                chat_id,
                f"وضعیت بات: ✅ فعال\nادمین ثبت‌شده: {self.store.is_admin(uid)}\nگروه‌های فعال: {sum(1 for x in self.store.data.get('active_groups', {}).values() if x)}",
            )
            return

    async def handle_callback(self, cq: dict[str, Any]) -> None:
        callback_id = str(cq.get("id") or "")
        from_user = cq.get("from") or {}
        uid = user_id(from_user)
        data = str(cq.get("data") or "")
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        msg_id = msg.get("message_id")

        try:
            await self.api.answer_callback(callback_id)
        except Exception:
            pass

        if chat.get("type") != "private" or chat_id is None or msg_id is None:
            return
        if uid is None:
            return

        if data == "home":
            await self.api.edit_message_text(
                chat_id,
                msg_id,
                "درود 👋\n\nبرای دریافت فایل‌های علوم هشتم از گزینه‌های زیر اقدام فرمایید:",
                main_keyboard(),
            )
            return

        if data == "text_questions":
            await self.api.edit_message_text(
                chat_id,
                msg_id,
                "📘 سؤالات متن\n\nشماره فصل موردنظر را انتخاب کنید:",
                lessons_keyboard(),
            )
            return

        if data == "samples":
            await self.api.edit_message_text(
                chat_id,
                msg_id,
                "📝 نمونه سؤال\n\nنوع نمونه سؤال را انتخاب کنید:",
                samples_keyboard(),
            )
            return

        if data.startswith("lesson:"):
            try:
                number = int(data.split(":", 1)[1])
            except ValueError:
                return
            item = LESSONS.get(number)
            if not item:
                return
            title, path = item
            await self.safe_send(chat_id, f"📚 {title}\n\nفایل در حال ارسال است...")
            if not path.exists():
                await self.safe_send(
                    chat_id,
                    f"⚠️ PDF این فصل هنوز در پوشه `pdfs/text` قرار نگرفته است.\nنام فایل مورد انتظار: `{path.name}`",
                )
                return
            try:
                await self.api.send_document(chat_id, path, caption=f"📘 {title}\n{BOT_NAME}")
            except Exception as exc:
                await self.safe_send(chat_id, f"❌ خطا در ارسال PDF: {exc}")
            return

        if data.startswith("sample:"):
            key = data.split(":", 1)[1]
            item = SAMPLES.get(key)
            if not item:
                return
            title, path = item
            await self.safe_send(chat_id, f"📝 {title}\n\nفایل در حال ارسال است...")
            if not path.exists():
                await self.safe_send(
                    chat_id,
                    f"⚠️ PDF این مورد هنوز در پوشه `pdfs/samples` قرار نگرفته است.\nنام فایل مورد انتظار: `{path.name}`",
                )
                return
            try:
                await self.api.send_document(chat_id, path, caption=f"📝 {title}\n{BOT_NAME}")
            except Exception as exc:
                await self.safe_send(chat_id, f"❌ خطا در ارسال PDF: {exc}")
            return

    async def punish_mute(self, message: dict[str, Any], reason: str) -> None:
        chat_id = (message.get("chat") or {}).get("id")
        uid = user_id(message.get("from"))
        if chat_id is None or uid is None:
            return
        try:
            until = int(time.time()) + MUTE_SECONDS
            await self.api.restrict_chat_member(int(chat_id), uid, until)
        except Exception as exc:
            print("restrictChatMember error:", exc)
            await self.report(message, reason, "⚠️ حذف انجام شد، اما سکوت ۵ روزه اجرا نشد؛ دسترسی API را بررسی کنید.")
            return
        await self.report(message, reason, "🔇 مدت سکوت: ۵ روز")

    async def moderate_group_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat.get("type") not in {"group", "supergroup"} or chat_id is None:
            return
        chat_id = int(chat_id)

        if not self.store.is_active(chat_id):
            return

        sender = message.get("from") or {}
        uid = user_id(sender)
        if uid is None:
            return
        if self.bot_id is not None and uid == self.bot_id:
            return

        # مدیران استثنا هستند.
        admins = await self.get_group_admin_ids(chat_id)
        if uid in admins:
            return

        message_id = message.get("message_id")
        if message_id is None:
            return

        # لینک
        if has_link(message):
            try:
                await self.api.delete_message(chat_id, int(message_id))
            except Exception as exc:
                print("delete link error:", exc)
            await self.report(message, "لینک")
            return

        # استیکر
        if message.get("sticker") is not None:
            try:
                await self.api.delete_message(chat_id, int(message_id))
            except Exception as exc:
                print("delete sticker error:", exc)
            await self.report(message, "استیکر")
            return

        # GIF / Animation
        if message.get("animation") is not None:
            try:
                await self.api.delete_message(chat_id, int(message_id))
            except Exception as exc:
                print("delete animation error:", exc)
            await self.report(message, "GIF / انیمیشن")
            return

        text = normalize_text(message.get("text") or message.get("caption") or "")
        bad = contains_profanity(text)
        aggressive = contains_any(text, FIGHT_WORDS)

        # فحش یا پیام تهاجمی: حذف + سکوت ۵ روز
        if bad or aggressive:
            reason = "فحش" if bad else "پیام تهاجمی / بحث"
            try:
                await self.api.delete_message(chat_id, int(message_id))
            except Exception as exc:
                print("delete bad-message error:", exc)
            await self.punish_mute(message, reason)

            # درگیری دو نفره: اگر شخص دیگری اخیراً پیام تهاجمی داده باشد، هر دو سکوت می‌شوند.
            now = time.time()
            previous = self.recent_aggressive.get(chat_id)
            current_display = user_display(sender)
            if previous:
                previous_uid, previous_time, previous_display = previous
                if previous_uid != uid and now - previous_time <= FIGHT_WINDOW:
                    # کاربر قبلی را هم محدود کن.
                    try:
                        await self.api.restrict_chat_member(
                            chat_id,
                            previous_uid,
                            int(now) + MUTE_SECONDS,
                        )
                        await self.safe_send(
                            self.store.admins()[0] if self.store.admins() else uid,
                            "🚨 تشخیص درگیری دو نفره:\n\n"
                            f"نفر اول: {previous_display}\n"
                            f"نفر دوم: {current_display}\n"
                            "🔇 هر دو نفر برای ۵ روز محدود شدند.",
                        )
                    except Exception as exc:
                        print("second-user mute error:", exc)
            self.recent_aggressive[chat_id] = (uid, now, current_display)
            return

        # پیام عادی: ورودی اخیر تهاجمی را منقضی کن.
        previous = self.recent_aggressive.get(chat_id)
        if previous and time.time() - previous[1] > FIGHT_WINDOW:
            self.recent_aggressive.pop(chat_id, None)

    async def handle_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        chat_type = chat.get("type")
        text = normalize_text(message.get("text"))

        if chat_type == "private":
            await self.handle_private_message(message)
            return

        if chat_type in {"group", "supergroup"}:
            if text == "فعال":
                await self.activate_group(message)
                return
            await self.moderate_group_message(message)
            return

    async def handle_update(self, update: dict[str, Any]) -> None:
        if update.get("callback_query") is not None:
            await self.handle_callback(update["callback_query"])
            return
        if update.get("message") is not None:
            await self.handle_message(update["message"])

    async def run(self) -> None:
        await self.startup()
        offset: int | None = None
        try:
            while True:
                try:
                    updates = await self.api.get_updates(offset, timeout=35)
                    for update in updates:
                        try:
                            await self.handle_update(update)
                        except Exception as exc:
                            print("update handler error:", exc)
                        try:
                            update_id = int(update.get("update_id"))
                            if offset is None or update_id >= offset:
                                offset = update_id + 1
                        except (TypeError, ValueError):
                            pass
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print("polling error:", exc)
                    await asyncio.sleep(3)
        finally:
            await self.api.close()


async def main() -> None:
    if not TOKEN or TOKEN == "توکن_بات_را_اینجا_قرار_بده":
        raise SystemExit(
            "توکن بله تنظیم نشده است. مقدار BALE_TOKEN را در محیط قرار بده یا TOKEN را داخل main.py تنظیم کن."
        )

    api = BaleAPI(TOKEN)
    store = Store(DATA_FILE)
    bot = ScienceBot(api, store)
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped.")
