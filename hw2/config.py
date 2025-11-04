import asyncio
import json

# HOST = '140.113.17.13'
HOST = '192.168.56.1'
PORT = 52273
DB_PORT = 52274
LOG_FILE = 'server.log'

P2P_PORT_RANGE = (63042, 63142)
available_ports = {}
for i in range(63042, 63142 + 1):
    available_ports[i] = 1

MAX_MSG_SIZE = 65536

class server:
    def __init__(self):
        self.online_users = {}
        self.online_users_lock = asyncio.Lock()
        self.rooms = {}
        self.rooms_lock = asyncio.Lock()
        try:
            with open('userdata.json', 'r') as f:
                self.users = json.load(f)
        except:
            self.users = {}
        self.user_lock = asyncio.Lock()
        self.db_lock = asyncio.Lock()
        
tetris_server = server()