"""
RoMonitor - An item monitoring tool

Developed by RoWhoIs

CONTRIBUTORS:
https://github.com/aut-mn
"""
import asyncio, aiohttp, argparse, signal, datetime, json

class Item:
    def __init__(self, name: str, forsale: bool, price: int | None, description:str, creator: str, updated: str, islimited: bool, remaining: int | None):
        self.name = name
        self.forsale = forsale
        self.price = price
        self.description = description
        self.creator = creator
        self.updated = updated
        self.islimited = islimited
        self.remaining = remaining

async def validate_cookie() -> bool:
    """Validates the roblosecurity value from config.json"""
    if debugMode: await logs.debug("Validating roblosecurity cookie")
    async with aiohttp.ClientSession(cookies={".roblosecurity": roblosecurity}) as main_session:
        async with main_session.get("https://users.roblox.com/v1/users/authenticated") as resp:
            if resp.status == 200: return True
            await logs.error("Invalid ROBLOSECURITY cookie. RoModules will not function properly for limiteds.")
            return False

async def token_renewal() -> str | None: # Non-global var so RoMonitor gets the latest token per request
    """Renews the X-CSRF token for use in gathering resale data for limiteds"""
    if debugMode: await logs.debug("Gathering X-CSRF token")
    async with aiohttp.ClientSession(cookies={".roblosecurity": roblosecurity}) as session:
        async with session.post("https://auth.roblox.com/v2/logout") as resp:
            if 'x-csrf-token' in resp.headers: return resp.headers['x-csrf-token']

async def fetch_resale(item: int) -> int | None:
    """Fetches the lowest resale price for a specified limited"""
    retries = 10
    while retries > 0:
        if debugMode: await logs.debug("Fetching lowest resale price")
        async with aiohttp.ClientSession() as session:
            x_csrf_token = await token_renewal()
            if not x_csrf_token: await logs.error("Token renewal failed. Account Session Protection enabled?")
            data = await session.get(f"https://economy.roblox.com/v1/assets/{item}/resellers", headers={"x-csrf-token": x_csrf_token}, cookies={".roblosecurity": roblosecurity})
            if data.status == 200:
                data = await data.json()
                if 'seller' in data['data'][0]: return int(data['data'][0]['price'])
            else:
                retries -= 1
                await asyncio.sleep(5)
                if debugMode: await logs.debug(f"Got code {data.status} for fetch_resale. Retries left: {retries}")
    return None

async def handle_data(data: dict) -> str | None:
    """Handles datatypes. Returns key if it detects a change."""
    global monitoredItem
    if debugMode:
        if monitoredItem.name != "": await logs.debug(f"NAME: {monitoredItem.name} | CREATOR: {monitoredItem.creator}  | UPDATED: {monitoredItem.updated} | SALE: {monitoredItem.forsale} | PRICE: {monitoredItem.price} | LIMITED: {monitoredItem.islimited}")
        await logs.debug("Received data, comparing values")
    isLimited = data['IsLimited'] if True else data['IsLimitedUnique']
    robuxPrice = data['PriceInRobux'] if not isLimited else await fetch_resale(data['TargetId'])
    checks = {
        'Description': monitoredItem.description,
        'Updated': monitoredItem.updated,
        'Remaining': monitoredItem.remaining,
        'IsForSale': monitoredItem.forsale,
    }
    returnKey = None
    for key, value in checks.items():
        if data[key] != value: returnKey = key
    if isLimited != monitoredItem.islimited: returnKey = "islimited"
    elif robuxPrice != monitoredItem.price: returnKey = "price"
    if debugMode:
        if returnKey is None: await logs.debug("Item data matched, returning None")
        else: await logs.debug(f"Item data changed, returning key '{returnKey}'")
    monitoredItem = Item(data['Name'], data['IsForSale'], robuxPrice, data['Description'], data['Creator']['Name'], data['Updated'], isLimited, data['Remaining'])
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
        self.log_levels = {'DEBUG': '\033[90mDEBUG\033[0m', 'INFO': '\033[32mINFO\033[0m','WARN': '\033[33mWARN\033[0m','ERROR': '\033[31mERROR\033[0m','FATAL': '\033[31;1mFATAL\033[0m'}
    async def log(self, level, message):
        timestamp = await self.get_colored_timestamp()
        print(self.log_format % {'timestamp': timestamp, 'level': self.log_levels.get(level, level), 'message': message})

    async def debug(self, message): await self.log('DEBUG', message)
    async def info(self, message): await self.log('INFO', message)
    async def warn(self, message): await self.log('WARN', message)
    async def error(self, message): await self.log('ERROR', message)
    async def fatal(self, message): await self.log('FATAL', message)
    async def get_colored_timestamp(self): return '\033[90m' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '\033[0m'

logs = AsyncLogCollector()

async def initialize(item: int) -> bool:
    """Initializes RoMonitor and validates that the item is valid"""
    global monitoredItem, roblosecurity, webhookURL, debugMode
    await logs.info("Initializing RoMonitor...")
    with open('config.json', 'r') as configfile:
        try:
            config = json.load(configfile)
            roblosecurity = config['roblosecurity']
            webhookURL = config['webhook']
            debugMode = config['debug']
        except json.decoder.JSONDecodeError:
            await logs.fatal("Invalid config.json!")
            return False
        except KeyError: # Theoretically both values can be passed as blank strings
            await logs.fatal("Missing values from config.json!")
            return False
        except FileNotFoundError:
            await logs.fatal("Missing config.json!")
            return False
        except Exception as e:
            await logs.fatal(f"Encountered an unkown exception: {e}")
            return False
    monitoredItem = Item("", False, None, "", "", "", False, None)
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://economy.roblox.com/v2/assets/{item}/details") as response:
            if response.status != 200:
                if response.status in [404, 400]: await logs.fatal("The specified item does not exist.")
                if response.status == 429: await logs.fatal("You're being rate limited. Please try again later.")
                else: await logs.fatal(f"Failed to initialize. Item {item} might not be valid.")
                return False
            else: await handle_data(await response.json()) # Will return true on init because we fed it dummy data
    await logs.info(f"Now monitoring [\033[94m{monitoredItem.name}\033[0m] by [\033[94m{monitoredItem.creator}\033[0m]")
    return True

async def send_webhook(message: str, title: str | None = None, url: str | None = None) -> None:
    """Sends a message through the webhook"""
    webhookContents = {"username": "RoMonitor", "avatar_url": "https://robloxians.com/resources/bkg-blur.png","content": f"<@{mention}>","embeds": [{"color": 923269,"description": message}]}
    aiohttp.request("POST", webhook, json=webhookContents)

async def monitor(item: int, mention: int | None = None, minprice: int = 0, time: int = 60, trackall: bool = False, runforever:bool = False) -> None:
    """Monitors the given item for the specified changes"""
    firstTry = True
    try:
        while True:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://economy.roblox.com/v2/assets/{item}/details") as response:
                    if response.status == 200:
                        data = await response.json()
                        result = await handle_data(data)
                        if not firstTry:
                            if minprice != 0 and monitoredItem.price >= minprice: await send_webhook(f"{monitoredItem.name} is below {minprice} Robux!", title=monitoredItem.name)
                            if result is not None and runforever == False: break
                        else: firstTry = True
                    elif response.status == 429:
                        if debugMode: await logs.debug("Recieved 429. Waiting before retrying")
                        await asyncio.sleep(5)
                    else: await logs.error("Failed to retrieve item data.")
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
parser.add_argument("-a", "--allchanges", action="store_true", help="Triggers notifications for all changes to the item, overrides minprice")
parser.add_argument("-r", "--runforever", action="store_true", help="Continues monitoring even after an event trigger")
args = parser.parse_args()
loop = asyncio.new_event_loop()
itemValid = loop.run_until_complete(initialize(args.item))
if itemValid:
    try:
        checkTime = args.time if args.time >= 5 else 5
        loop.run_until_complete(monitor(args.item, args.mention, args.minprice, checkTime, args.allchanges, args.runforever))
        loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(shutdown(loop)))
    except KeyboardInterrupt: pass
    asyncio.new_event_loop().run_until_complete(logs.info("Exiting RoMonitor. Have a nice day!"))
    exit(1)
