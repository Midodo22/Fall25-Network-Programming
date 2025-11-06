import asyncio
import logging
import json
import hashlib

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
                logging.log(f"[DB] Error when unpacking message: {e}")
                
            if not message:
                logging.info(f"[DB] Connection closed by {addr}")
                break
            
            message_json = json.loads(message)
            command = message_json.get("command", "").upper()
            params = message_json.get("params", [])

            if command == "REGISTER":
                logging.log("[DB] Received command to register user")
                await db_register(params, writer)

            elif command == "CREATE_ROOM":
                await db_create_room(params, writer)

            elif command == "INVITE_PLAYER":
                await db_invite_player(params, writer)
            
            elif command == "JOIN_ROOM":
                if username:
                    await handle_join_room(params, username, writer)
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
            
            else:
                await ut.send_message(writer, ut.build_response("error", "Unknown command"))
    
    except Exception as e:
        await ut.send_message(writer, ut.build_response("error", "Db server error"))
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
        hashed_pswd = hash(password)
        tetris_server.users[username] = hashed_pswd

    # Update database
    async with tetris_server.db_lock:
        with open('data.json', 'r') as f:
            data = json.load(f)
        
        data["users"] = tetris_server.users
        
        with open('data.json', 'w') as f:
            json.dump(data, f, indent=4)
        logging.info(f"[DB] Updated data.json successfully.")
        
    await ut.send_message(writer, ut.build_response("success", "REGISTRATION_SUCCESS", "writer"))
    logging.info(f"[DB] User {username} registered successfully.")


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

    async with tetris_server.online_users_lock:
        if username in tetris_server.online_users:
            tetris_server.online_users[username]["status"] = "in_room"
    
    # Update database
    async with tetris_server.db_lock:
        with open('data.json', 'r') as f:
            data = json.load(f)
        
        data["rooms"] = tetris_server.rooms
        
        with open('data.json', 'w') as f:
            json.dump(data, f, indent=4)

    await ut.send_message(writer, ut.build_response("success", f"CREATE_ROOM_SUCCESS {room_id}"))

    logging.info(f"[DB] User {username} created room {room_id}")
    logging.info(f"[DB] Waiting for another player to join room {room_id}")
    return


async def db_join_room(params, writer):
    return


async def db_invite_player(params, writer):
    return


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
