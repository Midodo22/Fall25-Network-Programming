import asyncio
import json

# HOST = '140.113.17.13'
HOST = '192.168.56.1'
# WSL
# HOST = '172.31.158.104'
# HOST = '127.0.0.1'

PORT = 52273
DB_PORT = 52274
GAME_PORT_RANGE = (52275, 52325)
GAME_HOST = HOST
LOG_FILE = 'logger.log'
SNAPSHOT_LOG_FILE = 'snapshots.log'
DB_FILE = 'data.json'

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
        self.rooms_lock = asyncio.Lock()
        self.user_lock = asyncio.Lock()
        self.db_lock = asyncio.Lock()
        self.game_servers = {}
        self.game_servers_lock = asyncio.Lock()

        try:
            with open('data.json', 'r') as f:
                data = json.load(f)
            
            self.users = data["users"]
            self.rooms = data["rooms"]

        except:
            self.users = {}
            self.rooms = {}
        
tetris_server = server()
