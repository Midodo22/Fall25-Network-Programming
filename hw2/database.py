import asyncio
import logging
import json

import utils as ut
import config
from config import tetris_server

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
                await db_logout(params, writer)

            elif command == "CREATE_ROOM":
                logging.info("[DB] Received command to create room")
                await db_create_room(params, writer)

            elif command == "INVITE_PLAYER":
                await db_invite_player(params, writer)
            
            elif command == "JOIN_ROOM":
                await db_join_room(params, writer)

        
            # elif command == "GAME_OVER":
            #     if username:
            #         await handle_game_over(username)
            #     else:
            #         await ut.send_message(writer, ut.build_response("database", "error", "Not logged in"))
            
            elif command == "SHOW_STATUS":
                await db_show_status(writer)

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
    username, password = params
    async with tetris_server.user_lock:
        if username in tetris_server.users:
            await ut.send_message(writer, ut.build_response("database", "error", "Username exists, please choose a new one."))
            return
    
        hashed_pswd = ut.hash(password)
        tetris_server.users[username] = {
            "password": hashed_pswd,
        }
    
    print(tetris_server.users)

    # Update database
    async with tetris_server.db_lock:
        with open(config.DB_FILE, 'r') as f:
            data = json.load(f)
        
        data["users"] = tetris_server.users
        
        with open(config.DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        logging.info(f"[DB] Updated {config.DB_FILE} successfully.")
        
    await ut.send_message(writer, ut.build_response("database", "success", "REGISTRATION_SUCCESS"))
    logging.info(f"[DB] User {username} registered successfully.")


async def db_login(params, writer):
    username, password, client_ip, client_port = params

    async with tetris_server.user_lock:
        if username not in tetris_server.users:
            await ut.send_message(writer, ut.build_response("database", "error", "User not registered."))
            return
        else:
            hashed_pswd = ut.hash(password)
            if tetris_server.users[username]["password"] != hashed_pswd:
                await ut.send_message(writer, ut.build_response("database", "error", "Password incorrect."))
            else:  # User logs in
                async with tetris_server.online_users_lock:
                    if username in tetris_server.online_users:
                        await ut.send_message(writer, ut.build_response("database", "error", "User already logged in"))
                        logging.warning(f"User {username} tried to login repeatedly.")
                        return
                    else:
                        tetris_server.online_users[username] = {
                            "status": "idle",
                            "ip": client_ip,
                            "port": int(client_port),
                            "invites": []
                        }
                        async with tetris_server.db_lock:
                            with open(config.DB_FILE, 'r') as f:
                                data = json.load(f)
                            
                            data["online_users"] = tetris_server.online_users
                            
                            with open(config.DB_FILE, 'w') as f:
                                json.dump(data, f, indent=4)
                            
                await ut.send_message(writer, ut.build_response("database", "success", "LOGIN_SUCCESS"))
                logging.info(f"User {username} logged in successfully.")


async def db_logout(username, writer):
    user_removed = False
    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            del tetris_server.online_users[username]
            user_removed = True
            
            async with tetris_server.db_lock:
                async with tetris_server.db_lock:
                    with open(config.DB_FILE, 'r') as f:
                        data = json.load(f)
                    
                    data["online_users"] = tetris_server.online_users
                    
                    with open(config.DB_FILE, 'w') as f:
                        json.dump(data, f, indent=4)

    if user_removed:
        try:
            await ut.send_message(writer, ut.build_response("database", "success", "LOGOUT_SUCCESS"))
        except Exception as e:
            logging.error(f"Failed to send logout success message to {username}: {e}")

        logging.info(f"User {username} logged out.")

        async with tetris_server.rooms_lock:
            remove_room = []
            for room in tetris_server.rooms:
                if tetris_server.rooms[room]['creator'] == username:
                    remove_room.append(room)
            for room in remove_room:
                del tetris_server.rooms[room]
                logging.info(f"Removed room {room}")
            
            async with tetris_server.db_lock:
                with open(config.DB_FILE, 'r') as f:
                    data = json.load(f)
                
                data["rooms"] = tetris_server.rooms
                
                with open(config.DB_FILE, 'w') as f:
                    json.dump(data, f, indent=4)
    else:
        await ut.send_message(writer, ut.build_response("database", "error", "User not logged in."))


"""
Game-related
"""
async def db_create_room(params, writer):
    room_id = ut.get_room_id()
    username, room_type = params
    
    # Update server
    async with tetris_server.rooms_lock:
        tetris_server.rooms[room_id] = {
            'creator': username,
            'players': [username],
            'type': room_type,
            'status': 'waiting',
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
        if username in tetris_server.online_users:
            tetris_server.online_users[username]["status"] = "in_room"
    

    await ut.send_message(writer, ut.build_response("database", "success", f"CREATE_ROOM_SUCCESS {room_id}"))

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
        if room['type'] == 'private' and username not in room['players']:
            await ut.send_message(writer, ut.build_response("database", "error", "Cannot join a private room without invitation"))
            return
        if username in room['players']:
            await ut.send_message(writer, ut.build_response("database", "error", "You are already in the room"))
            return

        room['players'].append(username)

    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            tetris_server.online_users[username]["status"] = "in_room"

    await ut.send_message(writer, ut.build_response("database", "success", f"JOIN_ROOM_SUCCESS {room_id}"))

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
        
            async with tetris_server.db_lock:
                with open(config.DB_FILE, "r") as f:
                    data = json.load(f)
                
                data["rooms"] = tetris_server.rooms
                    
                with open(config.DB_FILE, "w") as f:
                    json.dump(data, f, indent=4)
                
        logging.info(f"[Lobby] Game server info has been sent to players in room {room_id}")

    logging.info(f"[Lobby] User {username} has joined room {room_id}")
    return


async def db_invite_player(params, writer):
    target_username, room_id, inviter = params
    async with tetris_server.rooms_lock:
        if room_id not in tetris_server.rooms:
            await ut.send_message(writer, ut.build_response("database", "error", "Room does not exist"))
            return
        room = tetris_server.rooms[room_id]
        if room['creator'] != inviter:
            print(inviter)
            await ut.send_message(writer, ut.build_response("database", "error", "Only room creator can invite players"))
            return
        if len(room['players']) >= 2:
            await ut.send_message(writer, ut.build_response("database", "error", "Room is full"))
            return

    async with tetris_server.online_users_lock:
        if target_username not in tetris_server.online_users:
            await ut.send_message(writer, ut.build_response("database", "error", "Target user not online"))
            return
        target_info = tetris_server.online_users[target_username]
        
        if target_info["status"] != "idle":
            await ut.send_message(writer, ut.build_response("database", "error", "Target user is not idle"))
            return
        
    try:
        # send invite
        await ut.send_message(writer, ut.build_response("database", "success", f"INVITE_SENT {target_username} {room_id}"))
        logging.info(f"User {inviter} invited {target_username} to join room: {room_id}")
    except Exception as e:
        logging.error(f"Failed to send invite to {target_username}: {e}")
        await ut.send_message(writer, ut.build_response("database", "error", "Failed to send invite"))
    
    invite_info = {
        "inviter": inviter, 
        "room_id": room_id
    }
    
    async with tetris_server.online_users_lock:
        tetris_server.online_users[target_username]["invites"].append(invite_info)
        async with tetris_server.db_lock:
            with open(config.DB_FILE, "r") as f:
                data = json.load(f)
            
            data["online_users"] = tetris_server.online_users
                
            with open(config.DB_FILE, "w") as f:
                json.dump(data, f, indent=4)

    return


"""
UTILS
"""
async def db_show_status(writer):
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
        status_message += "----------------------------"

        status_response = {
            "sender": "database",
            "status": "status",
            "message": status_message,
            "params": []
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
        invites = tetris_server.online_users[username]["invites"]

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
    async with tetris_server.online_users_lock:
        if(username in tetris_server.online_users):
            del tetris_server.online_users[username]
        
        async with tetris_server.db_lock:
            with open(config.DB_FILE, "r") as f:
                data = json.load(f)
            
            data["online_users"] = tetris_server.online_users
                
            with open(config.DB_FILE, "w") as f:
                json.dump(data, f, indent=4)
    
    async with tetris_server.rooms_lock:
        rm_room = []
        for room in tetris_server.rooms:
            if(tetris_server.rooms[room]["creator"] == username):
                rm_room.append(room)
                
        for rm in rm_room:
            del tetris_server.rooms[rm]
        
        async with tetris_server.db_lock:
            with open(config.DB_FILE, "r") as f:
                data = json.load(f)
            
            data["rooms"] = tetris_server.rooms
                
            with open(config.DB_FILE, "w") as f:
                json.dump(data, f, indent=4)
    
    logging.info(f"[DB] Successfully disconnected client {username}")


async def main():
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
    asyncio.run(main())
