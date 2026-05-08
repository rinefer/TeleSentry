from telethon import TelegramClient, events
from models.config import api_id, api_hash, session_name, BOT_VERSION, ADMIN_IDS, NOTIFY_CHAT_ID, media_folder, txt_logs_folder, DEVICE_SETTINGS
from models.database import conn, cursor
from models.media_handler import save_media, save_to_txt, send_notification
import datetime
import os

# Global message cache
message_cache = {}

# Initialize client with device masking
client = TelegramClient(
    session_name,
    api_id,
    api_hash,
    device_model=DEVICE_SETTINGS['device_model'],
    app_version=DEVICE_SETTINGS['app_version'],
    system_version=DEVICE_SETTINGS['system_version'],
    lang_code=DEVICE_SETTINGS['lang_code'],
    system_lang_code=DEVICE_SETTINGS['system_lang_code'],
    flood_sleep_threshold=DEVICE_SETTINGS['flood_sleep_threshold']
)

# Register handlers from other modules
from models.admin_tools import register_handlers as register_admin_handlers
from models.utils import register_handlers as register_utils_handlers
from models.parsers import register_handlers as register_parsers_handlers
from models.downloader import register_handlers as register_downloader_handlers
from models.osint import register_handlers as register_osint_handlers
from models.chat_logger import register_handlers as register_chat_logger_handlers
from models.invite_manager import register_handlers as register_invite_handlers
from models.global_search import register_handlers as register_global_search_handlers

register_admin_handlers(client)
register_utils_handlers(client)
register_parsers_handlers(client)
register_downloader_handlers(client)
register_osint_handlers(client)
register_chat_logger_handlers(client)
register_invite_handlers(client)
register_global_search_handlers(client)

@client.on(events.NewMessage(incoming=True))
async def handle_new_message(event):
    """Handle incoming messages and save them to cache"""
    if event.is_private:
        try:
            chat = await event.get_chat()
            sender = await event.get_sender()

            # Verify objects are obtained
            if not chat or not sender:
                print(f"[ERROR] Failed to get chat or sender for message {event.message.id}")
                return

            media_path, media_type, is_view_once = await save_media(event.message, media_folder)

            # Determine message type
            if is_view_once:
                msg_type = "🔥 SELF-DESTRUCTING"
            elif media_type:
                msg_type = f"📷 {media_type.upper()}"
            else:
                msg_type = "📝 TEXT"

            message_cache[event.message.id] = {
                "chat_id": chat.id,
                "chat_name": getattr(chat, 'first_name', 'Unknown') or getattr(chat, 'title', 'Unknown'),
                "sender_id": sender.id,
                "sender_name": getattr(sender, 'first_name', 'Unknown') or getattr(sender, 'username', 'Unknown'),
                "text": event.message.text,
                "date": event.message.date,
                "media_path": media_path,
                "media_type": media_type,
                "is_view_once": is_view_once,
                "message_type": msg_type
            }
        except Exception as e:
            print(f"[ERROR] in handle_new_message: {e}")

@client.on(events.MessageDeleted())
async def handle_deleted_messages(event):
    """Handle deleted messages and save them to database"""
    for msg_id in event.deleted_ids:
        if msg_id in message_cache:
            msg = message_cache[msg_id]
            try:
                cursor.execute('''
                INSERT INTO deleted_messages
                (chat_id, chat_name, sender_id, sender_name, message_text,
                 message_date, deleted_at, media_path, media_type, is_view_once)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    msg["chat_id"],
                    msg["chat_name"],
                    msg["sender_id"],
                    msg["sender_name"],
                    msg["text"],
                    msg["date"],
                    datetime.datetime.now(),
                    msg["media_path"],
                    msg["media_type"],
                    1 if msg.get("is_view_once") else 0
                ))
                conn.commit()

                current_time = datetime.datetime.now().strftime("%d.%m.%Y_%H-%M-%S")
                txt_filename = f"deleted_messages_{current_time}.txt"
                txt_filepath = os.path.join(txt_logs_folder, txt_filename)
                save_to_txt(msg, txt_filepath)

                await send_notification(msg, client)
                print(f"💾 Saved deleted message from {msg['sender_name']} {'🔥' if msg.get('is_view_once') else ''}")
            except Exception as e:
                print(f"Error saving: {e}")

# ===== BOT STARTUP =====
print("Bot started...")
print(f"Admins: {ADMIN_IDS}")
print(f"Notifications: {NOTIFY_CHAT_ID if NOTIFY_CHAT_ID else 'disabled'}")
print(f"Device masking: {DEVICE_SETTINGS['device_model']} ({DEVICE_SETTINGS['system_version']})")

client.start()
client.run_until_disconnected()
