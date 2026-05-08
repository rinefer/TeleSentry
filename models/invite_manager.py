from telethon import events, Button, types
from telethon.tl.types import InputPeerUser, InputPeerChannel
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.contacts import ResolveUsernameRequest
import csv
import os
import asyncio
import random
import datetime
import time
from models.config import txt_logs_folder, ADMIN_IDS
from models.database import cursor
from models.admin_tools import is_admin

# Path to main CSV file for invites
INVITE_CSV_PATH = os.path.join(txt_logs_folder, 'users.csv')
# Path to invite logs file
INVITE_LOG_PATH = os.path.join(txt_logs_folder, 'invite_logs.csv')
# Path to file with temporary blocked users
BLOCKED_USERS_PATH = os.path.join(txt_logs_folder, 'blocked_users.csv')

class InviteManager:
    def __init__(self):
        """Initialize invite manager with rate limits and statistics"""
        self.rate_limits = {
            'min_delay': 15,  # minimum delay between invites (seconds)
            'max_delay': 45,  # maximum delay between invites
            'batch_size': 20,  # number of users to process in one batch
            'daily_limit': 200,  # daily invite limit
            'hourly_limit': 50,  # hourly invite limit
            'consecutive_errors_limit': 5,  # limit of consecutive errors
            'cooldown_after_errors': 3600  # cooldown period after errors (seconds)
        }
        self.stats = {
            'today': 0,
            'this_hour': 0,
            'last_invite_time': 0,
            'consecutive_errors': 0,
            'last_error_time': 0
        }
        self._load_stats()
        self._ensure_files_exist()

    def _ensure_files_exist(self):
        """Create necessary files if they don't exist"""
        for filepath in [INVITE_CSV_PATH, INVITE_LOG_PATH, BLOCKED_USERS_PATH]:
            if not os.path.exists(filepath):
                try:
                    with open(filepath, 'w', encoding='utf-8', newline='') as f:
                        if filepath == INVITE_CSV_PATH:
                            writer = csv.DictWriter(f, fieldnames=['id', 'access_hash', 'first_name', 'last_name', 'username'])
                            writer.writeheader()
                        elif filepath == INVITE_LOG_PATH:
                            writer = csv.DictWriter(f, fieldnames=['timestamp', 'chat_id', 'user_id', 'status', 'error'])
                            writer.writeheader()
                        elif filepath == BLOCKED_USERS_PATH:
                            writer = csv.DictWriter(f, fieldnames=['user_id', 'blocked_until', 'reason'])
                            writer.writeheader()
                except Exception as e:
                    print(f"Error creating file {filepath}: {e}")

    def _load_stats(self):
        """Load invite statistics from logs"""
        try:
            if os.path.exists(INVITE_LOG_PATH):
                with open(INVITE_LOG_PATH, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    today = datetime.date.today()
                    current_hour = datetime.datetime.now().hour

                    for row in reader:
                        try:
                            timestamp = datetime.datetime.fromisoformat(row['timestamp'])
                            if timestamp.date() == today:
                                self.stats['today'] += 1
                                if timestamp.hour == current_hour:
                                    self.stats['this_hour'] += 1
                        except Exception:
                            continue
        except Exception as e:
            print(f"Error loading statistics: {e}")

    def _log_invite(self, chat_id, user_id, status, error=None):
        """Log invite attempt"""
        try:
            with open(INVITE_LOG_PATH, 'a', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['timestamp', 'chat_id', 'user_id', 'status', 'error'])
                writer.writerow({
                    'timestamp': datetime.datetime.now().isoformat(),
                    'chat_id': chat_id,
                    'user_id': user_id,
                    'status': status,
                    'error': str(error) if error else ''
                })
        except Exception as e:
            print(f"Error logging invite: {e}")

    def _is_user_blocked(self, user_id):
        """Check if user is temporarily blocked"""
        try:
            if not os.path.exists(BLOCKED_USERS_PATH):
                return False

            with open(BLOCKED_USERS_PATH, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if int(row['user_id']) == user_id:
                        blocked_until = datetime.datetime.fromisoformat(row['blocked_until'])
                        if blocked_until > datetime.datetime.now():
                            return True
                        else:
                            # Remove expired block
                            self._remove_blocked_user(user_id)
                            return False
            return False
        except Exception as e:
            print(f"Error checking blocked user: {e}")
            return False

    def _add_blocked_user(self, user_id, reason):
        """Add user to blocked list"""
        try:
            blocked_until = datetime.datetime.now() + datetime.timedelta(hours=24)
            with open(BLOCKED_USERS_PATH, 'a', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['user_id', 'blocked_until', 'reason'])
                writer.writerow({
                    'user_id': user_id,
                    'blocked_until': blocked_until.isoformat(),
                    'reason': reason
                })
        except Exception as e:
            print(f"Error adding blocked user: {e}")

    def _remove_blocked_user(self, user_id):
        """Remove user from blocked list"""
        try:
            if not os.path.exists(BLOCKED_USERS_PATH):
                return

            temp_path = BLOCKED_USERS_PATH + '.tmp'
            with open(BLOCKED_USERS_PATH, 'r', encoding='utf-8') as infile, \
                 open(temp_path, 'w', encoding='utf-8', newline='') as outfile:

                reader = csv.DictReader(infile)
                writer = csv.DictWriter(outfile, fieldnames=['user_id', 'blocked_until', 'reason'])
                writer.writeheader()

                for row in reader:
                    if int(row['user_id']) != user_id:
                        writer.writerow(row)

            os.replace(temp_path, BLOCKED_USERS_PATH)
        except Exception as e:
            print(f"Error removing blocked user: {e}")

    def _check_rate_limits(self):
        """Check current invite rate limits"""
        now = datetime.datetime.now()
        today = now.date()
        current_hour = now.hour

        # Reset daily counter if day changed
        if 'last_day' in self.stats and self.stats['last_day'] != today:
            self.stats['today'] = 0
            self.stats['last_day'] = today

        # Reset hourly counter if hour changed
        if 'last_hour' in self.stats and self.stats['last_hour'] != current_hour:
            self.stats['this_hour'] = 0
            self.stats['last_hour'] = current_hour

        # Check limits
        if self.stats['today'] >= self.rate_limits['daily_limit']:
            return False, f"Daily invite limit exceeded ({self.rate_limits['daily_limit']})"

        if self.stats['this_hour'] >= self.rate_limits['hourly_limit']:
            return False, f"Hourly invite limit exceeded ({self.rate_limits['hourly_limit']})"

        # Check time after last error
        if self.stats['consecutive_errors'] >= self.rate_limits['consecutive_errors_limit']:
            if (now - datetime.datetime.fromtimestamp(self.stats['last_error_time'])).total_seconds() < self.rate_limits['cooldown_after_errors']:
                return False, f"Too many errors. Waiting {self.rate_limits['cooldown_after_errors']//60} minutes"

        return True, ""

    def _get_delay(self):
        """Get random delay between invites"""
        return random.randint(self.rate_limits['min_delay'], self.rate_limits['max_delay'])

    def _update_stats(self, success=True):
        """Update invite statistics"""
        now = datetime.datetime.now()
        self.stats['today'] += 1
        self.stats['this_hour'] += 1
        self.stats['last_invite_time'] = time.time()

        if not success:
            self.stats['consecutive_errors'] += 1
            self.stats['last_error_time'] = time.time()
        else:
            self.stats['consecutive_errors'] = 0

    async def _get_target_entity(self, client, target):
        """Get target chat entity with validation"""
        try:
            entity = await client.get_entity(target)
            if not isinstance(entity, (types.Channel, types.Chat)):
                return None, "Specified object is not a chat or channel"

            me = await client.get_me()
            my_perms = await client.get_permissions(entity.id, me)
            if not my_perms.invite_users:
                return None, "Bot doesn't have invite permissions"

            return entity, None
        except Exception as e:
            return None, f"Error getting chat: {str(e)}"

    async def _get_user_entity(self, client, user_data):
        """Get user entity for invite"""
        try:
            if user_data.get('username'):
                try:
                    return await client.get_input_entity(user_data['username']), None
                except Exception:
                    pass

            if user_data['access_hash']:
                return InputPeerUser(user_data['id'], user_data['access_hash']), None

            return None, "Could not get user entity"
        except Exception as e:
            return None, f"Error getting user entity: {str(e)}"

    async def _invite_user(self, client, target_entity, user_entity, user_data):
        """Invite single user to chat"""
        try:
            await client(InviteToChannelRequest(
                channel=target_entity,
                users=[user_entity]
            ))
            return True, None
        except Exception as e:
            error_msg = str(e)
            if "USER_PRIVACY_RESTRICTED" in error_msg:
                return False, "User restricted invites"
            elif "USER_NOT_MUTUAL_CONTACT" in error_msg:
                return False, "User is not a mutual contact"
            elif "USERS_TOO_MUCH" in error_msg:
                return False, "Chat user limit reached"
            elif "CHAT_ADMIN_REQUIRED" in error_msg:
                return False, "Admin rights required"
            elif "PEER_FLOOD" in error_msg:
                return False, "Request limit exceeded (flood)"
            elif "USER_BANNED_IN_CHANNEL" in error_msg:
                return False, "User is banned in chat"
            elif "USER_KICKED" in error_msg:
                return False, "User was kicked"
            elif "USER_ID_INVALID" in error_msg:
                return False, "Invalid user ID"
            elif "CHANNEL_PRIVATE" in error_msg:
                return False, "Chat is private"
            else:
                return False, error_msg

    async def invite_users_from_csv(self, client, event, target_chat, csv_filepath=None):
        """Main method to invite users from CSV file"""
        if not await is_admin(event):
            await event.reply("⛔ Admin privileges required")
            return

        # Check rate limits
        can_invite, limit_msg = self._check_rate_limits()
        if not can_invite:
            await event.reply(f"⚠️ {limit_msg}\nPlease try later.")
            return

        # Get target chat
        target_entity, error = await self._get_target_entity(client, target_chat)
        if not target_entity:
            await event.reply(f"❌ {error}")
            return

        # Determine CSV file path
        if not csv_filepath:
            csv_filepath = INVITE_CSV_PATH

        if not os.path.exists(csv_filepath):
            await event.reply(f"❌ File {os.path.basename(csv_filepath)} not found!")
            return

        # Load users from CSV
        users = []
        with open(csv_filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    user_id = int(row['id'])
                    if self._is_user_blocked(user_id):
                        continue

                    access_hash = int(row['access_hash']) if row.get('access_hash') and row['access_hash'].isdigit() else 0
                    users.append({
                        'id': user_id,
                        'access_hash': access_hash,
                        'name': f"{row.get('first_name', '')} {row.get('last_name', '')}".strip() or str(user_id),
                        'username': row.get('username', '')
                    })
                except Exception as e:
                    print(f"Error processing row: {row} - {str(e)}")
                    continue

        if not users:
            await event.reply("❌ No valid users in CSV")
            return

        # If multiple CSV files exist, offer to choose
        csv_files = []
        for filename in os.listdir(txt_logs_folder):
            if filename.startswith('users') and filename.endswith('.csv') and filename != os.path.basename(INVITE_CSV_PATH):
                csv_files.append(os.path.join(txt_logs_folder, filename))

        if len(csv_files) > 0 and not csv_filepath:
            buttons = []
            for i, filepath in enumerate(csv_files):
                buttons.append([Button.inline(os.path.basename(filepath), f"select_invite_csv_{i}")])

            await event.reply("Select CSV file with users:", buttons=buttons)
            return

        # Start invite process
        progress_msg = await event.reply(f"🔄 Starting to add {len(users)} users to {target_entity.title}...")
        success = 0
        failed = []
        target_input_entity = InputPeerChannel(target_entity.id, target_entity.access_hash)

        # Process users in batches
        for i in range(0, len(users), self.rate_limits['batch_size']):
            batch = users[i:i + self.rate_limits['batch_size']]
            batch_success = 0
            batch_failed = []

            for user in batch:
                if self.stats['consecutive_errors'] >= self.rate_limits['consecutive_errors_limit']:
                    await progress_msg.edit(
                        f"⚠️ Stopped due to too many errors\n"
                        f"✅ Success: {success}\n"
                        f"❌ Failed: {len(failed)}"
                    )
                    return

                # Check rate limits before each invite
                can_invite, limit_msg = self._check_rate_limits()
                if not can_invite:
                    await progress_msg.edit(
                        f"⚠️ Stopped: {limit_msg}\n"
                        f"✅ Success: {success}\n"
                        f"❌ Failed: {len(failed)}"
                    )
                    return

                try:
                    # Get user entity
                    user_entity, error = await self._get_user_entity(client, user)
                    if not user_entity:
                        failed.append(f"{user['id']} ({user['name']}): {error}")
                        self._log_invite(target_entity.id, user['id'], "failed", error)
                        self._update_stats(success=False)
                        continue

                    # Perform invite
                    invite_success, error = await self._invite_user(client, target_input_entity, user_entity, user)
                    if invite_success:
                        success += 1
                        batch_success += 1
                        self._log_invite(target_entity.id, user['id'], "success")
                        self._update_stats(success=True)
                    else:
                        failed.append(f"{user['id']} ({user['name']}): {error}")
                        self._log_invite(target_entity.id, user['id'], "failed", error)
                        self._update_stats(success=False)

                        # Add user to block list if error is serious
                        if "PEER_FLOOD" in error or "USER_PRIVACY_RESTRICTED" in error:
                            self._add_blocked_user(user['id'], error)

                except Exception as e:
                    failed.append(f"{user['id']} ({user['name']}): {str(e)}")
                    self._log_invite(target_entity.id, user['id'], "failed", str(e))
                    self._update_stats(success=False)
                    continue

                # Delay between invites
                if i + batch.index(user) < len(users) - 1:  # Don't wait after last user
                    delay = self._get_delay()
                    await asyncio.sleep(delay)

            # Update progress after each batch
            await progress_msg.edit(
                f"🔄 Processed: {i + len(batch)}/{len(users)}\n"
                f"✅ Success: {success}\n"
                f"❌ Failed: {len(failed)}\n\n"
                f"Last batch: {batch_success} success, {len(batch) - batch_success} failed"
            )

        # Generate final report
        report = (
            f"📊 Invite results for {target_entity.title}:\n"
            f"✅ Success: {success}\n"
            f"❌ Failed: {len(failed)}\n"
        )

        if failed:
            report += "\n🔴 Example errors:\n" + "\n".join(failed[:5])
            log_file = f"invite_errors_{target_entity.id}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
            with open(os.path.join(txt_logs_folder, log_file), 'w', encoding='utf-8') as f:
                f.write("\n".join(failed))
            report += f"\n\n📄 Full error log: {log_file}"

        await progress_msg.edit(report)

    async def handle_invite_command(self, client, event):
        """Handler for /invite command"""
        args = event.text.split(maxsplit=1)
        if len(args) < 2:
            await event.reply("ℹ️ Usage: `/invite @chat_username`")
            return

        await self.invite_users_from_csv(client, event, args[1].strip())

    async def handle_csv_selection(self, client, event):
        """Handler for CSV file selection"""
        if not await is_admin(event):
            await event.answer("Access denied!", alert=True)
            return

        try:
            index = int(event.data.decode().split('_')[-1])
            csv_files = []
            for filename in os.listdir(txt_logs_folder):
                if filename.startswith('users') and filename.endswith('.csv') and filename != os.path.basename(INVITE_CSV_PATH):
                    csv_files.append(os.path.join(txt_logs_folder, filename))

            if index >= len(csv_files):
                await event.answer("File not found!", alert=True)
                return

            filepath = csv_files[index]
            await event.answer(f"Selected file: {os.path.basename(filepath)}")

            # Get original /invite command arguments
            original_message = await event.get_message()
            args = original_message.text.split(maxsplit=1)
            if len(args) < 2:
                await event.edit("❌ Error: no chat specified for invite")
                return

            await self.invite_users_from_csv(client, event, args[1].strip(), csv_filepath=filepath)

        except Exception as e:
            await event.answer(f"Error: {str(e)}", alert=True)

    def get_blocked_users(self):
        """Get list of currently blocked users"""
        blocked_users = []
        try:
            if os.path.exists(BLOCKED_USERS_PATH):
                with open(BLOCKED_USERS_PATH, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        blocked_until = datetime.datetime.fromisoformat(row['blocked_until'])
                        if blocked_until > datetime.datetime.now():
                            blocked_users.append({
                                'user_id': int(row['user_id']),
                                'blocked_until': blocked_until,
                                'reason': row['reason']
                            })
        except Exception as e:
            print(f"Error getting blocked users: {e}")
        return blocked_users

def register_handlers(client):
    """Register invite handlers"""
    invite_manager = InviteManager()

    @client.on(events.NewMessage(pattern='/invite'))
    async def handle_invite(event):
        await invite_manager.handle_invite_command(client, event)

    @client.on(events.CallbackQuery(pattern=b'select_invite_csv_'))
    async def select_csv_file(event):
        await invite_manager.handle_csv_selection(client, event)

    @client.on(events.NewMessage(pattern='/invite_stats'))
    async def handle_invite_stats(event):
        """Show invite statistics"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        stats = invite_manager.stats
        rate_limits = invite_manager.rate_limits

        today = datetime.date.today()
        current_hour = datetime.datetime.now().hour

        # Reset counters if needed
        if 'last_day' in stats and stats['last_day'] != today:
            stats['today'] = 0
            stats['last_day'] = today

        if 'last_hour' in stats and stats['last_hour'] != current_hour:
            stats['this_hour'] = 0
            stats['last_hour'] = current_hour

        response = (
            f"📊 Invite statistics:\n\n"
            f"📅 Today: {stats['today']}/{rate_limits['daily_limit']}\n"
            f"⏰ This hour: {stats['this_hour']}/{rate_limits['hourly_limit']}\n"
            f"❌ Consecutive errors: {stats['consecutive_errors']}/{rate_limits['consecutive_errors_limit']}\n\n"
            f"⏳ Delays between invites: {rate_limits['min_delay']}-{rate_limits['max_delay']} sec\n"
            f"📦 Batch size: {rate_limits['batch_size']} users\n\n"
            f"🔒 Blocked users: {len(invite_manager.get_blocked_users())}\n"
            f"📄 Total invite logs: {sum(1 for _ in open(INVITE_LOG_PATH, 'r', encoding='utf-8')) - 1 if os.path.exists(INVITE_LOG_PATH) else 0}"
        )

        await event.reply(response)
