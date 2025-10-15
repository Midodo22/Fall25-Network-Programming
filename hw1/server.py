import asyncio
import logging
import json
import utils as ut
import uuid
import game
import config
from config import server_data as server

ut.init_logging()

    
async def handle_create_room(username, writer):
    room_id = str(uuid.uuid4())
    async with server.rooms_lock:
        server.rooms[room_id] = {
            'creator': username,
            'status': 'waiting',
            'players': [username],
            'board': game.board()
        }

    async with server.online_users_lock:
        if username in server.online_users:
            server.online_users[username]["status"] = "in_room"
    await ut.send_message(writer, ut.build_response("success", f"CREATE_ROOM_SUCCESS {room_id}"))
    # Broadcast updated room list for all users to see
    async with server.rooms_lock:
        room_data = [
            {
                "room_id": r_id,
                "creator": room["creator"],
                "status": room["status"]
            }
            for r_id, room in server.rooms.items()
        ]
    room_message = {
        "status": "update",
        "data": room_data
    }
    await ut.broadcast(json.dumps(room_message) + '\n')
    
    logging.info(f"User {username} created room {room_id}")
    logging.info(f"Waiting for another player to join room {room_id}")


async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    logging.info(f"Connection from {addr}")
    username = None
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
                    await ut.handle_register(params, writer)

                elif command == "LOGIN":
                    await ut.handle_login(params, reader, writer)
                    if len(params) >= 1:
                        username = params[0]

                elif command == "LOGOUT":
                    if username:
                        await ut.handle_logout(username, writer)
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

                elif command == "ACCEPT_INVITE":
                    if username:
                        await handle_accept_invite(params, username, writer)
                    else:
                        await ut.send_message(writer, ut.build_response("error", "Not logged in"))

                elif command == "DECLINE_INVITE":
                    if username:
                        await handle_decline_invite(params, username, writer)
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
            async with server.online_users_lock:
                if username in server.online_users:
                    del server.online_users[username]
                    user_removed = True
            if user_removed:
                try:
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
                    await ut.broadcast(json.dumps(online_users_message) + '\n')
                    logging.info(f"User disconnected: {username}")
                except Exception as e:
                    logging.error(f"Failed to broadcast updated online users list after disconnection: {e}")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def handle_show_status(writer):
    try:
        async with server.online_users_lock:
            users_data = [
                {"username": user, "status": info["status"]}
                for user, info in server.online_users.items()
            ]
        
        async with server.rooms_lock:
            rooms_data = [
                {
                    "room_id": r_id,
                    "creator": room["creator"],
                    "status": room["status"]
                }
                for r_id, room in server.rooms.items()
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
    async with server.online_users_lock:
        if username in server.online_users:
            server.online_users[username]["status"] = "idle"

    room_to_delete = None
    async with server.rooms_lock:
        for room_id, room in list(server.rooms.items()):
            if username in room["players"]:
                room["players"].remove(username)
                if len(room["players"]) == 0:
                    room_to_delete = room_id
                else:
                    # If room still has players, update its status to "Waiting"
                    room["status"] = "Waiting"
                break
        if room_to_delete:
            del server.rooms[room_to_delete]

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
    await ut.broadcast(json.dumps(online_users_message) + '\n')

    async with server.rooms_lock:
        rooms_data = [
            {
                "room_id": r_id,
                "creator": room["creator"],
                "status": room["status"]
            }
            for r_id, room in server.rooms.items()
        ]
    rooms_message = {
        "status": "update",
        "data": rooms_data
    }
    await ut.broadcast(json.dumps(rooms_message) + '\n')

    logging.info(f"User {username} has ended the game and is now idle.")
    

async def handle_decline_invite(params, username, writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("error", "Invalid DECLINE_INVITE command"))
        return
    inviter_username, room_id = params
    # Notify inviter that invite was declined
    async with server.online_users_lock:
        if inviter_username in server.online_users:
            inviter_info = server.online_users[inviter_username]
            inviter_writer = inviter_info["writer"]
            decline_message = {
                "status": "invite_declined",
                "from": username,
                "room_id": room_id
            }
            await ut.send_message(inviter_writer, json.dumps(decline_message) + '\n')
            logging.info(f"User {username} declined invitation from {inviter_username} to room: {room_id}")
    await ut.send_message(writer, ut.build_response("success", f"DECLINE_INVITE_SUCCESS {room_id}"))
    
async def handle_accept_invite(params, username, writer):
    if len(params) != 1:
        await ut.send_message(writer, ut.build_response("error", "Invalid ACCEPT_INVITE command"))
        return
    room_id = params[0]
    async with server.rooms_lock:
        if room_id not in server.rooms:
            await ut.send_message(writer, ut.build_response("error", "Room does not exist"))
            return
        room = server.rooms[room_id]
        if room['status'] == 'In Game':
            await ut.send_message(writer, ut.build_response("error", "Room is already in game"))
            return
        if len(room['players']) >= 2:
            await ut.send_message(writer, ut.build_response("error", "Room is full"))
            return
        if username in room['players']:
            await ut.send_message(writer, ut.build_response("error", "You are already in the room"))
            return
        room['players'].append(username)

    async with server.online_users_lock:
        if username in server.online_users:
            server.online_users[username]["status"] = "in_room"
    await ut.send_message(writer, ut.build_response("success", f"JOIN_ROOM_SUCCESS {room_id}"))
    
    if len(room['players']) == 2:
        async with server.rooms_lock:
            room['status'] = 'In Game'
            creator = room["players"][0]
            joiner = username
            
            async with server.online_users_lock:
                for player in room['players']:
                    if player in server.online_users:
                        server.online_users[player]["status"] = "in_game"

                creator_info = server.online_users[creator]
                joiner_info = server.online_users[joiner]
                creator_port = ut.get_port()
                joiner_port = ut.get_port()
                creator_message = {
                    "status": "p2p_info",
                    "role": "host",
                    "peer_ip": joiner_info["ip"],
                    "peer_port": joiner_port,
                    "own_port": creator_port,
                }
                joiner_message = {
                    "status": "p2p_info",
                    "role": "client",
                    "peer_ip": creator_info["ip"],
                    "peer_port": creator_port,
                    "own_port": joiner_port,
                }
                await ut.send_message(creator_info["writer"], json.dumps(creator_message) + '\n')
                await ut.send_message(joiner_info["writer"], json.dumps(joiner_message) + '\n')
            logging.info(f"Game server info sent to players in room: {room_id}")

    async with server.rooms_lock:
        rooms_data = [
            {
                "room_id": r_id,
                "creator": room["creator"],
                "status": room["status"]
            }
            for r_id, room in server.rooms.items()
        ]
    rooms_message = {
        "status": "update",
        "data": rooms_data
    }
    await ut.broadcast(json.dumps(rooms_message) + '\n')
    logging.info(f"User {username} accepted invite to join room: {room_id}")
    
async def handle_invite_player(params, username, writer):
    if len(params) != 2:
        await ut.send_message(writer, ut.build_response("error", "Invalid INVITE_PLAYER command"))
        return
    target_username, room_id = params
    
    # Check if room is available
    async with server.rooms_lock:
        if room_id not in server.rooms:
            await ut.send_message(writer, ut.build_response("error", "Room does not exist"))
            return
        room = server.rooms[room_id]
        if room['creator'] != username:
            await ut.send_message(writer, ut.build_response("error", "Only room creator can invite players"))
            return
        if len(room['players']) >= 2:
            await ut.send_message(writer, ut.build_response("error", "Room is full"))
            return
        
    # Check user
    async with server.online_users_lock:
        if target_username not in server.online_users:
            await ut.send_message(writer, ut.build_response("error", "Target user not online"))
            return
        target_info = server.online_users[target_username]
        if target_info["status"] != "idle":
            await ut.send_message(writer, ut.build_response("error", "Target user is not idle"))
            return
        # target_writer = target_info["writer"]
    await ut.send_message(writer, ut.build_response("success", f"READY_TO_INVITE {target_username} {room_id}"))
    logging.info(f"User {username} is ready to send UDP invite to {target_username}")

async def main():  
    server_ = await asyncio.start_server(handle_client, config.HOST, config.PORT)
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
