"""Legacy terminal bootstrap retired in favor of owner-only Telegram commands.

This script intentionally does not request phone OTP/2FA, create Telegram
channels, or write raw SESSION/channel IDs into an environment file.
"""


def main():
    print(
        "The interactive session-string generator has been retired.\n"
        "Set BOT_TOKEN, MONGO_SRV, and numeric OWNER in your host environment,\n"
        "attach persistent storage at /usr/src/app/.state, start the bot, then use:\n"
        "  /login\n"
        "  /setchannel main -1001234567890\n"
        "  /setchannel forcesub -1001234567890 temp\n"
        "Use /channels to see all settings and remaining command help."
    )


if __name__ == "__main__":
    main()
