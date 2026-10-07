#    This file is part of the AutoAnime distribution.
#    Copyright (c) 2026 Kaif_00z
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3.
#
#    This program is distributed in the hope that it will be useful, but
#    WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
#    General Public License for more details.
#
# License can be found at:
# https://github.com/kaif-00z/AutoAnimeBot/blob/main/LICENSE

from decouple import config


def _int_config(name, default):
    value = config(name, default=default)
    return int(value) if str(value).strip() else int(default)


class Var:
    __version__ = "v0.3"

    # Bot/database credentials. API_ID/API_HASH retain the upstream defaults;
    # SESSION is intentionally not required or loaded from the environment.
    API_ID = _int_config("API_ID", 6)
    API_HASH = config(
        "API_HASH", default="eb06d4abfb49dc3eeb1aeb98ae0f581e"
    ) or "eb06d4abfb49dc3eeb1aeb98ae0f581e"
    BOT_TOKEN = config("BOT_TOKEN", default="")
    MONGO_SRV = config("MONGO_SRV", default="")
    OWNER = _int_config("OWNER", 0)

    # Legacy channel variables are optional and used only once to migrate an
    # existing deployment into MongoDB. New channel setup is done in Telegram.
    LEGACY_MAIN_CHANNEL = _int_config("MAIN_CHANNEL", 0)
    LEGACY_LOG_CHANNEL = _int_config("LOG_CHANNEL", 0)
    LEGACY_CLOUD_CHANNEL = _int_config("CLOUD_CHANNEL", 0)
    LEGACY_BACKUP_CHANNEL = _int_config("BACKUP_CHANNEL", 0)
    LEGACY_FORCESUB_CHANNEL = _int_config("FORCESUB_CHANNEL", 0)
    LEGACY_FORCESUB_LINK = config("FORCESUB_CHANNEL_LINK", default="")

    # Runtime channel values are hydrated from MongoDB before the anime watcher starts.
    MAIN_CHANNELS = []
    MAIN_CHANNEL = 0
    LOG_CHANNEL = 0
    CLOUD_CHANNEL = 0
    BACKUP_CHANNEL = 0
    FORCESUB_CHANNELS = []
    FORCESUB_CHANNEL = 0
    FORCESUB_CHANNEL_LINK = ""

    THUMB = config(
        "THUMBNAIL", default="https://graph.org/file/ad1b25807b81cdf1dff65.jpg"
    )
    FFMPEG = config("FFMPEG", default="ffmpeg")
    CRF = config("CRF", default="27")
    SEND_SCHEDULE = config("SEND_SCHEDULE", default=False, cast=bool)
    RESTART_EVERDAY = config("RESTART_EVERDAY", default=True, cast=bool)
    LOG_ON_MAIN = config("LOG_ON_MAIN", default=False, cast=bool)
