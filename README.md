# AutoAnimeBot

Telegram bot that watches ongoing anime releases, encodes and posts episodes, and serves stored files through bot deep links. The existing anime polling, download, encoding, button-upload, and sample/screenshot workflows remain available.

This repository is a fork of [AutoAnimeBot](https://github.com/kaif-00z/AutoAnimeBot). It retains the upstream GPLv3 license and required source attribution.

## Docker deployment

The host can build the repository's `Dockerfile` from GitHub or you can build it on a Docker server. The owner Telegram session is stored directly as plain text in MongoDB; no persistent volume or `SESSION_ENCRYPTION_KEY` is required for login.

**Security warning:** anyone with read access to the MongoDB session document can use that session to access the Telegram account without its OTP or 2FA password. Use a dedicated MongoDB database/user with a strong password, restrict network access to trusted hosts, do not expose database credentials or backups, and do not share the session or MongoDB access. This is an intentional security downgrade from encrypted session storage.

Older records saved by a previous encrypted version are migrated when their original key is available. If that key was lost, run `/login` again; the new owner session will replace the old record.

### Environment variables

Required:

- `BOT_TOKEN` — token from @BotFather.
- `MONGO_SRV` — MongoDB connection URI.
- `OWNER` — numeric Telegram user ID. Only this ID can run `/login`, configure channels, and use admin callbacks.

Optional:

- `API_ID` and `API_HASH` — Telegram app credentials; upstream-compatible defaults are used when blank.
- `SEND_SCHEDULE`, `RESTART_EVERDAY`, `THUMBNAIL`, `CRF`, `FFMPEG`, `LOG_ON_MAIN` — optional runtime settings.

Do **not** set `SESSION` or channel-ID variables. The Telegram user session is created with `/login`; channel IDs are stored in MongoDB by bot commands. Old channel environment values, if present during the first start after updating, are migrated once into MongoDB.

See [`.sample.env`](.sample.env) for the template. Never put real secrets in Git or in a Docker image.

## First run and owner login

1. Set `BOT_TOKEN`, `MONGO_SRV`, and your numeric `OWNER` in the host's Variables/Secrets.
2. Deploy the Docker image; session storage does not need a mounted volume or encryption-key variable.
3. Open the bot's private chat as the configured owner and send `/login`.
4. Enter your Telegram phone number, OTP, and 2-step-verification password in that private conversation if requested. Input messages are deleted best-effort; do not share OTPs or passwords with anyone. The login is accepted only if the Telegram account ID matches `OWNER`.
5. Use `/channels` and the commands below to configure destinations.

The owner user session is stored unencrypted in MongoDB at the owner's explicit request. The `/login` command remains owner-only and still verifies that the logged-in Telegram account ID matches `OWNER`.

## Channel setup commands

Run these in a private chat with the bot as the configured owner:

| Command | Purpose |
|---|---|
| `/channels` | Show current channel settings and help |
| `/setchannel main -1001234567890` | Add a main destination; maximum 2 |
| `/setchannel log -1001234567890` | Set the progress/error log channel |
| `/setchannel backup -1001234567890` | Set the stored-file/backup channel |
| `/setchannel cloud -1001234567890` | Set the sample and screenshot channel |
| `/setchannel forcesub -1001234567890 temp` | Add a temporary-link force-sub channel; maximum 6 |
| `/setchannel forcesub -1001234567890 fixed` | Add a reusable, non-expiring force-sub link |
| `/unsetchannel main -1001234567890` | Remove one main channel |
| `/unsetchannel main all` | Remove all main channels |
| `/unsetchannel forcesub -1001234567890` | Remove one force-sub channel |
| `/unsetchannel forcesub all` | Remove all force-sub channels |
| `/unsetchannel log` / `backup` / `cloud` | Remove that destination |

Use the channel's **negative numeric ID**. Add the bot as an administrator of every configured channel. Destination channels need post permission; force-sub channels need **Invite Users** permission so the bot can create join-request links. The bot starts or resumes its anime release watcher when at least one main channel is configured.

### Force-sub behavior

- Up to 6 force-sub channels are stored in MongoDB. On `/start`, the bot checks each separately and shows only the channels the user has not joined.
- Both `temp` and `fixed` links are created in **join-request mode**. Channel administrators approve requests; after approval, the user can tap Refresh in the bot.
- `temp` creates a per-user link that expires after 10 minutes. When another link is issued for that same user/channel, the prior link is revoked.
- `fixed` reuses a join-request invite link that has no automatic expiry. Change the channel to `temp` if it should rotate and expire.
- Since Telegram join requests require administrator approval, clicking the link does not immediately make the user a member. The bot will continue to show that channel until approval is complete.

## Anime and delivery behavior

- Anime release polling and episode processing continue as before once a main channel is configured.
- Episodes and posters are mirrored to both configured main channels (maximum 2). Daily airing schedule posts are also sent to both.
- Button uploads require a backup channel. Samples/screenshots require a cloud channel; the bot skips that optional work if no cloud channel is configured.
- A file delivered to a user's private chat through a bot deep link, including sample/screenshot delivery, is deleted after 10 minutes. Users should save or forward it before then.
- Separate per-anime channel upload uses the logged-in owner session; run `/login` first.

## Other commands and panel

- `/start` — open the bot or fetch a linked file.
- `/about` — show bot and runtime information.
- `/login` — owner-only Telegram user login.
- `/channels`, `/setchannel`, `/unsetchannel` — owner-only channel management.
- Admin-panel callbacks are also restricted to the configured owner.
- `/cancel` is used while the broadcast conversation is active.

The bot starts with the existing MongoDB database name `ONGOINGANIME`; settings and the owner session are stored in MongoDB. The current version stores the session as plain text, as noted in the security warning above.

## Local Docker

Copy `.sample.env` to `.env`, fill in `BOT_TOKEN`, `MONGO_SRV`, and numeric `OWNER`, then build and start the bot with Docker Compose. Session and channel settings are stored in MongoDB, so this version does not need a `.state` volume or `SESSION_ENCRYPTION_KEY`. The `.env` file is supplied at runtime and is excluded from the image.

```bash
cp .sample.env .env
# Edit .env with your own values, then:
docker compose up -d --build
docker compose logs -f bot
```

Stop the container with `docker compose down`. Run only one live instance for a given `BOT_TOKEN`; stop the old host deployment before starting another copy against the same bot/database.

## License

GPLv3. See [`LICENSE`](LICENSE). This fork preserves the original project attribution.
