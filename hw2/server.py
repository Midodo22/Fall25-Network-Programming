import asyncio
import logging
import json
import utils as ut
import config
from config import tetris_server


async def handle_client(reader, writer):
    username = None
    addr = writer.get_extra_info('peername')
    print((f"[Lobby] Connection from {addr}"))
    logging.info(f"[Lobby] Connection from {addr}")
    
    # connect to db server
    try:
        db_reader, db_writer = await asyncio.open_connection(config.HOST, config.DB_PORT)
        print("Successfully connected to database server.")
        logging.info(f"[Lobby] Successfully connected to database server {config.HOST}:{config.DB_PORT}")
    
    except ConnectionRefusedError:
        print("Connection declined, please check if the database server is running.")
        logging.error("[Lobby] Connection declined, please check if the database server is running.")
        return
    
    except Exception as e:
        await ut.send_message(writer, ut.build_response("lobby", "error", "DB unavailable"))
        print(f"Unable to connect to database server: {e}")
        logging.error(f"[Lobby] Unable to connect to database server: {e}")
        writer.close()
        await writer.wait_closed()
        return

    # From client to db
    username = None
    async def handle_client_messages():
        nonlocal username
        try:
            while True:
                message = await ut.unpack_message(reader)
                if message is None:
                    logging.info(f"[Lobby] Client from  {addr} disconnected")
                    if username:
                        await ut.send_command("lobby", db_writer, "SERVER_CLOSED", [username])
    
                    break
                
                if username:
                    await process_client_message(message, username, reader, writer, db_reader, db_writer)
                else:
                    username = await process_client_message(message, username, reader, writer, db_reader, db_writer)
        
        except Exception as e:
            await ut.send_message(writer, ut.build_response("lobby", "error", "Server error"))
            logging.error(f"[Lobby] Error when processing client at {addr}: {e}")

    # From db to client
    async def handle_db_messages():
        try:
            while True:
                message = await ut.unpack_message(db_reader)
                if not message:
                    logging.info(f"[Lobby] DB connection closed for {addr}")
                    break
                await process_db_message(message, username, reader, writer, db_reader, db_writer)
        
        except Exception as e:
            await ut.send_message(writer, ut.build_response("lobby", "error", "Server error"))
            logging.error(f"[Lobby] Error when processing DB for {addr}: {e}")

    # Run both at the same time
    try:
        client_task = asyncio.create_task(handle_client_messages())
        db_task = asyncio.create_task(handle_db_messages())

        done, pending = await asyncio.wait(
            [client_task, db_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Cleanup
        for task in pending:
            task.cancel()

    finally:
        try:
            writer.close()
            await writer.wait_closed()
            db_writer.close()
            await db_writer.wait_closed()
        except Exception:
            pass


async def process_client_message(message, username, client_reader, client_writer, db_reader, db_writer):
    try:
        message_json = json.loads(message)
        sender = message_json.get("sender", "")
        command = message_json.get("command", "").upper()
        params = message_json.get("params", [])
        
        if sender != "client":
            return

        if command == "REGISTER":
            await handle_register(params, client_writer, db_writer)

        elif command == "LOGIN":
            await handle_login(params, client_reader, client_writer, db_writer)
            if len(params) >= 1:
                return params[0]

        elif command == "LOGOUT":
            if username:
                await handle_logout(username, client_writer, db_writer)
                username = None
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))

        elif command == "CREATE_ROOM":
            if username:
                await handle_create_room(params, username, client_writer, db_writer)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))

        elif command == "INVITE_PLAYER":
            if username:
                await handle_invite_player(params, username, client_writer, db_writer)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))

        elif command == "CHECK":
            if username:
                await ut.send_command("lobby", db_writer, "CHECK", [username])
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))

        elif command == "GAME_OVER":
            if username:
                await handle_game_over(username)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        
        elif command == "SHOW_STATUS":
            if username:
                await ut.send_command("lobby", db_writer, "SHOW_STATUS", [])
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        
        elif command == "JOIN_ROOM":
            if username:
                await handle_join_room(params, username, client_writer, db_writer)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))

        else:
            await ut.send_message(client_writer, ut.build_response("lobby", "error", "Unknown client command"))

    except json.JSONDecodeError:
        await ut.send_message(client_writer, ut.build_response("lobby", "error", "Invalid message format"))

    return None

async def process_db_message(message, username, client_reader, client_writer, db_reader, db_writer):
    try:
        try:
            message_json = json.loads(message)
        except Exception as e:
            logging.info(f"[DB] Error when unpacking message: {e}")
        
        sender = message_json.get("sender", "")
        status = message_json.get("status")
        msg = message_json.get("message", "")
        
        if sender != "database":
            return
        
        if status == "success":
            if msg.startswith("REGISTRATION_SUCCESS"):
                await ut.send_message(client_writer, ut.build_response("lobby", "success", "REGISTRATION_SUCCESS"))

            elif msg.startswith("LOGIN_SUCCESS"):
                async with config.target_lock:
                    config.targets[username] = {
                        "writer": client_writer,
                        "reader": client_reader
                    }
                await ut.send_message(client_writer, ut.build_response("lobby", "success", "LOGIN_SUCCESS"))

            elif msg.startswith("LOGOUT_SUCCESS"):
                await ut.send_message(client_writer, ut.build_response("lobby", "success", "LOGOUT_SUCCESS"))

            elif msg.startswith("CREATE_ROOM_SUCCESS"):
                parts = msg.split()
                room_id = parts[1]
                await ut.send_message(client_writer, ut.build_response("lobby", "success", f"CREATE_ROOM_SUCCESS {room_id}"))
            
            elif msg.startswith("JOIN_ROOM_SUCCESS"):
                parts = msg.split()
                room_id = parts[1]
                await ut.send_message(client_writer, ut.build_response("lobby", "success", "JOIN_ROOM_SUCCESS"))

            elif msg.startswith("INVITE_SENT"):
                parts = msg.split()
                target_username = parts[1]
                room_id = parts[2]
                target_writer = None
                
                try:
                    target_writer = config.targets[target_username]["writer"]
                except:
                    logging.error(f"Target {target_username} not found")

                await ut.send_message(target_writer, ut.build_response("lobby", "invite", f"{username} {room_id}"))
                await ut.send_message(client_writer, ut.build_response("lobby", "success", f"INVITE_SENT {target_username} {room_id}"))

        elif status == "status":
            await ut.send_message(client_writer, ut.build_response("lobby", "status", msg))
        
        elif status == "error":
            await ut.send_message(client_writer, ut.build_response("lobby", "error", f"\nError: {msg}\n"))
            
        elif status == "invite_declined":
            sender = message_json.get("from")
            room_id = message_json.get("room_id")
            print(f"\nUser {sender} has declined your invite to room {room_id}.")
            logging.info(f"[Lobby] User {sender} declined joining {room_id}.")

        elif status == "update":
            update_type = message_json.get("type")
            if update_type == "online_users":
                online_users = message_json.get("data", [])
            elif update_type == "room_status":
                room_id = message_json.get("room_id")
                updated_status = message_json.get("status")
                print(f"\nRoom {room_id} status updated as {updated_status}")
                
    except Exception as e:
        logging.error(f"[Lobby] Error handling DB message with status {status}: {e}")



"""
User-related, need to use db server
"""
async def handle_register(params, writer, db_writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid REGISTER command"))
        return
    
    await ut.send_command("lobby", db_writer, "REGISTER", params)
    logging.info(f"[Lobby] Sent command to register user {params[0]}.")


async def handle_login(params, reader, writer, db_writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid REGISTER command"))
        return
    
    client_ip, client_port = writer.get_extra_info('peername')
    params.append(client_ip)
    params.append(str(client_port))
    
    await ut.send_command("lobby", db_writer, "LOGIN", params)
    logging.info(f"[Lobby] Sent command to login user {params[0]}.")


async def handle_logout(params, writer, db_writer):
    await ut.send_command("lobby", db_writer, "LOGOUT", params)
    logging.info(f"[Lobby] Sent command to logout.")

"""
Game-related
"""
async def handle_create_room(params, username, writer, db_writer):
    if len(params) != 1:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid CREATE_ROOM command"))
        return
    room_type = params[0].lower()
    
    if room_type not in ['public', 'private']:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid room type"))
        return
    
    await ut.send_command("lobby", db_writer, "CREATE_ROOM", [username, room_type])


async def handle_invite_player(params, username, writer, db_writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid INVITE_PLAYER command"))
        return
    
    params.append(username)
    await ut.send_command("lobby", db_writer, "INVITE_PLAYER", params)


async def handle_accept_invite(params, username, writer):
    if len(params) != 1:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid ACCEPT_INVITE command"))
        return
    room_id = params[0]
    async with tetris_server.rooms_lock:
        if room_id not in tetris_server.rooms:
            await ut.send_message(writer, ut.build_response("lobby", "error", "Room does not exist"))
            return
        room = tetris_server.rooms[room_id]
        if room['status'] == 'In Game':
            await ut.send_message(writer, ut.build_response("lobby", "error", "Room is already in game"))
            return
        if len(room['players']) >= 2:
            await ut.send_message(writer, ut.build_response("lobby", "error", "Room is full"))
            return
        if room['type'] != 'private':
            await ut.send_message(writer, ut.build_response("lobby", "error", "Cannot accept invite to a public room"))
            return
        if username in room['players']:
            await ut.send_message(writer, ut.build_response("lobby", "error", "You are already in the room"))
            return
        room['players'].append(username)

    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            tetris_server.online_users[username]["status"] = "in_room"
    await ut.send_message(writer, ut.build_response("lobby", "success", f"JOIN_ROOM_SUCCESS {room_id} {room['game_type']}"))
    
    if len(room['players']) == 2:
        async with tetris_server.rooms_lock:
            room['status'] = 'In Game'
            game_type = room['game_type']
            creator = room["players"][0]
            joiner = username
            async with tetris_server.online_users_lock:
                for player in room['players']:
                    if player in tetris_server.online_users:
                        tetris_server.online_users[player]["status"] = "in_game"

                creator_info = tetris_server.online_users[creator]
                joiner_info = tetris_server.online_users[joiner]
                creator_port = ut.get_port()
                joiner_port = ut.get_port()
                creator_message = {
                    "status": "p2p_info",
                    "role": "host",
                    "peer_ip": joiner_info["ip"],
                    "peer_port": joiner_port,
                    "own_port": creator_port,
                    "game_type": game_type
                }
                joiner_message = {
                    "status": "p2p_info",
                    "role": "client",
                    "peer_ip": creator_info["ip"],
                    "peer_port": creator_port,
                    "own_port": joiner_port,
                    "game_type": game_type
                }
                await ut.send_message(creator_info["writer"], json.dumps(creator_message) + '\n')
                await ut.send_message(joiner_info["writer"], json.dumps(joiner_message) + '\n')
            logging.info(f"Game server info sent to players in room: {room_id}")

    logging.info(f"User {username} accepted invite to join room: {room_id}")

async def handle_decline_invite(params, username, writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid DECLINE_INVITE command"))
        return
    inviter_username, room_id = params
    # Notify the inviter that the invite was declined
    async with tetris_server.online_users_lock:
        if inviter_username in tetris_server.online_users:
            inviter_info = tetris_server.online_users[inviter_username]
            inviter_writer = inviter_info["writer"]
            decline_message = {
                "status": "invite_declined",
                "from": username,
                "room_id": room_id
            }
            await ut.send_message(inviter_writer, json.dumps(decline_message) + '\n')
            logging.info(f"User {username} declined invitation from {inviter_username} to room: {room_id}")
    await ut.send_message(writer, ut.build_response("lobby", "success", f"DECLINE_INVITE_SUCCESS {room_id}"))


async def handle_join_room(params, username, writer, db_writer):
    if len(params) != 1:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid JOIN_ROOM command"))
        return
    
    params.append(username)

    await ut.send_command("lobby", db_writer, "JOIN_ROOM", params)


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

    logging.info(f"[Lobby] User {username} has ended the game and is now idle.")


async def main():
    ut.init_logging()
    
    server_ = await asyncio.start_server(handle_client, config.HOST, config.PORT)
    addr = server_.sockets[0].getsockname()
    logging.info(f"[Lobby] Lobby Server running on {addr}")
    print(f"Lobby Server running on {addr}")

    async with server_:
        try:
            await server_.serve_forever()
        except KeyboardInterrupt:
            logging.info("[Lobby] Received keyboard interrupt, closing server...")
        finally:
            server_.close()
            await server_.wait_closed()
            logging.info("[Lobby] Server is closed.")

if __name__ == "__main__":
    asyncio.run(main())
