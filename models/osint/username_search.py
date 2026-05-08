import json
import os
import asyncio
import datetime
import logging
from models.config import ADMIN_IDS, txt_logs_folder

async def is_admin(event):
    """Check if user has admin privileges"""
    from models.admin_tools import is_admin
    return await is_admin(event)

async def search_username_maigret(username):
    """Search for username across 500+ websites using Maigret library"""
    try:
        import maigret as _maigret_pkg
        from maigret.checking import maigret as run_check
        from maigret.sites import MaigretDatabase
        from maigret.result import MaigretCheckResult

        # Suppress logging
        logging.getLogger('maigret').setLevel(logging.CRITICAL)
        logging.getLogger('aiohttp').setLevel(logging.CRITICAL)

        # Path to sites database within the package
        pkg_dir = os.path.dirname(_maigret_pkg.__file__)
        data_path = os.path.join(pkg_dir, 'resources', 'data.json')

        logger = logging.getLogger('maigret_silent')
        logger.setLevel(logging.CRITICAL)

        db = MaigretDatabase().load_from_path(data_path)
        sites = db.sites_dict

        raw = await run_check(
            username,
            sites,
            logger,
            no_progressbar=True,
            timeout=10,
            max_connections=10,
        )

        if not raw:
            return None

        # Process results
        processed_results = {}
        for site_name, site_data in raw.items():
            result_obj = site_data.get('status')
            site_obj = site_data.get('site')

            exists = False
            if isinstance(result_obj, MaigretCheckResult):
                exists = result_obj.is_found()

            category = 'Unknown'
            tags = []
            country = 'Unknown'
            if site_obj is not None:
                category = getattr(site_obj, 'category', 'Unknown') or 'Unknown'
                tags = getattr(site_obj, 'tags', []) or []
                country = getattr(site_obj, 'country', 'Unknown') or 'Unknown'

            processed_results[site_name] = {
                "status": str(result_obj) if result_obj else 'UNKNOWN',
                "url": site_data.get('url_user', 'Unknown'),
                "username": site_data.get('username', username),
                "exists": exists,
                "http_status": site_data.get('http_status', 'Unknown'),
                "response_time": site_data.get('response_time', 'Unknown'),
                "category": category,
                "tags": tags,
                "country": country,
            }

        return processed_results if processed_results else None

    except ImportError as e:
        return {"error": f"Maigret import error: {e}. Install with: pip install maigret"}
    except Exception as e:
        print(f"Error searching with Maigret: {e}")
        return {"error": str(e)}

def search_username_social_media(username):
    """Search for username on popular social media platforms"""
    platforms = {
        "Instagram":  {"url": f"https://www.instagram.com/{username}/",     "category": "Social Network"},
        "Twitter":    {"url": f"https://twitter.com/{username}",             "category": "Social Network"},
        "Facebook":   {"url": f"https://www.facebook.com/{username}",        "category": "Social Network"},
        "GitHub":     {"url": f"https://github.com/{username}",              "category": "Development"},
        "Reddit":     {"url": f"https://www.reddit.com/user/{username}",     "category": "Forum"},
        "YouTube":    {"url": f"https://www.youtube.com/{username}",         "category": "Video Hosting"},
        "TikTok":     {"url": f"https://www.tiktok.com/@{username}",         "category": "Video Hosting"},
        "LinkedIn":   {"url": f"https://www.linkedin.com/in/{username}/",    "category": "Professional Network"},
        "Pinterest":  {"url": f"https://www.pinterest.com/{username}/",      "category": "Social Network"},
        "VK":         {"url": f"https://vk.com/{username}",                  "category": "Social Network"},
        "OK.ru":      {"url": f"https://ok.ru/profile/{username}",           "category": "Social Network"},
        "Twitch":     {"url": f"https://www.twitch.tv/{username}",           "category": "Streaming"},
        "Telegram":   {"url": f"https://t.me/{username}",                    "category": "Messenger"},
        "Snapchat":   {"url": f"https://www.snapchat.com/add/{username}",    "category": "Social Network"},
        "Steam":      {"url": f"https://steamcommunity.com/id/{username}",   "category": "Gaming"},
    }

    import requests
    results = {}
    for name, data in platforms.items():
        try:
            response = requests.head(
                data["url"],
                timeout=10,
                allow_redirects=True,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            results[name] = {
                "status": "FOUND" if response.status_code == 200 else "NOT_FOUND",
                "url": data["url"],
                "category": data["category"],
                "http_status": response.status_code
            }
        except Exception as e:
            print(f"Error checking {name}: {e}")
            results[name] = {
                "status": "ERROR",
                "error": str(e),
                "url": data["url"],
                "category": data["category"]
            }

    return results if results else None

async def search_username_telegram(client, username):
    """Search for user in Telegram with detailed information"""
    try:
        entity = await client.get_entity(username)
        if entity:
            return {
                "telegram": {
                    "id": entity.id,
                    "username": getattr(entity, 'username', None),
                    "first_name": getattr(entity, 'first_name', None),
                    "last_name": getattr(entity, 'last_name', None),
                    "phone": getattr(entity, 'phone', None),
                    "bot": getattr(entity, 'bot', False),
                    "restricted": getattr(entity, 'restricted', False),
                    "verified": getattr(entity, 'verified', False),
                    "scam": getattr(entity, 'scam', False),
                    "fake": getattr(entity, 'fake', False),
                    "premium": getattr(entity, 'premium', False),
                    "status": str(getattr(entity, 'status', 'Unknown')),
                    "last_seen": str(getattr(entity.status, 'was_online', 'Unknown'))
                }
            }
        return None
    except Exception as e:
        print(f"Telegram search error: {e}")
        return {"error": str(e)}

async def handle_username_search(event, client):
    """Handler for /username_search command - search for accounts by username"""
    if not await is_admin(event):
        await event.reply("⛔ Access denied. Admin privileges required.")
        return

    args = event.message.text.split()
    if len(args) < 2:
        await event.reply(
            "ℹ️ Usage:\n"
            "<code>/username_search username</code> - search for accounts by username\n\n"
            "Examples:\n"
            "<code>/username_search johndoe</code>\n"
            "<code>/username_search @johndoe</code>",
            parse_mode='HTML'
        )
        return

    username = args[1].replace('@', '').strip()
    if not username:
        await event.reply("⚠️ Please specify a valid username")
        return

    try:
        await event.reply(f"🔍 Searching for accounts with username <code>{username}</code>...", parse_mode='HTML')
        progress_msg = await event.reply("🔄 Searching Telegram...")
        results = {}

        # Search Telegram
        tg_result = await search_username_telegram(client, username)
        if tg_result:
            results.update(tg_result)
        await progress_msg.edit("🔄 Searching Telegram... ✅\n🔄 Searching popular platforms...")

        # Search popular platforms
        social_result = search_username_social_media(username)
        if social_result:
            results["social_media"] = social_result
        await progress_msg.edit(
            "🔄 Searching Telegram... ✅\n"
            "🔄 Searching popular platforms... ✅\n"
            "🔄 Searching with Maigret (500+ sites)..."
        )

        # Search with Maigret
        maigret_result = await search_username_maigret(username)
        if maigret_result:
            results["maigret"] = maigret_result
        await progress_msg.edit(
            "🔄 Searching Telegram... ✅\n"
            "🔄 Searching popular platforms... ✅\n"
            "🔄 Searching with Maigret... ✅"
        )

        if not results:
            await progress_msg.edit(f"❌ No accounts found with username <code>{username}</code>")
            return

        # Generate report
        report = f"🔎 <b>Username search results</b> <code>{username}</code>\n\n"
        report += f"📅 Search date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        # Telegram
        if "telegram" in results:
            tg = results["telegram"]
            if "error" in tg:
                report += f"❌ <b>Telegram:</b> Error - {tg['error']}\n\n"
            else:
                report += "📱 <b>Telegram:</b>\n"
                report += f"• ID: <code>{tg['id']}</code>\n"
                if tg['username']:   report += f"• Username: @{tg['username']}\n"
                if tg['first_name']: report += f"• First name: {tg['first_name']}\n"
                if tg['last_name']:  report += f"• Last name: {tg['last_name']}\n"
                if tg['phone']:      report += f"• Phone: {tg['phone']}\n"
                report += f"• Bot: {'Yes' if tg['bot'] else 'No'}\n"
                report += f"• Premium: {'Yes' if tg['premium'] else 'No'}\n"
                report += f"• Restricted: {'Yes' if tg['restricted'] else 'No'}\n"
                report += f"• Verified: {'Yes' if tg['verified'] else 'No'}\n"
                report += f"• Scam: {'Yes' if tg['scam'] else 'No'}\n"
                report += f"• Fake: {'Yes' if tg['fake'] else 'No'}\n"
                report += f"• Status: {tg['status']}\n"
                report += f"• Last seen: {tg['last_seen']}\n\n"

        # Popular platforms
        if "social_media" in results:
            social = results["social_media"]
            report += "🌐 <b>Popular platforms:</b>\n"
            found_sites = [n for n, d in social.items() if d.get("status") == "FOUND"]
            if found_sites:
                categories = {}
                for site in found_sites:
                    cat = social[site]["category"]
                    categories.setdefault(cat, []).append(site)
                for cat, sites in categories.items():
                    report += f"📌 <b>{cat}:</b>\n"
                    for site in sites[:5]:
                        report += f"• {site}: {social[site].get('url', 'No link')}\n"
                    if len(sites) > 5:
                        report += f"• And {len(sites) - 5} more sites...\n"
                    report += "\n"
            else:
                report += "• No accounts found\n\n"

        # Maigret
        if "maigret" in results:
            maigret_data = results["maigret"]
            if "error" in maigret_data:
                report += f"❌ <b>Maigret:</b> Error - {maigret_data['error']}\n\n"
            else:
                report += "🔍 <b>Maigret (500+ sites):</b>\n"
                found_sites = [n for n, d in maigret_data.items() if d.get("exists")]
                if found_sites:
                    categories = {}
                    for site in found_sites:
                        cat = maigret_data[site]["category"]
                        categories.setdefault(cat, []).append(site)
                    for cat, sites in categories.items():
                        report += f"📌 <b>{cat}:</b>\n"
                        for site in sites[:3]:
                            report += f"• {site}: {maigret_data[site].get('url', 'No link')}\n"
                        if len(sites) > 3:
                            report += f"• And {len(sites) - 3} more sites...\n"
                        report += "\n"
                    report += f"📊 Total found: {len(found_sites)} accounts\n\n"
                else:
                    report += "• No accounts found\n\n"

        # Summary statistics
        total_found = 0
        if "telegram" in results and "error" not in results.get("telegram", {}):
            total_found += 1
        if "social_media" in results:
            total_found += len([n for n, d in results["social_media"].items() if d.get("status") == "FOUND"])
        if "maigret" in results and "error" not in results.get("maigret", {}):
            total_found += len([n for n, d in results["maigret"].items() if d.get("exists")])

        report += f"📈 <b>Summary statistics:</b>\n"
        report += f"• Total accounts found: {total_found}\n"
        report += f"• Telegram: {'Yes' if 'telegram' in results and 'error' not in results['telegram'] else 'No'}\n"
        report += (
            f"• Popular platforms: "
            f"{'Yes' if 'social_media' in results and any(d.get('status') == 'FOUND' for d in results['social_media'].values()) else 'No'}\n"
        )
        report += (
            f"• Maigret: "
            f"{'Yes' if 'maigret' in results and 'error' not in results['maigret'] and any(d.get('exists') for d in results['maigret'].values()) else 'No'}\n\n"
        )

        report += "💡 <b>Recommendations:</b>\n"
        if total_found > 0:
            report += "• Found accounts may belong to the same person\n"
            report += "• Check activity on found platforms\n"
            report += "• Be careful when interacting with unknown accounts\n"
            if "telegram" in results and "error" not in results.get("telegram", {}):
                report += "• Telegram account may be used for communication\n"
        else:
            report += "• No accounts found with this username\n"
            report += "• Try searching with similar usernames\n"
            report += "• Note that some accounts may be hidden or deleted\n"

        # Save full report to file
        current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"username_search_{username}_{current_time}.json"
        filepath = os.path.join(txt_logs_folder, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)

        await progress_msg.edit(
            f"{report}\n📄 Full report saved to file: <code>{filename}</code>",
            file=filepath,
            parse_mode='HTML'
        )

    except Exception as e:
        await event.reply(f"❌ Search error: {str(e)}")
