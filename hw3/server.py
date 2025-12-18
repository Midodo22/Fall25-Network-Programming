import asyncio
import logging
import json
import utils as ut
import config
from config import tetris_server
import aiofiles
import os
import uuid
from database import start_db_server

games = {}
DEV_ONLY_COMMANDS = {"UPLOAD_GAME", "UPDATE_GAME", "DELETE_GAME", "LIST_OWN_GAMES"}
async def handle_client(reader, writer):
    username = None
    user_role = None
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
        nonlocal username, user_role
        try:
            while True:
                message = await ut.unpack_message(reader)
                if message is None:
                    logging.info(f"[Lobby] Client from  {addr} disconnected")
                    if username:
                        await ut.send_command(
                            "lobby",
                            db_writer,
                            "SERVER_CLOSED",
                            [username, user_role or "client"]
                        )

                    break
                
                username, user_role = await process_client_message(
                    message,
                    username,
                    user_role,
                    reader,
                    writer,
                    db_reader,
                    db_writer
                )
        
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
                await process_db_message(
                    message,
                    username,
                    user_role,
                    reader,
                    writer,
                    db_reader,
                    db_writer
                )
        
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
async def process_client_message(message, username, user_role, client_reader, client_writer, db_reader, db_writer):
    try:
        message_json = json.loads(message)
        sender = message_json.get("sender", "")
        command = message_json.get("command", "").upper()
        params = message_json.get("params", [])
        
        if sender not in ("client", "game_dev"):
            return username, user_role
        is_game_dev = sender == "game_dev"
        if command in DEV_ONLY_COMMANDS and not is_game_dev:
            await ut.send_message(client_writer, ut.build_response("lobby", "error", "Only game developers can perform this action"))
            return username, user_role
        if command == "REGISTER":
            await handle_register(params, client_writer, db_writer, sender)
        elif command == "LOGIN":
            await handle_login(params, client_reader, client_writer, db_writer, sender)
            if len(params) >= 1:
                username = params[0]
                user_role = sender
        elif command == "LOGOUT":
            if username:
                await handle_logout(username, client_writer, db_writer, sender)
                username = None
                user_role = None
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
        elif command == "LEAVE_ROOM":
            if username:
                await handle_leave_room(username, client_writer, db_writer)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        
        elif command == "JOIN_ROOM":
            if username:
                await handle_join_room(params, username, client_writer, db_writer)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        
        elif command == "DOWNLOAD_GAME_FILE":
            if username:
                await handle_download_game_file(params, client_writer)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        
        elif command == "UPLOAD_GAME":
            if username:
                await handle_upload_game(params, username, client_reader, client_writer, db_writer)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        elif command == "UPDATE_GAME":
            if username:
                await handle_update_game(params, username, client_reader, client_writer, db_writer)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        elif command == "DELETE_GAME":
            if username:
                await handle_delete_game(params, username, client_writer, db_writer)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        elif command == "LIST_OWN_GAMES":
            if username:
                await ut.send_command("lobby", db_writer, "LIST_OWN_GAMES", [username])
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        elif command == "LIST_ALL_GAMES":
            if username:
                await ut.send_command("lobby", db_writer, "LIST_ALL_GAMES", [])
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        elif command == "LEAVE_REVIEW":
            if username:
                if len(params) < 3:
                    await ut.send_message(client_writer, ut.build_response("lobby", "error", "Invalid LEAVE_REVIEW command"))
                else:
                    await ut.send_command("lobby", db_writer, "LEAVE_REVIEW", [username, params[0], params[1], params[2]])
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        elif command == "GET_REVIEWS":
            if username:
                if len(params) != 1:
                    await ut.send_message(client_writer, ut.build_response("lobby", "error", "Invalid GET_REVIEWS command"))
                else:
                    await ut.send_command("lobby", db_writer, "GET_REVIEWS", params)
            else:
                await ut.send_message(client_writer, ut.build_response("lobby", "error", "Not logged in"))
        else:
            await ut.send_message(client_writer, ut.build_response("lobby", "error", "Unknown client command"))
    except json.JSONDecodeError:
        await ut.send_message(client_writer, ut.build_response("lobby", "error", "Invalid message format"))
    return username, user_role
async def process_db_message(message, username, user_role, client_reader, client_writer, db_reader, db_writer):
    global games
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
            is_dev = user_role == "game_dev"
            if msg.startswith("REGISTRATION_SUCCESS"):
                await ut.send_message(client_writer, ut.build_response("lobby", "success", "REGISTRATION_SUCCESS"))
            elif msg.startswith("LOGIN_SUCCESS"):
                client_ip, client_port = client_writer.get_extra_info('peername')
                if not is_dev:
                    async with config.target_lock:
                        config.targets[username] = {
                            "writer": client_writer,
                            "reader": client_reader
                        }
                    async with tetris_server.online_users_lock:
                        tetris_server.online_users[username] = {
                            "status": "idle",
                            "ip": client_ip,
                            "port": client_port
                        }
                else:
                    async with tetris_server.dev_online_users_lock:
                        tetris_server.dev_online_users[username] = {
                            "status": "idle",
                            "ip": client_ip,
                            "port": client_port
                        }
                await ut.send_message(client_writer, ut.build_response("lobby", "success", "LOGIN_SUCCESS"))
            elif msg.startswith("LOGOUT_SUCCESS"):
                async with tetris_server.online_users_lock:
                    tetris_server.online_users.pop(username, None)
                async with tetris_server.dev_online_users_lock:
                    tetris_server.dev_online_users.pop(username, None)
                await ut.send_message(client_writer, ut.build_response("lobby", "success", "LOGOUT_SUCCESS"))
            elif msg.startswith("CREATE_ROOM_SUCCESS"):
                parts = msg.split()
                room_id = parts[1]
                params_list = message_json.get("params") or []
                room_type = params_list[1] if len(params_list) >= 2 else "public"
                game_name = params_list[2] if len(params_list) >= 3 else None
                async with tetris_server.rooms_lock:
                    tetris_server.rooms[room_id] = {
                        "creator": username,
                        "players": [username],
                        "type": room_type,
                        "status": "Waiting",
                        "game_name": game_name
                    }
                await ut.send_message(client_writer, ut.build_response("lobby", "success", f"CREATE_ROOM_SUCCESS {room_id}", params_list))
            
            elif msg.startswith("JOIN_ROOM_SUCCESS"):
                parts = msg.split()
                room_id = parts[1]
                params_list = message_json.get("params") or []
                players = params_list[1] if len(params_list) >= 2 else []
                room_type = params_list[2] if len(params_list) >= 3 else "public"
                game_name = params_list[3] if len(params_list) >= 4 else None
                async with tetris_server.rooms_lock:
                    room_entry = tetris_server.rooms.get(room_id, {
                        "creator": players[0] if players else username,
                        "players": [],
                        "type": room_type,
                        "status": "Waiting",
                        "game_name": game_name
                    })
                    if players:
                        room_entry["players"] = players
                        room_entry["creator"] = players[0]
                    room_entry["type"] = room_type
                    room_entry["status"] = "Ready"
                    if game_name:
                        room_entry["game_name"] = game_name
                    tetris_server.rooms[room_id] = room_entry
                await ut.send_message(client_writer, ut.build_response("lobby", "success", f"JOIN_ROOM_SUCCESS {room_id}", params_list))
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
            elif msg.startswith("LEAVE_ROOM_SUCCESS"):
                parts = msg.split()
                room_id = parts[1] if len(parts) > 1 else None
                params_list = message_json.get("params") or []
                async with tetris_server.rooms_lock:
                    if params_list and len(params_list) >= 5 and params_list[1]:
                        players = params_list[1]
                        room_type = params_list[2]
                        creator = params_list[3]
                        status_value = params_list[4]
                        game_name = params_list[5] if len(params_list) >= 6 else None
                        tetris_server.rooms[room_id] = {
                            "creator": creator,
                            "players": players,
                            "type": room_type,
                            "status": status_value,
                            "game_name": game_name
                        }
                    elif room_id:
                        tetris_server.rooms.pop(room_id, None)
                await ut.send_message(client_writer, ut.build_response("lobby", "success", msg, params_list))
            elif msg.startswith("UPLOAD_GAME_SUCCESS") or msg.startswith("UPDATE_GAME_SUCCESS") or msg.startswith("DELETE_GAME_SUCCESS"):
                params_list = message_json.get("params", [])
                if msg.startswith("DELETE_GAME_SUCCESS"):
                    game_name = message_json.get("game_name")
                    games.pop(game_name, None)
                elif params_list:
                    game_entry = params_list[0]
                    games[game_entry.get("name")] = game_entry
                await ut.send_message(client_writer, message_json)
            elif msg.startswith("LEAVE_REVIEW_SUCCESS"):
                await ut.send_message(client_writer, message_json)
            elif "games" in message_json:
                await ut.send_message(client_writer, message_json)
            elif "reviews" in message_json:
                await ut.send_message(client_writer, message_json)
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
Game related
"""
async def load_games():
    global games
    games_data = {}
    games_file = config.GAMES_FILE
    if not os.path.exists(games_file):
        async with aiofiles.open(games_file, 'w') as f:
            await f.write(json.dumps(games_data))
        return games_data
    async with aiofiles.open(games_file, 'r') as f:
        content = await f.read()
        if content:
            try:
                games_data = json.loads(content)
                for game_name, info in games_data.items():
                    if isinstance(info, dict):
                        info.setdefault("name", game_name)
            except json.JSONDecodeError:
                games_data = {}
                await save_games()
    return games_data
async def save_games():
    global games
    games_file = config.GAMES_FILE
    async with aiofiles.open(games_file, 'w') as f:
        data = json.dumps(games, indent=4)
        await f.write(data)
        logging.debug(f"Saved games: {data}")
async def handle_upload_game(params, username, reader, writer, db_writer):
    global games
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid UPLOAD_GAME command"))
        return
    game_name, game_description = params
    async with tetris_server.games_lock:
        if game_name in games:
            await ut.send_message(writer, ut.build_response("lobby", "error", "Game already exists, use update if you are the publisher. Duplicates are not allowed."))
            return
    await ut.send_message(writer, ut.build_response("lobby", "ready", "Ready to receive game file", game_name=game_name))
    try:
        message = await ut.unpack_message(reader)
        if not message:
            await ut.send_message(writer, ut.build_response("lobby", "error", "No data received"))
            return
        message_json = json.loads(message)
        file_size = int(message_json.get('file_size', 0))
        if file_size <= 0:
            await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid file size"))
            return
        file_content = await reader.readexactly(file_size)
        if not os.path.exists('games-server'):
            os.makedirs('games-server')
        file_path = os.path.join('games-server', game_name + '.py')
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)
        version = str(uuid.uuid4())
        await ut.send_command("lobby", db_writer, "UPLOAD_GAME", [username, game_name, game_description, version])
        logging.info(f"[Lobby] Stored uploaded file for {game_name}, awaiting DB confirmation")
    except Exception as e:
        logging.error(f"Error while handling UPLOAD_GAME: {e}")
        await ut.send_message(writer, ut.build_response("lobby", "error", "Failed to upload game"))
async def handle_update_game(params, username, reader, writer, db_writer):
    global games
    if len(params) < 1:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid UPDATE_GAME command"))
        return
    game_name = params[0]
    game_description = params[1] if len(params) > 1 else ""
    async with tetris_server.games_lock:
        game_entry = games.get(game_name)
    if not game_entry:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Game does not exist"))
        return
    if game_entry.get("publisher") != username:
        await ut.send_message(writer, ut.build_response("lobby", "error", "You are not the publisher of this game"))
        return
    await ut.send_message(writer, ut.build_response("lobby", "ready", "Ready to receive updated game file", game_name=game_name))
    try:
        message = await ut.unpack_message(reader)
        if not message:
            await ut.send_message(writer, ut.build_response("lobby", "error", "No data received"))
            return
        message_json = json.loads(message)
        file_size = int(message_json.get('file_size', 0))
        if file_size <= 0:
            await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid file size"))
            return
        file_content = await reader.readexactly(file_size)
        if not os.path.exists('games-server'):
            os.makedirs('games-server')
        file_path = os.path.join('games-server', game_name + '.py')
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)
        version = str(uuid.uuid4())
        await ut.send_command("lobby", db_writer, "UPDATE_GAME", [username, game_name, version, game_description])
        logging.info(f"[Lobby] Stored updated file for {game_name}, awaiting DB confirmation")
    except Exception as e:
        logging.error(f"Error while handling UPDATE_GAME: {e}")
        await ut.send_message(writer, ut.build_response("lobby", "error", "Failed to update game"))
async def handle_delete_game(params, username, writer, db_writer):
    global games
    if len(params) != 1:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid DELETE_GAME command"))
        return
    game_name = params[0]
    async with tetris_server.games_lock:
        game_entry = games.get(game_name)
    if not game_entry:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Game does not exist"))
        return
    if game_entry.get("publisher") != username:
        await ut.send_message(writer, ut.build_response("lobby", "error", "You are not the publisher of this game"))
        return
    file_path = os.path.join('games-server', game_name + '.py')
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            logging.error(f"Failed to remove game file {file_path}: {e}")
    await ut.send_command("lobby", db_writer, "DELETE_GAME", [username, game_name])
    logging.info(f"[Lobby] Requested deletion of {game_name} metadata in DB")
async def handle_download_game_file(params, writer):
    if len(params) != 1:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid DOWNLOAD_GAME_FILE command"))
        return
    game_name = params[0]
    async with tetris_server.games_lock:
        game_entry = games.get(game_name)
        game_version = game_entry.get("version") if game_entry else None
    if not game_entry:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Game metadata not found"))
        return
    try:
        file_path = os.path.join('games-server', game_name + '.py')
        logging.info(f"Sending game file {game_name}")
        if not os.path.exists(file_path):
            await ut.send_message(writer, ut.build_response("lobby", "error", "Game file does not exist"))
            return
        file_size = os.path.getsize(file_path)
        file_transfer_message = {
            "status": "file_transfer",
            "game_name": game_name,
            "file_size": file_size,
            "version": game_version
        }
        await ut.send_message(writer, file_transfer_message)
        async with aiofiles.open(file_path, 'rb') as f:
            file_content = await f.read()
            writer.write(file_content)
            await writer.drain()
        logging.info(f"Sent game file {game_name}")
    except Exception as e:
        logging.error(f"Error while handling DOWNLOAD_GAME_FILE: {e}")
        await ut.send_message(writer, ut.build_response("lobby", "error", "Failed to download game file"))
# async def load_users():
#     users_data = {}
#     if not os.path.exists(USERS_FILE):
#         async with aiofiles.open(USERS_FILE, 'w') as f:
#             await f.write(json.dumps(users_data))
#         return users_data
#     async with aiofiles.open(USERS_FILE, 'r') as f:
#         content = await f.read()
#         if content:
#             try:
#                 users_data = json.loads(content)
#             except json.JSONDecodeError:
#                 users_data = {}
#                 await save_users()
#     return users_data
# async def save_users():
#     async with aiofiles.open(USERS_FILE, 'w') as f:
#         data = json.dumps(users, indent=4)
#         await f.write(data)
#         logging.debug(f"Saved users: {data}")
"""
User-related, need to use db server
"""
async def handle_register(params, writer, db_writer, sender):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid REGISTER command"))
        return
    
    await ut.send_command("lobby", db_writer, "REGISTER", params + [sender])
    logging.info(f"[Lobby] Sent command to register user {params[0]}.")
async def handle_login(params, reader, writer, db_writer, sender):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid LOGIN command"))
        return
    
    client_ip, client_port = writer.get_extra_info('peername')
    params.append(client_ip)
    params.append(str(client_port))
    params.append(sender)
    
    await ut.send_command("lobby", db_writer, "LOGIN", params)
    logging.info(f"[Lobby] Sent command to login user {params[0]}.")
async def handle_logout(username, writer, db_writer, sender):
    if not username:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Not logged in"))
        return
    await ut.send_command("lobby", db_writer, "LOGOUT", [username, sender])
    logging.info(f"[Lobby] Sent command to logout user {username}.")
async def handle_leave_room(username, writer, db_writer):
    await ut.send_command("lobby", db_writer, "LEAVE_ROOM", [username])
"""
Game-related
"""
async def handle_create_room(params, username, writer, db_writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid CREATE_ROOM command"))
        return
    room_type = params[0].lower()
    game_name = params[1]
    if room_type not in ['public', 'private']:
        await ut.send_message(writer, ut.build_response("lobby", "error", "Invalid room type"))
        return
    async with tetris_server.games_lock:
        if game_name not in games:
            await ut.send_message(writer, ut.build_response("lobby", "error", "Game not available on server"))
            return
    await ut.send_command("lobby", db_writer, "CREATE_ROOM", [username, room_type, game_name])
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
    game_name_param = params[3] if len(params) >= 4 else None
    if len(players) < 2:
        logging.info(f"[Lobby] Room {room_id} does not have enough players yet")
        return
    async with tetris_server.rooms_lock:
        room_entry = tetris_server.rooms.get(room_id, {})
        room_entry["players"] = players
        room_entry["creator"] = players[0]
        room_entry["status"] = "In Game"
        room_entry["type"] = room_visibility
        if game_name_param:
            room_entry["game_name"] = game_name_param
        tetris_server.rooms[room_id] = room_entry
        game_name = room_entry.get("game_name")
    async with tetris_server.games_lock:
        game_entry = games.get(game_name) if game_name else None
        latest_version = game_entry.get("version") if game_entry else None
    async with tetris_server.online_users_lock:
        online_snapshot = {player: tetris_server.online_users.get(player) for player in players}
        for player, info in online_snapshot.items():
            if not info:
                logging.error(f"[Lobby] Missing online info for player {player}")
                return
            tetris_server.online_users[player]["status"] = "in_game"
    if len(players) < 2:
        return
    host_player = players[0]
    client_player = players[1]
    host_info = online_snapshot[host_player]
    client_info = online_snapshot[client_player]
    host_writer = config.targets.get(host_player, {}).get("writer")
    client_writer = config.targets.get(client_player, {}).get("writer")
    if not host_writer or not client_writer:
        logging.error(f"[Lobby] Missing lobby connection for players {players}")
        return
    host_port = ut.get_port()
    client_port = ut.get_port()
    host_message = {
        "status": "p2p_info",
        "role": "host",
        "room_id": room_id,
        "peer_ip": client_info["ip"],
        "peer_port": client_port,
        "own_port": host_port,
        "game_name": game_name,
        "game_version": latest_version
    }
    client_message = {
        "status": "p2p_info",
        "role": "client",
        "room_id": room_id,
        "peer_ip": host_info["ip"],
        "peer_port": host_port,
        "own_port": client_port,
        "game_name": game_name,
        "game_version": latest_version
    }
    await ut.send_message(host_writer, host_message)
    await ut.send_message(client_writer, client_message)
    logging.info(f"[Lobby] Sent peer connection info for room {room_id}")
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
    global games
    games = await load_games()
    
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
