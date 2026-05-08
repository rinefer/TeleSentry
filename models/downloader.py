from telethon import events
import requests
from pytube import YouTube
import os
import asyncio
import datetime
from urllib.parse import quote
from models.config import media_folder

def register_handlers(client):
    """Registers handlers for content downloading commands"""

    @client.on(events.NewMessage(pattern='/download'))
    async def handle_download(event):
        """Handler for /download command - downloads videos from YouTube or TikTok with progress bar"""
        args = event.message.text.split(maxsplit=1)
        if len(args) < 2:
            await event.reply(
                "ℹ️ Usage:\n"
                "<code>/download link</code> - download video from YouTube/TikTok\n\n"
                "Examples:\n"
                "<code>/download https://youtu.be/example</code>\n"
                "<code>/download https://tiktok.com/@user/video/123</code>",
                parse_mode='HTML'
            )
            return

        url = args[1]
        last_progress = -1
        progress_msg = await event.reply("⏳ Preparing download...\n\n0% - []")

        def update_progress_bar(progress):
            """Updates progress bar with blocks"""
            filled = min(int(progress / 25) + 1, 4)
            bar = "[" + "⬛️" * filled + " " * (4 - filled) + "]"
            return f"{progress}% - {bar}"

        async def safe_edit_progress(progress):
            """Safely updates progress bar with change check"""
            nonlocal last_progress
            if progress != last_progress:
                try:
                    await progress_msg.edit(f"⏳ Downloading video...\n\n{update_progress_bar(progress)}")
                    last_progress = progress
                except Exception as e:
                    print(f"Error updating progress: {e}")

        try:
            if "youtube.com" in url or "youtu.be" in url:
                def youtube_progress(stream, chunk, bytes_remaining):
                    total_size = stream.filesize
                    bytes_downloaded = total_size - bytes_remaining
                    progress = min(int((bytes_downloaded / total_size) * 100), 100)
                    asyncio.create_task(safe_edit_progress(progress))

                yt = YouTube(url, on_progress_callback=youtube_progress)

                stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()

                if not stream:
                    await progress_msg.edit("❌ Could not find suitable video on YouTube.")
                    return

                filename = f"yt_{yt.video_id}.mp4"
                filepath = os.path.join(media_folder, filename)

                await asyncio.get_event_loop().run_in_executor(None, lambda: stream.download(output_path=media_folder, filename=filename))

                await progress_msg.edit("✅ Download complete!")
                await asyncio.sleep(0.5)

                await event.reply(
                    f"🎬 <b>YouTube video downloaded!</b>\n"
                    f"📹 <b>Title:</b> {yt.title}\n"
                    f"📂 <b>Size:</b> {stream.filesize // (1024 * 1024)} MB\n"
                    f"⏱ <b>Duration:</b> {yt.length // 60}:{yt.length % 60:02d}\n"
                    f"🔤 <b>Extension:</b> MP4",
                    file=filepath,
                    parse_mode='HTML'
                )

            elif "tiktok.com" in url:
                api_url = f"https://tikwm.com/api?url={url}"
                response = requests.get(api_url)
                data = response.json()

                if not data.get("data"):
                    await progress_msg.edit("❌ Could not download video from TikTok.")
                    return

                video_url = data["data"]["play"]
                filename = f"tt_{int(datetime.datetime.now().timestamp())}.mp4"
                filepath = os.path.join(media_folder, filename)

                with requests.get(video_url, stream=True) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded = 0

                    with open(filepath, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                progress = min(int((downloaded / total_size) * 100), 100)
                                await safe_edit_progress(progress)

                await progress_msg.edit("✅ Download complete!")
                await asyncio.sleep(0.5)

                duration = data["data"].get("duration", 0)
                size_mb = os.path.getsize(filepath) / (1024 * 1024)

                await event.reply(
                    f"🎵 <b>TikTok video downloaded!</b>\n"
                    f"📂 <b>Size:</b> {size_mb:.1f} MB\n"
                    f"⏱ <b>Duration:</b> {duration // 60}:{duration % 60:02d}\n"
                    f"🔤 <b>Extension:</b> MP4",
                    file=filepath,
                    parse_mode='HTML'
                )

            else:
                await progress_msg.edit("❌ Only YouTube and TikTok links are supported.")

        except Exception as e:
            print(f"Error downloading video: {e}")
            await progress_msg.edit(f"⚠️ Error: {str(e)}")
