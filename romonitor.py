"""
RoMonitor - An item monitoring tool

Developed by RoWhoIs

CONTRIBUTORS:
https://github.com/aut-mn
"""
import asyncio
import argparse
import signal
import datetime
import json
import sys
import logging
from typing import Any, List, Tuple
from dataclasses import dataclass

import aiohttp


@dataclass
class Economy:
    """Used to better define and store economy data"""
    forsale: bool
    price: int | None
    resaleprice: int | None = None
    limited: bool | None = None
    limitedu: bool | None = None
    collectible: bool | None = None
    remaining: int | None = None


@dataclass
class Item:
    """Used to define and store item data"""
    id: int
    name: str
    economics: Economy
    description: str | None
    creator: str
    updated: datetime.datetime
    thumbnail: str = "https://rowhois.com/not-available.png"


@dataclass
class Token:
    """Used for dynamically refreshing x-csrf-tokens"""
    datetime: datetime.datetime
    token: str | None


@dataclass
class Authentication:
    """Used to store authentication data"""
    roblosecurity: str
    webhook: str
    xcsrf: Token


def compare(item1: Item, item2: Item) -> List[str] | None:
    """Compares this item with another item and returns a list of attributes that have changed"""
    changed_attributes = []
    for attribute in vars(item1):
        if getattr(item1, attribute) != getattr(item2, attribute):
            changed_attributes.append(attribute)
            old_value = getattr(item1, attribute)
            new_value = getattr(item2, attribute)
            logger.debug(
                "Diff: %s: %s -> %s",
                attribute, old_value if old_value not in [None, ''] else 'None',
                new_value if new_value not in [None, ''] else 'None'
            )
    if changed_attributes:
        logger.debug(
            "Item data changed, returning key%s %s",
            's' if len(changed_attributes) >= 2 else '', changed_attributes
        )
    return changed_attributes if changed_attributes else None


async def token_renewal() -> Token:
    """Updates the x-csrf-token"""
    try:
        if debug_mode:
            logger.debug("Renewing X-CSRF Token")
        async with aiohttp.ClientSession(cookies={".roblosecurity": roblosecurity}) as session:
            async with session.post("https://auth.roblox.com/v2/logout") as resp:
                if 'x-csrf-token' not in resp.headers and debug_mode:
                    logger.debug("Failed to renew token: %d", resp.status)
        return Token(datetime.datetime.now(), resp.headers.get('x-csrf-token', None))
    except Exception:  # noqa: W0718
        return Token(datetime.datetime.now(), None)


async def validate_cookie() -> bool:
    """Validates the roblosecurity value from config.json. Returns True if valid."""
    global x_token
    try:
        if debug_mode:
            logger.debug("Validating roblosecurity cookie")
        async with aiohttp.ClientSession(cookies={".roblosecurity": roblosecurity}) as main_session:
            async with main_session.get("https://users.roblox.com/v1/users/authenticated") as resp:
                if resp.status == 200:
                    x_token = await token_renewal()  # Initialize the token
                    return True
                logger.error("Invalid ROBLOSECURITY cookie. Aborting RoMonitor.")
        return False
    except aiohttp.ClientConnectionError:
        logger.fatal("Can't connect to the Roblox servers! Are you offline?")
        return False
    except Exception:  # noqa: W0718
        return False


async def rofetch(url: str, method: str = "get", debugmessage: str | None = None, **kwargs) -> tuple[int, Any] | None:  # noqa: E501
    """Fetches authenticated Roblox URLs. Error handler included. Free Robux not included."""
    global x_token
    try:
        async with aiohttp.ClientSession(cookies={".roblosecurity": roblosecurity}) as session:
            if debug_mode and debugmessage:
                logger.debug(debugmessage)
            for _ in range(5):
                response = await session.request(
                    method, url,  headers={"x-csrf-token": x_token.token}, **kwargs
                )
                if response.status == 200:
                    return response.status, await response.json()
                if response.status in [400, 404]:
                    return 404, None
                if response.status == 403:
                    x_token = await token_renewal()  # Renew just in case
                await asyncio.sleep(5)
            return 0, None
    except aiohttp.ClientConnectorError:
        logger.fatal("Can't connect to the Roblox servers! Are you offline?")
    except asyncio.CancelledError:
        return 0, None


async def fetch_resale(item_data: int) -> int | None:
    """Fetches the lowest resale price for a specified non-collectible limited"""
    try:
        data = await rofetch(
            f"https://economy.roblox.com/v1/assets/{item_data}/resellers",
            debugmessage="Fetching lowest resale price"
        )
        if not data:
            return None
        if 'seller' in data[1]['data'][0]:
            return int(data[1]['data'][0]['price'])
    except asyncio.CancelledError:
        return None


async def get_item(asset: int) -> Item | None:
    """Fetches item data and casts it to an Item. Returns None if failed."""
    try:
        data = await rofetch(
            f"https://economy.roblox.com/v2/assets/{asset}/details",
            debugmessage="Fetching latest item data"
        )
        if data is None:
            return None
        economy_data = Economy(
            data[1]['IsForSale'],
            data[1]['PriceInRobux'],
            data[1]['IsLimited'],
            data[1]['IsLimitedUnique'],
            data[1]['CollectiblesItemDetails']['IsLimited'] if data[1].get('CollectiblesItemDetails') is not None else False,  # noqa: E501
            data[1]['Remaining'] if data[1].get('Remaining') is not None else None
        )
        if economy_data.collectible or economy_data.limited or economy_data.limitedu:
            resale = await fetch_resale(asset)
            economy_data.resaleprice = resale
        return_item = Item(
            id=asset, name=data[1]['Name'], economics=economy_data,
            description=data[1]['Description'], creator=data[1]['Creator']['Name'],
            updated=datetime.datetime.strptime(data[1]['Updated'], "%Y-%m-%dT%H:%M:%S.%fZ"),
        )
        if data[0] != 200:
            logger.error("Failed to fetch item data: %d", data[0])
            return None
        return return_item
    except asyncio.CancelledError:
        return None


async def send_webhook(message: str, title: str | None = None, url: str | None = None) -> None:
    """Sends a message through the webhook"""
    if debug_mode:
        logger.debug("Pushing to webhook")
    webhook_contents = {
        "username": "RoMonitor", "avatar_url": "https://rowhois.com/builderman.png",
        "content": f"<@{mention}>" if mention != 0 else None,
        "embeds": [
            {
                "title": title if title is not None else None,
                "url": url if url is not None else None, "color": 65293, "description": message,
                "thumbnail": {"url": thumbnail}
            }
        ]
    }
    async with aiohttp.ClientSession() as session:
        await session.request("POST", webhookURL, json=webhook_contents)


async def validate_item() -> Tuple[bool, str | None]:
    """Validates an item and returns True and the item thumbnail if valid"""
    data, item_thumbnail = await asyncio.gather(
        rofetch(
            f"https://economy.roblox.com/v2/assets/{item}/details",
            debugmessage="Fetching latest item details"
        ),
        rofetch(
            f"https://thumbnails.roblox.com/v1/assets?assetIds={item}&size=420x420&format=Png",
            debugmessage="Fetching item thumbnail"
        )
    )
    if data is None or item_thumbnail is None:
        logger.debug("data and thumbnail returned None while validating an item")
        logger.fatal("Failed to initialize!")
        return False, "https://rowhois.com/not-available.png"
    if data[0] != 200:
        if data[0] in [400, 404]:
            logger.fatal("The specified item does not exist.")
        else:
            logger.fatal("Failed to initialize. Item '%s' seems to be invalid.", item)
        if debug_mode:
            logger.debug("Got code %d during initialization", data[0])
        return False, "https://rowhois.com/not-available.png"
    item_thumbnail = item_thumbnail[1]['data'][0]['imageUrl']
    return True, item_thumbnail


async def shutdown() -> None:  # Will error if ran during init
    """Closes the client and cancels all tasks in the loop"""
    for task in asyncio.all_tasks(loop):
        task.cancel()


parser = argparse.ArgumentParser(
    description="RoMonitor - An advanced Roblox item monitoring application to alert you on item updates."  # noqa: E501
)
parser.add_argument("-i", "--item", type=int, required=True, help="The item ID to monitor")
parser.add_argument(  # If 0, mention None
    "-M", "--mention", type=int, default=0, help="Set the user to mention if triggered"
)
parser.add_argument(  # If <=5 ignore
    "-t", "--time", type=int, default=60,
    help="Set the frequency at which RoMonitor checks an item"
)
parser.add_argument(
    "-m", "--minprice", type=int, default=None, help="The minimum price to trigger a notification"
)
parser.add_argument(
    "-r", "--runforever", action="store_true",
    help="Continues monitoring even after an event trigger"
)
args = parser.parse_args()
loop = asyncio.new_event_loop()
logger = logging.getLogger("RoMonitor")
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%m-%d-%y %H:%M:%S'
)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.info("Initializing RoMonitor...")
item = args.item
mention = args.mention
with open('config.json', 'r', encoding='utf-8') as configfile:
    config = json.load(configfile)
    roblosecurity = config['roblosecurity']
    webhookURL = config['webhook']
    debug_mode = config['debug']
    for key in [config, roblosecurity, webhookURL, debug_mode]:
        if key == "":
            raise KeyError

x_token = Token(datetime.datetime.now(), None)  # Must be init here to avoid unbound error
if not loop.run_until_complete(validate_cookie()):
    logging.fatal("Invalid roblosecurity cookie provided")
    sys.exit(1)
itemValid, thumbnail = loop.run_until_complete(validate_item())
if not itemValid:
    logger.fatal("Invalid item provided!")
    sys.exit(1)
try:
    main_item = loop.run_until_complete(get_item(item))
    if main_item is None:
        logger.error("Item [\033[94m%s\033[0m] is not a valid item.", item)
        sys.exit(1)
    loop.run_until_complete(send_webhook(
        f"RoMonitor is now monitoring `{main_item.name}` by `{main_item.creator}`.",
        title=f"{main_item.name}", url=f"https://www.roblox.com/catalog/{item}/"
    ))
    logger.info(
        "Initialized! Now monitoring [\033[94m%s\033[0m] by [\033[94m%s\033[0m]",
        main_item.name, main_item.creator
    )
    # if datetime.datetime.now() - x_token.datetime >= datetime.timedelta(minutes=5):
    #     x_token = await token_renewal()
    # if not x_token.token:
    #     logger.error("Token renewal failed. Account Session Protection enabled?")
    loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(shutdown()))
except KeyboardInterrupt:
    pass
except asyncio.CancelledError:
    pass
logger.info("Exiting RoMonitor. Have a nice day!")
sys.exit(0)
