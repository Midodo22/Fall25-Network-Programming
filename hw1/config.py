import asyncio
import json

HOST = '140.113.17.13'
# HOST = '192.168.56.1'
PORT = 52273
LOG_FILE = 'server.log'

UDP_PORT = 12000   # >10000
UDP_BROADCAST_RANGE = range(12000, 12100)

P2P_PORT_RANGE = (63042, 63142)
available_ports = {}
for i in range(63042, 63142 + 1):
    available_ports[i] = 1


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
        
server_data = server()