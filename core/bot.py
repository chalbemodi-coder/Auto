#    This file is part of the AutoAnime distribution.
#    Copyright (c) 2026 Kaif_00z
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3.

import asyncio
import sys
from datetime import datetime
from logging import Logger
from traceback import format_exc

from pyrogram import Client, utils
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import UserNotParticipant
from telethon import TelegramClient
from telethon.errors import (
    AccessTokenExpiredError,
    AccessTokenInvalidError,
    ApiIdInvalidError,
    AuthKeyDuplicatedError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import CreateChannelRequest, EditPhotoRequest
from telethon.tl.functions.messages import ExportChatInviteRequest

from functions.config import Var
from libs.logger import LOGS, TelethonLogger


class Bot(TelegramClient):
    def __init__(
        self,
        api_id=None,
        api_hash=None,
        bot_token=None,
        logger: Logger = LOGS,
        log_attempt=True,
        exit_on_error=True,
        *args,
        **kwargs,
    ):
        self._handle_error = exit_on_error
        self._log_at = log_attempt
        self.logger = logger
        kwargs["api_id"] = api_id or Var.API_ID
        kwargs["api_hash"] = api_hash or Var.API_HASH
        kwargs["base_logger"] = TelethonLogger
        utils.MIN_CHANNEL_ID = -1009147483647
        super().__init__(
            None,
            connection_retries=10,
            retry_delay=5,
            auto_reconnect=True,
            flood_sleep_threshold=60,
            **kwargs,
        )
        self.pyro_client = Client(
            name="pekka",
            api_id=kwargs["api_id"],
            api_hash=kwargs["api_hash"],
            bot_token=bot_token or Var.BOT_TOKEN,
            in_memory=True,
        )
        # Owner user sessions are restored from encrypted MongoDB data after
        # the database has initialized; never require a SESSION env string.
        self.user_client = None
        self.run_in_loop(self.start_client(bot_token=bot_token or Var.BOT_TOKEN))

    def __repr__(self):
        return "<AutoAnimeBot.Client :\n bot: {}\n>".format(self._bot)

    async def start_client(self, **kwargs):
        if self._log_at:
            self.logger.info("Trying To Login.")
        try:
            await self.start(**kwargs)
            await self.pyro_client.start()
        except ApiIdInvalidError:
            self.logger.critical("API ID and API_HASH combination does not match!")
            sys.exit(1)
        except (AccessTokenExpiredError, AccessTokenInvalidError):
            self.logger.critical(
                "Bot token is expired or invalid. Create a new one from @BotFather."
            )
            sys.exit(1)
        self.me = await self.get_me()
        if self.me.bot:
            me = f"@{self.me.username}"
        else:
            me = self.me.first_name
        if self._log_at:
            self.logger.info(f"Logged in as {me}")
        self._bot = await self.is_bot()

    async def attach_user_session(self, session_string: str):
        """Attach an already-authorized owner session restored from encrypted storage."""
        client = TelegramClient(
            StringSession(session_string), Var.API_ID, Var.API_HASH, base_logger=TelethonLogger
        )
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return False
        user = await client.get_me()
        if Var.OWNER and user.id != Var.OWNER:
            await client.disconnect()
            raise ValueError("The saved Telegram account does not match OWNER.")
        if self.user_client and self.user_client.is_connected():
            await self.user_client.disconnect()
        self.user_client = client
        self.logger.info("Encrypted owner Telegram session restored.")
        return True

    async def check_channel_rights(self, channel_id: int, role: str):
        """Ensure the bot is an admin with the rights needed for a channel role."""
        me = await self.pyro_client.get_me()
        member = await self.pyro_client.get_chat_member(channel_id, me.id)
        status = member.status
        if status not in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}:
            raise ValueError("Please make the bot an admin of this channel first.")
        if status == ChatMemberStatus.OWNER:
            return
        privileges = member.privileges
        if role == "forcesub" and not getattr(privileges, "can_invite_users", False):
            raise ValueError("For force-sub, give the bot the Invite Users permission.")
        chat = await self.pyro_client.get_chat(channel_id)
        if role != "forcesub" and chat.type == ChatType.CHANNEL:
            if not getattr(privileges, "can_post_messages", False):
                raise ValueError("For this channel role, give the bot permission to post messages.")

    async def upload_anime(self, file, caption, thumb=None, is_button=False):
        if not self.pyro_client.is_connected:
            try:
                await self.pyro_client.connect()
            except Exception:
                try:
                    await self.pyro_client.stop()
                except Exception:
                    pass
                await self.pyro_client.start()

        if is_button:
            channels = [Var.BACKUP_CHANNEL] if Var.BACKUP_CHANNEL else []
            if not channels:
                raise RuntimeError("Set a backup channel before enabling button upload.")
        else:
            channels = list(Var.MAIN_CHANNELS)
            if not channels and Var.MAIN_CHANNEL:
                channels = [Var.MAIN_CHANNEL]
            if not channels:
                raise RuntimeError("Set at least one main channel with /setchannel.")

        posts = []
        for channel_id in channels:
            try:
                posts.append(
                    await self.pyro_client.send_document(
                        channel_id,
                        file,
                        caption=f"`{caption}`",
                        force_document=True,
                        thumb=thumb or "thumb.jpg",
                    )
                )
            except Exception as error:
                self.logger.error(f"Anime upload failed for channel {channel_id}: {error}")
        if not posts:
            raise RuntimeError("The episode could not be uploaded to any configured channel.")
        return posts

    async def upload_poster(self, file, caption, channel_id=None):
        channels = [channel_id] if channel_id else list(Var.MAIN_CHANNELS)
        if not channels and Var.MAIN_CHANNEL:
            channels = [Var.MAIN_CHANNEL]
        if not channels:
            raise RuntimeError("Set at least one main channel with /setchannel.")
        posts = []
        for target in channels:
            try:
                posts.append(
                    await self.send_file(
                        target,
                        file=file,
                        caption=caption or "",
                    )
                )
            except Exception as error:
                self.logger.error(f"Poster upload failed for channel {target}: {error}")
        if not posts:
            raise RuntimeError("The poster could not be uploaded to any configured channel.")
        return posts

    async def is_joined(self, channel_id, user_id):
        try:
            member = await self.pyro_client.get_chat_member(channel_id, user_id)
        except UserNotParticipant:
            return False
        if member.status in {
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
        }:
            return True
        if member.status == ChatMemberStatus.RESTRICTED:
            return bool(member.is_member)
        return False

    async def create_force_sub_invite(
        self, channel_id: int, *, expires_at: datetime | None = None, name: str = "Auto FSub"
    ):
        return await self.pyro_client.create_chat_invite_link(
            chat_id=channel_id,
            name=name[:32],
            expire_date=expires_at,
            creates_join_request=True,
        )

    async def revoke_invite_link(self, channel_id: int, invite_link: str):
        if not invite_link:
            return
        try:
            await self.pyro_client.revoke_chat_invite_link(channel_id, invite_link)
        except Exception as error:
            self.logger.warning(f"Could not revoke an old invite link for {channel_id}: {error}")

    async def create_channel(self, title: str, logo=None):
        if not self.user_client or not await self.user_client.is_user_authorized():
            raise RuntimeError("Owner Telegram login is required for separate channel upload.")
        try:
            result = await self.user_client(
                CreateChannelRequest(
                    title=title,
                    about="Powered by @ahjin_anime",
                    megagroup=False,
                )
            )
            created_chat_id = result.chats[0].id
            chat_id = int(f"-100{created_chat_id}")
            await asyncio.sleep(2)
            await self.user_client.edit_admin(
                chat_id,
                f"{(await self.get_me()).username}",
                post_messages=True,
                edit_messages=True,
                delete_messages=True,
                pin_messages=True,
            )
            if logo:
                try:
                    await self.user_client(
                        EditPhotoRequest(chat_id, await self.user_client.upload_file(logo))
                    )
                except Exception:
                    pass
            return chat_id
        except Exception:
            LOGS.error(format_exc())
            raise

    async def generate_invite_link(self, channel_id):
        if not self.user_client or not await self.user_client.is_user_authorized():
            raise RuntimeError("Owner Telegram login is required for separate channel upload.")
        data = await self.user_client(
            ExportChatInviteRequest(
                peer=channel_id,
                title="Generated By Ongoing Anime Bot",
                request_needed=False,
                usage_limit=None,
            )
        )
        return data.link

    async def delete_after(self, messages, seconds: int = 600):
        await asyncio.sleep(seconds)
        await asyncio.gather(
            *(message.delete() for message in messages if message is not None),
            return_exceptions=True,
        )

    def run_in_loop(self, function):
        return self.loop.run_until_complete(function)

    def run(self):
        self.run_until_disconnected()

    def add_handler(self, func, *args, **kwargs):
        if func in [_[0] for _ in self.list_event_handlers()]:
            return
        self.add_event_handler(func, *args, **kwargs)
