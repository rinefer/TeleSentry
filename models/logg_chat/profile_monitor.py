import asyncio
import datetime
import os
import hashlib
import glob
from telethon import events
from models.config import LOG_CHAT_ID, ADMIN_IDS, media_folder
from models.database import (
    save_profile_snapshot,
    get_last_profile_snapshot,
    add_monitored_profile,
    remove_monitored_profile,
    get_monitored_profiles
)

# Global variables for monitoring state
monitoring_active = False
monitoring_status = {
    'active': False,
    'last_check': None,
    'checks_count': 0,
    'last_error': None
}
initial_notifications_sent = set()

async def is_admin(event):
    """Check if user has admin privileges"""
    from models.admin_tools import is_admin
    return await is_admin(event)

async def get_profile_state(client, user_id):
    """Get current profile state including avatar information"""
    try:
        if not client.is_connected():
            await client.connect()
            if not await client.is_user_authorized():
                raise Exception("Client not authorized")

        try:
            user = await client.get_entity(user_id)
        except ValueError:
            try:
                user = await client.get_entity(int(user_id))
            except Exception as e:
                print(f"Error getting user {user_id}: {e}")
                return None

        if not user:
            return None

        avatar_info = await get_avatar_info(client, user)

        return {
            'username': getattr(user, 'username', None),
            'first_name': getattr(user, 'first_name', None),
            'last_name': getattr(user, 'last_name', None),
            'phone': getattr(user, 'phone', None),
            'bio': getattr(user, 'about', None),
            'restricted': getattr(user, 'restricted', False),
            'verified': getattr(user, 'verified', False),
            'premium': getattr(user, 'premium', False),
            'avatar': avatar_info,
            'last_check': datetime.datetime.now()
        }
    except Exception as e:
        print(f"Error getting profile state for {user_id}: {e}")
        monitoring_status['last_error'] = str(e)
        return None

async def get_avatar_info(client, user):
    """Get information about user's avatar"""
    try:
        try:
            photos = await client.get_profile_photos(user)
        except Exception as e:
            print(f"Error getting profile photos for {user.id}: {e}")
            return {
                'has_avatar': False,
                'avatar_hash': None,
                'avatar_path': None,
                'avatar_id': None
            }

        if not photos or len(photos) == 0:
            return {
                'has_avatar': False,
                'avatar_hash': None,
                'avatar_path': None,
                'avatar_id': None
            }

        current_photo = photos[0]
        avatar_id = f"{user.id}_{current_photo.id}"
        avatar_path = os.path.join(media_folder, 'avatars', f"{avatar_id}.jpg")

        if not os.path.exists(avatar_path):
            os.makedirs(os.path.dirname(avatar_path), exist_ok=True)
            try:
                await client.download_profile_photo(user, file=avatar_path)
            except Exception as e:
                print(f"Error downloading avatar for {user.id}: {e}")
                return {
                    'has_avatar': False,
                    'avatar_hash': None,
                    'avatar_path': None,
                    'avatar_id': None
                }

        avatar_hash = None
        if os.path.exists(avatar_path):
            try:
                with open(avatar_path, 'rb') as f:
                    avatar_hash = hashlib.md5(f.read()).hexdigest()
            except Exception as e:
                print(f"Error calculating avatar hash for {user.id}: {e}")

        return {
            'has_avatar': True,
            'avatar_hash': avatar_hash,
            'avatar_path': avatar_path,
            'avatar_id': avatar_id
        }
    except Exception as e:
        print(f"Error getting avatar info for {user.id}: {e}")
        return {
            'has_avatar': False,
            'avatar_hash': None,
            'avatar_path': None,
            'avatar_id': None
        }

def normalize_value(value):
    """Normalize value for comparison"""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() if value.strip() else None
    return value

def compare_profiles(old_state, new_state):
    """Compare two profile states and return list of changes"""
    if not old_state:
        return []

    changes = []

    fields_to_check = [
        ('username', 'Username'),
        ('first_name', 'First name'),
        ('last_name', 'Last name'),
        ('phone', 'Phone'),
        ('bio', 'Bio'),
        ('restricted', 'Restricted'),
        ('verified', 'Verified'),
        ('premium', 'Premium')
    ]

    for field, display_name in fields_to_check:
        old_val = normalize_value(old_state.get(field))
        new_val = normalize_value(new_state.get(field))

        if old_val != new_val:
            changes.append({
                'field': field,
                'display_name': display_name,
                'old': old_val,
                'new': new_val
            })

    if old_state.get('avatar') and new_state.get('avatar'):
        old_avatar = old_state['avatar']
        new_avatar = new_state['avatar']

        if old_avatar.get('avatar_hash') != new_avatar.get('avatar_hash'):
            changes.append({
                'field': 'avatar',
                'display_name': 'Avatar',
                'old': f"Avatar (hash: {old_avatar.get('avatar_hash', 'unknown')})",
                'new': f"New avatar (hash: {new_avatar.get('avatar_hash', 'unknown')})"
            })

    return changes

async def check_profile_changes(client):
    """Check for changes in monitored profiles and send notifications"""
    global monitoring_status

    if not LOG_CHAT_ID or not monitoring_active:
        return

    try:
        if not client.is_connected():
            await client.connect()
            if not await client.is_user_authorized():
                raise Exception("Client not authorized")

        monitoring_status['last_check'] = datetime.datetime.now()
        monitoring_status['checks_count'] += 1
        monitoring_status['last_error'] = None

        monitored_profiles = get_monitored_profiles()
        if not monitored_profiles:
            return

        for user_id, chat_id in monitored_profiles:
            try:
                current_state = await get_profile_state(client, user_id)
                if not current_state:
                    continue

                last_snapshot = get_last_profile_snapshot(user_id)

                if not last_snapshot:
                    save_profile_snapshot(user_id, current_state)
                    if user_id not in initial_notifications_sent:
                        await send_initial_profile_notification(client, user_id, current_state, chat_id)
                        initial_notifications_sent.add(user_id)
                    continue

                try:
                    last_snapshot_dict = {
                        'username': last_snapshot[0],
                        'first_name': last_snapshot[1],
                        'last_name': last_snapshot[2],
                        'phone': last_snapshot[3],
                        'bio': last_snapshot[4],
                        'restricted': last_snapshot[5],
                        'verified': last_snapshot[6],
                        'premium': last_snapshot[7],
                        'avatar': {
                            'has_avatar': bool(last_snapshot[8]),
                            'avatar_hash': last_snapshot[9],
                            'avatar_path': last_snapshot[10],
                            'avatar_id': last_snapshot[11]
                        },
                        'last_check': last_snapshot[12]
                    }
                except IndexError:
                    save_profile_snapshot(user_id, current_state)
                    if user_id not in initial_notifications_sent:
                        await send_initial_profile_notification(client, user_id, current_state, chat_id)
                        initial_notifications_sent.add(user_id)
                    continue

                changes = compare_profiles(last_snapshot_dict, current_state)

                if changes:
                    await send_profile_change_notification(client, user_id, changes, chat_id)
                    save_profile_snapshot(user_id, current_state)

            except Exception as e:
                print(f"Error checking profile {user_id}: {e}")
                monitoring_status['last_error'] = str(e)
                continue

    except Exception as e:
        print(f"Error in check_profile_changes: {e}")
        monitoring_status['last_error'] = str(e)

async def send_initial_profile_notification(client, user_id, profile_data, chat_id=None):
    """Send initial notification with full profile snapshot"""
    try:
        if not client.is_connected():
            await client.connect()
            if not await client.is_user_authorized():
                raise Exception("Client not authorized")

        try:
            user = await client.get_entity(user_id)
        except Exception as e:
            print(f"Error getting user {user_id}: {e}")
            return

        username = getattr(user, 'username', None)
        first_name = getattr(user, 'first_name', None)
        last_name = getattr(user, 'last_name', None)

        message = (
            f"📌 <b>Profile monitoring started</b>\n\n"
            f"👤 <b>User:</b> {first_name or ''} {last_name or ''} "
            f"{f'(@{username})' if username else ''}\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"🕒 <b>Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"<b>Current state:</b>\n"
            f"• <b>Username:</b> <code>{profile_data['username'] or 'not set'}</code>\n"
            f"• <b>First name:</b> <code>{profile_data['first_name'] or 'not set'}</code>\n"
            f"• <b>Last name:</b> <code>{profile_data['last_name'] or 'not set'}</code>\n"
            f"• <b>Phone:</b> <code>{profile_data['phone'] or 'not set'}</code>\n"
            f"• <b>Bio:</b> <code>{profile_data['bio'] or 'not set'}</code>\n"
            f"• <b>Restricted:</b> <code>{'Yes' if profile_data['restricted'] else 'No'}</code>\n"
            f"• <b>Verified:</b> <code>{'Yes' if profile_data['verified'] else 'No'}</code>\n"
            f"• <b>Premium:</b> <code>{'Yes' if profile_data['premium'] else 'No'}</code>\n"
        )

        if profile_data['avatar']['has_avatar']:
            message += f"• <b>Avatar:</b> <code>Available (hash: {profile_data['avatar']['avatar_hash']})</code>\n"
        else:
            message += f"• <b>Avatar:</b> <code>Not available</code>\n"

        target_chat = chat_id if chat_id else LOG_CHAT_ID[0] if LOG_CHAT_ID else None
        if target_chat:
            await client.send_message(target_chat, message, parse_mode='HTML')

            if profile_data['avatar']['has_avatar'] and profile_data['avatar']['avatar_path']:
                try:
                    await client.send_file(
                        target_chat,
                        profile_data['avatar']['avatar_path'],
                        caption="🖼 Current user avatar"
                    )
                except Exception as e:
                    print(f"Error sending avatar: {e}")

    except Exception as e:
        print(f"Error sending initial notification: {e}")
        monitoring_status['last_error'] = str(e)

async def send_profile_change_notification(client, user_id, changes, chat_id=None):
    """Send notification about profile changes to log chat"""
    try:
        if not client.is_connected():
            await client.connect()
            if not await client.is_user_authorized():
                raise Exception("Client not authorized")

        try:
            user = await client.get_entity(user_id)
        except Exception as e:
            print(f"Error getting user {user_id}: {e}")
            return

        username = getattr(user, 'first_name', None)
        first_name = getattr(user, 'first_name', None)
        last_name = getattr(user, 'last_name', None)

        change_messages = []
        avatar_changed = False
        new_avatar_path = None

        for change in changes:
            old_val = change['old'] if change['old'] is not None else "not set"
            new_val = change['new'] if change['new'] is not None else "not set"

            if isinstance(old_val, bool):
                old_val = "Yes" if old_val else "No"
            if isinstance(new_val, bool):
                new_val = "Yes" if new_val else "No"

            if change['field'] == 'avatar':
                avatar_changed = True
                if 'hash:' in str(new_val):
                    try:
                        new_avatar_path = str(new_val).split('hash: ')[-1].split(')')[0]
                        if new_avatar_path == 'unknown':
                            new_avatar_path = None
                    except Exception:
                        new_avatar_path = None

            change_messages.append(
                f"• <b>{change['display_name']}:</b> "
                f"<code>{old_val}</code> → <code>{new_val}</code>"
            )

        message = (
            f"🚨 <b>Profile changes detected!</b>\n\n"
            f"👤 <b>User:</b> {first_name or ''} {last_name or ''} "
            f"{f'(@{username})' if username else ''}\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"🕒 <b>Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"<b>Changes:</b>\n" + "\n".join(change_messages)
        )

        target_chat = chat_id if chat_id else LOG_CHAT_ID[0] if LOG_CHAT_ID else None
        if target_chat:
            await client.send_message(target_chat, message, parse_mode='HTML')

            if avatar_changed and new_avatar_path:
                try:
                    if new_avatar_path:
                        avatar_path = os.path.join(media_folder, 'avatars', f"{user_id}_*.jpg")
                        matching_files = glob.glob(avatar_path)
                        if matching_files:
                            new_avatar_path = matching_files[0]
                        else:
                            current_state = await get_profile_state(client, user_id)
                            if current_state and current_state['avatar']['has_avatar']:
                                new_avatar_path = current_state['avatar']['avatar_path']

                    if new_avatar_path and os.path.exists(new_avatar_path):
                        await client.send_file(
                            target_chat,
                            new_avatar_path,
                            caption="🖼 New user avatar"
                        )
                except Exception as e:
                    print(f"Error sending new avatar: {e}")

    except Exception as e:
        print(f"Error sending profile change notification: {e}")
        monitoring_status['last_error'] = str(e)

def start_profile_monitoring(client):
    """Start periodic profile change checking"""
    global monitoring_active, monitoring_status, initial_notifications_sent
    monitoring_active = True
    monitoring_status['active'] = True
    monitoring_status['last_check'] = None
    monitoring_status['checks_count'] = 0
    monitoring_status['last_error'] = None
    initial_notifications_sent = set()

    async def periodic_check():
        """Periodic profile change checking"""
        while monitoring_active:
            try:
                await check_profile_changes(client)
            except Exception as e:
                print(f"Error in periodic_check: {e}")
                monitoring_status['last_error'] = str(e)
            await asyncio.sleep(500)

    client.loop.create_task(periodic_check())

def stop_profile_monitoring():
    """Stop profile monitoring"""
    global monitoring_active, monitoring_status
    monitoring_active = False
    monitoring_status['active'] = False

def add_monitored_user(user_id, chat_id=None):
    """Add user to monitoring list"""
    if add_monitored_profile(user_id, chat_id):
        return True
    return False

def remove_monitored_user(user_id):
    """Remove user from monitoring list"""
    if remove_monitored_profile(user_id):
        if user_id in initial_notifications_sent:
            initial_notifications_sent.remove(user_id)
        return True
    return False

def get_monitored_users():
    """Get list of monitored users"""
    return get_monitored_profiles()

def get_monitoring_status():
    """Get current monitoring status"""
    return monitoring_status

async def get_full_profile_snapshot(client, user_id):
    """Get full profile snapshot with comparison to last snapshot"""
    try:
        if not client.is_connected():
            await client.connect()
            if not await client.is_user_authorized():
                raise Exception("Client not authorized")

        profile_data = await get_profile_state(client, user_id)
        if not profile_data:
            return None

        last_snapshot = get_last_profile_snapshot(user_id)

        last_snapshot_dict = None
        if last_snapshot:
            try:
                last_snapshot_dict = {
                    'username': last_snapshot[0],
                    'first_name': last_snapshot[1],
                    'last_name': last_snapshot[2],
                    'phone': last_snapshot[3],
                    'bio': last_snapshot[4],
                    'restricted': last_snapshot[5],
                    'verified': last_snapshot[6],
                    'premium': last_snapshot[7],
                    'avatar': {
                        'has_avatar': bool(last_snapshot[8]),
                        'avatar_hash': last_snapshot[9],
                        'avatar_path': last_snapshot[10],
                        'avatar_id': last_snapshot[11]
                    },
                    'last_check': last_snapshot[12]
                }
            except IndexError:
                pass

        return {
            'current': profile_data,
            'last_snapshot': last_snapshot_dict,
            'changes': compare_profiles(last_snapshot_dict, profile_data) if last_snapshot_dict else None
        }
    except Exception as e:
        print(f"Error getting full profile snapshot: {e}")
        monitoring_status['last_error'] = str(e)
        return None

def register_monitoring_handlers(client):
    """Register handlers for /monitoring and /profile commands"""

    @client.on(events.NewMessage(pattern='/monitoring'))
    async def handle_monitoring(event):
        """Handler for /monitoring command"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split()
        if len(args) < 2:
            status = get_monitoring_status()
            error_info = f"\n⚠️ <b>Last error:</b> <code>{status['last_error']}</code>" if status['last_error'] else ""
            await event.reply(
                "ℹ️ <b>Profile monitoring</b>\n\n"
                f"🔄 <b>Status:</b> {'<code>Active</code>' if status['active'] else '<code>Inactive</code>'}\n"
                f"🕒 <b>Last check:</b> {status['last_check'].strftime('%Y-%m-%d %H:%M:%S') if status['last_check'] else 'never'}\n"
                f"🔢 <b>Total checks:</b> <code>{status['checks_count']}</code>\n"
                f"{error_info}\n\n"
                "Usage:\n"
                "<code>/monitoring add ID_or_username [chat_id]</code> - add user to monitoring\n"
                "<code>/monitoring remove ID_or_username</code> - remove user from monitoring\n"
                "<code>/monitoring list</code> - show monitored users\n"
                "<code>/monitoring status</code> - show monitoring status\n\n"
                "Examples:\n"
                "<code>/monitoring add 123456789</code>\n"
                "<code>/monitoring add @username -100123456789</code>\n"
                "<code>/monitoring remove 123456789</code>\n"
                "<code>/monitoring list</code>"
            , parse_mode='HTML')
            return

        command = args[1].lower()
        if command == "list":
            try:
                monitored = get_monitored_users()
                if not monitored:
                    await event.reply("ℹ️ No users being monitored")
                    return

                message = "📋 <b>Monitored users:</b>\n\n"
                for user_id, chat_id in monitored:
                    try:
                        user = await client.get_entity(user_id)
                        username = getattr(user, 'username', None)
                        first_name = getattr(user, 'first_name', None)
                        last_name = getattr(user, 'last_name', None)

                        message += (
                            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                            f"👤 <b>User:</b> {first_name or ''} {last_name or ''} "
                            f"{f'(@{username})' if username else ''}\n"
                            f"💬 <b>Notification chat:</b> <code>{chat_id}</code>\n\n"
                        )
                    except Exception:
                        message += (
                            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                            f"💬 <b>Notification chat:</b> <code>{chat_id}</code>\n\n"
                        )

                await event.reply(message, parse_mode='HTML')
            except Exception as e:
                await event.reply(f"❌ Error: {str(e)}")

        elif command == "status":
            status = get_monitoring_status()
            error_info = f"\n⚠️ <b>Last error:</b> <code>{status['last_error']}</code>" if status['last_error'] else ""
            await event.reply(
                "ℹ️ <b>Profile monitoring status</b>\n\n"
                f"🔄 <b>Status:</b> {'<code>Active</code>' if status['active'] else '<code>Inactive</code>'}\n"
                f"🕒 <b>Last check:</b> {status['last_check'].strftime('%Y-%m-%d %H:%M:%S') if status['last_check'] else 'never'}\n"
                f"🔢 <b>Total checks:</b> <code>{status['checks_count']}</code>\n"
                f"{error_info}\n\n"
                f"🔎 <b>Check interval:</b> <code>1 minute</code>\n"
                f"📊 <b>Instant notifications:</b> <code>Enabled</code>\n"
                f"🖼 <b>Avatar tracking:</b> <code>Enabled</code>"
            , parse_mode='HTML')

        elif command in ["add", "remove"]:
            if len(args) < 3:
                await event.reply("⚠️ Please specify user ID or username")
                return

            try:
                target = args[2]
                user_id = None
                chat_id = None

                if target.isdigit():
                    user_id = int(target)
                else:
                    if target.startswith('@'):
                        target = target[1:]
                    try:
                        user = await client.get_entity(target)
                        user_id = user.id
                    except Exception as e:
                        await event.reply(f"⚠️ Could not find user: {str(e)}")
                        return

                if len(args) > 3 and args[3].startswith('-100'):
                    chat_id = int(args[3])

                if command == "add":
                    if add_monitored_user(user_id, chat_id if chat_id else event.chat_id):
                        profile_data = await get_profile_state(client, user_id)
                        if profile_data:
                            save_profile_snapshot(user_id, profile_data)
                            await send_initial_profile_notification(client, user_id, profile_data, chat_id if chat_id else event.chat_id)
                            initial_notifications_sent.add(user_id)

                        if chat_id:
                            await event.reply(f"✅ User {user_id} added to monitoring with notifications in chat {chat_id}")
                        else:
                            await event.reply(f"✅ User {user_id} added to monitoring\n\n"
                                            f"🔔 Notifications will be sent to this chat")
                    else:
                        await event.reply(f"❌ Could not add user {user_id} to monitoring")
                else:
                    if remove_monitored_user(user_id):
                        await event.reply(f"✅ User {user_id} removed from monitoring")
                    else:
                        await event.reply(f"❌ User {user_id} not found in monitoring list")

            except ValueError:
                await event.reply("⚠️ Invalid user or chat ID")
            except Exception as e:
                await event.reply(f"❌ Error: {str(e)}")

        else:
            await event.reply("⚠️ Unknown command. Available commands: add, remove, list, status")

    @client.on(events.NewMessage(pattern='/profile'))
    async def handle_profile(event):
        """Handler for /profile command - get full profile snapshot"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split()
        if len(args) < 2:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/profile ID_or_username</code> - get full profile snapshot\n\n"
                "Examples:\n"
                "<code>/profile 123456789</code>\n"
                "<code>/profile @username</code>"
            )
            return

        try:
            target = args[1]
            user_id = None

            if target.isdigit():
                user_id = int(target)
            else:
                if target.startswith('@'):
                    target = target[1:]
                try:
                    user = await client.get_entity(target)
                    user_id = user.id
                except Exception as e:
                    await event.reply(f"⚠️ Could not find user: {str(e)}")
                    return

            snapshot = await get_full_profile_snapshot(client, user_id)
            if not snapshot:
                await event.reply(f"❌ Could not get profile data for user {user_id}")
                return

            try:
                user = await client.get_entity(user_id)
            except Exception:
                user = None

            username = getattr(user, 'username', None) if user else None
            first_name = getattr(user, 'first_name', None) if user else None
            last_name = getattr(user, 'last_name', None) if user else None

            message = (
                f"📊 <b>User profile snapshot</b>\n\n"
                f"👤 <b>User:</b> {first_name or ''} {last_name or ''} "
                f"{f'(@{username})' if username else ''}\n"
                f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                f"🕒 <b>Check time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            )

            current = snapshot['current']
            message += (
                f"<b>🔹 Current state:</b>\n"
                f"• <b>Username:</b> <code>{current['username'] or 'not set'}</code>\n"
                f"• <b>First name:</b> <code>{current['first_name'] or 'not set'}</code>\n"
                f"• <b>Last name:</b> <code>{current['last_name'] or 'not set'}</code>\n"
                f"• <b>Phone:</b> <code>{current['phone'] or 'not set'}</code>\n"
                f"• <b>Bio:</b> <code>{current['bio'] or 'not set'}</code>\n"
                f"• <b>Restricted:</b> <code>{'Yes' if current['restricted'] else 'No'}</code>\n"
                f"• <b>Verified:</b> <code>{'Yes' if current['verified'] else 'No'}</code>\n"
                f"• <b>Premium:</b> <code>{'Yes' if current['premium'] else 'No'}</code>\n"
            )

            if current['avatar']['has_avatar']:
                message += f"• <b>Avatar:</b> <code>Available (hash: {current['avatar']['avatar_hash']})</code>\n"
            else:
                message += f"• <b>Avatar:</b> <code>Not available</code>\n"

            if snapshot['last_snapshot']:
                last = snapshot['last_snapshot']
                message += (
                    f"\n<b>🔹 Last snapshot (from {last['last_check'].strftime('%Y-%m-%d %H:%M:%S') if last['last_check'] else 'unknown'}):</b>\n"
                    f"• <b>Username:</b> <code>{last['username'] or 'not set'}</code>\n"
                    f"• <b>First name:</b> <code>{last['first_name'] or 'not set'}</code>\n"
                    f"• <b>Last name:</b> <code>{last['last_name'] or 'not set'}</code>\n"
                    f"• <b>Phone:</b> <code>{last['phone'] or 'not set'}</code>\n"
                    f"• <b>Bio:</b> <code>{last['bio'] or 'not set'}</code>\n"
                    f"• <b>Restricted:</b> <code>{'Yes' if last['restricted'] else 'No'}</code>\n"
                    f"• <b>Verified:</b> <code>{'Yes' if last['verified'] else 'No'}</code>\n"
                    f"• <b>Premium:</b> <code>{'Yes' if last['premium'] else 'No'}</code>\n"
                )

                if last['avatar']['has_avatar']:
                    message += f"• <b>Avatar:</b> <code>Was available (hash: {last['avatar']['avatar_hash']})</code>\n"
                else:
                    message += f"• <b>Avatar:</b> <code>Was not available</code>\n"

            if snapshot['changes']:
                change_messages = []
                for change in snapshot['changes']:
                    old_val = change['old'] if change['old'] is not None else "not set"
                    new_val = change['new'] if change['new'] is not None else "not set"

                    if isinstance(old_val, bool):
                        old_val = "Yes" if old_val else "No"
                    if isinstance(new_val, bool):
                        new_val = "Yes" if new_val else "No"

                    change_messages.append(
                        f"• <b>{change['display_name']}:</b> "
                        f"<code>{old_val}</code> → <code>{new_val}</code>"
                    )

                message += f"\n<b>🔹 Changes since last snapshot:</b>\n" + "\n".join(change_messages)
            else:
                message += "\n<b>🔹 No changes detected since last snapshot</b>"

            await event.reply(message, parse_mode='HTML')

            if current['avatar']['has_avatar'] and current['avatar']['avatar_path']:
                try:
                    await event.reply(
                        file=current['avatar']['avatar_path'],
                        caption="🖼 Current user avatar"
                    )
                except Exception as e:
                    print(f"Error sending avatar: {e}")

        except ValueError:
            await event.reply("⚠️ Invalid user ID")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    @client.on(events.NewMessage(pattern='/avatar_history'))
    async def handle_avatar_history(event):
        """Show user's avatar history"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split()
        if len(args) < 2:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/avatar_history ID_or_username</code> - show user's avatar history\n\n"
                "Examples:\n"
                "<code>/avatar_history 123456789</code>\n"
                "<code>/avatar_history @username</code>"
            )
            return

        try:
            target = args[1]
            user_id = None

            if target.isdigit():
                user_id = int(target)
            else:
                if target.startswith('@'):
                    target = target[1:]
                try:
                    user = await client.get_entity(target)
                    user_id = user.id
                except Exception as e:
                    await event.reply(f"⚠️ Could not find user: {str(e)}")
                    return

            try:
                photos = await client.get_profile_photos(user_id)
            except Exception as e:
                await event.reply(f"❌ Error getting avatars: {str(e)}")
                return

            if not photos or len(photos) == 0:
                await event.reply(f"🖼 User {user_id} has no avatars")
                return

            try:
                user = await client.get_entity(user_id)
            except Exception:
                user = None

            username = getattr(user, 'username', None) if user else None
            first_name = getattr(user, 'first_name', None) if user else None
            last_name = getattr(user, 'last_name', None) if user else None

            message = (
                f"📸 <b>User avatar history</b>\n\n"
                f"👤 <b>User:</b> {first_name or ''} {last_name or ''} "
                f"{f'(@{username})' if username else ''}\n"
                f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                f"🖼 <b>Total avatars:</b> <code>{len(photos)}</code>\n\n"
            )

            avatar_files = []
            for i, photo in enumerate(photos[:5]):
                try:
                    avatar_id = f"{user_id}_{photo.id}"
                    avatar_path = os.path.join(media_folder, 'avatars', f"{avatar_id}.jpg")

                    if not os.path.exists(avatar_path):
                        os.makedirs(os.path.dirname(avatar_path), exist_ok=True)
                        try:
                            await client.download_profile_photo(user_id, file=avatar_path)
                        except Exception as e:
                            print(f"Error downloading avatar {i}: {e}")
                            message += f"📌 <b>Avatar #{i+1}:</b> Download error\n"
                            continue

                    if os.path.exists(avatar_path):
                        avatar_files.append(avatar_path)
                        message += f"📌 <b>Avatar #{i+1}:</b> <code>{photo.date.strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
                except Exception as e:
                    print(f"Error processing avatar {i}: {e}")
                    message += f"📌 <b>Avatar #{i+1}:</b> Download error\n"

            if len(photos) > 5:
                message += f"\n⚠️ Showing first 5 of {len(photos)} avatars"

            await event.reply(message, parse_mode='HTML')

            if avatar_files:
                for i, avatar_path in enumerate(avatar_files):
                    try:
                        await event.reply(
                            file=avatar_path,
                            caption=f"🖼 Avatar #{i+1} of user {user_id}"
                        )
                    except Exception as e:
                        print(f"Error sending avatar {i}: {e}")

        except ValueError:
            await event.reply("⚠️ Invalid user ID")
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")
