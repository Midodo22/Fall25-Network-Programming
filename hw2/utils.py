import struct
import asyncio
import hashlib

import logging
import json
import random
import config
from config import tetris_server as tetris_server

"""
General utils
"""
async def send_message(writer, msg):
    try:
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
        logging.info(f"Sent message: {msg}")
    except Exception as e:
        logging.error(f"Failed to send message: {e}")


async def send_command(writer, command, params):
    try:
        msg = build_command(command, params)
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


def build_response(status, message, params=""):
    return json.dumps({"status": status, "message": message, "params": params}) + '\n'


def build_command(command, params):
    return json.dumps({"status": "command", "command": command.upper(), "params": params}) + '\n'


async def unpack_message(reader):
    try:
        header = await reader.readexactly(4)
        (length,) = struct.unpack('!I', header)

        # Ignore oversized body and report error
        if length > config.MAX_MSG_SIZE:
            logging.error(f"Received oversized message ({length} bytes)")
            await reader.readexactly(length)
            return None

        # Read the message body
        body = await reader.readexactly(length)
        try:
            return body.decode('utf-8')
        except json.JSONDecodeError:
            logging.error("Invalid message format")

    except asyncio.IncompleteReadError:
        logging.error("Connection closed unexpectedly")
        return None
    
    except Exception as e:
        logging.error(f"Failed to receive message: {e}")
        return None


"""
User registration
"""
def hash(p):
    pswd = hashlib.sha256(p.encode()).hexdigest()
    return str(pswd)


async def handle_login(params, reader, writer):
    if len(params) != 2:
        await send_message(writer, build_response("error", "Invalid LOGIN command"))
        return
    username, password = params

    async with tetris_server.user_lock:
        if username not in tetris_server.users:
            await send_message(writer, build_response("error", "User not registered."))
            return
        else:
            hashed_pswd = hash(password)
            if tetris_server.users[username] != hashed_pswd:
                await send_message(writer, build_response("error", "Password incorrect."))
            else:  # User logs in
                async with tetris_server.online_users_lock:
                    if username in tetris_server.online_users:
                        await send_message(writer, build_response("error", "User already logged in"))
                        logging.warning(f"User {username} tried to login repeatedly.")
                        return
                    else:
                        client_ip, client_port = writer.get_extra_info('peername')
                        tetris_server.online_users[username] = {
                            "reader": reader,
                            "writer": writer,
                            "status": "idle",
                            "ip": client_ip,
                            "port": client_port  # TCP port
                        }
                await send_message(writer, build_response("success", "LOGIN_SUCCESS"))
                await send_lobby_info(writer)
                async with tetris_server.online_users_lock:
                    users_data = [
                        {"username": user, "status": info["status"]}
                        for user, info in tetris_server.online_users.items()
                    ]
                online_users_message = {
                    "status": "update",
                    "type": "online_users",
                    "data": users_data
                }
                logging.info(f"User {username} logged in successfully.")


async def handle_logout(username, writer):
    user_removed = False
    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            del tetris_server.online_users[username]
            user_removed = True

    if user_removed:
        try:
            await send_message(writer, build_response("success", "LOGOUT_SUCCESS"))
        except Exception as e:
            logging.error(f"Failed to send logout success message to {username}: {e}")

        try:
            # Update online user list
            async with tetris_server.online_users_lock:
                users_data = [
                    {"username": user, "status": info["status"]}
                    for user, info in tetris_server.online_users.items()
                ]

            online_users_message = {
                "status": "update",
                "type": "online_users",
                "data": users_data
            }
            logging.info(f"User {username} logged out.")
        except Exception as e:
            logging.error(f"Failed to broadcast updated online users list after logout: {e}")

        async with tetris_server.rooms_lock:
            remove_room = []
            for room in tetris_server.rooms:
                if tetris_server.rooms[room]['creator'] == username:
                    remove_room.append(room)
            for room in remove_room:
                logging.info(f"Removed room {room}")
                del tetris_server.rooms[room]
    else:
        await send_message(writer, build_response("error", "User not logged in."))


async def send_lobby_info(writer):
    try:
        async with tetris_server.online_users_lock:
            users_data = [
                {"username": user, "status": info["status"]}
                for user, info in tetris_server.online_users.items()
            ]

        async with tetris_server.rooms_lock:
            public_rooms_data = [
                {
                    "room_id": r_id,
                    "creator": room["creator"],
                    "status": room["status"]
                }
                for r_id, room in tetris_server.rooms.items()
            ]

        status_message = "------ List of Rooms ------\n"
        if not public_rooms_data:
            status_message += "There are no rooms available :(\n"
        else:
            for room in public_rooms_data:
                status_message += f"Room ID: {room['room_id']} | Creator: {room['creator']} | Status: {room['status']}\n"

        status_message += "----------------------------\n\n"
        status_message += "--- List of Online Users ---\n"
        if not users_data:
            status_message += "No users are online :(\n"
        else:
            for user in users_data:
                status_message += f"User: {user['username']} - Status: {user['status']}\n"
        status_message += "----------------------------\nInput command: "

        status_response = {
            "status": "status",
            "message": status_message
        }
        await send_message(writer, json.dumps(status_response) + '\n')
        logging.info("Sending SHOW_STATUS message to user")
    except Exception as e:
        logging.error(f"Failed to send lobby info: {e}")


def get_port():
    return random.randint(config.P2P_PORT_RANGE[0], config.P2P_PORT_RANGE[1])


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
