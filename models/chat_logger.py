from telethon import events, types
import sqlite3
import datetime
import os
import csv
from models.config import txt_logs_folder, ADMIN_IDS, LOG_CHAT_ID

# Database path for chat logs
LOG_DB_PATH = os.path.join(txt_logs_folder, 'chat_logs.db')

def init_db():
    """Initialize database for storing chat logs and tracked chats"""
    conn = sqlite3.connect(LOG_DB_PATH)
    cursor = conn.cursor()

    # Create table for tracked chats
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tracked_chats (
        chat_id INTEGER,
        user_id INTEGER,
        target_chat_id INTEGER,
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (chat_id, user_id)
    )
    ''')

    # Create table for message logs
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS message_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        user_id INTEGER,
        message_text TEXT,
        message_date DATETIME,
        logged_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()

init_db()

async def is_admin(event):
    """Check if user has admin privileges"""
    from models.admin_tools import is_admin
    return await is_admin(event)

def get_logged_chats():
    """Get list of currently tracked chats"""
    conn = sqlite3.connect(LOG_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id, user_id, target_chat_id FROM tracked_chats')
    chats = cursor.fetchall()
    conn.close()
    return chats

def add_tracked_chat(chat_id, user_id, target_chat_id=None):
    """Add chat to tracking list"""
    conn = sqlite3.connect(LOG_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
        INSERT OR REPLACE INTO tracked_chats (chat_id, user_id, target_chat_id)
        VALUES (?, ?, ?)
        ''', (chat_id, user_id, target_chat_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding chat to tracking: {e}")
        return False
    finally:
        conn.close()

def remove_tracked_chat(chat_id, user_id=None):
    """Remove chat from tracking list"""
    conn = sqlite3.connect(LOG_DB_PATH)
    cursor = conn.cursor()
    try:
        if user_id:
            cursor.execute('DELETE FROM tracked_chats WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
        else:
            cursor.execute('DELETE FROM tracked_chats WHERE chat_id = ?', (chat_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error removing chat from tracking: {e}")
        return False
    finally:
        conn.close()

def log_message(chat_id, user_id, message_text, message_date):
    """Log message to database"""
    conn = sqlite3.connect(LOG_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
        INSERT INTO message_logs (chat_id, user_id, message_text, message_date)
        VALUES (?, ?, ?, ?)
        ''', (chat_id, user_id, message_text, message_date))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error logging message: {e}")
        return False
    finally:
        conn.close()

def export_logs_to_csv(chat_id, filepath):
    """Export chat logs to CSV file"""
    conn = sqlite3.connect(LOG_DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
        SELECT user_id, message_text, message_date
        FROM message_logs
        WHERE chat_id = ?
        ORDER BY message_date
        ''', (chat_id,))

        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['User ID', 'Message Text', 'Message Date'])
            writer.writerows(cursor.fetchall())

        return True
    except Exception as e:
        print(f"Error exporting logs: {e}")
        return False
    finally:
        conn.close()

def register_handlers(client):
    """Register handlers for chat logging functionality"""

    @client.on(events.NewMessage(incoming=True))
    async def handle_incoming_messages(event):
        """Handle incoming messages for logging purposes"""
        try:
            # Check if this message should be logged
            logged_chats = get_logged_chats()
            if not logged_chats:
                return

            chat_id = event.chat_id
            user_id = event.sender_id

            # Check if we're logging this chat/user
            for lc_chat_id, lc_user_id, target_chat_id in logged_chats:
                if (lc_chat_id == chat_id and lc_user_id == user_id) or (lc_chat_id == chat_id and not lc_user_id):
                    # Only log text messages without media
                    if event.text and not event.media:
                        message_text = event.text
                        message_date = event.date
                        log_message(chat_id, user_id, message_text, message_date)
                    break

        except Exception as e:
            print(f"Error processing incoming message: {e}")

    @client.on(events.NewMessage(pattern='/logg_user'))
    async def handle_log_user(event):
        """Handler for /logg_user command - start logging user messages in chat"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split()
        if len(args) < 2:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/logg_user chat_id [user_id]</code>\n\n"
                "Examples:\n"
                "<code>/logg_user -100123456789 123456789</code> - log specific user\n"
                "<code>/logg_user -100123456789</code> - log all users in chat\n\n"
                "chat_id - Chat ID (get it with /myid)\n"
                "user_id - User ID to track (optional)"
            )
            return

        try:
            chat_id = int(args[1])
            user_id = int(args[2]) if len(args) > 2 else None

            if add_tracked_chat(chat_id, user_id):
                if user_id:
                    await event.reply(f"✅ Started logging messages from user {user_id} in chat {chat_id}")
                    # Add user to profile monitoring
                    from .logg_chat.profile_monitor import add_monitored_user
                    add_monitored_user(user_id, event.chat_id)
                else:
                    await event.reply(f"✅ Started logging all messages in chat {chat_id}")
            else:
                await event.reply("❌ Could not start logging")

        except ValueError:
            await event.reply("⚠️ Invalid chat or user ID")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(pattern='/stoplogg'))
    async def handle_stop_logging(event):
        """Handler for /stoplogg command - stop logging in chat"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split()
        if len(args) < 2:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/stoplogg chat_id [user_id]</code>\n\n"
                "Examples:\n"
                "<code>/stoplogg -100123456789</code> - stop logging entire chat\n"
                "<code>/stoplogg -100123456789 123456789</code> - stop logging specific user"
            )
            return

        try:
            chat_id = int(args[1])
            user_id = int(args[2]) if len(args) > 2 else None

            if remove_tracked_chat(chat_id, user_id):
                if user_id:
                    await event.reply(f"✅ Stopped logging user {user_id} in chat {chat_id}")
                    # Remove user from profile monitoring
                    from .logg_chat.profile_monitor import remove_monitored_user
                    remove_monitored_user(user_id)
                else:
                    await event.reply(f"✅ Stopped logging in chat {chat_id}")
            else:
                await event.reply("❌ Could not stop logging")

        except ValueError:
            await event.reply("⚠️ Invalid chat or user ID")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(pattern='/export_logs'))
    async def handle_export_logs(event):
        """Handler for /export_logs command - export logs to CSV"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split()
        if len(args) < 2:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/export_logs chat_id</code>\n\n"
                "Example:\n"
                "<code>/export_logs -100123456789</code>"
            )
            return

        try:
            chat_id = int(args[1])
            current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"chat_logs_{chat_id}_{current_time}.csv"
            filepath = os.path.join(txt_logs_folder, filename)

            if export_logs_to_csv(chat_id, filepath):
                await event.reply(
                    f"✅ Logs for chat {chat_id} exported to file:",
                    file=filepath
                )
            else:
                await event.reply("❌ Could not export logs")

        except ValueError:
            await event.reply("⚠️ Invalid chat ID")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(pattern='/list_logged'))
    async def handle_list_logged(event):
        """Handler for /list_logged command - show list of tracked chats"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        try:
            logged_chats = get_logged_chats()
            if not logged_chats:
                await event.reply("ℹ️ No chats being logged")
                return

            message = "📋 <b>Tracked chats:</b>\n\n"
            for chat_id, user_id, target_chat_id in logged_chats:
                if user_id:
                    message += (
                        f"🆔 <b>Chat:</b> <code>{chat_id}</code>\n"
                        f"👤 <b>User:</b> <code>{user_id}</code>\n\n"
                    )
                else:
                    message += f"🆔 <b>Chat:</b> <code>{chat_id}</code> (all users)\n\n"

            await event.reply(message, parse_mode='HTML')

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # Import and start profile monitoring
    from .logg_chat.profile_monitor import start_profile_monitoring, register_monitoring_handlers
    start_profile_monitoring(client)
    register_monitoring_handlers(client)
