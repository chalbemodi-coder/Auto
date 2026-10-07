# AutoAnimeBot

Telegram bot that watches ongoing anime releases, encodes and posts episodes, and serves stored files through bot deep links. The existing anime polling, download, encoding, button-upload, and sample/screenshot workflows remain available.

This repository is a fork of [AutoAnimeBot](https://github.com/kaif-00z/AutoAnimeBot). It retains the upstream GPLv3 license and required source attribution.

## Deploy on Railway

Railway builds the repository's `Dockerfile` when the service is connected to GitHub. Select the branch you intend to run; pushing commits to that linked branch triggers a deployment. Add a **persistent volume** to the bot service with this exact mount path:

```text
/usr/src/app/.state
```

The bot creates its own Fernet encryption key in that volume the first time the owner runs `/login`. Do not remove the volume or its key file: MongoDB stores only the encrypted Telegram user session, and the same volume is needed to decrypt it after redeploys. If that volume is lost, the saved encrypted session may no longer be usable and the owner must log in again after safely clearing/replacing the old session record.

### Environment variables

Required:

- `BOT_TOKEN` — token from @BotFather.
- `MONGO_SRV` — MongoDB connection URI.
- `OWNER` — numeric Telegram user ID. Only this ID can run `/login`, configure channels, and use admin callbacks.

Optional:

- `API_ID` and `API_HASH` — Telegram app credentials; upstream-compatible defaults are used when blank.
- `SEND_SCHEDULE`, `RESTART_EVERDAY`, `THUMBNAIL`, `CRF`, `FFMPEG`, `LOG_ON_MAIN` — optional runtime settings.

Do **not** set `SESSION`, `SESSION_ENCRYPTION_KEY`, or channel-ID variables. The Telegram user session is created with `/login`; channel IDs are stored in MongoDB by bot commands. Old channel environment values, if present during the first start after updating, are migrated once into MongoDB.

See [`.sample.env`](.sample.env) for the template. Never put real secrets in Git or in a Docker image.

## First run and owner login

1. Set `BOT_TOKEN`, `MONGO_SRV`, and your numeric `OWNER` in Railway Variables.
2. Attach the persistent volume at `/usr/src/app/.state` and deploy.
3. Open the bot's private chat as the configured owner and send `/login`.
4. Enter your Telegram phone number, OTP, and 2-step-verification password in that private conversation if requested. Input messages are deleted best-effort; do not share OTPs or passwords with anyone. The login is accepted only if the Telegram account ID matches `OWNER`.
5. Use `/channels` and the commands below to configure destinations.

The owner user session is encrypted before being stored in MongoDB. Its key is auto-generated, permission-restricted, and held on the persistent volume; no session string or encryption-key environment variable is required. The login command is owner-only and is not a public Telegram login service.

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

The bot starts with the existing MongoDB database name `ONGOINGANIME`; settings and encrypted session records are stored in separate collections/documents there.

## Local Docker

Build and run the image with the required environment variables, and bind a persistent host directory to `/usr/src/app/.state`. Do not run the container without persistent state if you need the owner session to survive restarts. On Railway, create the equivalent volume in the service settings rather than relying on container-local files.

```bash
docker build -t autoanimebot .
docker run -d --name autoanimebot --restart unless-stopped \
  --env-file .env \
  -v autoanimebot-state:/usr/src/app/.state \
  autoanimebot
```

## License

GPLv3. See [`LICENSE`](LICENSE). This fork preserves the original project attribution.
