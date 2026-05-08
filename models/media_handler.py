"""
Media handling module for the Telegram bot.
Responsible for:
- Saving media files from messages
- Detecting self-destructing (view-once) media
- Saving message information to text files
- Sending notifications about deleted messages
"""

import os
import datetime
from telethon import types

async def save_media(message, media_folder):
    """
    Save media from a message to disk and return file information.
    Handles different media types including photos, videos, and documents.
    Detects self-destructing (view-once) media.

    Args:
        message: Telegram message object containing media
        media_folder: Path to folder where media should be saved

    Returns:
        tuple: (file_path, media_type, is_view_once)
            - file_path: Path to saved file or None if no media
            - media_type: Type of media (photo, video, document, etc.)
            - is_view_once: Boolean indicating if media is self-destructing
    """
    is_view_once = False

    if message.photo:
        # Check if photo is self-destructing (view-once)
        if hasattr(message, 'ttl_seconds') and message.ttl_seconds:
            is_view_once = True
            media_type = 'self_destruct_photo'
        else:
            media_type = 'photo'

        filename = f"photo_{message.id}.jpg"
        path = os.path.join(media_folder, filename)
        await message.download_media(file=path)

    elif message.video:
        # Check if video is self-destructing (view-once)
        if hasattr(message, 'ttl_seconds') and message.ttl_seconds:
            is_view_once = True
            media_type = 'self_destruct_video'
        else:
            media_type = 'video'

        filename = f"video_{message.id}.mp4"
        path = os.path.join(media_folder, filename)
        await message.download_media(file=path)

    elif message.document:
        # Check if document is self-destructing (view-once)
        if hasattr(message, 'ttl_seconds') and message.ttl_seconds:
            is_view_once = True
            media_type = 'self_destruct_document'
        else:
            ext = message.document.mime_type.split('/')[-1] if message.document.mime_type else 'bin'
            media_type = 'document'

        filename = f"doc_{message.id}.{ext}"
        path = os.path.join(media_folder, filename)
        await message.download_media(file=path)

    else:
        return None, None, False

    return path, media_type, is_view_once

def save_to_txt(msg_data, filepath):
    """
    Save information about a deleted message to a text file.
    Creates a human-readable log with all relevant message information.

    Args:
        msg_data (dict): Dictionary containing message information with keys:
            - chat_id: ID of chat where message was sent
            - chat_name: Name of chat
            - sender_id: ID of message sender
            - sender_name: Name of sender
            - text: Message text
            - date: When message was sent
            - media_path: Path to saved media file
            - media_type: Type of media
            - is_view_once: Boolean indicating if media is self-destructing
        filepath: Path to text file where log should be saved
    """
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(f"=== Deleted Message ===\n")

        if msg_data.get('is_view_once'):
            f.write(f"🔥 TYPE: SELF-DESTRUCTING VIEW-ONCE MEDIA\n")

        f.write(f"Sent date: {msg_data['date']}\n")
        f.write(f"Deleted at: {datetime.datetime.now()}\n")
        f.write(f"Chat: {msg_data['chat_name']} (ID: {msg_data['chat_id']})\n")
        f.write(f"Sender: {msg_data['sender_name']} (ID: {msg_data['sender_id']})\n")
        f.write(f"Text: {msg_data['text']}\n")
        if msg_data['media_path']:
            media_type = msg_data['media_type']
            if msg_data.get('is_view_once'):
                media_type = f"🔥 {media_type} (VIEW-ONCE)"
            f.write(f"Media: {media_type} (path: {msg_data['media_path']})\n")
        f.write("\n")

async def send_notification(msg_data, client):
    """
    Send notification about a newly deleted message to configured notification chats.
    Handles different notification formats for regular messages vs view-once media.

    Args:
        msg_data (dict): Dictionary containing message information (same format as save_to_txt)
        client: Telegram client instance for sending messages
    """
    from .config import NOTIFY_CHAT_ID

    if not NOTIFY_CHAT_ID:
        return

    text = msg_data['text'] or 'No text'
    if len(text) > 500:
        text = text[:500] + "... [message too long]"

    # Create different notification formats for view-once vs regular messages
    if msg_data.get('is_view_once'):
        notification = (
            "🔥 **NEW VIEW-ONCE MEDIA (self-destructing) DETECTED!**\n\n"
            f"👤 **Sender:** {msg_data['sender_name']} (ID: `{msg_data['sender_id']}`)\n"
            f"💬 **Chat:** {msg_data['chat_name']} (ID: `{msg_data['chat_id']}`)\n"
            f"📅 **Sent at:** {msg_data['date'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🗑 **Deleted at:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
    else:
        notification = (
            "🚨 **New deleted message detected!**\n\n"
            f"👤 **Sender:** {msg_data['sender_name']} (ID: `{msg_data['sender_id']}`)\n"
            f"💬 **Chat:** {msg_data['chat_name']} (ID: `{msg_data['chat_id']}`)\n"
            f"📅 **Sent at:** {msg_data['date'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🗑 **Deleted at:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

    if text != 'No text':
        notification += f"📝 **Text:**\n`{text}`"

    if msg_data['media_path']:
        if msg_data.get('is_view_once'):
            notification += f"\n\n🔥 **Media:** {msg_data['media_type']} (VIEW-ONCE)"
        else:
            notification += f"\n\n📷 **Media:** {msg_data['media_type']}"

    # Send notification to all configured notification chats
    for chat_id in NOTIFY_CHAT_ID:
        try:
            # For view-once media, don't send the actual media file, just the info
            if msg_data.get('is_view_once'):
                await client.send_message(
                    chat_id,
                    notification,
                    parse_mode='markdown'
                )
            else:
                await client.send_message(
                    chat_id,
                    notification,
                    parse_mode='markdown',
                    file=msg_data['media_path'] if msg_data['media_path'] else None
                )
        except Exception as e:
            print(f"Error sending notification to {chat_id}: {e}")
