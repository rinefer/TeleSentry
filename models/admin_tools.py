from telethon import events, Button
from models.config import ADMIN_IDS, NOTIFY_CHAT_ID, txt_logs_folder, media_folder
from models.database import conn, cursor, get_user_count
import datetime
import os

async def is_admin(event):
    """Check if user has admin privileges by comparing their ID with ADMIN_IDS list"""
    try:
        user_id = event.sender_id
        return user_id in ADMIN_IDS
    except Exception as e:
        print(f"Error in is_admin: {e}")
        return False

def register_handlers(client):
    """Register handlers for admin commands"""

    @client.on(events.NewMessage(pattern='/deleted'))
    async def show_deleted(event):
        """Show last 10 deleted messages with details"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        try:
            cursor.execute('''
            SELECT chat_name, sender_name, message_text, deleted_at, media_type, media_path, is_view_once
            FROM deleted_messages
            ORDER BY deleted_at DESC
            LIMIT 10
            ''')
            deleted_msgs = cursor.fetchall()

            if not deleted_msgs:
                await event.reply("📭 No saved deleted messages.")
                return

            response = "🗑 Last deleted messages:\n\n"
            for i, msg in enumerate(deleted_msgs, 1):
                chat_name, sender_name, text, deleted_at, media_type, media_path, is_view_once = msg

                # Add fire emoji for self-destructing messages
                fire_emoji = "🔥 " if is_view_once else ""

                media_info = ""
                if media_type:
                    media_info = f"📷 [{media_type}]"
                    if os.path.exists(media_path):
                        media_info += f" (file saved)"

                response += (
                    f"{i}. {fire_emoji}👤 {sender_name} (in chat with {chat_name})\n"
                    f"   🕒 {deleted_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"   📝 {text if text else media_info}\n\n"
                )

            await event.reply(response)
        except Exception as e:
            await event.reply(f"Error: {e}")

    @client.on(events.NewMessage(pattern='/viewonce'))
    async def show_view_once(event):
        """Show all saved self-destructing media (view-once messages)"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        try:
            cursor.execute('''
            SELECT chat_name, sender_name, message_text, deleted_at, media_type, media_path
            FROM deleted_messages
            WHERE media_type LIKE '%self_destruct%' OR is_view_once = 1
            ORDER BY deleted_at DESC
            LIMIT 20
            ''')
            view_once_msgs = cursor.fetchall()

            if not view_once_msgs:
                await event.reply("🔥 No saved self-destructing media (view-once messages).")
                return

            # Show list
            response = "🔥 **Saved self-destructing media:**\n\n"
            for i, msg in enumerate(view_once_msgs, 1):
                chat_name, sender_name, text, deleted_at, media_type, media_path = msg
                media_type_clean = media_type.replace('self_destruct_', '').upper()

                response += (
                    f"{i}. 👤 **{sender_name}** → {chat_name}\n"
                    f"   🕒 {deleted_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"   📁 Type: {media_type_clean}\n"
                )

                if text and text != 'No text':
                    response += f"   📝 Text: {text[:50]}...\n"

                response += "\n"

            await event.reply(response, parse_mode='markdown')

            # Offer to view first 5
            if len(view_once_msgs) > 0:
                buttons = []
                for i in range(min(5, len(view_once_msgs))):
                    buttons.append([Button.inline(f"🔥 Show #{i+1}", f"show_viewonce_{i}")])

                await event.reply("Select view-once media to view:", buttons=buttons)

        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    @client.on(events.CallbackQuery(pattern=b'show_viewonce_'))
    async def show_specific_view_once(event):
        """Show specific self-destructing media file"""
        if not await is_admin(event):
            await event.answer("Access denied!", alert=True)
            return

        try:
            index = int(event.data.decode().split('_')[-1])

            cursor.execute('''
            SELECT sender_name, message_text, media_type, media_path
            FROM deleted_messages
            WHERE media_type LIKE '%self_destruct%' OR is_view_once = 1
            ORDER BY deleted_at DESC
            LIMIT 1 OFFSET ?
            ''', (index,))

            msg = cursor.fetchone()
            if not msg:
                await event.answer("Media not found!", alert=True)
                return

            sender_name, text, media_type, media_path = msg

            if not os.path.exists(media_path):
                await event.answer("File not found on disk!", alert=True)
                return

            # Send media with caption
            caption = f"🔥 **SAVED VIEW-ONCE MEDIA**\n👤 From: {sender_name}\n💬 Text: {text if text else 'No text'}"

            if 'photo' in media_type:
                await event.client.send_file(
                    event.chat_id,
                    media_path,
                    caption=caption,
                    parse_mode='markdown',
                    reply_to=event.message_id
                )
            elif 'video' in media_type:
                await event.client.send_file(
                    event.chat_id,
                    media_path,
                    caption=caption,
                    supports_streaming=True,
                    parse_mode='markdown',
                    reply_to=event.message_id
                )
            else:
                await event.client.send_file(
                    event.chat_id,
                    media_path,
                    caption=caption,
                    force_document=True,
                    parse_mode='markdown',
                    reply_to=event.message_id
                )

            await event.answer("✅ View-once media sent!")

        except Exception as e:
            await event.answer(f"Error: {str(e)}", alert=True)

    @client.on(events.NewMessage(pattern='/media'))
    async def show_media(event):
        """Show all saved media files with details"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        try:
            cursor.execute('''
            SELECT sender_name, message_text, media_type, media_path, is_view_once
            FROM deleted_messages
            WHERE media_type IS NOT NULL
            ORDER BY deleted_at DESC
            LIMIT 15
            ''')
            media_files = cursor.fetchall()

            if not media_files:
                await event.reply("📭 No saved media files.")
                return

            response = "📁 **Saved media files:**\n\n"
            for i, media in enumerate(media_files, 1):
                sender_name, text, media_type, media_path, is_view_once = media

                # Add fire emoji for self-destructing media
                fire_emoji = "🔥 " if is_view_once else ""

                response += (
                    f"{i}. {fire_emoji}👤 From: {sender_name}\n"
                    f"   🖼 Type: {media_type}\n"
                )

                if text and text != 'No text':
                    response += f"   📝 Text: {text[:50]}...\n"

                response += "\n"

            await event.reply(response, parse_mode='markdown')

            # Send first 5 media files
            for media in media_files[:5]:
                _, _, media_type, media_path, is_view_once = media
                if os.path.exists(media_path):
                    try:
                        if media_type == 'photo' or 'photo' in media_type:
                            await event.reply(file=media_path)
                        elif media_type == 'video' or 'video' in media_type:
                            await event.reply(file=media_path, supports_streaming=True)
                        elif media_type == 'document' or 'document' in media_type:
                            await event.reply(file=media_path, force_document=True)
                    except Exception as e:
                        print(f"Error sending media: {e}")
        except Exception as e:
            await event.reply(f"Error: {e}")

    @client.on(events.NewMessage(pattern='/stats'))
    async def show_stats(event):
        """Show statistics about deleted messages and saved media"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        try:
            cursor.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN media_type IS NULL THEN 1 ELSE 0 END) as text_only,
                SUM(CASE WHEN media_type = 'photo' OR media_type = 'self_destruct_photo' THEN 1 ELSE 0 END) as photos,
                SUM(CASE WHEN media_type = 'video' OR media_type = 'self_destruct_video' THEN 1 ELSE 0 END) as videos,
                SUM(CASE WHEN media_type = 'document' OR media_type = 'self_destruct_document' THEN 1 ELSE 0 END) as documents,
                SUM(CASE WHEN is_view_once = 1 OR media_type LIKE '%self_destruct%' THEN 1 ELSE 0 END) as view_once
            FROM deleted_messages
            ''')
            total_stats = cursor.fetchone()

            cursor.execute('''
            SELECT
                sender_id,
                sender_name,
                COUNT(*) as delete_count,
                SUM(CASE WHEN is_view_once = 1 OR media_type LIKE '%self_destruct%' THEN 1 ELSE 0 END) as view_once_count
            FROM deleted_messages
            GROUP BY sender_id
            ORDER BY delete_count DESC
            LIMIT 5
            ''')
            top_users = cursor.fetchall()

            # Get count of unique users
            user_count = get_user_count()

            response = (
                "📊 **Statistics:**\n"
                f"• Total messages: {total_stats[0]}\n"
                f"• Text only: {total_stats[1]}\n"
                f"• Photos: {total_stats[2]}\n"
                f"• Videos: {total_stats[3]}\n"
                f"• Documents: {total_stats[4]}\n"
                f"• 🔥 View-once media: {total_stats[5]}\n"
                f"• 👥 Unique users: {user_count}\n\n"
                "👥 **Top users by deletions:**\n"
            )

            for i, (user_id, user_name, count, view_once_count) in enumerate(top_users, 1):
                view_once_info = f" (🔥: {view_once_count})" if view_once_count > 0 else ""
                response += (
                    f"{i}. {user_name} (ID: `{user_id}`)\n"
                    f"   Deletions: **{count}**{view_once_info}\n\n"
                )

            await event.reply(response, parse_mode='markdown')
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(pattern='/delete_text_logs'))
    async def delete_text_logs(event):
        """Delete all text log files of deleted messages"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        try:
            deleted_files = 0
            for filename in os.listdir(txt_logs_folder):
                file_path = os.path.join(txt_logs_folder, filename)
                if os.path.isfile(file_path) and (filename.startswith("deleted_messages_") or filename.startswith("chat_logs_")):
                    os.unlink(file_path)
                    deleted_files += 1

            await event.reply(f"🧹 Deleted text logs: {deleted_files}")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(pattern='/delete_media'))
    async def delete_media(event):
        """Delete all saved media files"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        try:
            deleted_files = 0
            for filename in os.listdir(media_folder):
                file_path = os.path.join(media_folder, filename)
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                    deleted_files += 1

            await event.reply(f"🧹 Deleted media files: {deleted_files}")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(pattern='/cleardb'))
    async def clear_database(event):
        """Clear user database"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        try:
            cursor.execute('DELETE FROM parsed_users')
            conn.commit()
            await event.reply("🧹 User database cleared")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
