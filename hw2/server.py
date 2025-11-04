import asyncio
import logging
import json
import utils as ut
import config
from config import tetris_server as tetris_server


async def handle_client(reader, writer, db_reader, db_writer):
    addr = writer.get_extra_info('peername')
    logging.info(f"Connection from {addr}")
    username = None
    try:
        while True:
            message = await ut.unpack_message(reader)
            if not message:
                # Client disconnected
                break
            try:
                message_json = json.loads(message)
                status = message_json.get("status")
                
                # db messages starts with status
                if status == "command":
                    command = message_json.get("command", "").upper()
                    params = message_json.get("params", [])

                    if command == "REGISTER":
                        await handle_register(params, writer, db_reader, db_writer)

                    elif command == "LOGIN":
                        await handle_login(params, reader, writer, db_reader, db_writer)
                        if len(params) >= 1:
                            username = params[0]

                    elif command == "LOGOUT":
                        if username:
                            await handle_logout(username, writer, db_reader, db_writer)
                            username = None
                        else:
                            await ut.send_message(writer, ut.build_response("error", "Not logged in"))

                    elif command == "CREATE_ROOM":
                        if username:
                            await handle_create_room(username, writer, db_reader, db_writer)
                        else:
                            await ut.send_message(writer, ut.build_response("error", "Not logged in"))

                    elif command == "INVITE_PLAYER":
                        if username:
                            await handle_invite_player(params, username, writer, db_reader, db_writer)
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
                
                elif status == "success":
                    msg = message_json.get("message", "")
                    if msg.startswith("REGISTRATION_SUCCESS"):
                        params = message_json.get("params", "")
                        client_reader, client_writer = params
                        await ut.send_message(client_writer, ut.build_response("success", "REGISTRATION_SUCCESS"))
                    elif msg.startswith("LOGIN_SUCCESS"):
                        params = message_json.get("params", "")
                        client_reader, client_writer = params
                        await ut.send_message(client_writer, ut.build_response("success", "LOGIN_SUCCESS"))
                    elif msg.startswith("LOGOUT_SUCCESS"):
                        print("\nYou have logged out successfully.")
                        logged_in.value = False
                    elif msg.startswith("CREATE_ROOM_SUCCESS"):
                        parts = msg.split()
                        room_id = parts[1]
                        print(f"\nRoom successfully created. The room ID is {room_id}.\n")
                    elif msg.startswith("JOIN_ROOM_SUCCESS"):
                        parts = msg.split()
                        room_id = parts[1]
                        print(f"\nSuccessfully joined room {room_id}.\n")

                elif status == "error":
                    print(f"\nError: {msg}\n")
                    
                elif status == "invite_declined":
                    sender = message_json.get("from")
                    room_id = message_json.get("room_id")
                    print(f"\nUser {sender} has declined your invite to room {room_id}.")
                    logging.info(f"User {sender} declined joining {room_id}.")

                elif status == "update":
                    update_type = message_json.get("type")
                    if update_type == "online_users":
                        online_users = message_json.get("data", [])
                    elif update_type == "room_status":
                        room_id = message_json.get("room_id")
                        updated_status = message_json.get("status")
                        print(f"\nRoom {room_id} status updated as {updated_status}")
                
            except json.JSONDecodeError:
                await ut.send_message(writer, ut.build_response("error", "Invalid message format"))
            
            except Exception as e:
                logging.error(f"Error while processing message: {e}")
                await ut.send_message(writer, ut.build_response("error", "Server error"))
    except Exception as e:
        logging.error(f"Error when processing client at {addr}: {e}")
    finally:
        if username:
            user_removed = False
            async with tetris_server.online_users_lock:
                if username in tetris_server.online_users:
                    del tetris_server.online_users[username]
                    user_removed = True
            if user_removed:
                try:
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
                    logging.info(f"User disconnected: {username}")

                    async with tetris_server.rooms_lock:
                        remove_room = []
                        for room in tetris_server.rooms:
                            if tetris_server.rooms[room]['creator'] == username:
                                remove_room.append(room)
                        for room in remove_room:
                            logging.info(f"Removed room {room}")
                            del tetris_server.rooms[room]

                except Exception as e:
                    logging.error(f"Error when processing user disconnection: {e}")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


"""
User-related
"""
async def handle_register(params, writer, db_reader, db_writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("error", "Invalid REGISTER command"))
        return
    
    username, password = params
    if username in tetris_server.users:
        await ut.send_message(writer, ut.build_response("error", "Username exists, please choose a new one."))
        return
    
    await ut.send_command(db_writer, "REGISTER", params)


async def handle_login(params, reader, writer, db_reader, db_writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("error", "Invalid LOGIN command"))
        return
    username, password = params

    async with tetris_server.user_lock:
        if username not in tetris_server.users:
            await ut.send_message(writer, ut.build_response("error", "User not registered."))
            return
        else:
            # Db server handles anything database-related
            await ut.send_command(db_writer, "LOGIN", params)


async def handle_logout(username, writer):
    user_removed = False
    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            del tetris_server.online_users[username]
            user_removed = True

    if user_removed:
        try:
            await ut.send_message(writer, ut.build_response("success", "LOGOUT_SUCCESS"))
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
        await ut.send_message(writer, ut.build_response("error", "User not logged in."))


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
        logging.info("Sending SHOW_STATUS message to user")
    except Exception as e:
        logging.error(f"Error while processing SHOW_STATUS: {e}")
        await ut.send_message(writer, ut.build_response("error", "Failed to retrieve status"))


async def handle_game_over(username):
    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            tetris_server.online_users[username]["status"] = "idle"

    room_to_delete = None
    async with tetris_server.rooms_lock:
        for room_id, room in list(tetris_server.rooms.items()):
            if username in room["players"]:
                room["players"].remove(username)
                if len(room["players"]) == 0:
                    room_to_delete = room_id
                else:
                    # If room still has players, update its status to "Waiting"
                    room["status"] = "Waiting"
                break
        if room_to_delete:
            del tetris_server.rooms[room_to_delete]

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

    async with tetris_server.rooms_lock:
        rooms_data = [
            {
                "room_id": r_id,
                "creator": room["creator"],
                "status": room["status"]
            }
            for r_id, room in tetris_server.rooms.items()
        ]
    rooms_message = {
        "status": "update",
        "data": rooms_data
    }

    logging.info(f"User {username} has ended the game and is now idle.")


async def handle_join_room(params, username, writer):
    if len(params) != 1:
        await ut.send_message(writer, ut.build_response("error", "Invalid JOIN_ROOM command"))
        return

    room_id = params[0]

    # Check if room is available
    async with tetris_server.rooms_lock:
        if room_id not in tetris_server.rooms:
            await ut.send_message(writer, ut.build_response("error", "Room does not exist"))
            return

        room = tetris_server.rooms[room_id]

        if room['status'] == 'In Game':
            await ut.send_message(writer, ut.build_response("error", "Room is already in game"))
            return
        if len(room['players']) >= 2:
            await ut.send_message(writer, ut.build_response("error", "Room is full"))
            return
        if room['type'] == 'private' and username not in room['players']:
            await ut.send_message(writer, ut.build_response("error", "Cannot join a private room without invitation"))
            return
        if username in room['players']:
            await ut.send_message(writer, ut.build_response("error", "You are already in the room"))
            return

        room['players'].append(username)

    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            tetris_server.online_users[username]["status"] = "in_room"

    await ut.send_message(writer, ut.build_response("success", f"JOIN_ROOM_SUCCESS {room_id}"))

    if len(room['players']) == 2:

        async with tetris_server.rooms_lock:
            room['status'] = 'In Game'
            creator = room["players"][0]
            joiner = username
            async with tetris_server.online_users_lock:
                for player in room['players']:
                    if player in tetris_server.online_users:
                        tetris_server.online_users[player]["status"] = "in_game"

                # Retrieve creator and joiner info
                creator_info = tetris_server.online_users[creator]
                joiner_info = tetris_server.online_users[joiner]

                # Generate random ports for each role within the specified range
                creator_port = ut.get_port()
                joiner_port = ut.get_port()

                creator_message = {
                    "status": "p2p_info",
                    "role": "host",
                    "peer_ip": joiner_info["ip"],
                    "peer_port": joiner_port,
                    "own_port": creator_port,
                    "room_id": room_id
                }
                joiner_message = {
                    "status": "p2p_info",
                    "role": "client",
                    "peer_ip": creator_info["ip"],
                    "peer_port": creator_port,
                    "own_port": joiner_port,
                    "room_id": room_id
                }
                await ut.send_message(creator_info["writer"], json.dumps(creator_message) + '\n')
                await ut.send_message(joiner_info["writer"], json.dumps(joiner_message) + '\n')
        logging.info(f"[DB] Game server info has been sent to players in room {room_id}")

    async with tetris_server.rooms_lock:
        public_rooms_data = [
            {
                "room_id": r_id,
                "creator": room["creator"],
                "status": room["status"]
            }
            for r_id, room in tetris_server.rooms.items()
        ]
    public_rooms_message = {
        "status": "update",
        "type": "public_rooms",
        "data": public_rooms_data
    }

    logging.info(f"User {username} has joined room {room_id}")


async def main():
    ut.init_logging()
    
    # connect to db server
    try:
        db_reader, db_writer = await asyncio.open_connection(config.HOST, config.DB_PORT)
        print("Successfully connected to database server.")
        logging.info(f"Successfully connected to database server {config.HOST}:{config.DB_PORT}")
    except ConnectionRefusedError:
        print("Connection declined, please check if the database server is running.")
        logging.error("Connection declined, please check if the database server is running.")
        return
    except Exception as e:
        print(f"Unable to connect to database server: {e}")
        logging.error(f"Unable to connect to database server: {e}")
        return

    server_ = await asyncio.start_server(
        lambda r, w: handle_client(r, w, db_reader, db_writer),
        config.HOST, config.PORT
    )
    addr = server_.sockets[0].getsockname()
    logging.info(f"Lobby Server running on {addr}")

    async with server_:
        try:
            await server_.serve_forever()
        except KeyboardInterrupt:
            logging.info("Received keyboard interrupt, closing server...")
        finally:
            server_.close()
            await server_.wait_closed()
            logging.info("Server is closed.")

if __name__ == "__main__":
    asyncio.run(main())
