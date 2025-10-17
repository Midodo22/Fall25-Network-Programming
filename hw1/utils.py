import hashlib
import logging
import json
import random
import config
from config import server_data as server

"""
General utils
"""
async def send_message(writer, message):
    try:
        if isinstance(message, dict):
            message = json.dumps(message)
        writer.write(message.encode())
        await writer.drain()
    except Exception as e:
        logging.error(f"Failed to send message: {e}")


async def broadcast(message):
    async with server.online_users_lock:
        writers = [info["writer"] for info in server.online_users.values()]
    for writer in writers:
        await send_message(writer, message)


def build_response(status, message):
    return json.dumps({"status": status, "message": message}) + '\n'


def build_command(command, params):
    return json.dumps({"command": command.upper(), "params": params}) + '\n'


async def send_command(writer, command, params):
    try:
        message = build_command(command, params)
        writer.write(message.encode())
        await writer.drain()
        logging.info(f"Sent command: {command} {' '.join(params)}")
    except Exception as e:
        print(f"Error while sending command: {e}")
        logging.error(f"Error while sending command: {e}")


async def send_lobby_info(writer):
    try:
        async with server.online_users_lock:
            users_data = [
                {"username": user, "status": info["status"]}
                for user, info in server.online_users.items()
            ]

        async with server.rooms_lock:
            public_rooms_data = [
                {
                    "room_id": r_id,
                    "creator": room["creator"],
                    "status": room["status"]
                }
                for r_id, room in server.rooms.items()
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
Manage users and passwords
"""
def hash(p):
    pswd = hashlib.sha256(p.encode()).hexdigest()
    return str(pswd)


async def handle_register(params, writer):
    if len(params) != 2:
        await send_message(writer, build_response("error", "Invalid REGISTER command"))
        return
    username, password = params
    if username in server.users:
        await send_message(writer, build_response("error", "Username exists, please choose a new one."))
        return
    async with server.user_lock:
        hashed_pswd = hash(password)
        server.users[username] = hashed_pswd
        await send_message(writer, build_response("success", "REGISTRATION_SUCCESS"))
        logging.info(f"User {username} registered successfully.")

        with open('userdata.json', 'w') as f:
            json.dump(server.users, f)
        logging.info(f"Updated userdata.json successfully.")


async def handle_login(params, reader, writer):
    if len(params) != 2:
        await send_message(writer, build_response("error", "Invalid LOGIN command"))
        return
    username, password = params

    async with server.user_lock:
        if username not in server.users:
            await send_message(writer, build_response("error", "User not registered."))
            return
        else:
            hashed_pswd = hash(password)
            if server.users[username] != hashed_pswd:
                await send_message(writer, build_response("error", "Password incorrect."))
            else:  # User logs in
                async with server.online_users_lock:
                    if username in server.online_users:
                        await send_message(writer, build_response("error", "User already logged in"))
                        logging.warning(f"User {username} tried to login repeatedly.")
                        return
                    else:
                        client_ip, client_port = writer.get_extra_info('peername')
                        server.online_users[username] = {
                            "reader": reader,
                            "writer": writer,
                            "status": "idle",
                            "ip": client_ip,
                            "port": client_port  # TCP port
                        }
                await send_message(writer, build_response("success", "LOGIN_SUCCESS"))
                await send_lobby_info(writer)
                async with server.online_users_lock:
                    users_data = [
                        {"username": user, "status": info["status"]}
                        for user, info in server.online_users.items()
                    ]
                online_users_message = {
                    "status": "update",
                    "type": "online_users",
                    "data": users_data
                }
                await broadcast(json.dumps(online_users_message) + '\n')
                logging.info(f"User {username} logged in successfully.")


async def handle_logout(username, writer):
    user_removed = False
    async with server.online_users_lock:
        if username in server.online_users:
            del server.online_users[username]
            user_removed = True

    if user_removed:
        try:
            await send_message(writer, build_response("success", "LOGOUT_SUCCESS"))
        except Exception as e:
            logging.error(f"Failed to send logout success message to {username}: {e}")

        try:
            # Update online user list
            async with server.online_users_lock:
                users_data = [
                    {"username": user, "status": info["status"]}
                    for user, info in server.online_users.items()
                ]

            online_users_message = {
                "status": "update",
                "type": "online_users",
                "data": users_data
            }
            await broadcast(json.dumps(online_users_message) + '\n')
            logging.info(f"User {username} logged out.")
        except Exception as e:
            logging.error(f"Failed to broadcast updated online users list after logout: {e}")

        async with server.rooms_lock:
            remove_room = []
            for room in server.rooms:
                if server.rooms[room]['creator'] == username:
                    remove_room.append(room)
            for room in remove_room:
                logging.info(f"Removed room {room}")
                del server.rooms[room]
    else:
        await send_message(writer, build_response("error", "User not logged in."))


"""
Manage logger
"""


def init_logging():
    logging.basicConfig(level=logging.INFO, filename="logger.log", filemode="a",
                        format='%(asctime)s [%(levelname)s] %(message)s',
                        datefmt='%Y/%m/%d %H:%M:%S')
