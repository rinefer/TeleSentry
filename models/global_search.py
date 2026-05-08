import os
import csv
import asyncio
import random
import datetime
from telethon import events, types
from telethon.tl.functions.messages import SearchGlobalRequest
from models.config import txt_logs_folder, ADMIN_IDS

class GlobalSearchManager:
    def __init__(self):
        """Initialize global search manager with rate limits and statistics"""
        self.rate_limits = {
            'min_delay': 10,  # minimum delay between requests (seconds)
            'max_delay': 30,  # maximum delay between requests
            'daily_limit': 500,  # daily request limit
            'hourly_limit': 100,  # hourly request limit
            'consecutive_errors_limit': 3,  # limit of consecutive errors
            'cooldown_after_errors': 3600  # cooldown period after errors (seconds)
        }
        self.stats = {
            'today': 0,
            'this_hour': 0,
            'last_request_time': 0,
            'consecutive_errors': 0,
            'last_error_time': 0,
            'last_day': datetime.date.today(),
            'last_hour': datetime.datetime.now().hour
        }
        self.search_active = False
        self.current_search_keyword = None
        self.current_search_results = []

    def _check_rate_limits(self):
        """Check current search rate limits"""
        now = datetime.datetime.now()
        today = now.date()
        current_hour = now.hour

        # Reset daily counter if day changed
        if self.stats['last_day'] != today:
            self.stats['today'] = 0
            self.stats['last_day'] = today

        # Reset hourly counter if hour changed
        if self.stats['last_hour'] != current_hour:
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

    def _update_stats(self, success=True):
        """Update search statistics"""
        now = datetime.datetime.now()
        self.stats['today'] += 1
        self.stats['this_hour'] += 1
        self.stats['last_request_time'] = now.timestamp()

        if not success:
            self.stats['consecutive_errors'] += 1
            self.stats['last_error_time'] = now.timestamp()
        else:
            self.stats['consecutive_errors'] = 0

    async def stop_search(self):
        """Stop current search"""
        self.search_active = False
        self.current_search_keyword = None
        self.current_search_results = []
        return "Search stopped"

    async def search_chats(self, client, keyword, event):
        """Perform global search for chats by keyword"""
        self.search_active = True
        self.current_search_keyword = keyword
        self.current_search_results = []

        try:
            # Check client connection
            if not client.is_connected():
                await client.connect()
                if not await client.is_user_authorized():
                    return False, "Client not authorized"

            # Check rate limits before starting
            can_search, limit_msg = self._check_rate_limits()
            if not can_search:
                return False, limit_msg

            await event.edit("🔍 Starting global chat search...")

            found_chats = 0
            processed = 0

            # Create CSV file for results
            current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            csv_filename = f"parsed_global_{keyword}_{current_time}.csv"
            csv_filepath = os.path.join(txt_logs_folder, csv_filename)

            # Write CSV header
            with open(csv_filepath, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'chat_id', 'chat_title', 'chat_username',
                    'chat_description', 'chat_participants', 'keyword'
                ])
                writer.writeheader()

            # Get search results with proper parameters
            try:
                results = await client(SearchGlobalRequest(
                    q=keyword,
                    filter=types.InputMessagesFilterEmpty(),
                    limit=100,
                    min_date=None,
                    max_date=None,
                    offset_rate=0,
                    offset_peer=types.InputPeerEmpty(),
                    offset_id=0
                ))
            except Exception as e:
                error_msg = str(e)
                self._update_stats(success=False)
                return False, f"Search error: {error_msg}"

            if not results or not hasattr(results, 'chats'):
                self._update_stats(success=False)
                return False, "No results found for your query"

            # Process found chats
            for chat in results.chats:
                if not self.search_active:
                    break

                try:
                    # Check rate limits before each iteration
                    can_search, limit_msg = self._check_rate_limits()
                    if not can_search:
                        await event.edit(f"⚠️ {limit_msg}")
                        break

                    processed += 1
                    if isinstance(chat, (types.Channel, types.Chat)):
                        found_chats += 1

                        # Save chat information to CSV and memory
                        chat_data = {
                            'chat_id': chat.id,
                            'chat_title': getattr(chat, 'title', ''),
                            'chat_username': getattr(chat, 'username', ''),
                            'chat_description': getattr(chat, 'about', ''),
                            'chat_participants': getattr(chat, 'participants_count', 0),
                            'keyword': keyword
                        }

                        self.current_search_results.append(chat_data)

                        # Save to CSV file
                        with open(csv_filepath, 'a', encoding='utf-8', newline='') as f:
                            writer = csv.DictWriter(f, fieldnames=[
                                'chat_id', 'chat_title', 'chat_username',
                                'chat_description', 'chat_participants', 'keyword'
                            ])
                            writer.writerow(chat_data)

                    # Delay between processing chats
                    delay = self._get_delay()
                    await asyncio.sleep(delay)

                except Exception as e:
                    print(f"Error processing chat {getattr(chat, 'id', 'unknown')}: {e}")
                    continue

            self._update_stats(success=True)

            return True, {
                'found': found_chats,
                'processed': processed,
                'keyword': keyword,
                'csv_file': csv_filename,
                'csv_path': csv_filepath
            }

        except Exception as e:
            error_msg = str(e)
            self._update_stats(success=False)
            return False, f"Unexpected error: {error_msg}"

def register_handlers(client):
    """Register global search handlers"""
    search_manager = GlobalSearchManager()

    async def is_admin(event):
        """Check if user has admin privileges"""
        from models.admin_tools import is_admin
        return await is_admin(event)

    @client.on(events.NewMessage(pattern='/search_ch'))
    async def handle_search_chats(event):
        """Perform global search for chats by keyword"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        if search_manager.search_active:
            await event.reply("⚠️ Search is already in progress. Wait for completion or stop it with /stopsearch")
            return

        args = event.message.text.split(maxsplit=1)
        if len(args) < 2:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/search_ch keyword</code>\n\n"
                "Example: <code>/search_ch cryptocurrency</code>",
                parse_mode='HTML'
            )
            return

        keyword = args[1].strip()
        if not keyword:
            await event.reply("⚠️ Please specify a search keyword")
            return

        if len(keyword) < 3:
            await event.reply("⚠️ Keyword must be at least 3 characters long")
            return

        msg = await event.reply(f"🔍 Starting global search for: <code>{keyword}</code>", parse_mode='HTML')

        try:
            success, result = await search_manager.search_chats(client, keyword, msg)
            if not success:
                await msg.edit(f"❌ Search error: {result}")
                return

            # Create brief report with first 5 results
            response = (
                f"✅ Search completed\n\n"
                f"📄 <b>Results saved to file:</b> <code>{result['csv_file']}</code>\n\n"
                f"🔍 Keyword: <code>{keyword}</code>\n"
                f"📊 Chats found: {result['found']}\n"
                f"🔄 Processed: {result['processed']}\n\n"
                f"<b>First 5 results:</b>\n"
            )

            # Add first 5 results to response
            for i, chat in enumerate(search_manager.current_search_results[:5], 1):
                chat_link = f"https://t.me/{chat['chat_username']}" if chat['chat_username'] else "No link"
                response += (
                    f"{i}. <b>{chat['chat_title']}</b>\n"
                    f"   🆔 ID: <code>{chat['chat_id']}</code>\n"
                    f"   🔗 Link: {chat_link}\n"
                    f"   👥 Members: {chat['chat_participants']}\n"
                    f"   📝 Description: {chat['chat_description'][:50]}...\n\n"
                )

            if len(search_manager.current_search_results) > 5:
                response += f"📌 And {len(search_manager.current_search_results) - 5} more results in file\n"

            response += (
                f"\n📄 Available commands:\n"
                f"<code>/export_search {keyword}</code> - resend results\n"
                f"<code>/clear_search {keyword}</code> - clear search results\n\n"
                f"💡 Also check @tgdb_search_bot - you might find additional results for your query!"
            )

            # Send response with attached CSV file
            await msg.edit(
                response,
                parse_mode='HTML',
                file=result['csv_path']
            )

        except Exception as e:
            await msg.edit(f"❌ Unexpected error: {str(e)}")

    @client.on(events.NewMessage(pattern='/export_search'))
    async def handle_export_search(event):
        """Export search results to CSV file"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split(maxsplit=1)
        if len(args) < 2:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/export_search keyword</code>\n\n"
                "Example: <code>/export_search cryptocurrency</code>",
                parse_mode='HTML'
            )
            return

        keyword = args[1].strip()
        if not keyword:
            await event.reply("⚠️ Please specify a keyword for export")
            return

        msg = await event.reply(f"📤 Searching for files with results for <code>{keyword}</code>...", parse_mode='HTML')

        try:
            # Find all CSV files with search results for the keyword
            matching_files = []
            for filename in os.listdir(txt_logs_folder):
                if filename.startswith(f'parsed_global_{keyword}_') and filename.endswith('.csv'):
                    filepath = os.path.join(txt_logs_folder, filename)
                    matching_files.append(filepath)

            if not matching_files:
                await msg.edit(f"❌ No search results found for <code>{keyword}</code>", parse_mode='HTML')
                return

            # Send the most recent file
            latest_file = max(matching_files, key=os.path.getctime)
            await msg.edit(
                f"✅ Found search results for <code>{keyword}</code>\n\n"
                f"📄 File: <code>{os.path.basename(latest_file)}</code>",
                parse_mode='HTML',
                file=latest_file
            )

        except Exception as e:
            await msg.edit(f"❌ Export error: {str(e)}")

    @client.on(events.NewMessage(pattern='/clear_search'))
    async def handle_clear_search(event):
        """Clear search results for specified keyword"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        args = event.message.text.split(maxsplit=1)
        if len(args) < 2:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/clear_search keyword</code>\n\n"
                "Example: <code>/clear_search cryptocurrency</code>",
                parse_mode='HTML'
            )
            return

        keyword = args[1].strip()
        if not keyword:
            await event.reply("⚠️ Please specify a keyword to clear")
            return

        msg = await event.reply(f"🗑 Searching and deleting files with results for <code>{keyword}</code>...", parse_mode='HTML')

        try:
            # Find and delete all CSV files with search results for the keyword
            deleted_files = 0
            for filename in os.listdir(txt_logs_folder):
                if filename.startswith(f'parsed_global_{keyword}_') and filename.endswith('.csv'):
                    filepath = os.path.join(txt_logs_folder, filename)
                    try:
                        os.remove(filepath)
                        deleted_files += 1
                    except Exception as e:
                        print(f"Error deleting file {filename}: {e}")
                        continue

            await msg.edit(
                f"✅ Cleanup completed\n\n"
                f"🗑 Files deleted: {deleted_files}"
            )

        except Exception as e:
            await msg.edit(f"❌ Cleanup error: {str(e)}")

    @client.on(events.NewMessage(pattern='/stopsearch'))
    async def handle_stop_search(event):
        """Stop current search"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        if not search_manager.search_active:
            await event.reply("⚠️ No active search at the moment")
            return

        try:
            result = await search_manager.stop_search()
            await event.reply(f"✅ {result}")
        except Exception as e:
            await event.reply(f"❌ Error stopping search: {str(e)}")

    @client.on(events.NewMessage(pattern='/search_stats'))
    async def handle_search_stats(event):
        """Show global search statistics"""
        if not await is_admin(event):
            await event.reply("⛔ Access denied. Admin privileges required.")
            return

        stats = search_manager.stats
        rate_limits = search_manager.rate_limits

        today = datetime.date.today()
        current_hour = datetime.datetime.now().hour

        # Reset counters if needed
        if stats['last_day'] != today:
            stats['today'] = 0
            stats['last_day'] = today

        if stats['last_hour'] != current_hour:
            stats['this_hour'] = 0
            stats['last_hour'] = current_hour

        # Count search result files
        search_files_count = 0
        for filename in os.listdir(txt_logs_folder):
            if filename.startswith('parsed_global_') and filename.endswith('.csv'):
                search_files_count += 1

        response = (
            f"📊 Global search statistics:\n\n"
            f"📅 Today: {stats['today']}/{rate_limits['daily_limit']}\n"
            f"⏰ This hour: {stats['this_hour']}/{rate_limits['hourly_limit']}\n"
            f"❌ Consecutive errors: {stats['consecutive_errors']}/{rate_limits['consecutive_errors_limit']}\n\n"
            f"⏳ Delays between requests: {rate_limits['min_delay']}-{rate_limits['max_delay']} sec\n"
            f"📦 Daily limit: {rate_limits['daily_limit']} requests\n"
            f"⏰ Hourly limit: {rate_limits['hourly_limit']} requests\n\n"
            f"📁 Search result files: {search_files_count}\n\n"
            f"🔍 Current status: {'🔴 Active' if search_manager.search_active else '🟢 Inactive'}\n"
            f"   Last query: {search_manager.current_search_keyword or 'none'}"
        )

        await event.reply(response)
