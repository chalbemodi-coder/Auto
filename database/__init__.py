#    This file is part of the AutoAnime distribution.
#    Copyright (c) 2026 Kaif_00z
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3.

import sys
from datetime import datetime, timezone
from traceback import format_exc

from motor.motor_asyncio import AsyncIOMotorClient

from functions.config import Var
from functions.session_store import decrypt_session, encrypt_session
from libs.logger import LOGS


CHANNEL_SETTINGS_ID = "CHANNEL_SETTINGS"
OWNER_SESSION_ID = "OWNER_SESSION"


def _channel_id(value):
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return result if result < 0 else 0


def normalize_channel_settings(data):
    data = data or {}
    main_channels = []
    for item in data.get("main_channels", []):
        channel_id = _channel_id(item)
        if channel_id and channel_id not in main_channels:
            main_channels.append(channel_id)
        if len(main_channels) == 2:
            break

    force_sub_channels = []
    seen = set()
    for item in data.get("force_sub_channels", []):
        if not isinstance(item, dict):
            continue
        channel_id = _channel_id(item.get("channel_id", item.get("id")))
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        mode = "fixed" if item.get("mode") == "fixed" else "temp"
        force_sub_channels.append(
            {
                "channel_id": channel_id,
                "mode": mode,
                "fixed_link": str(item.get("fixed_link") or "") if mode == "fixed" else "",
            }
        )
        if len(force_sub_channels) == 6:
            break

    return {
        "main_channels": main_channels,
        "log_channel": _channel_id(data.get("log_channel")),
        "backup_channel": _channel_id(data.get("backup_channel")),
        "cloud_channel": _channel_id(data.get("cloud_channel")),
        "force_sub_channels": force_sub_channels,
    }


class DataBase:
    def __init__(self):
        try:
            if not Var.MONGO_SRV:
                raise ValueError("MONGO_SRV is required to connect to MongoDB")
            LOGS.info("Trying To Connect With MongoDB")
            self.client = AsyncIOMotorClient(Var.MONGO_SRV)
            self.db = self.client["ONGOINGANIME"]
            self.file_info_db = self.db["fileInfo"]
            self.channel_info_db = self.db["animeChannelInfo"]
            self.opts_db = self.db["opts"]
            self.file_store_db = self.db["fileStore"]
            self.broadcast_db = self.db["broadcastInfo"]
            self.user_session_db = self.db["userSessions"]
            self.fsub_invite_db = self.db["forceSubInvites"]
            LOGS.info("Successfully Connected With MongoDB")
        except Exception as error:
            LOGS.exception(format_exc())
            LOGS.critical(str(error))
            sys.exit(1)

    async def load_channel_settings(self):
        try:
            await self.fsub_invite_db.create_index(
                "expires_at", expireAfterSeconds=0, name="fsub_invite_expiry"
            )
        except Exception as error:
            LOGS.warning(f"Could not create optional force-sub invite TTL index: {error}")

        data = await self.opts_db.find_one({"_id": CHANNEL_SETTINGS_ID})
        if data:
            settings = normalize_channel_settings(data)
        else:
            # One-time migration for deployments that previously used channel env vars.
            legacy_fsub = []
            if Var.LEGACY_FORCESUB_CHANNEL:
                legacy_fsub.append(
                    {
                        "channel_id": Var.LEGACY_FORCESUB_CHANNEL,
                        "mode": "temp",
                        "fixed_link": "",
                    }
                )
            settings = normalize_channel_settings(
                {
                    "main_channels": [Var.LEGACY_MAIN_CHANNEL]
                    if Var.LEGACY_MAIN_CHANNEL
                    else [],
                    "log_channel": Var.LEGACY_LOG_CHANNEL,
                    "backup_channel": Var.LEGACY_BACKUP_CHANNEL,
                    "cloud_channel": Var.LEGACY_CLOUD_CHANNEL,
                    "force_sub_channels": legacy_fsub,
                }
            )
            await self.opts_db.update_one(
                {"_id": CHANNEL_SETTINGS_ID},
                {"$set": settings},
                upsert=True,
            )

        self._apply_channel_settings(settings)
        return settings

    async def get_channel_settings(self):
        data = await self.opts_db.find_one({"_id": CHANNEL_SETTINGS_ID})
        if not data:
            return await self.load_channel_settings()
        settings = normalize_channel_settings(data)
        self._apply_channel_settings(settings)
        return settings

    async def save_channel_settings(self, settings):
        settings = normalize_channel_settings(settings)
        await self.opts_db.update_one(
            {"_id": CHANNEL_SETTINGS_ID},
            {"$set": settings},
            upsert=True,
        )
        self._apply_channel_settings(settings)
        return settings

    @staticmethod
    def _apply_channel_settings(settings):
        Var.MAIN_CHANNELS = list(settings["main_channels"])
        Var.MAIN_CHANNEL = Var.MAIN_CHANNELS[0] if Var.MAIN_CHANNELS else 0
        Var.LOG_CHANNEL = settings["log_channel"]
        Var.BACKUP_CHANNEL = settings["backup_channel"]
        Var.CLOUD_CHANNEL = settings["cloud_channel"]
        Var.FORCESUB_CHANNELS = list(settings["force_sub_channels"])
        Var.FORCESUB_CHANNEL = (
            Var.FORCESUB_CHANNELS[0]["channel_id"] if Var.FORCESUB_CHANNELS else 0
        )
        Var.FORCESUB_CHANNEL_LINK = (
            Var.FORCESUB_CHANNELS[0].get("fixed_link", "")
            if Var.FORCESUB_CHANNELS
            else ""
        )

    async def set_channel(self, role, channel_id, *, mode="temp", fixed_link=""):
        settings = await self.get_channel_settings()
        role = role.lower()
        channel_id = _channel_id(channel_id)
        if not channel_id:
            raise ValueError("Use a negative Telegram channel ID, such as -1001234567890.")

        if role == "main":
            main = settings["main_channels"]
            if channel_id not in main and len(main) >= 2:
                raise ValueError("You can configure at most 2 main channels.")
            if channel_id not in main:
                main.append(channel_id)
        elif role == "forcesub":
            entries = settings["force_sub_channels"]
            existing = next((i for i in entries if i["channel_id"] == channel_id), None)
            mode = "fixed" if mode == "fixed" else "temp"
            if existing:
                existing.update(mode=mode, fixed_link=fixed_link if mode == "fixed" else "")
            else:
                if len(entries) >= 6:
                    raise ValueError("You can configure at most 6 force-sub channels.")
                entries.append(
                    {
                        "channel_id": channel_id,
                        "mode": mode,
                        "fixed_link": fixed_link if mode == "fixed" else "",
                    }
                )
        elif role in {"log", "backup", "cloud"}:
            settings[f"{role}_channel"] = channel_id
        else:
            raise ValueError("Role must be main, log, backup, cloud, or forcesub.")
        return await self.save_channel_settings(settings)

    async def unset_channel(self, role, channel_id=None):
        settings = await self.get_channel_settings()
        role = role.lower()
        if role == "main":
            if channel_id is None:
                settings["main_channels"] = []
            else:
                settings["main_channels"] = [
                    item for item in settings["main_channels"] if item != channel_id
                ]
        elif role == "forcesub":
            if channel_id is None:
                settings["force_sub_channels"] = []
            else:
                settings["force_sub_channels"] = [
                    item
                    for item in settings["force_sub_channels"]
                    if item["channel_id"] != channel_id
                ]
        elif role in {"log", "backup", "cloud"}:
            settings[f"{role}_channel"] = 0
        else:
            raise ValueError("Role must be main, log, backup, cloud, or forcesub.")
        return await self.save_channel_settings(settings)

    async def get_temp_invite(self, user_id, channel_id):
        return await self.fsub_invite_db.find_one(
            {"_id": f"{int(user_id)}:{int(channel_id)}"}
        )

    async def save_temp_invite(self, user_id, channel_id, link, expires_at):
        await self.fsub_invite_db.update_one(
            {"_id": f"{int(user_id)}:{int(channel_id)}"},
            {
                "$set": {
                    "user_id": int(user_id),
                    "channel_id": int(channel_id),
                    "invite_link": link,
                    "expires_at": expires_at,
                }
            },
            upsert=True,
        )

    async def delete_temp_invite(self, user_id, channel_id):
        await self.fsub_invite_db.delete_one(
            {"_id": f"{int(user_id)}:{int(channel_id)}"}
        )

    async def get_temp_invites_for_channel(self, channel_id):
        cursor = self.fsub_invite_db.find({"channel_id": int(channel_id)})
        return await cursor.to_list(length=None)

    async def delete_temp_invites_for_channel(self, channel_id):
        docs = await self.get_temp_invites_for_channel(channel_id)
        await self.fsub_invite_db.delete_many({"channel_id": int(channel_id)})
        return docs

    async def save_user_session(self, session_string):
        session_string = str(session_string or "")
        if not session_string:
            raise ValueError("Refusing to save an empty Telegram session.")
        encrypted_session = encrypt_session(session_string)
        await self.user_session_db.update_one(
            {"_id": OWNER_SESSION_ID},
            {
                "$set": {
                    "encrypted_session": encrypted_session,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$unset": {"session_string": ""},
            },
            upsert=True,
        )

    async def get_user_session(self):
        data = await self.user_session_db.find_one({"_id": OWNER_SESSION_ID})
        if not data:
            return None
        encrypted = data.get("encrypted_session")
        if encrypted:
            session_string = decrypt_session(encrypted)
            if data.get("session_string"):
                await self.user_session_db.update_one(
                    {"_id": OWNER_SESSION_ID},
                    {"$unset": {"session_string": ""}},
                )
            return session_string

        # Upgrade a session saved in plaintext by an older release. The plaintext
        # field is removed only after encryption succeeds with the configured key.
        session_string = str(data.get("session_string") or "")
        if not session_string:
            return None
        encrypted = encrypt_session(session_string)
        await self.user_session_db.update_one(
            {"_id": OWNER_SESSION_ID},
            {
                "$set": {
                    "encrypted_session": encrypted,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$unset": {"session_string": ""},
            },
        )
        return session_string

    async def clear_user_session(self):
        await self.user_session_db.delete_one({"_id": OWNER_SESSION_ID})

    async def add_anime(self, uid):
        data = await self.file_info_db.find_one({"_id": uid})
        if not data:
            await self.file_info_db.insert_one({"_id": uid})

    async def toggle_separate_channel_upload(self):
        data = await self.opts_db.find_one({"_id": "SEPARATE_CHANNEL_UPLOAD"})
        value = not (data or {}).get("switch", False)
        await self.opts_db.update_one(
            {"_id": "SEPARATE_CHANNEL_UPLOAD"}, {"$set": {"switch": value}}, upsert=True
        )

    async def is_separate_channel_upload(self):
        data = await self.opts_db.find_one({"_id": "SEPARATE_CHANNEL_UPLOAD"})
        return (data or {}).get("switch", False)

    async def toggle_original_upload(self):
        data = await self.opts_db.find_one({"_id": "OG_UPLOAD"})
        value = not (data or {}).get("switch", False)
        await self.opts_db.update_one(
            {"_id": "OG_UPLOAD"}, {"$set": {"switch": value}}, upsert=True
        )

    async def is_original_upload(self):
        data = await self.opts_db.find_one({"_id": "OG_UPLOAD"})
        return (data or {}).get("switch", False)

    async def toggle_button_upload(self):
        data = await self.opts_db.find_one({"_id": "BUTTON_UPLOAD"})
        value = not (data or {}).get("switch", False)
        await self.opts_db.update_one(
            {"_id": "BUTTON_UPLOAD"}, {"$set": {"switch": value}}, upsert=True
        )

    async def is_button_upload(self):
        data = await self.opts_db.find_one({"_id": "BUTTON_UPLOAD"})
        return (data or {}).get("switch", False)

    async def is_anime_uploaded(self, uid):
        return bool(await self.file_info_db.find_one({"_id": uid}))

    async def add_anime_channel_info(self, title, data):
        await self.channel_info_db.update_one(
            {"_id": title}, {"$set": {"data": data}}, upsert=True
        )

    async def get_anime_channel_info(self, title):
        data = await self.channel_info_db.find_one({"_id": title})
        return (data or {}).get("data", {})

    async def store_items(self, _hash, _list):
        await self.file_store_db.update_one(
            {"_id": _hash}, {"$set": {"data": _list}}, upsert=True
        )

    async def get_store_items(self, _hash):
        data = await self.file_store_db.find_one({"_id": _hash})
        return (data or {}).get("data", [])

    async def add_broadcast_user(self, user_id):
        await self.broadcast_db.update_one(
            {"_id": int(user_id)}, {"$setOnInsert": {"_id": int(user_id)}}, upsert=True
        )

    async def get_broadcast_user(self):
        data = self.broadcast_db.find()
        return [i["_id"] for i in await data.to_list(length=None)]

    async def toggle_ss_upload(self):
        data = await self.opts_db.find_one({"_id": "SS_UPLOAD"})
        value = not (data or {}).get("switch", True)
        await self.opts_db.update_one(
            {"_id": "SS_UPLOAD"}, {"$set": {"switch": value}}, upsert=True
        )

    async def is_ss_upload(self):
        data = await self.opts_db.find_one({"_id": "SS_UPLOAD"})
        return (data or {}).get("switch", True)
