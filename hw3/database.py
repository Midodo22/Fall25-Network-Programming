import asyncio
import logging
import json
import copy
from datetime import datetime

import utils as ut
import config
from config import tetris_server


def _load_db_document():
    data = copy.deepcopy(config.DEFAULT_DB_STRUCTURE)
    try:
        with open(config.DB_FILE, 'r') as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data.update(loaded)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return data


def _write_db_document(data):
    with open(config.DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# The reader and writer here are for lobby server
async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    logging.info(f"[DB] Connection from {addr}")

    try:
        while True:
            try:
                message = await ut.unpack_message(reader)
            except Exception as e:
                logging.info(f"[DB] Error when unpacking message: {e}")
                
            if not message:
                logging.info(f"[DB] Connection closed by {addr}")
                break
            
            message_json = json.loads(message)
            sender = message_json.get("sender", "")
            # if sender != "lobby":
            command = message_json.get("command", "").upper()
            params = message_json.get("params", [])

            if command == "REGISTER":
                logging.info("[DB] Received command to register user")
                await db_register(params, writer)
            
            elif command == "LOGIN":
                logging.info("[DB] Received command to login user")
                await db_login(params, writer)

            elif command == "LOGOUT":
                logging.info("[DB] Received command to logout user")
                if not params:
                    await ut.send_message(writer, ut.build_response("database", "error", "LOGOUT missing username"))
                else:
                    role = params[1] if len(params) > 1 else None
                    await db_logout(params[0], writer, role)

            elif command == "CREATE_ROOM":
                logging.info("[DB] Received command to create room")
                await db_create_room(params, writer)

            elif command == "INVITE_PLAYER":
                await db_invite_player(params, writer)
            
            elif command == "ACCEPT":
                await db_accept_invite(params, writer)
            
            elif command == "DECLINE":
                await db_decline_invite(params, writer)
            
            elif command == "JOIN_ROOM":
                await db_join_room(params, writer)

            elif command == "LEAVE_ROOM":
                await db_leave_room(params, writer)

            elif command == "UPLOAD_GAME":
                await db_upload_game(params, writer)

            elif command == "UPDATE_GAME":
                await db_update_game(params, writer)

            elif command == "DELETE_GAME":
                await db_delete_game(params, writer)

            elif command == "LIST_OWN_GAMES":
                await db_list_own_games(params, writer)

            elif command == "LIST_ALL_GAMES":
                await db_list_all_games(writer)

            elif command == "LEAVE_REVIEW":
                await db_leave_review(params, writer)

            elif command == "GET_REVIEWS":
                await db_get_reviews(params, writer)
            

            # elif command == "GAME_OVER":
            #     if username:
            #         await handle_game_over(username)
            #     else:
            #         await ut.send_message(writer, ut.build_response("database", "error", "Not logged in"))
            
            elif command == "SHOW_STATUS":
                await db_show_status(writer, params)

            elif command == "CHECK":
                await db_show_invites(writer, params)

            elif command == "SERVER_CLOSED":
                await db_close_server(params)
            
            else:
                await ut.send_message(writer, ut.build_response("database", "error", "[DB] Unknown command"))
    
    except Exception as e:
        await ut.send_message(writer, ut.build_response("database", "error", "[DB] Db server error"))
        logging.error(f"[DB] Error when processing client at {addr}: {e}")
    
    finally:
        # Lobby server closed
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


"""
User login/out, registration
"""
async def db_register(params, writer):
    if len(params) < 2:
        await ut.send_message(writer, ut.build_response("database", "error", "Invalid registration payload"))
        return
    username, password = params[:2]
    sender = params[2] if len(params) > 2 else "client"
    is_dev = sender == "game_dev"
    user_lock = tetris_server.dev_user_lock if is_dev else tetris_server.user_lock
    db_lock = tetris_server.dev_db_lock if is_dev else tetris_server.db_lock
    users = tetris_server.dev_users if is_dev else tetris_server.users
    data_key = "game_devs" if is_dev else "users"
    async with user_lock:
        if username in users:
            await ut.send_message(writer, ut.build_response("database", "error", "Username exists, please choose a new one."))
            return
    
        hashed_pswd = ut.hash(password)
        users[username] = {
            "password": hashed_pswd,
        }
    # Update database
    async with db_lock:
        data = _load_db_document()
        data[data_key] = users
        _write_db_document(data)
        logging.info(f"[DB] Updated {config.DB_FILE} successfully.")
        
    await ut.send_message(writer, ut.build_response("database", "success", "REGISTRATION_SUCCESS"))
    logging.info(f"[DB] User {username} registered successfully.")


async def db_login(params, writer):
    if len(params) < 4:
        await ut.send_message(writer, ut.build_response("database", "error", "Invalid login payload"))
        return
    username, password, client_ip, client_port = params[:4]
    sender = params[4] if len(params) > 4 else "client"
    is_dev = sender == "game_dev"
    user_lock = tetris_server.dev_user_lock if is_dev else tetris_server.user_lock
    online_lock = tetris_server.dev_online_users_lock if is_dev else tetris_server.online_users_lock
    db_lock = tetris_server.dev_db_lock if is_dev else tetris_server.db_lock
    users = tetris_server.dev_users if is_dev else tetris_server.users
    online_users = tetris_server.dev_online_users if is_dev else tetris_server.online_users
    online_key = "game_dev_online_users" if is_dev else "online_users"

    async with user_lock:
        if username not in users:
            await ut.send_message(writer, ut.build_response("database", "error", "User not registered."))
            return
        else:
            hashed_pswd = ut.hash(password)
            if users[username]["password"] != hashed_pswd:
                await ut.send_message(writer, ut.build_response("database", "error", "Password incorrect."))
            else:  # User logs in
                async with online_lock:
                    logging.info(f"[DB] Login acquired {'dev_' if is_dev else ''}online_users_lock")
                    if username in online_users:
                        await ut.send_message(writer, ut.build_response("database", "error", "User already logged in"))
                        logging.warning(f"User {username} tried to login repeatedly.")
                        return
                    else:
                        online_users[username] = {
                            "status": "idle",
                            "ip": client_ip,
                            "port": int(client_port),
                            "invites": []
                        }
                        async with db_lock:
                            data = _load_db_document()
                            data[online_key] = online_users
                            _write_db_document(data)
                             
                logging.info(f"[DB] Login released {'dev_' if is_dev else ''}online_users_lock")
                await ut.send_message(writer, ut.build_response("database", "success", "LOGIN_SUCCESS"))
                logging.info(f"User {username} logged in successfully.")


async def db_logout(username, writer, sender=None):
    is_dev = sender == "game_dev"
    online_lock = tetris_server.dev_online_users_lock if is_dev else tetris_server.online_users_lock
    db_lock = tetris_server.dev_db_lock if is_dev else tetris_server.db_lock
    rooms_lock = tetris_server.dev_rooms_lock if is_dev else tetris_server.rooms_lock
    online_users = tetris_server.dev_online_users if is_dev else tetris_server.online_users
    rooms = tetris_server.dev_rooms if is_dev else tetris_server.rooms
    online_key = "game_dev_online_users" if is_dev else "online_users"
    rooms_key = "game_dev_rooms" if is_dev else "rooms"

    user_removed = False
    async with online_lock:
        logging.info(f"[DB] Log out acquired {'dev_' if is_dev else ''}online_users_lock")
        if username in online_users:
            del online_users[username]
            user_removed = True
            
            async with db_lock:
                data = _load_db_document()
                data[online_key] = online_users
                _write_db_document(data)
    logging.info(f"[DB] Log out released {'dev_' if is_dev else ''}online_users_lock")

    if user_removed:
        try:
            await ut.send_message(writer, ut.build_response("database", "success", "LOGOUT_SUCCESS"))
        except Exception as e:
            logging.error(f"Failed to send logout success message to {username}: {e}")

        logging.info(f"User {username} logged out.")

        async with rooms_lock:
            remove_room = []
            for room in rooms:
                if rooms[room].get('creator') == username:
                    remove_room.append(room)
            for room in remove_room:
                del rooms[room]
                logging.info(f"Removed room {room}")
            
            async with db_lock:
                data = _load_db_document()
                data[rooms_key] = rooms
                _write_db_document(data)
    else:
        await ut.send_message(writer, ut.build_response("database", "error", "User not logged in."))


"""
Game-related
"""
async def db_create_room(params, writer):
    room_id = ut.get_room_id()
    username, room_type, game_name = params
    
    # Update server
    async with tetris_server.rooms_lock:
        tetris_server.rooms[room_id] = {
            'creator': username,
            'players': [username],
            'type': room_type,
            'status': 'Waiting',
            'game_type': 'custom',
            'game_name': game_name,
            "game_results":{
                "score": 0,
                "winner": "None"
            }
        }

        async with tetris_server.db_lock:
            # Update database
            with open(config.DB_FILE, 'r') as f:
                data = json.load(f)
            
            data["rooms"] = tetris_server.rooms
            
            with open(config.DB_FILE, 'w') as f:
                json.dump(data, f, indent=4)

    async with tetris_server.online_users_lock:
        logging.info(f"[DB] Create room acquired online_users_lock")
        if username in tetris_server.online_users:
            tetris_server.online_users[username]["status"] = "in_room"
    logging.info(f"[DB] Create room released online_users_lock")
    

    response_params = [room_id, room_type, game_name]
    await ut.send_message(writer, ut.build_response("database", "success", f"CREATE_ROOM_SUCCESS {room_id}", response_params))

    logging.info(f"[DB] User {username} created room {room_id}")
    logging.info(f"[DB] Waiting for another player to join room {room_id}")
    return


    
# 
# Joining rooms
# 
async def db_join_room(params, writer):
    room_id, username = params
    
    # Check if room is available
    async with tetris_server.rooms_lock:
        if room_id not in tetris_server.rooms:
            await ut.send_message(writer, ut.build_response("database", "error", "Room does not exist"))
            return

        room = tetris_server.rooms[room_id]

        if room['status'] == 'In Game':
            await ut.send_message(writer, ut.build_response("database", "error", "Room is already in game"))
            return
        if len(room['players']) >= 2:
            await ut.send_message(writer, ut.build_response("database", "error", "Room is full"))
            return
        if room['type'] == 'private':
            await ut.send_message(writer, ut.build_response("database", "error", "Cannot join a private room without invitation"))
            return
        if username in room['players']:
            await ut.send_message(writer, ut.build_response("database", "error", "You are already in the room"))
            return

        room['players'].append(username)

    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            tetris_server.online_users[username]["status"] = "in_room"
    logging.info(f"[DB] Join room released online_users_lock")

    response_params = [room_id, room["players"], room.get("type", "public"), room.get("game_name")]
    await ut.send_message(writer, ut.build_response("database", "success", f"JOIN_ROOM_SUCCESS {room_id}", response_params))

    logging.info(f"[DB] User {username} has joined room {room_id}")
    return


async def db_leave_room(params, writer):
    username = params[0]
    room_id = None
    response_snapshot = None
    game_name = None
    async with tetris_server.rooms_lock:
        for r_id, room in list(tetris_server.rooms.items()):
            if username in room['players']:
                room['players'].remove(username)
                room_id = r_id
                game_name = room.get("game_name")
                if room['creator'] == username:
                    if room['players']:
                        room['creator'] = room['players'][0]
                    else:
                        room['creator'] = None
                if room['players']:
                    room['status'] = 'Waiting'
                    response_snapshot = {
                        "room_id": r_id,
                        "players": list(room['players']),
                        "type": room.get('type', 'public'),
                        "creator": room['creator'],
                        "status": room.get('status', 'Waiting'),
                        "game_name": game_name
                    }
                else:
                    del tetris_server.rooms[r_id]
                break
    if not room_id:
        await ut.send_message(writer, ut.build_response("database", "error", "User not in a room"))
        return

    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            tetris_server.online_users[username]["status"] = "idle"

    async with tetris_server.db_lock:
        with open(config.DB_FILE, 'r') as f:
            data = json.load(f)
        data["rooms"] = tetris_server.rooms
        data["online_users"] = tetris_server.online_users
        with open(config.DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)

    if response_snapshot:
        response_params = [
            response_snapshot["room_id"],
            response_snapshot["players"],
            response_snapshot["type"],
            response_snapshot["creator"],
            response_snapshot["status"],
            response_snapshot.get("game_name")
        ]
    else:
        response_params = [room_id, [], None, None, "deleted", game_name]
    await ut.send_message(writer, ut.build_response("database", "success", f"LEAVE_ROOM_SUCCESS {room_id}", response_params))
    logging.info(f"[DB] User {username} left room {room_id}")


async def db_invite_player(params, writer):
    target_username, room_id, inviter = params
    async with tetris_server.rooms_lock:
        if room_id not in tetris_server.rooms:
            await ut.send_message(writer, ut.build_response("database", "error", "Room does not exist"))
            return
        room = tetris_server.rooms[room_id]
        if len(room['players']) >= 2:
            await ut.send_message(writer, ut.build_response("database", "error", "Room is full"))
            return

    async with tetris_server.online_users_lock:
        logging.info(f"[DB] Invite player acquired online_users_lock")
        if target_username not in tetris_server.online_users:
            await ut.send_message(writer, ut.build_response("database", "error", "Target user not online"))
            return
        target_info = tetris_server.online_users[target_username]
        
        if target_info["status"] != "idle":
            await ut.send_message(writer, ut.build_response("database", "error", "Target user is not idle"))
            return
    logging.info(f"[DB] Invite player released online_users_lock")
        
    try:
        # send invite
        await ut.send_message(writer, ut.build_response("database", "success", f"INVITE_SENT {target_username} {room_id}"))
        logging.info(f"[DB] User {inviter} invited {target_username} to join room: {room_id}")
    except Exception as e:
        logging.error(f"[DB] Failed to send invite to {target_username}: {e}")
        await ut.send_message(writer, ut.build_response("database", "error", "Failed to send invite"))
    
    invite_info = {
        "inviter": inviter, 
        "room_id": room_id
    }
    
    async with tetris_server.online_users_lock:
        logging.info(f"[DB] Invite player acquired online_users_lock")
        tetris_server.online_users[target_username]["invites"].append(invite_info)
        async with tetris_server.db_lock:
            with open(config.DB_FILE, "r") as f:
                data = json.load(f)
            
            data["online_users"] = tetris_server.online_users
                
            with open(config.DB_FILE, "w") as f:
                json.dump(data, f, indent=4)
    logging.info(f"[DB] Invite player released online_users_lock")

    return


async def db_accept_invite(params, writer):
    inviter, room_id, username = params
    async with tetris_server.rooms_lock:
        if room_id not in tetris_server.rooms:
            await ut.send_message(writer, ut.build_response("database", "error", "Room does not exist"))
            return
        room = tetris_server.rooms[room_id]
        if room["creator"] != inviter:
            await ut.send_message(writer, ut.build_response("database", "error", "Incorrect inviter"))
            return
        if room['status'] == 'In Game':
            await ut.send_message(writer, ut.build_response("database", "error", "Room is already in game"))
            return
        if len(room['players']) >= 2:
            await ut.send_message(writer, ut.build_response("database", "error", "Room is full"))
            return
        if username in room['players']:
            await ut.send_message(writer, ut.build_response("database", "error", "You are already in the room"))
            return
        async with tetris_server.online_users_lock:
            logging.info(f"[DB] Accept invite acquired online_users_lock")
            if username not in tetris_server.online_users:
                await ut.send_message(writer, ut.build_response("database", "error", "User not online"))
                return
            invites = tetris_server.online_users[username].get("invites", [])
            remove_idx = -1
            for i, invite in enumerate(invites):
                if invite["inviter"] == inviter and invite["room_id"] == room_id:
                    remove_idx = i
                    break
            if remove_idx == -1:
                await ut.send_message(writer, ut.build_response("database", "error", "Invite not found"))
                return
            del invites[remove_idx]
            tetris_server.online_users[username]["status"] = "in_room"
            room['players'].append(username)
        logging.info(f"[DB] Accept invite released online_users_lock")

    async with tetris_server.db_lock:
        with open(config.DB_FILE, "r") as f:
            data = json.load(f)
        data["online_users"] = tetris_server.online_users
        data["rooms"] = tetris_server.rooms
        with open(config.DB_FILE, "w") as f:
            json.dump(data, f, indent=4)
    
    response_params = [room_id, room["players"], room.get("type", "public"), room.get("game_name")]
    await ut.send_message(writer, ut.build_response("database", "success", f"JOIN_ROOM_SUCCESS {room_id}", response_params))
    logging.info(f"[DB] Player {username} has joined room {room_id}")


async def db_decline_invite(params, writer):
    inviter, room_id, username = params
    async with tetris_server.rooms_lock:
        if room_id not in tetris_server.rooms:
            await ut.send_message(writer, ut.build_response("database", "error", "Room does not exist"))
            return
        room = tetris_server.rooms[room_id]
        if room["creator"] != inviter:
            await ut.send_message(writer, ut.build_response("database", "error", "Incorrect inviter"))
            return
    
    async with tetris_server.online_users_lock:
        logging.info(f"[DB] Decline invites acquired online_users_lock")
        if inviter not in tetris_server.online_users:
            await ut.send_message(writer, ut.build_response("database", "error", "Target user not online"))
            return
        
        invites = tetris_server.online_users[username]["invites"]
        remove = -1
        for i in range(len(invites)):
            if(invites[i]["inviter"] == inviter and invites[i]["room_id"] == room_id):
                remove = i
                break

        if remove == -1:
            await ut.send_message(writer, ut.build_response("database", "error", "Invite not found"))
        else:
            del tetris_server.online_users[username]["invites"][remove]
        
        async with tetris_server.db_lock:
            with open(config.DB_FILE, "r") as f:
                data = json.load(f)
            
            data["online_users"] = tetris_server.online_users
                
            with open(config.DB_FILE, "w") as f:
                json.dump(data, f, indent=4)
    logging.info(f"[DB] Decline invites released online_users_lock")
    
    try:
        # send decline
        await ut.send_message(writer, ut.build_response("database", "success", f"DECLINED_INVITE {inviter} {room_id}"))
        logging.info(f"User {username} declined invite from {inviter} to join room: {room_id}")
    except Exception as e:
        logging.error(f"Failed to send decline to {inviter}: {e}")
        await ut.send_message(writer, ut.build_response("database", "error", "Failed to send invite"))
    
            

"""
UTILS
"""
async def db_show_status(writer, params):
    username = params[0]
    try:
        async with tetris_server.online_users_lock:
            logging.info(f"[DB] Show invites acquired online_users_lock")
            users_data = [
                {"username": user, "status": info["status"]}
                for user, info in tetris_server.online_users.items()
            ]
        logging.info(f"[DB] Show invites released online_users_lock")

        async with tetris_server.rooms_lock:
            rooms_data = [
                {
                    "room_id": r_id,
                    "creator": room["creator"],
                    "status": room["status"],
                    "game_name": room.get("game_name")
                }
                for r_id, room in tetris_server.rooms.items()
                if ((room.get("type") == "public") or (room.get("type") == "private" and room["creator"] == username))
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
        status_message += "----------------------------"

        status_response = {
            "sender": "database",
            "status": "status",
            "message": status_message,
            "params": [],
            "rooms_data": rooms_data
        }
        await ut.send_message(writer, json.dumps(status_response) + '\n')
        logging.info("[DB] Sending SHOW_STATUS message to user")
    except Exception as e:
        logging.error(f"[DB] Error while processing SHOW_STATUS: {e}")
        await ut.send_message(writer, ut.build_response("database", "error", "Failed to retrieve status"))


async def db_show_invites(writer, params):
    username = params[0]
    invites = None
    async with tetris_server.online_users_lock:
        logging.info(f"[DB] Show invites acquired online_users_lock")
        invites = tetris_server.online_users[username]["invites"]
    logging.info(f"[DB] Show invites released online_users_lock")

    try:
            
        status_message = "------ List of Invites ------\n"
        if invites == None:
            status_message += "There are no invites available :(\n"
        else:
            for inv in invites:
                status_message += f"Room ID: {inv['room_id']} | Inviter: {inv['inviter']}\n"

        status_message += "----------------------------\nYou can accept invites with the \"accept\" command."

        status_response = {
            "sender": "database",
            "status": "status",
            "message": status_message,
            "params": []
        }
        await ut.send_message(writer, json.dumps(status_response) + '\n')
        logging.info("[DB] Sending CHECK message to user")
    except Exception as e:
        logging.error(f"[DB] Error while processing CHECK: {e}")
        await ut.send_message(writer, ut.build_response("database", "error", "Failed to retrieve status"))


async def db_close_server(params):
    username = params[0]
    role = params[1] if len(params) > 1 else "client"
    is_dev = role == "game_dev"
    online_lock = tetris_server.dev_online_users_lock if is_dev else tetris_server.online_users_lock
    db_lock = tetris_server.dev_db_lock if is_dev else tetris_server.db_lock
    rooms_lock = tetris_server.dev_rooms_lock if is_dev else tetris_server.rooms_lock
    online_users = tetris_server.dev_online_users if is_dev else tetris_server.online_users
    rooms = tetris_server.dev_rooms if is_dev else tetris_server.rooms
    online_key = "game_dev_online_users" if is_dev else "online_users"
    rooms_key = "game_dev_rooms" if is_dev else "rooms"

    async with online_lock:
        if username in online_users:
            del online_users[username]

        async with db_lock:
            data = _load_db_document()
            data[online_key] = online_users
            _write_db_document(data)
        logging.info(f"[DB] Close server released {'dev_' if is_dev else ''}online_users_lock")
    
    async with rooms_lock:
        rm_room = []
        for room_id, room in list(rooms.items()):
            if room.get("creator") == username:
                rm_room.append(room_id)
                
        for rm in rm_room:
            del rooms[rm]
        
        async with db_lock:
            data = _load_db_document()
            data[rooms_key] = rooms
            _write_db_document(data)
    
    logging.info(f"[DB] Successfully disconnected client {username}")


def _persist_games_unlocked():
    with open(config.GAMES_FILE, 'w') as f:
        json.dump(tetris_server.games, f, indent=4)


async def db_upload_game(params, writer):
    username, game_name, game_description, version = params
    game_description = game_description or ""
    async with tetris_server.games_lock:
        if game_name in tetris_server.games:
            await ut.send_message(writer, ut.build_response("database", "error", "Game already exists"))
            return
        tetris_server.games[game_name] = {
            "name": game_name,
            "publisher": username,
            "description": game_description,
            "file_name": game_name,
            "version": version
        }
        _persist_games_unlocked()
        game_data = dict(tetris_server.games[game_name])
    response = {
        "sender": "database",
        "status": "success",
        "message": "UPLOAD_GAME_SUCCESS",
        "game_name": game_name,
        "params": [game_data]
    }
    await ut.send_message(writer, response)
    logging.info(f"[DB] Game {game_name} uploaded by {username}")


async def db_update_game(params, writer):
    username, game_name, version, game_description = params
    game_description = game_description or ""
    async with tetris_server.games_lock:
        game_entry = tetris_server.games.get(game_name)
        if not game_entry:
            await ut.send_message(writer, ut.build_response("database", "error", "Game does not exist"))
            return
        if game_entry["publisher"] != username:
            await ut.send_message(writer, ut.build_response("database", "error", "You are not the publisher of this game"))
            return
        if game_description:
            game_entry["description"] = game_description
        game_entry["version"] = version
        _persist_games_unlocked()
        updated_entry = dict(game_entry)
    response = {
        "sender": "database",
        "status": "success",
        "message": "UPDATE_GAME_SUCCESS",
        "game_name": game_name,
        "params": [updated_entry]
    }
    await ut.send_message(writer, response)
    logging.info(f"[DB] Game {game_name} updated by {username}")


async def db_delete_game(params, writer):
    username, game_name = params
    async with tetris_server.games_lock:
        game_entry = tetris_server.games.get(game_name)
        if not game_entry:
            await ut.send_message(writer, ut.build_response("database", "error", "Game does not exist"))
            return
        if game_entry["publisher"] != username:
            await ut.send_message(writer, ut.build_response("database", "error", "You are not the publisher of this game"))
            return
        del tetris_server.games[game_name]
        _persist_games_unlocked()
    response = {
        "sender": "database",
        "status": "success",
        "message": "DELETE_GAME_SUCCESS",
        "game_name": game_name,
        "params": []
    }
    await ut.send_message(writer, response)
    logging.info(f"[DB] Game {game_name} deleted by {username}")


async def db_list_own_games(params, writer):
    username = params[0]
    async with tetris_server.games_lock:
        games_list = [
            {
                "name": name,
                "description": data.get("description", ""),
                "version": data.get("version", "N/A")
            }
            for name, data in tetris_server.games.items()
            if data.get("publisher") == username
        ]
    response = {
        "sender": "database",
        "status": "success",
        "games": games_list,
        "scope": "own"
    }
    await ut.send_message(writer, response)
    logging.info(f"[DB] Sent own games list to {username}")


async def db_list_all_games(writer):
    async with tetris_server.games_lock:
        games_list = [
            {
                "name": name,
                "description": data.get("description", ""),
                "version": data.get("version", "N/A"),
                "publisher": data.get("publisher", "unknown")
            }
            for name, data in tetris_server.games.items()
        ]
    response = {
        "sender": "database",
        "status": "success",
        "games": games_list,
        "scope": "all"
    }
    await ut.send_message(writer, response)
    logging.info("[DB] Sent marketplace games list")


async def db_leave_review(params, writer):
    if len(params) < 4:
        await ut.send_message(writer, ut.build_response("database", "error", "Invalid review payload"))
        return
    username, game_name, rating_str, comment = params[:4]
    try:
        rating = int(rating_str)
    except ValueError:
        await ut.send_message(writer, ut.build_response("database", "error", "Rating must be an integer"))
        return
    if rating < 1 or rating > 5:
        await ut.send_message(writer, ut.build_response("database", "error", "Rating must be between 1 and 5"))
        return
    review_entry = {
        "username": username,
        "rating": rating,
        "comment": comment,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    async with tetris_server.game_reviews_lock:
        reviews = tetris_server.game_reviews.setdefault(game_name, [])
        reviews.append(review_entry)
        async with tetris_server.db_lock:
            data = _load_db_document()
            data["game_reviews"] = tetris_server.game_reviews
            _write_db_document(data)
    response = {
        "sender": "database",
        "status": "success",
        "message": "LEAVE_REVIEW_SUCCESS",
        "game_name": game_name,
        "params": [review_entry]
    }
    await ut.send_message(writer, response)
    logging.info(f"[DB] Stored review for {game_name} by {username}")


async def db_get_reviews(params, writer):
    if not params:
        await ut.send_message(writer, ut.build_response("database", "error", "Missing game name for reviews"))
        return
    game_name = params[0]
    async with tetris_server.game_reviews_lock:
        reviews = list(tetris_server.game_reviews.get(game_name, []))
    response = {
        "sender": "database",
        "status": "success",
        "message": "GET_REVIEWS_SUCCESS",
        "game_name": game_name,
        "reviews": reviews
    }
    await ut.send_message(writer, response)
    logging.info(f"[DB] Sent {len(reviews)} reviews for {game_name}")


async def start_db_server():
    # init logger, remove any info from prev startup
    with open(config.LOG_FILE, 'w'):
        pass

    ut.init_logging()

    server_ = await asyncio.start_server(handle_client, config.HOST, config.DB_PORT)
    addr = server_.sockets[0].getsockname()
    logging.info(f"[DB] Database Server running on {addr}")
    print(f"[DB] Database Server running on {addr}")

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
    asyncio.run(start_db_server())
