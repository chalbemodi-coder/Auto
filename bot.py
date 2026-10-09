#    This file is part of the AutoAnime distribution.
#    Copyright (c) 2026 Kaif_00z
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3.

import asyncio
import os
from datetime import datetime, timedelta, timezone
from traceback import format_exc

from telethon import Button, events
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from core.bot import Bot
from core.executors import Executors
from database import DataBase
from functions.config import Var
from functions.info import AnimeInfo
from functions.schedule import ScheduleTasks
from functions.tools import Tools
from functions.utils import AdminUtils
from libs.ariawarp import Torrent
from libs.logger import LOGS, Reporter
from libs.subsplease import SubsPlease


tools = Tools()
tools.init_dir()
bot = Bot()
dB = DataBase()
bot.run_in_loop(dB.load_channel_settings())


async def _restore_user_session():
    try:
        session_string = await dB.get_user_session()
        if session_string:
            await bot.attach_user_session(session_string)
    except Exception as error:
        # Keep the bot running so the owner can authenticate again with /login.
        LOGS.error(f"Could not restore owner Telegram session: {error}")


bot.run_in_loop(_restore_user_session())
subsplease = SubsPlease(dB)
torrent = Torrent()
schedule = ScheduleTasks(bot)
admin = AdminUtils(dB, bot)
anime_task = None


def _is_owner(event):
    return bool(Var.OWNER and event.sender_id == Var.OWNER)


async def _deny_non_owner(event):
    if _is_owner(event):
        return False
    try:
        await event.reply("This command is only available to the configured bot owner.")
    except Exception:
        pass
    return True


def _ensure_anime_watcher():
    global anime_task
    if not Var.MAIN_CHANNELS:
        return
    if anime_task is None or anime_task.done():
        anime_task = bot.loop.create_task(subsplease.on_new_anime(anime))
        LOGS.info("Anime release watcher started.")


def _channel_help():
    return (
        "**Channel setup (owner only)**\n"
        "`/channels` — show current channel settings\n"
        "`/setchannel main -1001234567890` — add a main channel (maximum 2)\n"
        "`/setchannel log -1001234567890`\n"
        "`/setchannel backup -1001234567890`\n"
        "`/setchannel cloud -1001234567890`\n"
        "`/setchannel forcesub -1001234567890 temp` — per-user invite expires in 10 minutes; next issue revokes the prior link\n"
        "`/setchannel forcesub -1001234567890 fixed` — reusable invite, still requires join approval\n"
        "`/unsetchannel main -1001234567890` or `/unsetchannel main all`\n"
        "`/unsetchannel forcesub -1001234567890` or `/unsetchannel forcesub all`\n"
        "`/unsetchannel log`, `/unsetchannel backup`, `/unsetchannel cloud`\n\n"
        "Give the bot admin rights in each channel. For force-sub it needs **Invite Users**; "
        "for destination channels it needs permission to post. Force-sub invite links use join-request mode."
    )


async def _channel_summary():
    settings = await dB.get_channel_settings()
    main = ", ".join(map(str, settings["main_channels"])) or "not set"
    fsub = "\n".join(
        f"• `{item['channel_id']}` — `{item['mode']}` (join request)"
        for item in settings["force_sub_channels"]
    ) or "not set"
    return (
        "**Current channels**\n"
        f"Main (max 2): {main}\n"
        f"Log: `{settings['log_channel'] or 'not set'}`\n"
        f"Backup: `{settings['backup_channel'] or 'not set'}`\n"
        f"Cloud: `{settings['cloud_channel'] or 'not set'}`\n"
        f"Force-sub (max 6):\n{fsub}\n\n"
        + _channel_help()
    )


async def _rotate_temp_link(user_id, channel_id):
    old = await dB.get_temp_invite(user_id, channel_id)
    if old and old.get("invite_link"):
        await bot.revoke_invite_link(channel_id, old["invite_link"])
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    invite = await bot.create_force_sub_invite(
        channel_id,
        expires_at=expires_at,
        name=f"u{user_id}-10m",
    )
    await dB.save_temp_invite(user_id, channel_id, invite.invite_link, expires_at)
    return invite.invite_link


async def _cleanup_user_invite(user_id, channel_id):
    old = await dB.get_temp_invite(user_id, channel_id)
    if old and old.get("invite_link"):
        await bot.revoke_invite_link(channel_id, old["invite_link"])
    await dB.delete_temp_invite(user_id, channel_id)


async def _expire_private_delivery(messages):
    if not messages:
        return
    if not isinstance(messages, (list, tuple)):
        messages = [messages]
    notice = None
    try:
        notice = await messages[0].reply(
            "__This private copy will be deleted in 10 minutes. Save or forward it before then.__"
        )
    except Exception:
        pass
    asyncio.create_task(bot.delete_after([notice, *messages], seconds=600))


@bot.on(
    events.NewMessage(
        incoming=True, pattern=r"^/start(?:\s+(.+))?$", func=lambda event: event.is_private
    )
)
async def _start(event):
    xnx = await event.reply("`Please wait...`")
    payload = (event.pattern_match.group(1) or "").strip()
    await dB.add_broadcast_user(event.sender_id)

    missing = []
    for index, item in enumerate(Var.FORCESUB_CHANNELS, start=1):
        channel_id = item["channel_id"]
        try:
            joined = await bot.is_joined(channel_id, event.sender_id)
        except Exception as error:
            LOGS.error(f"Force-sub membership check failed for {channel_id}: {error}")
            return await xnx.edit(
                "I could not check a required channel right now. Please try again shortly."
            )
        if joined:
            await _cleanup_user_invite(event.sender_id, channel_id)
            continue

        try:
            if item["mode"] == "fixed":
                link = item.get("fixed_link")
                if not link:
                    raise RuntimeError("Fixed join-request link is missing; owner must reset this force-sub channel.")
            else:
                link = await _rotate_temp_link(event.sender_id, channel_id)
        except Exception as error:
            LOGS.error(f"Could not create force-sub invite for {channel_id}: {error}")
            return await xnx.edit(
                "A force-sub invite could not be created. Please contact the bot owner."
            )
        missing.append(Button.url(f"📨 REQUEST TO JOIN {index}", url=link))

    if missing:
        buttons = [[button] for button in missing]
        buttons.append(
            [
                Button.url(
                    "♻️ REFRESH AFTER APPROVAL",
                    url=f"https://t.me/{(await bot.get_me()).username}?start={payload}",
                )
            ]
        )
        return await xnx.edit(
            "**Please join the remaining channels to use this bot.**\n"
            "These links send a join request; wait for the channel admin to approve it, then tap Refresh.\n"
            "Temporary links expire in 10 minutes and are replaced on the next visit.",
            buttons=buttons,
        )

    if payload:
        if payload.isdigit():
            if not Var.BACKUP_CHANNEL:
                return await xnx.edit("This file link is not available right now.")
            try:
                message = await bot.get_messages(Var.BACKUP_CHANNEL, ids=int(payload))
                if not message:
                    return await xnx.edit("This file link is no longer available.")
                sent = await event.reply(message)
                await _expire_private_delivery(sent)
            except Exception as error:
                LOGS.error(f"Private file delivery failed: {error}")
                return await xnx.edit("This file could not be delivered. Please request a fresh link.")
        else:
            items = await dB.get_store_items(payload)
            sent_messages = []
            if items:
                for item_ids in items:
                    messages = await bot.get_messages(Var.CLOUD_CHANNEL, ids=item_ids)
                    if messages:
                        sent = await event.reply(file=[message for message in messages])
                        sent_messages.extend(sent if isinstance(sent, list) else [sent])
                await _expire_private_delivery(sent_messages)
    else:
        if _is_owner(event):
            await xnx.edit(
                "__Browse Admin Options:__\nUse `/channels` to configure destinations and `/login` for the owner Telegram session.",
                buttons=admin.admin_panel(),
            )
            return
        await xnx.edit(
            "**Enjoy ongoing anime releases and episodes.**",
            buttons=[[Button.url("👨‍💻 DEV", url="https://t.me/ahjin_anime")]],
        )
        return
    await xnx.delete()


@bot.on(events.NewMessage(incoming=True, pattern=r"^/login(?:@\w+)?$", func=lambda event: event.is_private))
async def _login(event):
    if await _deny_non_owner(event):
        return
    if not Var.OWNER:
        return await event.reply("Owner login is disabled: configure the numeric OWNER ID first.")
    if bot.user_client:
        try:
            if bot.user_client.is_connected() and await bot.user_client.is_user_authorized():
                return await event.reply("Owner Telegram login is already active.")
        except Exception:
            pass

    login_client = TelegramClient(
        StringSession(), Var.API_ID, Var.API_HASH
    )
    messages_to_delete = []
    login_completed = False

    async def ask_secret(conversation, text):
        prompt = await event.reply(text)
        messages_to_delete.append(prompt)
        response = await conversation.get_response()
        messages_to_delete.append(response)
        value = (response.raw_text or "").strip()
        try:
            await response.delete()
        except Exception:
            pass
        return value

    try:
        async with bot.conversation(event.sender_id, timeout=240) as conversation:
            phone = await ask_secret(
                conversation,
                "Send your Telegram phone number in international format. It will be deleted after reading. Send `/cancel` to stop.",
            )
            if phone.lower() == "/cancel":
                return await event.reply("Login cancelled.")
            try:
                sent_code = await login_client.send_code_request(phone)
            except PhoneNumberInvalidError:
                return await event.reply("That phone number is invalid. Start `/login` again with the correct number.")

            authorized = False
            for attempt in range(1, 4):
                code = await ask_secret(
                    conversation,
                    f"Enter the Telegram login code ({attempt}/3). Do not share it with anyone.",
                )
                if code.lower() == "/cancel":
                    return await event.reply("Login cancelled.")
                try:
                    await login_client.sign_in(
                        phone=phone,
                        code=code.replace(" ", ""),
                        phone_code_hash=sent_code.phone_code_hash,
                    )
                    authorized = True
                    break
                except PhoneCodeInvalidError:
                    await event.reply("That OTP is incorrect. Please enter the latest code again.")
                except PhoneCodeExpiredError:
                    sent_code = await login_client.send_code_request(phone)
                    await event.reply("That OTP expired. Telegram sent a new code; enter the latest OTP.")
                except SessionPasswordNeededError:
                    for password_attempt in range(1, 4):
                        password = await ask_secret(
                            conversation,
                            f"Enter your Telegram 2-step verification password ({password_attempt}/3). It will be deleted after reading.",
                        )
                        if password.lower() == "/cancel":
                            return await event.reply("Login cancelled.")
                        try:
                            await login_client.sign_in(password=password)
                            authorized = True
                            break
                        except PasswordHashInvalidError:
                            await event.reply("That 2FA password is incorrect. Try again.")
                    if authorized:
                        break
                    return await event.reply("Login stopped after three incorrect 2FA attempts. Run `/login` to try again.")

            if not authorized:
                return await event.reply("Login stopped after three incorrect OTP attempts. Run `/login` to try again.")

            user = await login_client.get_me()
            if user.id != Var.OWNER:
                await login_client.disconnect()
                return await event.reply(
                    "The Telegram account you logged in with does not match OWNER. No session was saved."
                )
            session_string = login_client.session.save()
            await dB.save_user_session(session_string)
            bot.user_client = login_client
            login_completed = True
            LOGS.info(f"Owner Telegram session authorized for numeric owner ID {Var.OWNER}.")
            return await event.reply(
                "Telegram login succeeded. The session is saved as plain text in MongoDB without encryption. Restrict database access."
            )
    except TimeoutError:
        return await event.reply("Login timed out. Run `/login` again when ready.")
    except Exception as error:
        LOGS.error(f"Owner Telegram login failed: {error}")
        try:
            await login_client.disconnect()
        except Exception:
            pass
        return await event.reply("Login failed safely. Check the bot logs and try `/login` again.")
    finally:
        if not login_completed:
            try:
                await login_client.disconnect()
            except Exception:
                pass
        for message in messages_to_delete:
            try:
                await message.delete()
            except Exception:
                pass


@bot.on(events.NewMessage(incoming=True, pattern=r"^/channels(?:@\w+)?$", func=lambda event: event.is_private))
async def _channels(event):
    if await _deny_non_owner(event):
        return
    await event.reply(await _channel_summary(), link_preview=False)


@bot.on(events.NewMessage(incoming=True, pattern=r"^/setchannel(?:@\w+)?(?:\s+(.+))?$", func=lambda event: event.is_private))
async def _setchannel(event):
    if await _deny_non_owner(event):
        return
    parts = (event.pattern_match.group(1) or "").split()
    if len(parts) < 2:
        return await event.reply(_channel_help())

    role = parts[0].lower()
    try:
        channel_id = int(parts[1])
    except ValueError:
        return await event.reply("Send a numeric Telegram channel ID, for example `-1001234567890`.")
    if channel_id >= 0:
        return await event.reply("Channel ID must be negative, for example `-1001234567890`.")

    mode = parts[2].lower() if len(parts) > 2 else "temp"
    if role not in {"main", "log", "backup", "cloud", "forcesub"}:
        return await event.reply(_channel_help())
    if role == "forcesub" and len(parts) > 3:
        return await event.reply("Use `/setchannel forcesub <channel_id> temp|fixed`.")
    if role == "forcesub" and mode not in {"temp", "fixed"}:
        return await event.reply("Force-sub mode must be `temp` or `fixed`.")
    if role != "forcesub" and len(parts) > 2:
        return await event.reply("Only force-sub accepts a mode: `temp` or `fixed`.")

    invite = None
    settings_saved = False
    try:
        await bot.check_channel_rights(channel_id, role)
        settings = await dB.get_channel_settings()
        current_fsub = next(
            (item for item in settings["force_sub_channels"] if item["channel_id"] == channel_id),
            None,
        )
        if (
            role == "forcesub"
            and current_fsub is None
            and len(settings["force_sub_channels"]) >= 6
        ):
            raise ValueError("You can configure at most 6 force-sub channels.")
        fixed_link = ""
        invite = None
        if role == "forcesub" and mode == "fixed":
            invite = await bot.create_force_sub_invite(channel_id, name="Auto FSub fixed")
            fixed_link = invite.invite_link

        await dB.set_channel(role, channel_id, mode=mode, fixed_link=fixed_link)
        settings_saved = True
        if role == "forcesub":
            if current_fsub and current_fsub.get("fixed_link"):
                await bot.revoke_invite_link(channel_id, current_fsub["fixed_link"])
            for old_invite in await dB.delete_temp_invites_for_channel(channel_id):
                await bot.revoke_invite_link(channel_id, old_invite.get("invite_link", ""))
        if role == "main":
            _ensure_anime_watcher()
        detail = " Join requests require channel-admin approval." if role == "forcesub" else ""
        if role == "forcesub" and mode == "temp":
            detail += " Per-user links expire in 10 minutes; a new link revokes the previous one."
        if role == "forcesub" and mode == "fixed":
            detail += " This join-request link does not expire automatically."
        await event.reply(f"Saved `{role}` channel `{channel_id}` in MongoDB.{detail}")
    except ValueError as error:
        if invite and not settings_saved:
            await bot.revoke_invite_link(channel_id, invite.invite_link)
        await event.reply(str(error))
    except Exception as error:
        if invite and not settings_saved:
            await bot.revoke_invite_link(channel_id, invite.invite_link)
        LOGS.error(f"Could not set channel role {role} for {channel_id}: {error}")
        await event.reply("Could not configure that channel. Check that the ID is correct and the bot has the required admin rights.")


@bot.on(events.NewMessage(incoming=True, pattern=r"^/unsetchannel(?:@\w+)?(?:\s+(.+))?$", func=lambda event: event.is_private))
async def _unsetchannel(event):
    if await _deny_non_owner(event):
        return
    parts = (event.pattern_match.group(1) or "").split()
    if not parts:
        return await event.reply(_channel_help())
    role = parts[0].lower()
    if role not in {"main", "log", "backup", "cloud", "forcesub"}:
        return await event.reply(_channel_help())

    channel_id = None
    if len(parts) > 1 and parts[1].lower() != "all":
        try:
            channel_id = int(parts[1])
        except ValueError:
            return await event.reply("Use a numeric channel ID or `all`.")
    if role in {"log", "backup", "cloud"}:
        channel_id = None

    try:
        settings = await dB.get_channel_settings()
        if role == "forcesub":
            targets = [
                item for item in settings["force_sub_channels"]
                if channel_id is None or item["channel_id"] == channel_id
            ]
            for item in targets:
                if item.get("fixed_link"):
                    await bot.revoke_invite_link(item["channel_id"], item["fixed_link"])
                for old_invite in await dB.delete_temp_invites_for_channel(item["channel_id"]):
                    await bot.revoke_invite_link(item["channel_id"], old_invite.get("invite_link", ""))
        await dB.unset_channel(role, channel_id)
        await event.reply(f"Removed `{role}` channel setting from MongoDB.")
    except Exception as error:
        LOGS.error(f"Could not unset channel role {role}: {error}")
        await event.reply("Could not remove that channel setting. Try `/channels` and check the channel ID.")


@bot.on(
    events.NewMessage(incoming=True, pattern="^/about", func=lambda event: event.is_private)
)
async def _about(event):
    await admin._about(event)


async def _guard_callback(event):
    if _is_owner(event):
        return False
    await event.answer("Owner only", alert=True)
    return True


@bot.on(events.callbackquery.CallbackQuery(data="slog"))
async def _logs(event):
    if await _guard_callback(event):
        return
    await admin._logs(event)


@bot.on(events.callbackquery.CallbackQuery(data="sret"))
async def _restart(event):
    if await _guard_callback(event):
        return
    await admin._restart(event, schedule)


@bot.on(events.callbackquery.CallbackQuery(data="entg"))
async def _encode(event):
    if await _guard_callback(event):
        return
    await admin._encode_t(event)


@bot.on(events.callbackquery.CallbackQuery(data="sstg"))
async def _ss(event):
    if await _guard_callback(event):
        return
    await admin._ss_t(event)


@bot.on(events.callbackquery.CallbackQuery(data="butg"))
async def _button_upload(event):
    if await _guard_callback(event):
        return
    await admin._btn_t(event)


@bot.on(events.callbackquery.CallbackQuery(data="scul"))
async def _separate_upload(event):
    if await _guard_callback(event):
        return
    await admin._sep_c_t(event)


@bot.on(events.callbackquery.CallbackQuery(data="cast"))
async def _broadcast(event):
    if await _guard_callback(event):
        return
    await admin.broadcast_bt(event)


@bot.on(events.callbackquery.CallbackQuery(data="bek"))
async def _back(event):
    if await _guard_callback(event):
        return
    await event.edit(
        "** <                ADMIN PANEL                 > **",
        buttons=admin.admin_panel(),
    )


@bot.on(events.callbackquery.CallbackQuery(data="channels"))
async def _channel_setup_callback(event):
    if await _guard_callback(event):
        return
    await event.edit(await _channel_summary(), buttons=admin.back_btn(), link_preview=False)


async def anime(data):
    try:
        torrents = [data.get("480p"), data.get("720p"), data.get("1080p")]
        torrents = [item for item in torrents if item]
        if not torrents or not Var.MAIN_CHANNELS:
            LOGS.warning("Skipping anime release: no torrent or no main channel is configured.")
            return
        anime_info = AnimeInfo(torrents[0].title)
        # Main-channel post is created only after the first quality upload succeeds.
        posters = []
        side_posters = []
        chat_info = None
        buttons = [[]]
        original_upload = await dB.is_original_upload()
        button_upload = await dB.is_button_upload()
        first_quality = torrents[0]
        for item in torrents:
            try:
                filename = f"downloads/{item.title}"
                reporter = Reporter(
                    bot,
                    item.title,
                    status_channel=chat_info["chat_id"] if chat_info else None,
                )
                await reporter.alert_new_file_founded()
                downloaded = await torrent.download_magnet(item.link, "./downloads/", reporter)
                if not downloaded or not os.path.isfile(filename) or os.path.getsize(filename) == 0:
                    await reporter.report_error(
                        f"Download failed or no peers were available for `{item.title}`.",
                        log=True,
                    )
                    if reporter.msg:
                        await reporter.msg.delete()
                    continue
                if await dB.is_separate_channel_upload() and not chat_info:
                    chat_info = await tools.get_chat_info(bot, anime_info, dB)
                    if not chat_info:
                        raise RuntimeError("Could not create/find the separate anime channel.")
                    buttons = [[
                        Button.url(
                            f"🟦 EPISODE {anime_info.data.get('episode_number', '')}".strip(),
                            url=chat_info["invite_link"],
                        )
                    ]]
                    reporter.status_channel = chat_info["chat_id"]
                    if reporter.msg:
                        await reporter.msg.delete()
                    await reporter.alert_new_file_founded()
                executor = Executors(
                    bot,
                    dB,
                    {"original_upload": original_upload, "button_upload": button_upload},
                    filename,
                    AnimeInfo(item.title),
                    reporter,
                )
                result, button = await executor.execute()
                if result:
                    if not posters and item is first_quality:
                        posters = await tools._poster(bot, anime_info)
                        if not isinstance(posters, list):
                            posters = [posters]
                    if chat_info and not side_posters and item is first_quality:
                        side_posters = await tools._poster(
                            bot, anime_info, chat_info["chat_id"]
                        )
                        if not isinstance(side_posters, list):
                            side_posters = [side_posters]
                        for poster in side_posters:
                            await poster.edit(buttons=buttons)
                    if button:
                        if len(buttons[0]) == 2:
                            buttons.append([button])
                        else:
                            buttons[0].append(button)
                        for poster in posters:
                            await poster.edit(buttons=buttons)
                    asyncio.create_task(executor.further_work())
                    continue
                await reporter.report_error(button, log=True)
                if reporter.msg:
                    await reporter.msg.delete()
            except Exception:
                await reporter.report_error(str(format_exc()), log=True)
                if reporter.msg:
                    await reporter.msg.delete()
    except Exception:
        LOGS.error(str(format_exc()))


# Channels can be configured after the bot starts; start the release watcher as soon as a main channel exists.
_ensure_anime_watcher()

try:
    bot.run()
except KeyboardInterrupt:
    subsplease._exit()
