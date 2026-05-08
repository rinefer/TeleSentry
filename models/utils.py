from telethon import events
from models.config import ADMIN_IDS, BOT_VERSION
import datetime

async def is_admin(event):
    """Import admin check function from admin_tools"""
    from models.admin_tools import is_admin
    return await is_admin(event)

def register_handlers(client):
    """Register utility command handlers"""

    @client.on(events.NewMessage(pattern='/myid'))
    async def show_my_id(event):
        """Show user ID and account information"""
        try:
            user_id = event.sender_id
            try:
                user = await event.get_sender()
                if user:
                    user_info = (
                        f"👤 **Your information:**\n\n"
                        f"🆔 **ID:** `{user.id}`\n"
                        f"📛 **Name:** {user.first_name or 'Not set'}\n"
                        f"👥 **Username:** @{user.username or 'Not set'}\n"
                        f"🤖 **Bot:** {'Yes' if user.bot else 'No'}"
                    )
                else:
                    user_info = f"👤 **Your ID:** `{user_id}`"
            except:
                user_info = f"👤 **Your ID:** `{user_id}`"

            response = (
                f"{user_info}\n\n"
                f"📋 **Admin list:** {ADMIN_IDS}\n\n"
                f"✅ **You {'are' if user_id in ADMIN_IDS else 'are NOT'} an administrator**\n\n"
                f"📝 **Tip:** Add your ID `{user_id}` to the `ADMIN_IDS` variable in config.py"
            )

            await event.reply(response, parse_mode='markdown')
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(pattern='/ping'))
    async def handle_ping(event):
        """Check bot responsiveness and system status"""
        start_time = datetime.datetime.now()

        try:
            from models.database import cursor
            cursor.execute('SELECT 1')
            db_status = '✅ Active'
        except Exception as e:
            db_status = f'❌ Error: {str(e)}'

        msg = await event.reply('🏓 Checking connections...')
        end_time = datetime.datetime.now()

        ping_time = (end_time - start_time).total_seconds() * 1000

        # Check profile monitoring status
        try:
            from models.logg_chat.profile_monitor import get_monitoring_status
            monitoring_status = get_monitoring_status()
            monitoring_text = (
                f"• <b>Profile monitoring:</b> {'<code>Active</code>' if monitoring_status['active'] else '<code>Inactive</code>'}\n"
                f"  Last check: {monitoring_status['last_check'].strftime('%Y-%m-%d %H:%M:%S') if monitoring_status['last_check'] else 'never'}\n"
                f"  Total checks: <code>{monitoring_status['checks_count']}</code>"
            )
        except Exception as e:
            monitoring_text = f"• <b>Profile monitoring:</b> ❌ Error: {str(e)}"

        await msg.edit(
            f'🔄 **Bot Status** (v{BOT_VERSION})\n\n'
            f'• **Response time:** `{ping_time:.2f} ms`\n'
            f'• **Database:** {db_status}\n'
            f'{monitoring_text}\n'
            f'• **Uptime:** `{datetime.datetime.now() - start_time}`\n'
            f'• **Last activity:** `{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}`\n\n'
            f'👤 **Your ID:** `{event.sender_id}`'
        , parse_mode='HTML')

    @client.on(events.NewMessage(pattern='/admins'))
    async def show_admins(event):
        """Show list of bot administrators"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        try:
            user_id = event.sender_id
            user_info = f"👤 Your ID: `{user_id}`\n"
            admins_list = "\n".join([f"• 👤 `{admin_id}`" for admin_id in ADMIN_IDS])
            await event.reply(
                f"🛡 **Administrators list:**\n\n"
                f"{user_info}\n"
                f"{admins_list}\n\n"
                f"✅ You {'are' if user_id in ADMIN_IDS else 'are NOT'} an administrator",
                parse_mode='markdown'
            )
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(pattern='/help'))
    async def show_help(event):
        """Show list of all available commands"""
        help_text = """
🛠 <b>Available Commands:</b>

🔍 <b>Main Commands:</b>
<code>/help</code> - Show this message
<code>/ping</code> - Check bot responsiveness
<code>/myid</code> - Show your user ID
<code>/admins</code> - Show administrators list
<code>/usercount</code> - Show count of unique users in database

<b>📊 User Parsing and Message Collection:</b>
<code>/pars all_uss username_or_link</code> - Collect user data (multi-stage collection)
<code>/parsmsg username_or_link user_id limit</code> - Collect user messages
<code>/invite @chat_username</code> - Add users from CSV to chat
<code>/msgcopy message_link</code> - Copy message from protected chat

<b>🌍 Global Chat/Channel Search:</b>
<code>/search_ch keyword</code> - Global search for chats/channels by keyword
<code>/export_search keyword</code> - Export search results to CSV
<code>/clear_search keyword</code> - Clear search results
<code>/search_stats</code> - Show global search statistics

<b>📝 Chat Logging:</b>
<code>/logg_user chat user_id</code> - Start logging user messages in chat
<code>/stoplogg chat</code> - Stop logging in chat
<code>/export_logs chat</code> - Export logs to CSV
<code>/list_logged</code> - Show list of tracked chats
<code>/profile ID_or_username</code> - Get full user profile snapshot
<code>/monitoring</code> - Manage profile monitoring
<code>/avatar_history ID_or_username</code> - Show user's avatar history

<b>📥 Content Downloading:</b>
<code>/download link</code> - Download video from YouTube/TikTok

<b>🔎 OSINT (Open Source Intelligence):</b>
<code>/username_search username</code> - Search for accounts by username
<code>/number_user +79991234567</code> - Search for information by phone number
<code>/email_search email@example.com</code> - Search for information by email

📝 <b>Message Management (Admin only):</b>
<code>/deleted</code> - Show last deleted messages
<code>/viewonce</code> - Show saved self-destructing media
<code>/media</code> - Show all saved media files
<code>/stats</code> - Show statistics about deleted messages

🗑 <b>Data Cleanup (Admin only):</b>
<code>/delete_text_logs</code> - Delete text log files
<code>/delete_media</code> - Delete media files
<code>/cleardb</code> - Clear user database
"""
        await event.reply(help_text, parse_mode='HTML')
