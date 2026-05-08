from telethon import events, Button, types
import csv
import os
import asyncio
import random
import datetime
import time
from telethon.tl.types import InputPeerUser, InputPeerChannel
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.functions.contacts import ResolveUsernameRequest
from models.config import txt_logs_folder, media_folder, ADMIN_IDS
from models.database import save_user_to_db, get_user_count, cursor
from models.global_search import register_handlers as register_global_search_handlers

# Path to main CSV file for invites
INVITE_CSV_PATH = os.path.join(txt_logs_folder, 'users.csv')
# Path to file with parsing logs
PARSE_LOG_PATH = os.path.join(txt_logs_folder, 'parse_logs.csv')
# Path to file with temporary blocks
PARSE_BLOCKED_PATH = os.path.join(txt_logs_folder, 'parse_blocked.csv')

class ParseManager:
    def __init__(self):
        """Initialize parsing manager with rate limits and statistics"""
        self.rate_limits = {
            'min_delay': 5,  # minimum delay between requests (seconds)
            'max_delay': 15,  # maximum delay between requests
            'batch_size': 100,  # number of messages to process in one batch
            'daily_limit': 1000,  # daily request limit
            'hourly_limit': 300,  # hourly request limit
            'consecutive_errors_limit': 3,  # limit of consecutive errors
            'cooldown_after_errors': 1800  # cooldown period after errors (seconds)
        }
        self.stats = {
            'today': 0,
            'this_hour': 0,
            'last_request_time': 0,
            'consecutive_errors': 0,
            'last_error_time': 0
        }
        self._ensure_files_exist()
        self._load_stats()

    def _ensure_files_exist(self):
        """Create necessary files if they don't exist"""
        for filepath in [INVITE_CSV_PATH, PARSE_LOG_PATH, PARSE_BLOCKED_PATH]:
            if not os.path.exists(filepath):
                try:
                    with open(filepath, 'w', encoding='utf-8', newline='') as f:
                        if filepath == INVITE_CSV_PATH:
                            writer = csv.DictWriter(f, fieldnames=['id', 'access_hash', 'first_name', 'last_name', 'username'])
                            writer.writeheader()
                        elif filepath == PARSE_LOG_PATH:
                            writer = csv.DictWriter(f, fieldnames=['timestamp', 'chat_id', 'method', 'status', 'error', 'processed', 'new'])
                            writer.writeheader()
                        elif filepath == PARSE_BLOCKED_PATH:
                            writer = csv.DictWriter(f, fieldnames=['chat_id', 'blocked_until', 'reason'])
                            writer.writeheader()
                except Exception as e:
                    print(f"Error creating file {filepath}: {e}")

    def _load_stats(self):
        """Load statistics from logs"""
        try:
            if os.path.exists(PARSE_LOG_PATH):
                with open(PARSE_LOG_PATH, 'r', encoding='utf-8') as f:
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

    def _log_parse(self, chat_id, method, status, error=None, processed=0, new=0):
        """Log parsing attempt"""
        try:
            with open(PARSE_LOG_PATH, 'a', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['timestamp', 'chat_id', 'method', 'status', 'error', 'processed', 'new'])
                writer.writerow({
                    'timestamp': datetime.datetime.now().isoformat(),
                    'chat_id': chat_id,
                    'method': method,
                    'status': status,
                    'error': str(error) if error else '',
                    'processed': processed,
                    'new': new
                })
        except Exception as e:
            print(f"Error logging parsing: {e}")

    def _is_chat_blocked(self, chat_id):
        """Check if chat is temporarily blocked"""
        try:
            if not os.path.exists(PARSE_BLOCKED_PATH):
                return False

            with open(PARSE_BLOCKED_PATH, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if int(row['chat_id']) == chat_id:
                        blocked_until = datetime.datetime.fromisoformat(row['blocked_until'])
                        if blocked_until > datetime.datetime.now():
                            return True
                        else:
                            # Remove expired block
                            self._remove_blocked_chat(chat_id)
                            return False
            return False
        except Exception as e:
            print(f"Error checking blocked chat: {e}")
            return False

    def _add_blocked_chat(self, chat_id, reason):
        """Add chat to blocked list"""
        try:
            blocked_until = datetime.datetime.now() + datetime.timedelta(hours=12)
            with open(PARSE_BLOCKED_PATH, 'a', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['chat_id', 'blocked_until', 'reason'])
                writer.writerow({
                    'chat_id': chat_id,
                    'blocked_until': blocked_until.isoformat(),
                    'reason': reason
                })
        except Exception as e:
            print(f"Error adding blocked chat: {e}")

    def _remove_blocked_chat(self, chat_id):
        """Remove chat from blocked list"""
        try:
            if not os.path.exists(PARSE_BLOCKED_PATH):
                return

            temp_path = PARSE_BLOCKED_PATH + '.tmp'
            with open(PARSE_BLOCKED_PATH, 'r', encoding='utf-8') as infile, \
                 open(temp_path, 'w', encoding='utf-8', newline='') as outfile:

                reader = csv.DictReader(infile)
                writer = csv.DictWriter(outfile, fieldnames=['chat_id', 'blocked_until', 'reason'])
                writer.writeheader()

                for row in reader:
                    if int(row['chat_id']) != chat_id:
                        writer.writerow(row)

            os.replace(temp_path, PARSE_BLOCKED_PATH)
        except Exception as e:
            print(f"Error removing blocked chat: {e}")

    def _check_rate_limits(self):
        """Check current parsing rate limits"""
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
            return False, f"Daily request limit exceeded ({self.rate_limits['daily_limit']})"

        if self.stats['this_hour'] >= self.rate_limits['hourly_limit']:
            return False, f"Hourly request limit exceeded ({self.rate_limits['hourly_limit']})"

        # Check time after last error
        if self.stats['consecutive_errors'] >= self.rate_limits['consecutive_errors_limit']:
            if (now - datetime.datetime.fromtimestamp(self.stats['last_error_time'])).total_seconds() < self.rate_limits['cooldown_after_errors']:
                return False, f"Too many errors. Waiting {self.rate_limits['cooldown_after_errors']//60} minutes"

        return True, ""

    def _get_delay(self):
        """Get random delay between requests"""
        return random.randint(self.rate_limits['min_delay'], self.rate_limits['max_delay'])

    def _update_stats(self, success=True, processed=0, new=0):
        """Update parsing statistics"""
        now = datetime.datetime.now()
        self.stats['today'] += 1
        self.stats['this_hour'] += 1
        self.stats['last_request_time'] = time.time()

        if not success:
            self.stats['consecutive_errors'] += 1
            self.stats['last_error_time'] = time.time()
        else:
            self.stats['consecutive_errors'] = 0

async def is_admin(event):
    """Check if user has admin privileges"""
    from models.admin_tools import is_admin
    return await is_admin(event)

async def download_media(message):
    """Download media to temporary file"""
    try:
        temp_dir = os.path.join(media_folder, 'temp')
        os.makedirs(temp_dir, exist_ok=True)

        ext = None
        if message.photo:
            ext = 'jpg'
        elif message.video:
            ext = 'mp4'
        elif message.document:
            ext = message.document.mime_type.split('/')[-1] if message.document.mime_type else 'bin'

        if not ext:
            return None

        filename = f"copy_{message.id}.{ext}"
        filepath = os.path.join(temp_dir, filename)
        await message.download_media(file=filepath)
        return filepath

    except Exception as e:
        print(f"Error downloading media: {e}")
        return None

def get_user_data(user):
    """Extract full user data from Telegram user object"""
    try:
        last_seen = None
        if hasattr(user, 'status'):
            if hasattr(user.status, 'was_online'):
                last_seen = user.status.was_online
            elif hasattr(user.status, 'to_dict') and callable(user.status.to_dict):
                status_dict = user.status.to_dict()
                last_seen = status_dict.get('was_online')

        return {
            'id': user.id,
            'access_hash': user.access_hash if hasattr(user, 'access_hash') else 0,
            'first_name': user.first_name if hasattr(user, 'first_name') else '',
            'last_name': user.last_name if hasattr(user, 'last_name') else '',
            'username': user.username if hasattr(user, 'username') else '',
            'phone': user.phone if hasattr(user, 'phone') else '',
            'is_bot': getattr(user, 'bot', False),
            'is_restricted': getattr(user, 'restricted', False),
            'is_scam': getattr(user, 'scam', False),
            'is_fake': getattr(user, 'fake', False),
            'is_verified': getattr(user, 'verified', False),
            'language': getattr(user, 'lang_code', ''),
            'last_seen': last_seen,
            'is_admin': hasattr(user, 'admin_rights') and user.admin_rights is not None,
            'is_deleted': hasattr(user, 'deleted') and user.deleted
        }
    except Exception as e:
        print(f"Error getting user data for {getattr(user, 'id', 'unknown')}: {e}")
        return {
            'id': getattr(user, 'id', 0),
            'access_hash': 0,
            'first_name': '',
            'last_name': '',
            'username': '',
            'phone': '',
            'is_bot': False,
            'is_restricted': False,
            'is_scam': False,
            'is_fake': False,
            'is_verified': False,
            'language': '',
            'last_seen': None,
            'is_admin': False,
            'is_deleted': False
        }

def save_user_to_csv(user_data, filepath):
    """Save user data to CSV with duplicate checking"""
    file_exists = os.path.isfile(filepath)
    user_exists = False

    if file_exists:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if int(row['id']) == user_data['id']:
                        user_exists = True
                        break
        except Exception as e:
            print(f"Error reading CSV: {e}")
            file_exists = False

    if not user_exists:
        try:
            with open(filepath, 'a', encoding='utf-8', newline='') as f:
                fieldnames = ['id', 'access_hash', 'first_name', 'last_name', 'username', 'phone']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({k: user_data[k] for k in fieldnames})
        except Exception as e:
            print(f"Error writing to CSV: {e}")
            return False

    return not user_exists

def save_user_to_invite_csv(user_data, filepath=INVITE_CSV_PATH):
    """Save user data to CSV for forced invites"""
    file_exists = os.path.isfile(filepath)
    user_exists = False

    if file_exists:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if int(row['id']) == user_data['id']:
                        user_exists = True
                        break
        except Exception as e:
            print(f"Error reading invite CSV: {e}")
            file_exists = False

    if not user_exists:
        try:
            with open(filepath, 'a', encoding='utf-8', newline='') as f:
                fieldnames = ['id', 'access_hash', 'first_name', 'last_name', 'username']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    'id': user_data['id'],
                    'access_hash': user_data['access_hash'],
                    'first_name': user_data['first_name'],
                    'last_name': user_data['last_name'],
                    'username': user_data['username']
                })
        except Exception as e:
            print(f"Error writing to invite CSV: {e}")
            return False

    return not user_exists

def save_user_to_log(user_data, log_filepath):
    """Save user data to compact text log"""
    log_exists = os.path.isfile(log_filepath)
    user_exists = False

    if log_exists:
        try:
            with open(log_filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith(f"{user_data['id']} |"):
                        user_exists = True
                        break
        except Exception as e:
            print(f"Error reading log file: {e}")
            log_exists = False

    if not user_exists:
        try:
            with open(log_filepath, 'a', encoding='utf-8') as f:
                if not log_exists:
                    f.write("=== CHAT USERS LOG ===\n\n")
                    f.write("Format: ID | Name Surname | @username | Phone\n")
                    f.write("="*60 + "\n\n")

                name = f"{user_data['first_name']} {user_data['last_name']}".strip()
                username = f"@{user_data['username']}" if user_data['username'] else "None"
                phone = user_data['phone'] if user_data['phone'] else "None"

                f.write(f"{user_data['id']} | {name} | {username} | {phone}\n")
        except Exception as e:
            print(f"Error writing to log file: {e}")
            return False

    return not user_exists

async def parse_users_normal_mode(client, entity, event, parse_manager):
    """Parse users using standard get_participants method"""
    try:
        # Check limits before starting
        can_parse, limit_msg = parse_manager._check_rate_limits()
        if not can_parse:
            return False, limit_msg

        if parse_manager._is_chat_blocked(entity.id):
            return False, "Chat is temporarily blocked due to previous errors"

        participants = []
        async for participant in client.iter_participants(entity, aggressive=True):
            participants.append(participant)

        if not participants:
            return False, "Could not get participants"

        current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        csv_filename = f"parsed_users_{entity.id}_{current_time}.csv"
        log_filename = f"chat_logs_{current_time}.txt"
        csv_filepath = os.path.join(txt_logs_folder, csv_filename)
        log_filepath = os.path.join(txt_logs_folder, log_filename)

        new_users = 0
        for user in participants:
            try:
                user_data = get_user_data(user)
                if save_user_to_db(user_data):
                    if save_user_to_csv(user_data, csv_filepath):
                        if save_user_to_log(user_data, log_filepath):
                            new_users += 1
                    # Save to main invite CSV
                    save_user_to_invite_csv(user_data)
            except Exception as e:
                print(f"Error processing user {user.id}: {e}")
                continue

        parse_manager._log_parse(entity.id, "normal", "success", processed=len(participants), new=new_users)
        return True, {
            'total': len(participants),
            'new': new_users,
            'csv_file': csv_filename,
            'log_file': log_filename,
            'csv_path': csv_filepath,
            'log_path': log_filepath
        }

    except Exception as e:
        error_msg = str(e)
        parse_manager._log_parse(entity.id, "normal", "failed", error=error_msg)
        parse_manager._update_stats(success=False)

        # Block chat for serious errors
        if "FLOOD_WAIT" in error_msg or "PEER_FLOOD" in error_msg:
            parse_manager._add_blocked_chat(entity.id, error_msg)

        return False, f"Error: {error_msg}"

async def parse_users_message_mode(client, entity, event, parse_manager, limit=1000):
    """Parse users by analyzing messages with pagination"""
    try:
        # Check limits before starting
        can_parse, limit_msg = parse_manager._check_rate_limits()
        if not can_parse:
            return False, limit_msg

        if parse_manager._is_chat_blocked(entity.id):
            return False, "Chat is temporarily blocked due to previous errors"

        current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        csv_filename = f"parsed_users_msg_{entity.id}_{current_time}.csv"
        log_filename = f"chat_logs_msg_{current_time}.txt"
        csv_filepath = os.path.join(txt_logs_folder, csv_filename)
        log_filepath = os.path.join(txt_logs_folder, log_filename)

        processed_users = set()
        new_users = 0
        offset = 0
        batch_size = parse_manager.rate_limits['batch_size']
        total_processed = 0

        while True:
            # Check limits before each request
            can_parse, limit_msg = parse_manager._check_rate_limits()
            if not can_parse:
                return False, limit_msg

            try:
                messages = await client.get_messages(entity, limit=batch_size, offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=offset)
            except Exception as e:
                error_msg = str(e)
                parse_manager._log_parse(entity.id, "message", "failed", error=error_msg)
                parse_manager._update_stats(success=False)

                # Block chat for serious errors
                if "FLOOD_WAIT" in error_msg or "PEER_FLOOD" in error_msg:
                    parse_manager._add_blocked_chat(entity.id, error_msg)

                return False, f"Error getting messages: {error_msg}"

            if not messages:
                break

            for message in messages:
                if not message.sender_id or message.sender_id in processed_users:
                    continue

                try:
                    user = await client.get_entity(message.sender_id)
                    if not user:
                        continue

                    user_data = get_user_data(user)
                    if save_user_to_db(user_data):
                        if save_user_to_csv(user_data, csv_filepath):
                            if save_user_to_log(user_data, log_filepath):
                                new_users += 1

                    # Save to main invite CSV
                    save_user_to_invite_csv(user_data)
                    processed_users.add(message.sender_id)
                    total_processed += 1

                except Exception as e:
                    print(f"Error processing user {message.sender_id}: {e}")
                    continue

            offset += batch_size
            # Delay between requests
            delay = parse_manager._get_delay()
            await asyncio.sleep(delay)

        parse_manager._log_parse(entity.id, "message", "success", processed=len(processed_users), new=new_users)
        return True, {
            'total': len(processed_users),
            'new': new_users,
            'csv_file': csv_filename,
            'log_file': log_filename,
            'csv_path': csv_filepath,
            'log_path': log_filepath
        }

    except Exception as e:
        error_msg = str(e)
        parse_manager._log_parse(entity.id, "message", "failed", error=error_msg)
        parse_manager._update_stats(success=False)

        # Block chat for serious errors
        if "FLOOD_WAIT" in error_msg or "PEER_FLOOD" in error_msg:
            parse_manager._add_blocked_chat(entity.id, error_msg)

        return False, f"Error: {error_msg}"

async def parse_users_dialogs_mode(client, event, parse_manager):
    """Parse users through dialogs (additional method)"""
    try:
        # Check limits before starting
        can_parse, limit_msg = parse_manager._check_rate_limits()
        if not can_parse:
            return False, limit_msg

        current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        csv_filename = f"parsed_users_dialogs_{current_time}.csv"
        log_filename = f"chat_logs_dialogs_{current_time}.txt"
        csv_filepath = os.path.join(txt_logs_folder, csv_filename)
        log_filepath = os.path.join(txt_logs_folder, log_filename)

        processed_users = set()
        new_users = 0

        async for dialog in client.iter_dialogs():
            # Check limits before each iteration
            can_parse, limit_msg = parse_manager._check_rate_limits()
            if not can_parse:
                return False, limit_msg

            if not dialog.is_user:
                continue

            try:
                user = await dialog.get_entity()
                if not user or user.id in processed_users:
                    continue

                user_data = get_user_data(user)
                if save_user_to_db(user_data):
                    if save_user_to_csv(user_data, csv_filepath):
                        if save_user_to_log(user_data, log_filepath):
                            new_users += 1

                # Save to main invite CSV
                save_user_to_invite_csv(user_data)
                processed_users.add(user.id)

                # Delay between requests
                delay = parse_manager._get_delay()
                await asyncio.sleep(delay)

            except Exception as e:
                print(f"Error processing user from dialogs: {e}")
                continue

        parse_manager._log_parse(0, "dialogs", "success", processed=len(processed_users), new=new_users)
        return True, {
            'total': len(processed_users),
            'new': new_users,
            'csv_file': csv_filename,
            'log_file': log_filename,
            'csv_path': csv_filepath,
            'log_path': log_filepath
        }

    except Exception as e:
        error_msg = str(e)
        parse_manager._log_parse(0, "dialogs", "failed", error=error_msg)
        parse_manager._update_stats(success=False)
        return False, f"Error: {error_msg}"

def register_handlers(client):
    """Register all parsing handlers"""
    parse_manager = ParseManager()

    @client.on(events.NewMessage(pattern='/pars'))
    async def handle_parse_users(event):
        """Parse users from specified chat/channel with multi-stage collection"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split(maxsplit=2)
        if len(args) < 2 or args[1].lower() != 'all_uss':
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/pars all_uss username_or_link</code> - collect user data\n\n"
                "Example: <code>/pars all_uss @my_channel</code>",
                parse_mode='HTML'
            )
            return

        target = args[2] if len(args) > 2 else ''
        if not target:
            await event.reply("⚠️ Please specify username or link to chat/channel")
            return

        try:
            await event.reply("🔍 Starting to collect user data...")

            try:
                entity = await client.get_entity(target)
            except ValueError:
                await event.reply("❌ Could not find specified chat/channel")
                return

            if not isinstance(entity, (types.Channel, types.Chat)):
                await event.reply("❌ Specified object is not a chat or channel")
                return

            # Method 1: Standard participant parsing
            await event.reply("🔄 Trying standard method (participant list)...")
            success1, result1 = await parse_users_normal_mode(client, entity, event, parse_manager)
            if not success1:
                await event.reply(f"⚠️ Standard method failed: {result1}")

            # Method 2: Message-based parsing with pagination
            await event.reply("🔄 Trying backup method (message parsing)...")
            success2, result2 = await parse_users_message_mode(client, entity, event, parse_manager)
            if not success2:
                await event.reply(f"⚠️ Backup method failed: {result2}")

            # Method 3: Dialog-based parsing (additional)
            await event.reply("🔄 Trying additional method (dialog parsing)...")
            success3, result3 = await parse_users_dialogs_mode(client, event, parse_manager)
            if not success3:
                await event.reply(f"⚠️ Additional method failed: {result3}")

            # Combine results
            total_users = 0
            new_users = 0
            results = []

            if success1:
                total_users += result1['total']
                new_users += result1['new']
                results.append(result1)
            if success2:
                total_users += result2['total']
                new_users += result2['new']
                results.append(result2)
            if success3:
                total_users += result3['total']
                new_users += result3['new']
                results.append(result3)

            # Get total count of unique users in database
            unique_users = get_user_count()

            # Check if files exist before sending
            files_to_send = []
            combined_csv = os.path.join(txt_logs_folder, f"combined_users_{entity.id}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv")

            # Create combined CSV file from database
            try:
                cursor.execute('SELECT id, access_hash, first_name, last_name, username, phone FROM parsed_users')
                users = cursor.fetchall()

                with open(combined_csv, 'w', encoding='utf-8', newline='') as outfile:
                    fieldnames = ['id', 'access_hash', 'first_name', 'last_name', 'username', 'phone']
                    writer = csv.DictWriter(outfile, fieldnames=fieldnames)
                    writer.writeheader()

                    for user in users:
                        writer.writerow({
                            'id': user[0],
                            'access_hash': user[1],
                            'first_name': user[2],
                            'last_name': user[3],
                            'username': user[4],
                            'phone': user[5]
                        })

                files_to_send = [combined_csv]
            except Exception as e:
                print(f"Error creating combined CSV: {e}")

            # Create response
            response = (
                f"✅ Successfully collected user data\n"
                f"📊 Total processed: {total_users}\n"
                f"🆕 New users: {new_users}\n"
                f"👥 Unique in database: {unique_users}\n\n"
            )

            for i, result in enumerate(results, 1):
                response += (
                    f"🔹 Method {i} ({result.get('method', 'unknown')}):\n"
                    f"   Processed: {result['total']}\n"
                    f"   New: {result['new']}\n"
                    f"   CSV: <code>{result['csv_file']}</code>\n"
                    f"   Log: <code>{result['log_file']}</code>\n\n"
                )

            response += (
                f"📄 Combined CSV file: <code>{os.path.basename(combined_csv)}</code>\n"
                f"📄 Main invite CSV: <code>{os.path.basename(INVITE_CSV_PATH)}</code>\n\n"
                f"🔹 Log format: ID | Name Surname | @username | Phone\n\n"
                f"💡 You can now use <code>/invite @chat_username</code> to invite users"
            )

            # Send files if they exist
            if files_to_send:
                await event.reply(
                    response,
                    parse_mode='HTML',
                    file=files_to_send
                )
            else:
                await event.reply(
                    f"{response}\n\n⚠️ Warning: files were not created due to errors"
                )

        except Exception as e:
            await event.reply(f"❌ Unexpected error: {str(e)}")

    @client.on(events.NewMessage(pattern='/parsmsg'))
    async def handle_parse_messages(event):
        """Parse user messages with access_hash saving and CSV creation for invites"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split(maxsplit=3)
        if len(args) < 4:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/parsmsg username_or_link user_id limit</code>\n\n"
                "Example: <code>/parsmsg @my_channel 123456789 100</code>",
                parse_mode='HTML'
            )
            return

        target = args[1]
        user_id = int(args[2])
        limit = min(int(args[3]), 1000) if len(args) > 3 else 100

        try:
            # Check limits before starting
            can_parse, limit_msg = parse_manager._check_rate_limits()
            if not can_parse:
                await event.reply(f"⚠️ {limit_msg}")
                return

            await event.reply(f"🔍 Starting to collect messages from user {user_id}...")

            entity = await client.get_entity(target)
            user = await client.get_entity(user_id)

            current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"parsed_msgs_{entity.id}_{user_id}_{current_time}.txt"
            csv_filename = f"parsed_user_{user_id}_{current_time}.csv"
            filepath = os.path.join(txt_logs_folder, filename)
            csv_filepath = os.path.join(txt_logs_folder, csv_filename)

            user_data = get_user_data(user)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("=== USER INFORMATION ===\n\n")
                f.write(f"ID: {user_data['id']}\n")
                f.write(f"Access Hash: {user_data['access_hash']}\n")
                f.write(f"Name: {user_data['first_name']} {user_data['last_name']}\n")
                f.write(f"Username: @{user_data['username']}\n")
                f.write(f"Phone: {user_data['phone'] or 'None'}\n\n")
                f.write("=== MESSAGES ===\n\n")

                count = 0
                async for message in client.iter_messages(entity, from_user=user, limit=limit):
                    count += 1
                    f.write(f"📅 {message.date.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"📝 {message.text or '[Media]'}\n")
                    f.write("="*40 + "\n\n")

                    # Delay between requests
                    if count % 10 == 0:  # Every 10 messages
                        delay = parse_manager._get_delay()
                        await asyncio.sleep(delay)

            # Save user to CSV for future use
            save_user_to_csv(user_data, csv_filepath)
            save_user_to_invite_csv(user_data)

            parse_manager._log_parse(entity.id, "parsmsg", "success", processed=count, new=1)
            parse_manager._update_stats(success=True, processed=count, new=1)

            if os.path.exists(filepath):
                files_to_send = [filepath, csv_filepath]
                await event.reply(
                    f"✅ Successfully collected {count} messages\n"
                    f"📄 Message file: <code>{filename}</code>\n"
                    f"📄 CSV file: <code>{csv_filename}</code>\n"
                    f"📄 Main invite CSV updated: <code>{os.path.basename(INVITE_CSV_PATH)}</code>\n\n"
                    f"💡 You can now use <code>/invite @chat_username</code> to invite this user",
                    parse_mode='HTML',
                    file=files_to_send
                )
            else:
                await event.reply(f"✅ Processed {count} messages, but file was not created")

        except Exception as e:
            error_msg = str(e)
            parse_manager._log_parse(0, "parsmsg", "failed", error=error_msg)
            parse_manager._update_stats(success=False)

            await event.reply(f"❌ Error: {error_msg}")

    @client.on(events.NewMessage(pattern='/msgcopy'))
    async def handle_msg_copy(event):
        """Copy messages from protected chats bypassing restrictions"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split(maxsplit=1)
        if len(args) < 2:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/msgcopy message_link</code>\n\n"
                "Example: <code>/msgcopy https://t.me/channel/123</code>",
                parse_mode='HTML'
            )
            return

        try:
            await event.delete()
            url = args[1].strip()

            if not url.startswith('https://t.me/'):
                reply = await event.respond("❌ Invalid link")
                await asyncio.sleep(5)
                await reply.delete()
                return

            parts = url.split('/')
            if len(parts) < 4 or not parts[-1].isdigit():
                reply = await event.respond("❌ Invalid link format")
                await asyncio.sleep(5)
                await reply.delete()
                return

            chat_entity = parts[3] if len(parts) == 5 else '/'.join(parts[3:-1])
            msg_id = int(parts[-1])

            try:
                # Check limits before request
                can_parse, limit_msg = parse_manager._check_rate_limits()
                if not can_parse:
                    reply = await event.respond(f"⚠️ {limit_msg}")
                    await asyncio.sleep(5)
                    await reply.delete()
                    return

                # Try to get message directly
                source_msg = await client.get_messages(chat_entity, ids=msg_id)
                if not source_msg:
                    # Try to bypass forwarding restriction via ResolveUsername
                    try:
                        resolved = await client(ResolveUsernameRequest(chat_entity))
                        if resolved.peer:
                            source_msg = await client.get_messages(resolved.peer, ids=msg_id)
                    except Exception as e:
                        print(f"ResolveUsername error: {e}")
            except ValueError:
                reply = await event.respond("❌ Chat not found")
                await asyncio.sleep(5)
                await reply.delete()
                return

            if not source_msg:
                reply = await event.respond("❌ Message not found")
                await asyncio.sleep(5)
                await reply.delete()
                return

            text = f"{source_msg.text}\n\n🔗 [Source]({url})" if source_msg.text else f"🔗 [Source]({url})"

            if source_msg.media:
                temp_file = await download_media(source_msg)
                if not temp_file:
                    await event.respond("❌ Could not process media")
                    return

                buttons = [[Button.url("🔗 Go to original", url=url)]]
                try:
                    if isinstance(source_msg.media, types.MessageMediaPhoto):
                        await event.client.send_file(
                            event.chat_id,
                            temp_file,
                            caption=text,
                            buttons=buttons,
                            parse_mode='markdown'
                        )
                    else:
                        await event.client.send_file(
                            event.chat_id,
                            temp_file,
                            caption=text,
                            buttons=buttons,
                            supports_streaming=True,
                            parse_mode='markdown'
                        )
                finally:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
            else:
                buttons = [[Button.url("🔗 Go to original", url=url)]]
                await event.client.send_message(
                    event.chat_id,
                    text,
                    buttons=buttons,
                    parse_mode='markdown',
                    link_preview=False
                )

            parse_manager._log_parse(0, "msgcopy", "success")
            parse_manager._update_stats(success=True)

        except Exception as e:
            error_msg = str(e)
            parse_manager._log_parse(0, "msgcopy", "failed", error=error_msg)
            parse_manager._update_stats(success=False)

            error_msg = await event.respond(f"❌ Error: {error_msg}")
            await asyncio.sleep(5)
            await error_msg.delete()

    @client.on(events.NewMessage(pattern='/parse_stats'))
    async def handle_parse_stats(event):
        """Show parsing statistics"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        stats = parse_manager.stats
        rate_limits = parse_manager.rate_limits

        today = datetime.date.today()
        current_hour = datetime.datetime.now().hour

        # Reset counters if needed
        if 'last_day' in stats and stats['last_day'] != today:
            stats['today'] = 0
            stats['last_day'] = today

        if 'last_hour' in stats and stats['last_hour'] != current_hour:
            stats['this_hour'] = 0
            stats['last_hour'] = current_hour

        # Get count of blocked chats
        blocked_chats = 0
        if os.path.exists(PARSE_BLOCKED_PATH):
            with open(PARSE_BLOCKED_PATH, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    blocked_until = datetime.datetime.fromisoformat(row['blocked_until'])
                    if blocked_until > datetime.datetime.now():
                        blocked_chats += 1

        response = (
            f"📊 Parsing statistics:\n\n"
            f"📅 Today: {stats['today']}/{rate_limits['daily_limit']}\n"
            f"⏰ This hour: {stats['this_hour']}/{rate_limits['hourly_limit']}\n"
            f"❌ Consecutive errors: {stats['consecutive_errors']}/{rate_limits['consecutive_errors_limit']}\n\n"
            f"⏳ Delays between requests: {rate_limits['min_delay']}-{rate_limits['max_delay']} sec\n"
            f"📦 Batch size: {rate_limits['batch_size']} messages\n\n"
            f"🔒 Blocked chats: {blocked_chats}\n"
            f"📄 Total parsing logs: {sum(1 for _ in open(PARSE_LOG_PATH, 'r', encoding='utf-8')) - 1 if os.path.exists(PARSE_LOG_PATH) else 0}"
        )

        await event.reply(response)

    @client.on(events.NewMessage(pattern='/usercount'))
    async def handle_user_count(event):
        """Show count of unique users in database"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        try:
            count = get_user_count()
            invite_count = 0

            if os.path.exists(INVITE_CSV_PATH):
                with open(INVITE_CSV_PATH, 'r', encoding='utf-8') as f:
                    invite_count = sum(1 for line in f) - 1  # minus header

            await event.reply(
                f"👥 Count of unique users:\n"
                f"• In database: {count}\n"
                f"• In main invite CSV: {invite_count}"
            )
        except Exception as e:
            await event.reply(f"❌ Error: {str(e)}")

    # Register global search handlers
    register_global_search_handlers(client)
