import struct
import asyncio
import hashlib

import logging
import json
import random
import config
from config import tetris_server as tetris_server

_snapshot_logger = logging.getLogger("snapshot")

"""
General utils
"""
async def send_message(writer, msg):
    try:
        log_payload = msg
        if isinstance(msg, dict):
            msg = json.dumps(msg)
        message = msg.encode('utf-8')
        length = len(message)
        
        # If message too long, log error
        if length > config.MAX_MSG_SIZE:
            logging.error(f"Message length {length} bytes exceeds {config.MAX_MSG_SIZE}")
            return
        
        # Format message 
        # [4-byte length (uint32, network byte order)] [body: length bytes (custom format)]
        header = struct.pack('!I', length)
        writer.write(header + message)
        
        await writer.drain()
        
        parsed_payload = None
        if isinstance(log_payload, dict):
            parsed_payload = log_payload
        else:
            try:
                parsed_payload = json.loads(log_payload)
            except Exception:
                parsed_payload = None
        
        if isinstance(parsed_payload, dict) and parsed_payload.get("type") == "SNAPSHOT":
            _snapshot_logger.info(msg)
        else:
            logging.info(f"Sent message: {msg}")
    except Exception as e:
        logging.error(f"Failed to send message: {e}")


async def send_command(sender, writer, command, params):
    try:
        msg = build_command(sender, command, params)
        message = msg.encode('utf-8')
        length = len(message)
        
        # If message too long, log error
        if length > config.MAX_MSG_SIZE:
            logging.error(f"Message length {length} bytes exceeds {config.MAX_MSG_SIZE}")
            return
        
        # Format message 
        # [4-byte length (uint32, network byte order)] [body: length bytes (custom format)]
        header = struct.pack('!I', length)
        writer.write(header + message)
        
        await writer.drain()
        logging.info(f"Sent command: {command} {' '.join(params)}")
    except Exception as e:
        print(f"Error while sending command: {e}")
        logging.error(f"Error while sending command: {e}")


def build_response(sender, status, message, params=[]):
    return json.dumps({"sender": sender, "status": status, "message": message, "params": params}) + '\n'


def build_command(sender, command, params):
    return json.dumps({"sender": sender, "status": "command", "command": command.upper(), "params": params}) + '\n'


async def unpack_message(reader):
    try:
        header = await reader.readexactly(4)
        (length,) = struct.unpack('!I', header)

        # Ignore oversized body and report error
        if length > config.MAX_MSG_SIZE:
            logging.warning(f"Received oversized message ({length} bytes)")
            await reader.readexactly(length)
            return None

        body = await reader.readexactly(length)
        return body.decode('utf-8')

    except asyncio.IncompleteReadError:
        # Normal disconnection
        logging.info("[Network] Connection closed by peer")
        return None

    except Exception as e:
        logging.error(f"[Network] Failed to receive message: {e}")
        return None


"""
General utilities
"""
def hash(p):
    pswd = hashlib.sha256(p.encode()).hexdigest()
    return str(pswd)

def get_port():
    return random.randint(config.P2P_PORT_RANGE[0], config.P2P_PORT_RANGE[1])


def get_game_port():
    return random.randint(config.GAME_PORT_RANGE[0], config.GAME_PORT_RANGE[1])


def get_room_id():
    id = ''.join(str(random.randint(0, 9)) for x in range(6))
    return id


"""
Manage logger
"""
def init_logging():
    logging.basicConfig(level=logging.INFO, filename=config.LOG_FILE, filemode="a",
                        format='%(asctime)s [%(levelname)s] %(message)s',
                        datefmt='%Y/%m/%d %H:%M:%S')
    snapshot_logger = logging.getLogger("snapshot")
    if not snapshot_logger.handlers:
        handler = logging.FileHandler(config.SNAPSHOT_LOG_FILE, mode="a")
        handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        snapshot_logger.addHandler(handler)
    snapshot_logger.setLevel(logging.INFO)
    snapshot_logger.propagate = False
