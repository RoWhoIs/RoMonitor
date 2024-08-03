"""
RoMonitor - An item monitoring tool

Developed by RoWhoIs

CONTRIBUTORS:
https://github.com/aut-mn
"""
import asyncio
import argparse
import datetime
import json
import sys
import logging
import time
import re
from typing import Any, Tuple, List
from dataclasses import dataclass, fields, is_dataclass

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
    updated: datetime.datetime | None
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


def fancy_time(initstamp: Any) -> datetime.datetime | None:
    """Converts a datetime string to a datetime object."""
    if isinstance(initstamp, (int, float)):
        return datetime.datetime.fromtimestamp(initstamp, tz=datetime.timezone.utc)
    if isinstance(initstamp, str):
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?Z", initstamp)
        if match:
            year, month, day, hour, minute, second, _ = match.groups()
            return datetime.datetime(
                int(year), int(month), int(day), int(hour), int(minute), int(second),
                tzinfo=datetime.timezone.utc
            )
    return None


def compare(obj1, obj2, parent_key='') -> List[str]:
    """Compares two dataclasses and returns a list of changed keys"""
    changes = []

    def key_path(accesskey):
        return f"{parent_key}.{accesskey}" if parent_key else accesskey
    for field in fields(obj1):
        accesskey = field.name
        kpath = key_path(accesskey)
        value1 = getattr(obj1, accesskey)
        value2 = getattr(obj2, accesskey)
        if is_dataclass(value1) and is_dataclass(value2):
            changes.extend(compare(value1, value2, kpath))
        elif value1 != value2:
            logger.debug("Diff '%s': '%s' -> '%s'", kpath, value1, value2)
            changes.append(kpath)
    return changes


async def token_renewal() -> Token:
    """Updates the x-csrf-token"""
    try:
        logger.debug("%s X-CSRF Token", "Renewing" if x_token.token else "Fetching")
        async with aiohttp.ClientSession(cookies={".roblosecurity": roblosecurity}) as session:
            async with session.post("https://auth.roblox.com/v2/logout") as resp:
                if 'x-csrf-token' not in resp.headers:
                    logger.debug("Failed to renew token: %d", resp.status)
        return Token(datetime.datetime.now(), resp.headers.get('x-csrf-token', None))
    except Exception:  # noqa: W0718
        return Token(datetime.datetime.now(), None)


async def validate_cookie() -> bool:
    """Validates the roblosecurity value from config.json. Returns True if valid."""
    global x_token  # noqa: W0603
    try:
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
    global x_token  # noqa: W0603
    try:
        async with aiohttp.ClientSession(cookies={".roblosecurity": roblosecurity}) as session:
            if debugmessage:
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
            forsale=data[1]['IsForSale'],
            price=data[1]['PriceInRobux'],
            resaleprice=None,
            limited=data[1]['IsLimited'],
            limitedu=data[1]['IsLimitedUnique'],
            collectible=data[1]['CollectiblesItemDetails']['IsLimited'] if data[1].get('CollectiblesItemDetails') is not None else False,  # noqa: E501
            remaining=data[1]['Remaining'] if data[1].get('Remaining') is not None else None
        )
        if economy_data.collectible or economy_data.limited or economy_data.limitedu:
            resale = await fetch_resale(asset)
            economy_data.resaleprice = resale
        return_item = Item(
            id=asset, name=data[1]['Name'], economics=economy_data,
            description=data[1]['Description'], creator=data[1]['Creator']['Name'],
            updated=fancy_time(data[1]['Updated']),
        )
        if data[0] != 200:
            logger.error("Failed to fetch item data: %d", data[0])
            return None
        return return_item
    except asyncio.CancelledError:
        return None


async def send_webhook(message: str, title: str | None = None, url: str | None = None) -> None:
    """Sends a message through the webhook"""
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
            debugmessage="Validating asset"
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
        logger.debug("Got code %d during initialization", data[0])
        return False, "https://rowhois.com/not-available.png"
    item_thumbnail = item_thumbnail[1]['data'][0]['imageUrl']
    return True, item_thumbnail


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
    if not config['debug']:
        logger.setLevel(logging.INFO)
    for key in [config, roblosecurity, webhookURL]:
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

main_item = loop.run_until_complete(get_item(item))
if main_item is None:
    logger.error("Item [\033[94m%s\033[0m] is not a valid item.", item)
    sys.exit(1)

loop.run_until_complete(send_webhook(
    f"RoMonitor is now monitoring `{main_item.name}` by `{main_item.creator}`",
    title=f"{main_item.name}", url=f"https://www.roblox.com/catalog/{item}/"
))
logger.info(
    "Initialized! Now monitoring [\033[94m%s\033[0m] by [\033[94m%s\033[0m]",
    main_item.name, main_item.creator
)

# Here's the bread and butter of the program if you will
try:
    while True:
        time.sleep(args.time + 5 if args.time <= 5 else args.time)
        if datetime.datetime.now() - x_token.datetime >= datetime.timedelta(minutes=5):
            x_token = loop.run_until_complete(token_renewal())
            if not x_token.token:
                logger.error("Token renewal failed. Account Session Protection enabled?")
                continue
        if main_item is None:
            raise ValueError("main_item is None")
        old_item = main_item
        # ^ Could result in unbound error if main_item is None but shouldn't happen
        main_item = loop.run_until_complete(get_item(item))
        if main_item is not None:
            CHANGES = compare(old_item, main_item)
            if CHANGES:
                if  'economics.price' in CHANGES:
                    loop.run_until_complete(
                        send_webhook(
                            title=f"{old_item.name}",
                            url=f"https://www.roblox.com/catalog/{main_item.id}",
                            message=f"""`{main_item.name}` is now {main_item.economics.price} {'Robux' if main_item.economics.price != None else 'Free'}!
                            **Old price**: `{old_item.economics.price}`
                            **New price**: `{main_item.economics.price}`
                            """  # noqa: E501
                        )
                    )
                if args.runforever is False:
                    break
            else:
                main_item = old_item
except KeyboardInterrupt:
    pass
except asyncio.CancelledError:
    pass

logger.info("Exiting RoMonitor. Have a nice day!")
for task in asyncio.all_tasks(loop):
    task.cancel()
sys.exit(0)
