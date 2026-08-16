import logging
import os
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)


def load_pedalboard(board_name: str, mod_api_url: str, pedalboards_dir: str) -> None:
    logger.info(f"Resetting engine and loading: {board_name}")

    try:
        urllib.request.urlopen(f"{mod_api_url}/reset", timeout=2)
        time.sleep(0.5)
    except (URLError, TimeoutError, HTTPError):
        logger.warning("Could not reset engine. Attempting to load pedalboard...")

    url = f"{mod_api_url}/pedalboard/load_bundle/"
    bundle_path = os.path.join(pedalboards_dir, f"{board_name}.pedalboard")
    data = urllib.parse.urlencode({"bundlepath": bundle_path}).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                logger.info(f"Successfully loaded {board_name}")

    except HTTPError as e:
        logger.error(
            f"Failed to load {board_name}. The server returned: {e.code} - {e.reason}"
        )
    except TimeoutError:
        logger.error(f"Failed to load {board_name}. The request timed out.")
    except URLError as e:
        logger.error(f"Failed to reach pi-stomp API. Reason: {e.reason}")
