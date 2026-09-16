import logging
from dotenv import load_dotenv
from .config import Config


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = Config.load()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    from .discord_app import Fodw
    Fodw(config).run(config.token, log_handler=None)


if __name__ == "__main__":
    main()
