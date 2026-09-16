import asyncio
import logging
from dotenv import load_dotenv
from .config import Config


async def run_bot(bot, token):
    try:
        await bot.start(token)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await bot.close()


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = Config.load()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    from .discord_app import Fodw
    # Client.run() catches Ctrl+C outside asyncio.run(), which can cancel the
    # loop before custom voice cleanup has finished. Keep cleanup in the async
    # lifetime so it is awaited before the process exits.
    asyncio.run(run_bot(Fodw(config), config.token))


if __name__ == "__main__":
    main()
