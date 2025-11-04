import asyncio
import logging
import json
import hashlib

import utils as ut
import config
from config import tetris_server as tetris_server

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    logging.info(f"[DB] Connection from {addr}")
    lobbyserver = None
    try:
        while True:
            data = await reader.readline()
            if not data:
                # Client disconnected
                break
            try:
                message = data.decode().strip()
                if not message:
                    continue
                message_json = json.loads(message)
                command = message_json.get("command", "").upper()
                params = message_json.get("params", [])

                if command == "REGISTER":
                    await db_register(params, writer)

                elif command == "LOGIN":
                    await db_login(params, reader, writer)
                    if len(params) >= 1:
                        username = params[0]

                elif command == "LOGOUT":
                    if username:
                        await db_logout(username, writer)
                        username = None
                    else:
                        await ut.send_message(writer, ut.build_response("error", "Not logged in"))

                elif command == "CREATE_ROOM":
                    if username:
                        await handle_create_room(username, writer)
                    else:
                        await ut.send_message(writer, ut.build_response("error", "Not logged in"))

                elif command == "INVITE_PLAYER":
                    if username:
                        await handle_invite_player(params, username, writer)
                    else:
                        await ut.send_message(writer, ut.build_response("error", "Not logged in"))

                elif command == "GAME_OVER":
                    if username:
                        await handle_game_over(username)
                    else:
                        await ut.send_message(writer, ut.build_response("error", "Not logged in"))
                
                elif command == "SHOW_STATUS":
                    if username:
                        await handle_show_status(writer)
                    else:
                        await ut.send_message(writer, ut.build_response("error", "Not logged in"))
                elif command == "JOIN_ROOM":
                    if username:
                        await handle_join_room(params, username, writer)
                    else:
                        await ut.send_message(writer, ut.build_response("error", "Not logged in"))

                else:
                    await ut.send_message(writer, ut.build_response("error", "Unknown command"))

            except json.JSONDecodeError:
                await ut.send_message(writer, ut.build_response("error", "Invalid message format"))
            except Exception as e:
                logging.error(f"[DB] Error while processing message: {e}")
                await ut.send_message(writer, ut.build_response("error", "Server error"))
    except Exception as e:
        logging.error(f"[DB] Error when processing client at {addr}: {e}")
    finally:
        # Lobby server closed
        if lobbyserver:
            logging.info(f"[DB] Lobby server disconnected")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


"""
User login/out, registration
"""
def hash(p):
    pswd = hashlib.sha256(p.encode()).hexdigest()
    return str(pswd)


async def db_register(params, writer):
    username, password = params
    async with tetris_server.user_lock:
        hashed_pswd = hash(password)
        tetris_server.users[username] = hashed_pswd
        await ut.send_message(writer, ut.build_response("success", "REGISTRATION_SUCCESS", "writer"))
        logging.info(f"[DB] User {username} registered successfully.")

        with open('data.json', 'w') as f:
            json.dump(tetris_server.users, f)
        logging.info(f"[DB] Updated data.json successfully.")


async def db_login(params, reader, writer):
    username, password = params
    async with tetris_server.user_lock:
        hashed_pswd = hash(password)
        if tetris_server.users[username] != hashed_pswd:
            await ut.send_message(writer, ut.build_response("error", "Password incorrect."))
        else:  # User logs in
            async with tetris_server.online_users_lock:
                if username in tetris_server.online_users:
                    await ut.send_message(writer, ut.build_response("error", "User already logged in"))
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
            await ut.send_message(writer, ut.build_response("success", "LOGIN_SUCCESS", [reader, writer]))
            await ut.send_lobby_info(writer)
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


async def handle_show_status(writer):
    try:
        async with tetris_server.online_users_lock:
            users_data = [
                {"username": user, "status": info["status"]}
                for user, info in tetris_server.online_users.items()
            ]

        async with tetris_server.rooms_lock:
            rooms_data = [
                {
                    "room_id": r_id,
                    "creator": room["creator"],
                    "status": room["status"]
                }
                for r_id, room in tetris_server.rooms.items()
            ]

        status_message = "------ List of Rooms ------\n"
        if not rooms_data:
            status_message += "There are no rooms available :(\n"
        else:
            for room in rooms_data:
                status_message += f"Room ID: {room['room_id']} | Creator: {room['creator']} | Status: {room['status']}\n"

        status_message += "----------------------------\n\n"
        status_message += "--- List of Online Users ---\n"
        if not users_data:
            status_message += "No users are online :(\n"
        else:
            for user in users_data:
                status_message += f"User: {user['username']} - Status: {user['status']}\n"
        status_message += "----------------------------\nInput a command: "

        status_response = {
            "status": "status",
            "message": status_message
        }
        await ut.send_message(writer, json.dumps(status_response) + '\n')
        logging.info("[DB] Sending SHOW_STATUS message to user")
    except Exception as e:
        logging.error(f"[DB] Error while processing SHOW_STATUS: {e}")
        await ut.send_message(writer, ut.build_response("error", "Failed to retrieve status"))


async def handle_create_room(params, username, writer):
    if len(params) != 1:
        await ut.send_message(writer, ut.build_response("error", "Invalid CREATE_ROOM command"))
        return
    room_id = ut.get_room_id()
    room_type = params
    
    if room_type not in ['public', 'private']:
        await ut.send_message(writer, ut.build_response("error", "Invalid room type"))
        return

    async with tetris_server.rooms_lock:
        tetris_server.rooms[room_id] = {
            'creator': username,
            'type': room_type,
            'status': 'waiting',
            'players': [username],
        }

    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            tetris_server.online_users[username]["status"] = "in_room"
    await ut.send_message(writer, ut.build_response("success", f"CREATE_ROOM_SUCCESS {room_id}"))
    # Broadcast updated room list for all users to see
    async with tetris_server.rooms_lock:
        room_data = [
            {
                "room_id": r_id,
                "creator": room["creator"],
                "status": room["status"]
            }
            for r_id, room in tetris_server.rooms.items()
            if room["type"] == "public"
        ]
    room_message = {
        "status": "update",
        "data": room_data
    }

    logging.info(f"[DB] User {username} created room {room_id}")
    logging.info(f"[DB] Waiting for another player to join room {room_id}")



async def main():
    # init logger, remove any info from prev startup
    with open('logger.log', 'w'):
        pass

    ut.init_logging()

    server_ = await asyncio.start_server(handle_client, config.HOST, config.DB_PORT)
    addr = server_.sockets[0].getsockname()
    logging.info(f"[DB] Database Server running on {addr}")

    async with server_:
        try:
            await server_.serve_forever()
        except KeyboardInterrupt:
            logging.info("[DB] Received keyboard interrupt, closing server...")
        finally:
            server_.close()
            await server_.wait_closed()
            logging.info("[DB] Database server is closed.")


if __name__ == "__main__":
    asyncio.run(main())
