import asyncio
import logging
import json
import contextlib
import utils as ut
import config
from config import tetris_server
import game


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

        elif command == "ACCEPT":
            if username:
                await handle_accept_invite(params, username, client_writer, db_writer)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))

        elif command == "DECLINE":
            if username:
                await handle_decline_invite(params, username, client_writer, db_writer)
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
                await ut.send_command("lobby", db_writer, "SHOW_STATUS", [username])
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
                client_ip, client_port = client_writer.get_extra_info('peername')
                async with tetris_server.online_users_lock:
                    tetris_server.online_users[username] = {
                        "status": "idle",
                        "ip": client_ip,
                        "port": client_port
                    }
                await ut.send_message(client_writer, ut.build_response("lobby", "success", "LOGIN_SUCCESS"))

            elif msg.startswith("LOGOUT_SUCCESS"):
                async with tetris_server.online_users_lock:
                    if username in tetris_server.online_users:
                        del tetris_server.online_users[username]
                await ut.send_message(client_writer, ut.build_response("lobby", "success", "LOGOUT_SUCCESS"))

            elif msg.startswith("CREATE_ROOM_SUCCESS"):
                parts = msg.split()
                room_id = parts[1]
                params_list = message_json.get("params", [])
                room_type = params_list[1] if len(params_list) >= 2 else "public"
                async with tetris_server.rooms_lock:
                    tetris_server.rooms[room_id] = {
                        "creator": username,
                        "players": [username],
                        "type": room_type,
                        "status": "Waiting"
                    }
                await ut.send_message(client_writer, ut.build_response("lobby", "success", f"CREATE_ROOM_SUCCESS {room_id}"))
            
            elif msg.startswith("JOIN_ROOM_SUCCESS"):
                parts = msg.split()
                room_id = parts[1]
                params_list = message_json.get("params", [])
                players = params_list[1] if len(params_list) >= 2 else []
                room_type = params_list[2] if len(params_list) >= 3 else "public"
                async with tetris_server.rooms_lock:
                    room_entry = tetris_server.rooms.get(room_id, {
                        "creator": players[0] if players else username,
                        "players": [],
                        "type": room_type,
                        "status": "Waiting"
                    })
                    if players:
                        room_entry["players"] = players
                        room_entry["creator"] = players[0]
                    room_entry["type"] = room_type
                    room_entry["status"] = "Ready"
                    tetris_server.rooms[room_id] = room_entry
                await ut.send_message(client_writer, ut.build_response("lobby", "success", f"JOIN_ROOM_SUCCESS {room_id}"))
                await send_p2p_info(params_list if params_list else [room_id], username, client_writer)

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
            
            elif msg.startswith("DECLINED_INVITE"):
                parts = msg.split()
                target_username = parts[1]
                room_id = parts[2]
                target_writer = None
                
                try:
                    target_writer = config.targets[target_username]["writer"]
                except:
                    logging.error(f"Decline target {target_username} not found")

                await ut.send_message(target_writer, ut.build_response("lobby", "invite_declined", f"{username} {room_id}"))
                await ut.send_message(client_writer, ut.build_response("lobby", "success", f"DECLINED_INVITE {target_username} {room_id}"))

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
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid LOGIN command"))
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


async def handle_accept_invite(params, username, writer, db_writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid ACCEPT_INVITE command"))
        return
    params.append(username)
    await ut.send_command("lobby", db_writer, "ACCEPT", params)


async def send_p2p_info(params, username, writer):
    if not params:
        logging.error("[Lobby] Missing room info for P2P setup")
        return

    room_id = params[0]
    players = params[1] if len(params) >= 2 and isinstance(params[1], list) else []
    room_visibility = params[2] if len(params) >= 3 else "public"
    if len(players) < 2:
        logging.info(f"[Lobby] Room {room_id} does not have enough players yet")
        return

    async with tetris_server.rooms_lock:
        room_entry = tetris_server.rooms.get(room_id, {})
        room_entry["players"] = players
        room_entry["creator"] = players[0]
        room_entry["status"] = "In Game"
        room_entry["type"] = room_visibility
        tetris_server.rooms[room_id] = room_entry

    async with tetris_server.online_users_lock:
        for player in players:
            if player in tetris_server.online_users:
                tetris_server.online_users[player]["status"] = "in_game"

    port = await launch_game_instance(room_id)
    if not port:
        logging.error(f"[Lobby] Failed to start game server for room {room_id}")
        error_msg = ut.build_response("lobby", "error", "Unable to start game server")
        for player in players:
            target = config.targets.get(player)
            if target and target.get("writer"):
                await ut.send_message(target["writer"], error_msg)
        return

    game_host = config.GAME_HOST
    for idx, player in enumerate(players):
        target = config.targets.get(player)
        if not target or not target.get("writer"):
            logging.error(f"[Lobby] Missing lobby connection for player {player}")
            continue
        role = f"P{idx + 1}"
        message = {
            "status": "p2p_info",
            "role": role,
            "room_id": room_id,
            "game_type": "tetris",
            "game_host": game_host,
            "game_port": port
        }
        await ut.send_message(target["writer"], message)
    logging.info(f"[Lobby] Central game server info sent for room {room_id}")


async def launch_game_instance(room_id):
    async with tetris_server.game_servers_lock:
        if room_id in tetris_server.game_servers:
            return tetris_server.game_servers[room_id]["port"]
    result = await game.start_game_server(room_id, host_bind="0.0.0.0")
    if not result:
        return None
    server_obj, port, tick_task, game_ctx = result

    async def _run():
        async with server_obj:
            await server_obj.serve_forever()

    task = asyncio.create_task(_run())
    async with tetris_server.game_servers_lock:
        tetris_server.game_servers[room_id] = {
            "server": server_obj,
            "task": task,
            "port": port,
            "tick_task": tick_task,
            "ctx": game_ctx
        }
    logging.info(f"[Lobby] Started game server for room {room_id} on port {port}")
    return port


async def stop_game_instance(room_id):
    async with tetris_server.game_servers_lock:
        info = tetris_server.game_servers.pop(room_id, None)
    if not info:
        return
    server_obj = info["server"]
    task = info["task"]
    tick_task = info.get("tick_task")
    server_obj.close()
    await server_obj.wait_closed()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    if tick_task:
        tick_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tick_task
    logging.info(f"[Lobby] Stopped game server for room {room_id}")

async def handle_decline_invite(params, username, writer, db_writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid DECLINE_INVITE command"))
        return
    
    params.append(username)
    await ut.send_command("lobby", db_writer, "DECLINE", params)


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
    target_room = None
    async with tetris_server.rooms_lock:
        for room_id, room in list(tetris_server.rooms.items()):
            if username in room["players"]:
                target_room = room_id
                room["players"].remove(username)
                if len(room["players"]) == 0:
                    room_to_delete = room_id
                else:
                    # If room still has players, update its status to "Waiting"
                    room["status"] = "Waiting"
                break
        if room_to_delete:
            del tetris_server.rooms[room_to_delete]
    if target_room:
        await stop_game_instance(target_room)

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
