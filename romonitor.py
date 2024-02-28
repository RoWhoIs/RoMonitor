"""
RoMonitor - An item monitoring tool

Developed by RoWhoIs

CONTRIBUTORS:
https://github.com/aut-mn
"""
import asyncio, aiohttp, argparse, signal, datetime, json
from typing import Optional, Any, Union

class Item:
    def __init__(self, name: str, forsale: bool, price: Optional[Union[int, str, None]], description: str, creator: str, updated: str, islimited: bool, remaining: Optional[int], thumbnail: Optional[str]):
        self.name = name
        self.forsale = forsale
        self.price = price
        self.description = description
        self.creator = creator
        self.updated = updated
        self.islimited = islimited
        self.remaining = remaining
        self.thumbnail = thumbnail

class Token:
    """Used for dynamically refreshing tokens"""
    def __init__(self, token):
        self.datetime = datetime.datetime.now()
        self.token = token


async def validate_cookie() -> bool:
    """Validates the roblosecurity value from config.json. Returns True if valid."""
    try:
        if debugMode: await logs.debug("Validating roblosecurity cookie")
        async with aiohttp.ClientSession(cookies={".roblosecurity": roblosecurity}) as main_session:
            async with main_session.get("https://users.roblox.com/v1/users/authenticated") as resp:
                if resp.status == 200:
                    await token_renewal() # Initialize the token
                    return True
                await logs.error("Invalid ROBLOSECURITY cookie. RoModules will not function properly for limiteds.")
        return False
    except aiohttp.client_exceptions.ClientConnectorError:
        await logs.fatal("Can't connect to the Roblox servers! Are you offline?")
        return False
    except Exception: return False

async def token_renewal() -> None: # Non-global var so RoMonitor gets the latest token per request
    """Updates the x-csrf-token"""
    global xToken
    try:
        if debugMode: await logs.debug("Renewing X-CSRF Token")
        async with aiohttp.ClientSession(cookies={".roblosecurity": roblosecurity}) as session:
            async with session.post("https://auth.roblox.com/v2/logout") as resp:
                if 'x-csrf-token' in resp.headers: xToken = Token(resp.headers['x-csrf-token'])
                elif debugMode: await logs.debug(f"Failed to renew token: {resp.status}")
    except Exception: pass

async def rofetch(url: str, method: str = "get", expectedresponse: int = 200, debugmessage: str = None, **kwargs) -> tuple[int, Any]:
    """Fetches authenticated Roblox URLS. Error handler included. Free Robux not included."""
    try:
        async with aiohttp.ClientSession(cookies={".roblosecurity": roblosecurity}) as session:
            if debugMode and debugmessage: await logs.debug(debugmessage)
            for i in range(5):
                if datetime.datetime.now() - xToken.datetime >= datetime.timedelta(minutes=5): await token_renewal()
                if not xToken.token: await logs.error("Token renewal failed. Account Session Protection enabled?")
                response = await session.request(method, url, headers={"x-csrf-token": xToken.token}, **kwargs)
                if response.status == expectedresponse: return response.status, await response.json()
                elif response.status in [400, 404]: return 404, None
                elif response.status == 403: await token_renewal() # Renew just in case
                await asyncio.sleep(5)
            return response.status, None
    except aiohttp.client_exceptions.ClientConnectorError: await logs.fatal("Can't connect to the Roblox servers! Are you offline?")

async def fetch_resale(item: int) -> Optional[int]:
    """Fetches the lowest resale price for a specified limited"""
    data = await rofetch(f"https://economy.roblox.com/v1/assets/{item}/resellers", debugmessage="Fetching lowest resale price")
    if 'seller' in data[1]['data'][0]: return int(data[1]['data'][0]['price'])
    return None

async def handle_data(data: dict) -> Optional[str]:
    """Handles datatypes. Returns key if it detects a change."""
    global monitoredItem, thumbnail
    if debugMode:
        if monitoredItem.name != "": await logs.debug(f"NAME: {monitoredItem.name} | CREATOR: {monitoredItem.creator}  | UPDATED: {monitoredItem.updated} | SALE: {True if monitoredItem.forsale else True if monitoredItem.islimited else monitoredItem.forsale} | PRICE: {monitoredItem.price} | LIMITED: {monitoredItem.islimited}")
        await logs.debug("Received data, comparing values")
    isLimited = data['IsLimited'] if True else data['IsLimitedUnique']
    robuxPrice = "Free" if data['IsPublicDomain'] else data['PriceInRobux'] if not isLimited else await fetch_resale(data['TargetId'])
    checks = {'Description': monitoredItem.description, 'Updated': monitoredItem.updated, 'Remaining': monitoredItem.remaining, 'IsForSale': monitoredItem.forsale, 'Name': monitoredItem.name}
    returnKey = None
    for key, value in checks.items():
        if data[key] != value: returnKey = key
    if isLimited != monitoredItem.islimited: returnKey = "islimited"
    elif robuxPrice != monitoredItem.price: returnKey = "price"
    if debugMode:
        if returnKey is None: await logs.debug("Item data matched, returning None")
        else: await logs.debug(f"Item data changed, returning key '{returnKey}'")
    monitoredItem = Item(data['Name'], data['IsForSale'], robuxPrice, data['Description'], data['Creator']['Name'], data['Updated'], isLimited, data['Remaining'], thumbnail)
    return returnKey

class AsyncLogCollector:
    """
    Asynchronous logging utility
    Forked from https://github.com/aut-mn/AsyncLogger
    Modified for RoMonitor
    """
    def __init__(self):
        self.log_format = "%(timestamp)s [%(level)s] %(message)s"
        self.log_queue = asyncio.Queue()
        self.log_levels = {'DEBUG': '\033[90mDEBUG\033[0m', 'INFO': '\033[32mINFO\033[0m', 'WARN': '\033[33mWARN\033[0m', 'ERROR': '\033[31mERROR\033[0m', 'FATAL': '\033[31;1mFATAL\033[0m'}
    async def log(self, level, message):
        print(self.log_format % {'timestamp': await self.get_colored_timestamp(), 'level': self.log_levels.get(level, level), 'message': message})
    async def debug(self, message): await self.log('DEBUG', message)
    async def info(self, message): await self.log('INFO', message)
    async def warn(self, message): await self.log('WARN', message)
    async def error(self, message): await self.log('ERROR', message)
    async def fatal(self, message): await self.log('FATAL', message)
    @staticmethod
    async def get_colored_timestamp(): return '\033[90m' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '\033[0m'

async def initialize(item: int) -> bool:
    """Initializes RoMonitor and validates that the item is valid"""
    global monitoredItem, roblosecurity, webhookURL, debugMode, thumbnail
    await logs.info("Initializing RoMonitor...")
    with open('config.json', 'r') as configfile:
        try:
            config = json.load(configfile)
            roblosecurity = config['roblosecurity']
            webhookURL = config['webhook']
            debugMode = config['debug']
            for key in [config, roblosecurity, webhookURL, debugMode]:
                if key == "": raise KeyError
        except json.decoder.JSONDecodeError:
            await logs.fatal("Invalid config.json!")
            return False
        except KeyError:
            await logs.fatal("Missing values from config.json!")
            return False
        except FileNotFoundError:
            await logs.fatal("Missing config.json!")
            return False
        except Exception as e:
            await logs.fatal(f"Encountered an unkown exception: {e}")
            return False
    if not await validate_cookie(): return False
    monitoredItem = Item("", False, None, "", "", "", False, None, None)
    data, thumbnail = await asyncio.gather(rofetch(f"https://economy.roblox.com/v2/assets/{item}/details", debugmessage="Fetching latest item details"), rofetch(f"https://thumbnails.roblox.com/v1/assets?assetIds={item}&returnPolicy=PlaceHolder&size=420x420&format=Png&isCircular=false", debugmessage="Fetching item thumbnail"))
    if data[0] != 200:
        if data[0] == 404: await logs.fatal("The specified item does not exist.")
        else: await logs.fatal(f"Failed to initialize. Item '{item}' seems to be invalid.")
        if debugMode: await logs.debug(f"Got code {data[0]} during initialization")
        return False
    thumbnail = thumbnail[1]['data'][0]['imageUrl'] if thumbnail[0] == 200 else "https://www.robloxians.com/resources/not-available.png" if thumbnail[0] == 403 else "https://www.robloxians.com/resources/not-available.png"
    await handle_data(data[1])
    await send_webhook(f"RoMonitor is now monitoring `{monitoredItem.name}` by `{monitoredItem.creator}`.", title=f"{monitoredItem.name}", url=f"https://www.roblox.com/catalog/{item}/")
    await logs.info(f"Now monitoring [\033[94m{monitoredItem.name}\033[0m] by [\033[94m{monitoredItem.creator}\033[0m]")
    return True

async def send_webhook(message: str, title: Optional[str] = None, url: Optional[str] = None) -> None:
    """Sends a message through the webhook"""
    if debugMode: await logs.debug("Pushing to webhook")
    webhookContents = {"username": "RoMonitor", "avatar_url": "https://robloxians.com/resources/builderman.png", "content": f"<@{mention}>" if mention != 0 else None, "embeds": [{"title": title if title is not None else None, "url": url if url is not None else None, "color": 65293, "description": message, "thumbnail": {"url": thumbnail}}]}
    async with aiohttp.ClientSession() as session: await session.request("POST", webhookURL, json=webhookContents)

async def monitor(item: int, minprice: int = 0, time: int = 60, runforever: bool = False) -> None:
    """Monitors the given item for the specified changes"""
    result, oldPrice = 'price', None # Trigger a check initially to prevent dual-checking if conditions already met
    try:
        while True:
            data = await rofetch(f"https://economy.roblox.com/v2/assets/{item}/details", debugmessage="Fetching latest item data")
            if result == 'price':
                if monitoredItem.price != oldPrice:
                    if monitoredItem.price is not None:
                        if monitoredItem.price == "Free" or monitoredItem.price == 0:
                            await send_webhook(f"`{monitoredItem.name}` is now free!", title=monitoredItem.name, url=f"https://www.roblox.com/catalog/{item}/")
                            await logs.info(f"[\033[94m{monitoredItem.name}\033[0m] is free!")
                            if not runforever: break
                        elif minprice != 0 and minprice >= monitoredItem.price:
                            await send_webhook(f"`{monitoredItem.name}` is below `{minprice}` Robux!\n\n**Curent Price:** `{monitoredItem.price}`\n**Difference:** `{minprice - monitoredItem.price}`", title=monitoredItem.name, url=f"https://www.roblox.com/catalog/{item}/")
                            await logs.info(f"Price of [\033[94m{monitoredItem.name}\033[0m] dropped below [\033[94m{minprice}\033[0m] by [\033[94m{minprice - monitoredItem.price}\033[0m] Robux.")
                            if not runforever: break
                else: oldPrice = monitoredItem.price
            if result == 'forsale':
                await send_webhook(f"`{monitoredItem.name}` is now on sale!\n\n**Price:** `{monitoredItem.price}`", title=monitoredItem.name, url=f"https://www.roblox.com/catalog/{item}/")
                await logs.info(f"[\033[94m{monitoredItem.name}\033[0m] is now on sale for [\033[94m{monitoredItem.price}\033[0m] Robux.")
                if not runforever: break
            if result == 'remaining' and runforever:
                await send_webhook(f"`{monitoredItem.name}` had a copy sold!\n\n**Remaining:** `{monitoredItem.remaining}`", title=monitoredItem.name, url=f"https://www.roblox.com/catalog/{item}/")
                await logs.info(f"[\033[94m{monitoredItem.name}\033[0m] sold a copy and now has [\033[94m{monitoredItem.remaining}\033[0m] copies remaining..")
                if not runforever: break
            result = await handle_data(data[1])
            await asyncio.sleep(time)
    except asyncio.CancelledError: return

async def shutdown(loop) -> None: # Will error if ran during init
    """Closes the client and cancels all tasks in the loop"""
    for task in asyncio.all_tasks(loop): task.cancel()

parser = argparse.ArgumentParser(description="RoMonitor - An advanced Roblox item monitoring application to alert you on item updates.")
parser.add_argument("-i", "--item", type=int, required=True, help="The item ID to monitor")
parser.add_argument("-M", "--mention", type=int, default=0, help="Set the user to mention if triggered") # If 0, mention None
parser.add_argument("-t", "--time", type=int, default=60, help="Set the frequency at which RoMonitor checks an item.") # If <=5 ignore
parser.add_argument("-m", "--minprice", type=int, default=0, help="The minimum price to trigger a notification")
parser.add_argument("-r", "--runforever", action="store_true", help="Continues monitoring even after an event trigger")
args = parser.parse_args()
loop = asyncio.new_event_loop()
logs = AsyncLogCollector()
mention = args.mention
itemValid = loop.run_until_complete(initialize(args.item))
if itemValid:
    try:
        checkTime = args.time if args.time >= 5 else 5
        loop.run_until_complete(monitor(args.item, args.minprice, checkTime, args.runforever))
        loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(shutdown(loop)))
    except KeyboardInterrupt: pass
    except asyncio.CancelledError: pass
    except Exception as e:
        print("Unexpected fatal error occured:", e)
        exit(1)
    asyncio.new_event_loop().run_until_complete(logs.info("Exiting RoMonitor. Have a nice day!"))
    exit(0)
