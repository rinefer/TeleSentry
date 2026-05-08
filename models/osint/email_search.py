import json
import os
import asyncio
import datetime
import logging
import requests
import trio
import httpx
from concurrent.futures import ThreadPoolExecutor
from holehe.core import import_submodules
from models.config import ADMIN_IDS, txt_logs_folder

async def is_admin(event):
    """Check if user has admin privileges"""
    from models.admin_tools import is_admin
    return await is_admin(event)

def _run_holehe_sync(email):
    """Run holehe in separate thread with trio event loop to avoid conflicts with asyncio"""
    out = []

    async def _trio_main():
        modules = import_submodules("holehe.modules")
        async with httpx.AsyncClient() as client:
            for module_name, module in modules.items():
                func_name = module_name.split(".")[-1]
                func = getattr(module, func_name, None)
                if func:
                    try:
                        await func(email, client, out)
                    except Exception as e:
                        logging.debug(f"Error in {module_name}: {str(e)}")
                        pass

    trio.run(_trio_main)
    return out

async def search_email_holehe(email):
    """Search email across 500+ services using holehe library"""
    try:
        # Suppress holehe logging
        logging.getLogger("holehe").setLevel(logging.CRITICAL)

        # Run trio in separate thread to avoid conflicts with asyncio (Telethon)
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            results_raw = await loop.run_in_executor(pool, _run_holehe_sync, email)

        processed_results = {}
        for site in results_raw:
            try:
                site_name = str(site.get("name", "unknown"))
                exists = bool(site.get("exists", False))
                email_recovery = str(site.get("emailrecovery", email))
                category = str(site.get("category", "Unknown"))
                url = str(site.get("url", "Unknown"))
                rate_limit = bool(site.get("rateLimit", False))
                phone_number = str(site.get("phoneNumber", "")) if site.get("phoneNumber") else None
                others = str(site.get("others", "")) if site.get("others") else None

                processed_results[site_name] = {
                    "exists": exists,
                    "email": email_recovery,
                    "domain": site_name,
                    "category": category,
                    "url": url,
                    "rateLimit": rate_limit,
                    "phoneNumber": phone_number,
                    "others": others,
                }
            except Exception as e:
                logging.debug(f"Error processing site data: {str(e)}")
                continue

        return processed_results if processed_results else None

    except Exception as e:
        print(f"Error searching with holehe: {e}")
        return {"error": str(e)}

def search_email_leakcheck(email):
    """Search email in LeakCheck database for data breaches"""
    try:
        url = f"https://leakcheck.io/api/public?check={email}"
        response = requests.get(url, timeout=30)
        response.encoding = 'utf-8'
        data = response.json()

        if response.status_code == 200 and data.get("success"):
            breach_count = data.get("found", 0)
            sources = data.get("sources", [])
            lines = data.get("lines", [])

            # Process breach sources
            detailed_sources = []
            for src in sources:
                try:
                    name = str(src.get("name", "Unknown source"))
                    date = str(src.get("date", "Unknown date"))
                    entries = int(src.get("entries", 0))
                    leak_date = str(src.get("leak_date", "Unknown"))
                    detailed_sources.append({
                        "name": name,
                        "date": date,
                        "entries": entries,
                        "leak_date": leak_date
                    })
                except Exception:
                    continue

            return {
                "leakcheck": {
                    "exists": breach_count > 0,
                    "email": str(email),
                    "breach_count": int(breach_count),
                    "sources": detailed_sources,
                    "lines": lines[:2],  # Save only first 2 password examples
                    "status": "FOUND" if breach_count > 0 else "NOT_FOUND"
                }
            }
        error_msg = str(data.get("error", "Unknown error"))
        return {"leakcheck": {"error": f"API error: {error_msg}"}}
    except Exception as e:
        return {"leakcheck": {"error": str(e)}}

def search_email_xposedornot(email):
    """Search email in XposedOrNot database for data breaches"""
    try:
        url = f"https://api.xposedornot.com/v1/check-email/{email}"
        response = requests.get(url, timeout=10)
        data = response.json()

        if response.status_code == 200:
            breaches = data.get("breaches", [])
            return {
                "xposedornot": {
                    "exists": len(breaches) > 0,
                    "email": str(email),
                    "breaches": [str(b) for b in breaches[:20]],  # Limit to 20 breaches
                    "breach_count": int(data.get("breach_count", 0)),
                    "status": "FOUND" if len(breaches) > 0 else "NOT_FOUND"
                }
            }
        return {"xposedornot": {"error": f"API error: {str(data.get('message', 'Unknown error'))}"}}
    except Exception as e:
        return {"xposedornot": {"error": str(e)}}

async def handle_email_search(event, client):
    """Handler for /email_search command - search for information by email"""
    if not await is_admin(event):
        await event.reply("⛔ Access denied. Admin privileges required.")
        return

    args = event.message.text.split()
    if len(args) < 2:
        await event.reply(
            "ℹ️ Usage:\n"
            "<code>/email_search email@example.com</code> - search for information by email\n\n"
            "Example:\n"
            "<code>/email_search test@gmail.com</code>",
            parse_mode="HTML"
        )
        return

    email = args[1].strip()
    if not email or '@' not in email:
        await event.reply("⚠️ Please specify a valid email address")
        return

    try:
        await event.reply(f"🔍 Searching for information about email <code>{email}</code>...", parse_mode="HTML")
        progress_msg = await event.reply("🔄 Searching external services...")
        results = {}

        # Search with LeakCheck
        leakcheck_result = search_email_leakcheck(email)
        if leakcheck_result:
            results.update(leakcheck_result)
        await progress_msg.edit(
            "🔄 Searching LeakCheck... ✅\n🔄 Searching XposedOrNot..."
        )

        # Search with XposedOrNot
        xposed_result = search_email_xposedornot(email)
        if xposed_result:
            results.update(xposed_result)
        await progress_msg.edit(
            "🔄 Searching LeakCheck... ✅\n"
            "🔄 Searching XposedOrNot... ✅\n"
            "🔄 Searching with Holehe (500+ sites, may take up to a minute)..."
        )

        # Search with Holehe
        holehe_result = await search_email_holehe(email)
        if holehe_result:
            results["holehe"] = holehe_result
        await progress_msg.edit(
            "🔄 Searching LeakCheck... ✅\n"
            "🔄 Searching XposedOrNot... ✅\n"
            "🔄 Searching with Holehe... ✅"
        )

        if not results:
            await progress_msg.edit(
                f"❌ No information found for email <code>{email}</code>"
            )
            return

        # Generate report with detailed information about first two breaches
        report = f"🔎 <b>Email search results</b> <code>{email}</code>\n\n"
        report += f"📅 Search date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        # LeakCheck results with detailed information about first two breaches
        if "leakcheck" in results:
            lc = results["leakcheck"]
            if "error" in lc:
                report += f"❌ <b>LeakCheck:</b> Error - {lc['error']}\n\n"
            else:
                report += "🔍 <b>LeakCheck:</b>\n"
                report += f"• Email found in breaches: {'Yes' if lc['exists'] else 'No'}\n"
                report += f"• Number of breaches: {lc['breach_count']}\n\n"

                if lc.get("sources") and len(lc["sources"]) > 0:
                    # Show detailed information about first two breaches
                    for i, source in enumerate(lc["sources"][:2]):
                        report += f"📌 <b>Breach #{i+1}:</b>\n"
                        report += f"• Name: {source.get('name', 'Unknown')}\n"
                        report += f"• Discovery date: {source.get('date', 'Unknown')}\n"
                        report += f"• Breach date: {source.get('leak_date', 'Unknown')}\n"
                        report += f"• Number of entries: {source.get('entries', 0):,}\n\n"

                if lc.get("lines") and len(lc["lines"]) > 0:
                    report += "🔑 <b>Compromised data examples:</b>\n"
                    for i, line in enumerate(lc["lines"][:2]):
                        report += f"• Example #{i+1}: <code>{line}</code>\n"
                    report += "\n"

        # XposedOrNot results with first two breaches
        if "xposedornot" in results:
            xp = results["xposedornot"]
            if "error" in xp:
                report += f"❌ <b>XposedOrNot:</b> Error - {xp['error']}\n\n"
            else:
                report += "🔍 <b>XposedOrNot:</b>\n"
                report += f"• Email found in breaches: {'Yes' if xp['exists'] else 'No'}\n"
                report += f"• Number of breaches: {xp['breach_count']}\n"

                if xp.get("breaches") and len(xp["breaches"]) > 0:
                    report += "• First two breaches: "
                    report += ", ".join(xp["breaches"][:2])
                    report += "\n\n"

        # Holehe results (only statistics in report)
        if "holehe" in results:
            holehe_data = results["holehe"]
            if "error" in holehe_data:
                report += f"❌ <b>Holehe:</b> Error - {holehe_data['error']}\n\n"
            else:
                report += "🔍 <b>Holehe (check on 500+ sites):</b>\n"
                found_sites = [
                    name for name, data in holehe_data.items() if data.get("exists")
                ]
                report += f"• Accounts found: {len(found_sites)}\n\n"

        # Summary statistics
        total_found = 0
        if "leakcheck" in results and "error" not in results.get("leakcheck", {}):
            total_found += 1 if results["leakcheck"].get("exists") else 0
        if "xposedornot" in results and "error" not in results.get("xposedornot", {}):
            total_found += 1 if results["xposedornot"].get("exists") else 0
        if "holehe" in results and "error" not in results.get("holehe", {}):
            total_found += len(
                [name for name, data in results["holehe"].items() if data.get("exists")]
            )

        report += "📈 <b>Summary statistics:</b>\n"
        report += f"• Total accounts found: {total_found}\n"
        report += f"• LeakCheck: {'Yes' if 'leakcheck' in results and 'error' not in results['leakcheck'] and results['leakcheck'].get('exists') else 'No'}\n"
        report += f"• XposedOrNot: {'Yes' if 'xposedornot' in results and 'error' not in results['xposedornot'] and results['xposedornot'].get('exists') else 'No'}\n"
        report += f"• Holehe: {'Yes' if 'holehe' in results and 'error' not in results['holehe'] and any(data.get('exists') for data in results['holehe'].values()) else 'No'}\n\n"

        # Recommendations
        report += "💡 <b>Recommendations:</b>\n"
        if total_found > 0:
            report += "• Email found in data breaches - change all passwords immediately!\n"
            report += "• Check all accounts associated with this email\n"
            report += "• Enable two-factor authentication where possible\n"
            report += "• Be careful with phishing emails\n"
            report += "• Consider changing email address\n"
        else:
            report += "• Email not found in known breaches\n"
            report += "• However, this doesn't guarantee complete security\n"
            report += "• Regularly check email for new breaches\n"
            report += "• Use strong unique passwords\n"

        # Save full report to file
        current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"email_search_{email.replace('@', '_at_')}_{current_time}.json"
        filepath = os.path.join(txt_logs_folder, filename)

        # Remove password examples from results before saving to JSON
        results_for_json = results.copy()
        if "leakcheck" in results_for_json and "lines" in results_for_json["leakcheck"]:
            results_for_json["leakcheck"]["lines"] = f"Found {len(results['leakcheck']['lines'])} examples"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(results_for_json, f, ensure_ascii=False, indent=2, default=str)

        # Send report
        await progress_msg.edit(
            f"{report}\n📄 Full report saved to file: <code>{filename}</code>",
            file=filepath,
            parse_mode="HTML",
        )

    except Exception as e:
        await event.reply(f"❌ Search error: {str(e)}")
