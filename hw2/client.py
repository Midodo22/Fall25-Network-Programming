import asyncio
import json
import sys
import logging
import random
from functools import partial

import utils as ut
import config
import socket
from config import tetris_server as tetris_server

peer_info = {
    "role": None,
    "peer_ip": None,
    "peer_port": None,
    "own_port": None,
}

COMMAND_ALIASES = {
    "REGISTER": ["REGISTER", "reg", "r", "register"],
    "LOGIN": ["LOGIN", "login"],
    "LOGOUT": ["LOGOUT", "logout"],
    "CREATE_ROOM": ["CREATE_ROOM", "create", "c"],
    "INVITE_PLAYER": ["INVITE_PLAYER", "invite", "i"],
    "EXIT": ["EXIT", "exit", "quit", "q"],
    "HELP": ["HELP", "help", "h"],
    "SHOW_STATUS": ["SHOW_STATUS", "status", "s"],
}

COMMANDS = [
    "register <Username> <Password> - Register new account",
    "login <Username> <Password> - Log in",
    "logout - Log out",
    "create - Create room",
    "invite <Port> <Room ID> - Invite user to join room",
    "exit - Leave client",
    "help - Displays list of available commands",
    "status - Displays current status",
]

"""
For server
"""
username = None


async def handle_server_messages(reader, writer, game_in_progress, logged_in):
    while True:
        try:
            # data = await reader.readline()
            message = await ut.unpack_message(reader)
            if message is None:
                async with tetris_server.rooms_lock:
                    for room in tetris_server.rooms:
                        if room['creator'] not in tetris_server.online_users:
                            del tetris_server.rooms[room['room_id']]
                print("\nServer has disconnected.")
                logging.info("Server has disconnected.")
                game_in_progress.value = False
                break

            try:
                message_json = json.loads(message)
                status = message_json.get("status")
                msg = message_json.get("message", "")

                if status == "success":
                    if msg.startswith("REGISTRATION_SUCCESS"):
                        print("\nRegistration successful, please log in.\n")
                    elif msg.startswith("LOGIN_SUCCESS"):
                        print("\nYou have logged in successfully.\n")
                        logged_in.value = True
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
                        display_online_users(online_users)
                    elif update_type == "room_status":
                        room_id = message_json.get("room_id")
                        updated_status = message_json.get("status")
                        print(f"\nRoom {room_id} status updated as {updated_status}")

                elif status == "p2p_info":
                    # p2p info from server; start the peer-to-peer game
                    peer_info["role"] = message_json.get("role")
                    peer_info["peer_ip"] = message_json.get("peer_ip")
                    peer_info["peer_port"] = message_json.get("peer_port")
                    peer_info["own_port"] = message_json.get("own_port")
                    peer_info["room_id"] = message_json.get("room_id")
                    room_id = peer_info["room_id"]

                    # Initialize local board for this room
                    if not hasattr(tetris_server, "rooms"):
                        tetris_server.rooms = {}
                    if room_id not in tetris_server.rooms:
                        tetris_server.rooms[room_id] = {"board": game.board()}

                    logging.debug(f"Role: {peer_info['role']} waiting for peer: {peer_info['peer_ip']} waiting for port: {peer_info['peer_port']}, self port: {peer_info['own_port']}")
                    print(f"Role: {peer_info['role']} waiting for peer: {peer_info['peer_ip']} waiting for port: {peer_info['peer_port']}, self port: {peer_info['own_port']}")

                    asyncio.create_task(initiate_game(game_in_progress, writer, room_id))
                    game_in_progress.value = True

                elif status == "status":
                    print(f"\n{msg}")

                else:
                    print(f"\nServer：{message}")

            except json.JSONDecodeError:
                print(f"\nServer：{message}")

        except Exception as e:
            if not game_in_progress.value:
                print(f"\nError while receiving data from server: {e}")
                logging.error(f"Error when receiving data from server: {e}")
                game_in_progress.value = False
            break


async def get_user_input(prompt):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt).strip().lower())


async def handle_user_input(writer, game_in_progress, logged_in):
    while True:
        global username
        try:
            if game_in_progress.value:
                await asyncio.sleep(0.1)
                continue
            await asyncio.sleep(1)
            user_input = await get_user_input("Input a command: ")
            if not user_input:
                continue
            parts = user_input.split()
            if not parts:
                continue
            command_input = parts[0].lower()
            params = parts[1:]

            command = None
            for cmd, aliases in COMMAND_ALIASES.items():
                if command_input in [alias.lower() for alias in aliases]:
                    command = cmd
                    break

            if not command:
                print("Invalid command, input 'help' to see list of available commands.")
                continue

            if command == "EXIT":
                print("Exiting...")
                logging.info("User chose to leave client.")
                if logged_in.value:
                    await ut.send_command(writer, "LOGOUT", [])
                game_in_progress.value = False
                try:
                    writer.close()
                    await writer.wait_closed()
                except:
                    pass
                # make sure program exits
                asyncio.get_event_loop().stop()
                break

            elif command == "HELP":
                print("\nAvailable commands:")
                for cmd in COMMANDS:
                    print(cmd)
                print("")
                continue

            elif command == "REGISTER":
                if len(params) != 2:
                    print("Usage: reg <username> <password>")
                    continue
                await ut.send_command(writer, "REGISTER", params)

            elif command == "LOGIN":
                if len(params) != 2:
                    print("Usage: login <username> <password>")
                    continue
                username = params[0]
                await ut.send_command(writer, "LOGIN", params)

            elif command == "LOGOUT":
                if not logged_in.value:
                    print("You aren't logged in.")
                    continue
                await ut.send_command(writer, "LOGOUT", [])

            elif command == "CREATE_ROOM":
                await ut.send_command(writer, "CREATE_ROOM", params)

            elif command == "INVITE_PLAYER":
                if len(params) != 2:
                    print("Usage: invite <Port> <Room ID>")
                    continue
                # await ut.send_command(writer, "INVITE_PLAYER", params)
                udp_port, room_id = params
                await send_invite(udp_port, room_id, username)

            elif command == "SHOW_STATUS":
                await ut.send_command(writer, "SHOW_STATUS", [])

            elif command == "JOIN_ROOM":
                if len(params) != 1:
                    print("Usage: join <Room ID>")
                    continue
                await ut.send_command(writer, "JOIN_ROOM", params)

            else:
                print("Invalid command, input 'help' to see list of available commands.")
        except KeyboardInterrupt:
            print("Exiting...")
            logging.info("User chose to leave client via keyboard interrupt.")
            await ut.send_command(writer, "LOGOUT", [])
            game_in_progress.value = False
            writer.close()
            await writer.wait_closed()
            break
        except Exception as e:
            print(f"Error when sending command: {e}")
            logging.error(f"Error when sending command: {e}")
            game_in_progress.value = False
            writer.close()
            await writer.wait_closed()
            break


"""
For game
"""


async def initiate_game(game_in_progress, writer, room_id):
    logging.info(f"Initiating game for room {room_id}...")
    try:
        if peer_info.get("role") == "host":
            await start_game_as_host(peer_info.get("own_port"), room_id)
        elif peer_info.get("role") == "client":
            await start_game_as_client(peer_info.get("peer_ip"), peer_info.get("peer_port"), room_id)

    finally:
        game_in_progress.value = False
        await ut.send_command(writer, "GAME_OVER", [])


async def start_game_as_host(own_port, room_id):

    game_server = await asyncio.start_server(
        partial(handle_game_client, room_id=room_id),
        config.HOST, own_port
    )

    # server = await asyncio.start_server(handle_game_client, config.HOST, own_port, room_id)
    logging.info(f"Waiting for client to connect to {own_port} as game server...")
    print(f"Waiting for client to connect to {own_port} as game server...")

    global server_close_event
    server_close_event = asyncio.Event()

    async def stop_server():
        await server_close_event.wait()
        game_server.close()
        await game_server.wait_closed()
        print("Game sever is closed.")

    async with game_server:
        await asyncio.gather(game_server.serve_forever(), stop_server())


async def handle_game_client(reader, writer, room_id):
    try:
        print("Client has connected.")
        await game_loop(reader, writer, "Host")
    except Exception as e:
        logging.error(f"Server error: {e}")
    finally:
        writer.close()
        await writer.wait_closed()


async def start_game_as_client(peer_ip, peer_port, room_id, max_retries=10, retry_delay=2):
    writer = None
    retries = 0

    while retries < max_retries:
        try:
            print(f"Connecting to server of {peer_ip}:{peer_port} as client... [Total tries: {retries + 1}]")
            reader, writer = await asyncio.open_connection(peer_ip, peer_port)
            print("Successfully connected to server.")
            await game_loop(reader, writer, "Client")
            break

        except ConnectionRefusedError:
            retries += 1
            if retries >= max_retries:
                logging.error(f"Failed to connect after {max_retries} tries.")
                print(f"Failed to connect after {max_retries} tries. Exiting...")
                return
            else:
                print(f"Connection declined, retrying after {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)

        except Exception as e:
            logging.error(f"Failed to start client server: {e}")
            break

    if writer is not None:
        writer.close()
        await writer.wait_closed()


"""
For broadcast
"""
def display_online_users(online_users):
    print("\n--- List of Online Users ---")
    if not online_users:
        print("No users are online :(")
    else:
        for user in online_users:
            name = user.get("username", "未知")
            status = user.get("status", "未知")
            print(f"User: {name} - Status: {status}")
    print("----------------------------\nInput a command: ")


def display_public_rooms(public_rooms):
    print("\n------ List of Rooms ------")
    if not public_rooms:
        print("There are no rooms available :(")
    else:
        for room in public_rooms:
            room_id = room.get("room_id", "未知")
            creator = room.get("creator", "未知")
            room_status = room.get("status", "未知")
            print(f"Room ID: {room_id} | Creator: {creator} | Status: {room_status}")
    print("----------------------------\nInput a command: ")


async def main():
    ut.init_logging()

    server_ip = config.HOST
    server_port = config.PORT

    try:
        reader, writer = await asyncio.open_connection(server_ip, server_port)
        print("Successfully connected to lobby server.")
        logging.info(f"Successfully connected to lobby server {server_ip}:{server_port}")
    except ConnectionRefusedError:
        print("Connection declined, please check if the server is running.")
        logging.error("Connection declined, please check if the server is running.")
        return
    except Exception as e:
        print(f"Unable to connect to server: {e}")
        logging.error(f"Unable to connect to server: {e}")
        return

    game_in_progress = type('', (), {'value': False})()
    logged_in = type('', (), {'value': False})()

    asyncio.create_task(handle_server_messages(reader, writer, game_in_progress, logged_in))
    asyncio.create_task(handle_user_input(writer, game_in_progress, logged_in))

    print("\nAvailable commands: ")
    for cmd in COMMANDS:
        print(cmd)
    print("")

    await asyncio.Future()

    print("Client end closed.")
    logging.info("Client end closed.")
    sys.exit()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Client end terminated with error: {e}")
        logging.error(f"Client end terminated with error: {e}")
