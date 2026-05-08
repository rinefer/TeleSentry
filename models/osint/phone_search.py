import requests
import json
import os
import datetime
import phonenumbers
from phonenumbers import carrier, geocoder, timezone
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from models.config import ADMIN_IDS, txt_logs_folder, INTELX_API_KEY, LEAKLOOKUP_API_KEY, LEAKIX_API_KEY

async def is_admin(event):
    """Check if user has admin privileges"""
    from models.admin_tools import is_admin
    return await is_admin(event)

def get_phone_info(phone_number):
    """Get information about phone number including carrier, region, and timezone"""
    try:
        # Parse phone number
        parsed_number = phonenumbers.parse(phone_number, None)

        if not phonenumbers.is_valid_number(parsed_number):
            return {
                "status": "ERROR",
                "message": "Invalid phone number"
            }

        # Get carrier information
        carrier_name = carrier.name_for_number(parsed_number, "en")

        # Get geographic information
        region = geocoder.description_for_number(parsed_number, "en")

        # Get timezone information
        time_zones = timezone.time_zones_for_number(parsed_number)

        # Format phone number in different formats
        international_format = phonenumbers.format_number(
            parsed_number,
            phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )

        national_format = phonenumbers.format_number(
            parsed_number,
            phonenumbers.PhoneNumberFormat.NATIONAL
        )

        return {
            "status": "SUCCESS",
            "number": {
                "original": phone_number,
                "international": international_format,
                "national": national_format,
                "country_code": parsed_number.country_code,
                "national_number": parsed_number.national_number,
                "e164": phonenumbers.format_number(
                    parsed_number,
                    phonenumbers.PhoneNumberFormat.E164
                )
            },
            "carrier": carrier_name if carrier_name else "Unknown",
            "region": region if region else "Unknown",
            "time_zones": time_zones if time_zones else ["Unknown"],
            "is_valid": True,
            "is_possible": phonenumbers.is_possible_number(parsed_number)
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": str(e)
        }

def check_phone_in_intelx(phone_number):
    """Check phone number in Intelligence X database for data leaks"""
    try:
        # Format phone number in international format
        formatted_phone = phone_number.replace('+', '')
        if formatted_phone.startswith('8'):
            formatted_phone = '7' + formatted_phone[1:]

        if not INTELX_API_KEY or INTELX_API_KEY == "YOUR_INTELX_API_KEY":
            return {
                "status": "ERROR",
                "message": "Intelligence X API key not configured"
            }

        headers = {
            'x-key': INTELX_API_KEY,
            'User-Agent': 'SohBot/1.0'
        }

        # Search by phone number
        search_url = "https://2.intelx.io/phonebook/search"
        search_data = {
            "term": formatted_phone,
            "buckets": [],
            "lookuplevel": 0,
            "maxresults": 10,
            "timeout": 5,
            "datefrom": "",
            "dateto": "",
            "sort": 4,
            "media": False,
            "terminate": []
        }

        response = requests.post(search_url, headers=headers, json=search_data, timeout=15)

        if response.status_code == 200:
            search_result = response.json()
            if search_result.get('status') == 0 and search_result.get('id'):
                # Get search results
                result_url = f"https://2.intelx.io/phonebook/search/result?id={search_result['id']}&limit=10"
                result_response = requests.get(result_url, headers=headers, timeout=15)

                if result_response.status_code == 200:
                    result_data = result_response.json()
                    if result_data.get('records'):
                        return {
                            "status": "FOUND",
                            "count": len(result_data['records']),
                            "records": result_data['records']
                        }
                    else:
                        return {
                            "status": "NOT_FOUND",
                            "message": "Phone number not found in leaks"
                        }
                else:
                    return {
                        "status": "ERROR",
                        "message": f"Error getting results: {result_response.status_code}"
                    }
            else:
                return {
                    "status": "NOT_FOUND",
                    "message": "Phone number not found in leaks"
                }
        elif response.status_code == 402:
            return {
                "status": "ERROR",
                "message": "Request limit exceeded or insufficient account balance"
            }
        elif response.status_code == 401:
            return {
                "status": "ERROR",
                "message": "Invalid API key"
            }
        else:
            return {
                "status": "ERROR",
                "message": f"API error: {response.status_code}"
            }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": str(e)
        }

def check_phone_in_leaklookup(phone_number):
    """Check phone number in Leak-Lookup database with improved error handling"""
    try:
        # Format phone number in international format
        formatted_phone = phone_number.replace('+', '')
        if formatted_phone.startswith('8'):
            formatted_phone = '7' + formatted_phone[1:]

        if not LEAKLOOKUP_API_KEY or LEAKLOOKUP_API_KEY == "YOUR_LEAKLOOKUP_API_KEY":
            return {
                "status": "ERROR",
                "message": "Leak-Lookup API key not configured"
            }

        # According to Leak-Lookup documentation, parameters should be sent in POST body
        data = {
            'key': LEAKLOOKUP_API_KEY,
            'type': 'phone',
            'query': formatted_phone
        }

        # Configure session with retry
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        session.mount('https://', HTTPAdapter(max_retries=retries))

        try:
            response = session.post(
                "https://leak-lookup.com/api/search",
                data=data,
                timeout=15,
                verify=True  # Try with certificate verification
            )
        except requests.exceptions.SSLError:
            # If certificate verification fails, try without it
            try:
                response = session.post(
                    "https://leak-lookup.com/api/search",
                    data=data,
                    timeout=15,
                    verify=False  # Without certificate verification
                )
            except Exception as e:
                return {
                    "status": "ERROR",
                    "message": f"SSL connection error: {str(e)}"
                }

        if response.status_code == 200:
            result = response.json()
            if result.get('error') == 'false':
                if result.get('message'):
                    return {
                        "status": "FOUND",
                        "count": len(result['message']),
                        "leaks": result['message']
                    }
                else:
                    return {
                        "status": "NOT_FOUND",
                        "message": "Phone number not found in leaks"
                    }
            elif result.get('error') == 'true':
                if "API key not found" in result.get('message', ''):
                    return {
                        "status": "ERROR",
                        "message": "Invalid API key"
                    }
                elif "API request limit reached" in result.get('message', ''):
                    return {
                        "status": "ERROR",
                        "message": "Request limit exceeded"
                    }
                elif "MISSING REQUIRED PARAMETERS" in result.get('message', ''):
                    return {
                        "status": "ERROR",
                        "message": "Missing required request parameters"
                    }
                else:
                    return {
                        "status": "ERROR",
                        "message": result.get('message', 'Unknown error')
                    }
            else:
                return {
                    "status": "ERROR",
                    "message": "Unexpected API response"
                }
        else:
            return {
                "status": "ERROR",
                "message": f"API error: {response.status_code}"
            }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": str(e)
        }

async def check_phone_in_leakix(phone_number):
    """Check phone number in LeakIX database using API key"""
    try:
        # Format phone number in international format
        formatted_phone = phone_number.replace('+', '')
        if formatted_phone.startswith('8'):
            formatted_phone = '7' + formatted_phone[1:]

        # Configure headers with API key
        headers = {
            'User-Agent': 'SohBot/1.0',
            'Accept': 'application/json',
            'api-key': LEAKIX_API_KEY
        }

        # According to LeakIX documentation, use /search endpoint
        # Add filter by leak type and phone number
        search_url = f"https://leakix.net/api/search?scope=leak&q=phone:{formatted_phone}"

        # Configure session with retry
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504, 204],
            allowed_methods=["GET"]
        )
        session.mount('https://', HTTPAdapter(max_retries=retries))

        try:
            response = session.get(
                search_url,
                headers=headers,
                timeout=30,
                verify=True
            )
        except requests.exceptions.SSLError:
            try:
                response = session.get(
                    search_url,
                    headers=headers,
                    timeout=30,
                    verify=False
                )
            except Exception as e:
                return {
                    "status": "ERROR",
                    "message": f"SSL connection error: {str(e)}"
                }

        # Handle 204 (No Content) status
        if response.status_code == 204:
            return {
                "status": "NOT_FOUND",
                "message": "Phone number not found in leaks (server returned empty response)"
            }
        elif response.status_code == 200:
            try:
                results = response.json()
            except ValueError:
                # If response is not valid JSON
                return {
                    "status": "ERROR",
                    "message": "Server returned invalid response"
                }

            if results:
                # Process results
                processed_results = []
                for result in results:
                    # Extract only relevant information
                    processed_result = {
                        "ip": result.get("ip", "Unknown"),
                        "port": result.get("port", "Unknown"),
                        "protocol": result.get("protocol", "Unknown"),
                        "service": result.get("service", {}).get("name", "Unknown"),
                        "leak_type": result.get("leak_type", "Unknown"),
                        "date": result.get("time", "Unknown"),
                        "organization": result.get("organization", {}).get("name", "Unknown"),
                        "data": result.get("data", {})
                    }

                    # Check if data contains phone number
                    if "data" in result and formatted_phone in str(result["data"]):
                        processed_result["phone_in_data"] = True
                    else:
                        processed_result["phone_in_data"] = False

                    processed_results.append(processed_result)

                return {
                    "status": "FOUND",
                    "count": len(processed_results),
                    "results": processed_results
                }
            else:
                return {
                    "status": "NOT_FOUND",
                    "message": "Phone number not found in leaks"
                }
        elif response.status_code == 401:
            return {
                "status": "ERROR",
                "message": "Invalid LeakIX API key"
            }
        elif response.status_code == 403:
            return {
                "status": "ERROR",
                "message": "Access denied. Check API key and restrictions"
            }
        elif response.status_code == 429:
            return {
                "status": "ERROR",
                "message": "Request limit exceeded. Try again later."
            }
        elif response.status_code == 404:
            # If API endpoint changed, try fallback method
            return await check_phone_in_leakix_fallback(phone_number)
        else:
            return {
                "status": "ERROR",
                "message": f"LeakIX API error: {response.status_code}"
            }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Error checking LeakIX: {str(e)}"
        }

async def check_phone_in_leakix_fallback(phone_number):
    """Alternative method to check LeakIX without API key"""
    try:
        # Format phone number in international format
        formatted_phone = phone_number.replace('+', '')
        if formatted_phone.startswith('8'):
            formatted_phone = '7' + formatted_phone[1:]

        # Use public endpoint without API key
        headers = {
            'User-Agent': 'SohBot/1.0',
            'Accept': 'application/json'
        }

        # Try different search variations
        search_queries = [
            f"phone:{formatted_phone}",
            f"tel:{formatted_phone}",
            f"mobile:{formatted_phone}",
            f"{formatted_phone}"
        ]

        for query in search_queries:
            search_url = f"https://leakix.net/search?scope=leak&q={query}"

            # Configure session with retry
            session = requests.Session()
            retries = Retry(
                total=2,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504, 204],
                allowed_methods=["GET"]
            )
            session.mount('https://', HTTPAdapter(max_retries=retries))

            try:
                response = session.get(
                    search_url,
                    headers=headers,
                    timeout=20,
                    verify=True
                )
            except requests.exceptions.SSLError:
                try:
                    response = session.get(
                        search_url,
                        headers=headers,
                        timeout=20,
                        verify=False
                    )
                except Exception as e:
                    continue

            # Handle 204 (No Content) status
            if response.status_code == 204:
                continue
            elif response.status_code == 200:
                try:
                    results = response.json()
                except ValueError:
                    continue

                if results:
                    # Process results
                    processed_results = []
                    for result in results:
                        processed_result = {
                            "ip": result.get("ip", "Unknown"),
                            "port": result.get("port", "Unknown"),
                            "protocol": result.get("protocol", "Unknown"),
                            "service": result.get("service", {}).get("name", "Unknown"),
                            "leak_type": result.get("leak_type", "Unknown"),
                            "date": result.get("time", "Unknown"),
                            "organization": result.get("organization", {}).get("name", "Unknown"),
                            "data": result.get("data", {})
                        }

                        # Check if data contains phone number
                        if "data" in result and formatted_phone in str(result["data"]):
                            processed_result["phone_in_data"] = True
                        else:
                            processed_result["phone_in_data"] = False

                        processed_results.append(processed_result)

                    if processed_results:
                        return {
                            "status": "FOUND",
                            "count": len(processed_results),
                            "results": processed_results,
                            "message": "Results obtained without API key (limitations may apply)"
                        }

        return {
            "status": "NOT_FOUND",
            "message": "Phone number not found in leaks (check without API key)"
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Error in LeakIX fallback method: {str(e)}"
        }

async def check_telegram_by_phone(client, phone_number):
    """Check if phone number is linked to a Telegram account with improved error handling"""
    try:
        # Format phone number in international format
        phone_info = get_phone_info(phone_number)
        if phone_info.get("status") != "SUCCESS":
            return {
                "status": "ERROR",
                "message": f"Invalid phone number: {phone_info.get('message', 'Unknown error')}"
            }

        # Try different phone number formats
        phone_formats = [
            phone_info["number"]["e164"],  # +79494101356
            phone_info["number"]["e164"].replace('+', ''),  # 79494101356
            phone_info["number"]["international"],  # +7 949 410-13-56
            phone_info["number"]["national"]  # 8 (949) 410-13-56
        ]

        for phone_format in phone_formats:
            try:
                # Try to find user by phone number
                user = await client.get_entity(phone_format)
                if user:
                    return {
                        "status": "FOUND",
                        "user": {
                            "id": user.id,
                            "username": getattr(user, 'username', None),
                            "first_name": getattr(user, 'first_name', None),
                            "last_name": getattr(user, 'last_name', None),
                            "phone": getattr(user, 'phone', None),
                            "bot": getattr(user, 'bot', False),
                            "restricted": getattr(user, 'restricted', False),
                            "verified": getattr(user, 'verified', False)
                        }
                    }
            except ValueError as e:
                # If error is related to invalid phone format, try next format
                if "Cannot find any entity" in str(e):
                    continue
                else:
                    return {
                        "status": "ERROR",
                        "message": f"Telegram search error: {str(e)}"
                    }
            except Exception as e:
                return {
                    "status": "ERROR",
                    "message": f"Telegram search error: {str(e)}"
                }

        return {
            "status": "NOT_FOUND",
            "message": "No Telegram account found with this phone number"
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Error checking Telegram: {str(e)}"
        }

async def handle_number_user(event, client):
    """Handler for /number_user command - search for information by phone number"""
    if not await is_admin(event):
        await event.reply("⛔ Access denied. Admin privileges required.")
        return

    args = event.message.text.split()
    if len(args) < 2:
        await event.reply(
            "ℹ️ Usage:\n"
            "<code>/number_user +79991234567</code> - search for information by phone number\n\n"
            "Examples:\n"
            "<code>/number_user +79991234567</code>\n"
            "<code>/number_user 89991234567</code>\n"
            "<code>/number_user 79991234567</code>\n\n"
            "🔹 Function performs:\n"
            "• Check in data leak databases (Intelligence X, Leak-Lookup, LeakIX)\n"
            "• Carrier identification\n"
            "• Region identification\n"
            "• Telegram account check",
            parse_mode='HTML'
        )
        return

    phone_number = args[1].strip()
    if not phone_number:
        await event.reply("⚠️ Please specify a valid phone number")
        return

    try:
        await event.reply(f"🔍 Searching for information about phone number <code>{phone_number}</code>...")

        # Create progress message
        progress_msg = await event.reply("🔄 Getting phone number information...")
        results = {}

        # 1. Get basic phone number information
        phone_info = get_phone_info(phone_number)
        if phone_info.get("status") == "SUCCESS":
            results["phone_info"] = phone_info
            await progress_msg.edit("🔄 Getting phone number information... ✅\n🔄 Checking Intelligence X...")
        else:
            await progress_msg.edit(f"⚠️ Invalid phone number: {phone_info.get('message', 'Unknown error')}")
            return

        # 2. Check in Intelligence X
        intelx_result = check_phone_in_intelx(phone_number)
        results["intelx"] = intelx_result
        await progress_msg.edit("🔄 Getting phone number information... ✅\n🔄 Checking Intelligence X... ✅\n🔄 Checking Leak-Lookup...")

        # 3. Check in Leak-Lookup
        leaklookup_result = check_phone_in_leaklookup(phone_number)
        results["leaklookup"] = leaklookup_result
        await progress_msg.edit("🔄 Getting phone number information... ✅\n🔄 Checking Intelligence X... ✅\n🔄 Checking Leak-Lookup... ✅\n🔄 Checking LeakIX...")

        # 4. Check in LeakIX
        leakix_result = await check_phone_in_leakix(phone_number)
        results["leakix"] = leakix_result
        await progress_msg.edit("🔄 Getting phone number information... ✅\n🔄 Checking Intelligence X... ✅\n🔄 Checking Leak-Lookup... ✅\n🔄 Checking LeakIX... ✅\n🔄 Checking Telegram...")

        # 5. Check Telegram association
        telegram_result = await check_telegram_by_phone(client, phone_number)
        results["telegram"] = telegram_result

        # Generate report
        report = f"📞 <b>Phone number search results</b> <code>{phone_number}</code>\n\n"

        # Phone number information
        if "phone_info" in results:
            info = results["phone_info"]
            report += "📱 <b>Phone number information:</b>\n"
            report += f"• Original number: <code>{info['number']['original']}</code>\n"
            report += f"• International format: <code>{info['number']['international']}</code>\n"
            report += f"• National format: <code>{info['number']['national']}</code>\n"
            report += f"• Country code: <code>+{info['number']['country_code']}</code>\n"
            report += f"• Carrier: <code>{info['carrier']}</code>\n"
            report += f"• Region: <code>{info['region']}</code>\n"
            report += f"• Time zones: <code>{', '.join(info['time_zones'])}</code>\n"
            report += f"• Valid number: <code>{'Yes' if info['is_valid'] else 'No'}</code>\n\n"

        # Data leak check results
        report += "🔓 <b>Data leak check results:</b>\n"

        # Intelligence X
        intelx = results["intelx"]
        if intelx["status"] == "FOUND":
            report += f"• <b>Intelligence X:</b> Found in {intelx.get('count', 'unknown')} leaks\n"
            if "records" in intelx and intelx["records"]:
                for record in intelx["records"][:3]:  # Show first 3 leaks
                    report += f"  - {record.get('title', 'Unknown leak')} ({record.get('date', 'unknown date')})\n"
                if intelx.get('count', 0) > 3:
                    report += f"  - And {intelx.get('count', 0) - 3} more leaks...\n"
        elif intelx["status"] == "NOT_FOUND":
            report += "• <b>Intelligence X:</b> Not found in leaks\n"
        else:
            report += f"• <b>Intelligence X:</b> {intelx['message']}\n"

        # Leak-Lookup
        leaklookup = results["leaklookup"]
        if leaklookup["status"] == "FOUND":
            report += f"• <b>Leak-Lookup:</b> Found in {leaklookup.get('count', 'unknown')} leaks\n"
            if "leaks" in leaklookup and leaklookup["leaks"]:
                for leak in list(leaklookup["leaks"].items())[:3]:  # Show first 3 leaks
                    report += f"  - {leak[0]}: {leak[1]}\n"
                if leaklookup.get('count', 0) > 3:
                    report += f"  - And {leaklookup.get('count', 0) - 3} more leaks...\n"
        elif leaklookup["status"] == "NOT_FOUND":
            report += "• <b>Leak-Lookup:</b> Not found in leaks\n"
        else:
            report += f"• <b>Leak-Lookup:</b> {leaklookup['message']}\n"

        # LeakIX
        leakix = results["leakix"]
        if leakix["status"] == "FOUND":
            report += f"• <b>LeakIX:</b> Found in {leakix.get('count', 'unknown')} leaks\n"
            if "results" in leakix and leakix["results"]:
                for result in leakix["results"][:3]:  # Show first 3 leaks
                    report += f"  - IP: {result.get('ip', 'Unknown')}\n"
                    report += f"    Port: {result.get('port', 'Unknown')}\n"
                    report += f"    Service: {result.get('service', 'Unknown')}\n"
                    report += f"    Organization: {result.get('organization', 'Unknown')}\n"
                    report += f"    Leak type: {result.get('leak_type', 'Unknown')}\n"
                    report += f"    Date: {result.get('date', 'Unknown')}\n"
                    if result.get('phone_in_data'):
                        report += f"    📞 Phone number found in leak data\n"
                if leakix.get('count', 0) > 3:
                    report += f"  - And {leakix.get('count', 0) - 3} more leaks...\n"
            if "message" in leakix:
                report += f"  ⚠️ {leakix['message']}\n"
        elif leakix["status"] == "NOT_FOUND":
            report += "• <b>LeakIX:</b> Not found in leaks\n"
        else:
            report += f"• <b>LeakIX:</b> {leakix['message']}\n"

        # Leak summary
        if all(
            results[service]["status"] in ["NOT_FOUND", "ERROR"]
            for service in ["intelx", "leaklookup", "leakix"]
        ):
            report += "• Phone number not found in any checked leak databases\n"

        report += "\n"

        # Telegram
        telegram = results["telegram"]
        report += "📱 <b>Telegram:</b>\n"
        if telegram["status"] == "FOUND":
            user = telegram["user"]
            report += f"• Telegram account found with this phone number\n"
            report += f"  - ID: <code>{user['id']}</code>\n"
            if user['username']:
                report += f"  - Username: @{user['username']}\n"
            if user['first_name']:
                report += f"  - First name: {user['first_name']}\n"
            if user['last_name']:
                report += f"  - Last name: {user['last_name']}\n"
            report += f"  - Bot: {'Yes' if user['bot'] else 'No'}\n"
            report += f"  - Premium: {'Yes' if user.get('premium', False) else 'No'}\n"
            report += f"  - Restricted: {'Yes' if user['restricted'] else 'No'}\n"
            report += f"  - Verified: {'Yes' if user['verified'] else 'No'}\n"
        elif telegram["status"] == "NOT_FOUND":
            report += "• No Telegram account found with this phone number\n"
        else:
            report += f"• {telegram['message']}\n"

        report += "\n💡 <b>Recommendations:</b>\n"
        if any(
            results[service]["status"] == "FOUND"
            for service in ["intelx", "leaklookup", "leakix"]
        ):
            report += "• Phone number found in data leaks! It is recommended to:\n"
            report += "  - Change passwords for all accounts where this phone number was used\n"
            report += "  - Enable two-factor authentication\n"
            report += "  - Check accounts for unauthorized access\n"
            report += "  - Be careful with phishing messages\n"
        else:
            report += "• Phone number not found in checked leak databases\n"
            report += "  - This does not guarantee complete security as new leaks appear constantly\n"
            report += "  - It is recommended to regularly check the phone number in security services\n"

        if telegram["status"] == "FOUND":
            report += "\n• Phone number is linked to a Telegram account:\n"
            report += "  - Be careful with phishing messages\n"
            report += "  - Do not follow suspicious links\n"
            report += "  - Verify senders before communication\n"

        # Save full report to file
        current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"phone_search_{phone_number.replace('+', '')}_{current_time}.json"
        filepath = os.path.join(txt_logs_folder, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        # Send report
        await progress_msg.edit(
            f"{report}\n"
            f"📄 Full report saved to file: <code>{filename}</code>",
            file=filepath,
            parse_mode='HTML'
        )

    except Exception as e:
        await event.reply(f"❌ Search error: {str(e)}")
