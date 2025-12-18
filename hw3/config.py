import asyncio
import json
import copy

# HOST = '140.113.17.13'
# HOST = '192.168.56.1'
# WSL
HOST = '172.31.158.104'
# HOST = '127.0.0.1'

PORT = 52273
DB_PORT = 52274
GAME_PORT_RANGE = (52275, 52325)
GAME_HOST = HOST
LOG_FILE = 'logger.log'
SNAPSHOT_LOG_FILE = 'snapshots.log'
DB_FILE = 'data.json'
GAMES_FILE = 'games.json'

DEFAULT_DB_STRUCTURE = {
    "users": {},
    "online_users": {},
    "rooms": {},
    "game_devs": {},
    "game_dev_online_users": {},
    "game_dev_rooms": {},
    "game_reviews": {}
}

P2P_PORT_RANGE = (63042, 63142)
available_ports = {}
for i in range(63042, 63142 + 1):
    available_ports[i] = 1

MAX_MSG_SIZE = 65536

id_count = 1

target_lock = asyncio.Lock()
targets = {
    "template":{
        "writer": None,
        "reader": None
    }
}

class server:
    def __init__(self):
        self.online_users = {}
        self.online_users_lock = asyncio.Lock()
        self.dev_online_users = {}
        self.dev_online_users_lock = asyncio.Lock()
        self.rooms_lock = asyncio.Lock()
        self.dev_rooms_lock = asyncio.Lock()
        self.user_lock = asyncio.Lock()
        self.dev_user_lock = asyncio.Lock()
        self.db_lock = asyncio.Lock()
        self.dev_db_lock = self.db_lock
        self.game_servers = {}
        self.game_servers_lock = asyncio.Lock()
        self.games = {}
        self.games_lock = asyncio.Lock()
        self.dev_users = {}
        self.dev_rooms = {}
        self.game_reviews = {}
        self.game_reviews_lock = asyncio.Lock()

        data = copy.deepcopy(DEFAULT_DB_STRUCTURE)
        try:
            with open(DB_FILE, 'r') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update(loaded)
        except FileNotFoundError:
            with open(DB_FILE, 'w') as f:
                json.dump(data, f, indent=4)
        except json.JSONDecodeError:
            pass

        self.users = data.get("users", {})
        self.rooms = data.get("rooms", {})
        self.online_users = data.get("online_users", {})
        self.dev_users = data.get("game_devs", {})
        self.dev_rooms = data.get("game_dev_rooms", {})
        self.dev_online_users = data.get("game_dev_online_users", {})
        self.game_reviews = data.get("game_reviews", {})

        try:
            with open(GAMES_FILE, 'r') as f:
                self.games = json.load(f)
        except FileNotFoundError:
            with open(GAMES_FILE, 'w') as f:
                json.dump({}, f, indent=4)
            self.games = {}
        except json.JSONDecodeError:
            self.games = {}
        
tetris_server = server()
