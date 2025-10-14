import asyncio
import json
import sys
import logging
import utils as ut
import server
import game
import config
import socket
from config import server_data as server

logging.basicConfig(
    filename='client.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

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
    "JOIN_ROOM": ["JOIN_ROOM", "join", "j"],
    "INVITE_PLAYER": ["INVITE_PLAYER", "invite", "i"],
    "EXIT": ["EXIT", "exit", "quit", "q"],
    "HELP": ["HELP", "help", "h"],
    "SHOW_STATUS": ["SHOW_STATUS", "status", "s"],
    "SCAN": ["SCAN", "scan"]
}

COMMANDS = [
    "register <Username> <Password> - Register new account",
    "login <Username> <Password> - Log in",
    "logout - Log out",
    "create - Create room",
    # "join <Room ID> - Join room",
    "invite <Username> <Room ID> - Invite user to join room",
    "exit - Leave client",
    "help - Displays list of available commands",
    "status - Displays current status",
    "scan - Scans UDP ports for available players"
]

"""
For server
"""
async def handle_server_messages(reader, writer, game_in_progress, logged_in):
    while True:
        try:
            data = await reader.readline()
            if not data:
                print("\nServer has disconnected.")
                logging.info("Server has disconnected.")
                game_in_progress.value = False
                break
            message = data.decode().strip()
            if not message:
                continue
            
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
                    elif msg.startswith("INVITE_SENT"):
                        print(f"\nInvite has been sent.\n")
                    elif msg.startswith("READY_TO_INVITE"):
                        parts = msg.split()
                        if len(parts) >= 3:
                            target_username = parts[1]
                            room_id = parts[2]
                            print(f"\n[INFO] You can now invite {target_username} via UDP for room {room_id}.")
                            await send_udp_invite(target_username)

                elif status == "error":
                    print(f"\nError: {msg}\n")
                elif status == "invite":
                    sender = message_json.get("from")
                    room_id = message_json.get("room_id")
                    response = await get_user_input(f"\nYou have received an invite from {sender} Would you like to join their room {room_id}? (yes/no)：\n")
                    if response == 'yes':
                        await ut.send_command(writer, "ACCEPT_INVITE", [room_id])
                        logging.info(f"You have accepted the invite to join room {room_id}.")
                    else:
                        await ut.send_command(writer, "DECLINE_INVITE", [sender, room_id])
                        print("You have declined the invite.")
                        logging.info(f"Invite to {room_id} has been declined.")
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
                    peer_info["role"] = message_json.get("role")
                    peer_info["peer_ip"] = message_json.get("peer_ip")
                    peer_info["peer_port"] = message_json.get("peer_port")
                    peer_info["own_port"] = message_json.get("own_port")
                    
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
                await ut.send_command(writer, "LOGOUT", [])
                game_in_progress.value = False
                writer.close()
                await writer.wait_closed()
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
                await ut.send_command(writer, "LOGIN", params)

            elif command == "LOGOUT":
                if not logged_in.value:
                    print("You aren't logged in.")
                    continue
                await ut.send_command(writer, "LOGOUT", [])

            elif command == "CREATE_ROOM":
                await ut.send_command(writer, "CREATE_ROOM", params)

            elif command == "JOIN_ROOM":
                if len(params) != 1:
                    print("Usage: join <Room ID>")
                    continue
                await ut.send_command(writer, "JOIN_ROOM", params)

            elif command == "INVITE_PLAYER":
                if len(params) != 2:
                    print("Usage: invite <username> <Room ID>")
                    continue
                await ut.send_command(writer, "INVITE_PLAYER", params)

            elif command == "SHOW_STATUS":
                await ut.send_command(writer, "SHOW_STATUS", [])
                
            elif command == "SCAN":
                players = await udp_discover_players()
                if players:
                    target_ip = players[0]  # example: pick first
                    print(f"[UDP] Sending invite to {target_ip}")
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    await asyncio.get_event_loop().sock_sendto(b"INVITE", (target_ip, config.UDP_PORT))
                else:
                    print("No players found.")

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
    try:
        if peer_info.get("role") == "host":
                await start_game_as_host(peer_info.get("own_port"), room_id)
        elif peer_info.get("role") == "client":
            await start_game_as_client(peer_info.get("peer_ip"), peer_info.get("peer_port"), room_id)

    finally:
        game_in_progress.value = False
        await ut.send_command(writer, "GAME_OVER", [])


async def start_game_as_host(own_port, room_id):
    server = await asyncio.start_server(handle_game_client, '0.0.0.0', own_port, room_id)
    logging.info(f"Waiting for client to connect to {own_port} as game server...")
    print(f"Waiting for client to connect to {own_port} as game server...")
    
    global server_close_event
    server_close_event = asyncio.Event()

    async def stop_server():
        await server_close_event.wait()
        server.close()
        await server.wait_closed()
        print("Game sever is closed.")

    async with server:
        await asyncio.gather(server.serve_forever(), stop_server())


async def handle_game_client(reader, writer, room_id):
    try:
        print("Client has connected.")
        await game_loop(reader, writer, "Host", room_id)
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
            await game_loop(reader, writer, "Client", room_id)
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


async def game_loop(reader, writer, role, room_id):
    my_move = None
    opponent_move = None
    game_over = False

    while not game_over:
        if role == "Host":
            # Host move
            my_move = await get_move("Host", server, room_id)
            await ut.send_message(writer, {"move": my_move})
            print("Waiting for opponent to choose pocket...")
            data = await reader.read(1024)
            if not data:
                print("Opponent has disconnected.")
                game_over = True
                break
            try:
                message = json.loads(data.decode())
                opponent_move = message.get("move")
                if not check_move(opponent_move):
                    print("Received invalid move.")
                    continue
            except json.JSONDecodeError:
                print("Received invalid message.")
                continue
        else:
            # Client move
            print("Waiting for opponent to choose pocket...")
            data = await reader.read(1024)
            if not data:
                print("Opponent has disconnected.")
                game_over = True
                break
            try:
                message = json.loads(data.decode())
                opponent_move = message.get("move")
                if not check_move(opponent_move):
                    print("Received invalid move.")
                    continue
            except json.JSONDecodeError:
                print("Received invalid message.")
                continue
            my_move = await get_move("Client")
            await ut.send_message(writer, {"move": my_move})

        if game.det_game_over(room_id):
            game_over = True
            server_close_event.set()
            game.det_winner(my_move, opponent_move, role)
        else:
            game.update_board()


async def check_move(input, room_id):
    try:
        move = int(input)
        cur_board = server.rooms[room_id]['board']
        if move > 6 or cur_board.BP1[move - 1] == 0:
            return False
        return True
    except:
        return False


async def get_move(player, room_id):
    while True:
        game.print_board(server, room_id)
        input = await get_user_input(f"{player}, which pocket do you want to move?")
        try:
            move = int(input)
            cur_board = server.rooms[room_id]['board']
            if move > 6:
                print("Index out of range, please choose another pocket.")
                continue
            elif cur_board.BP1[move - 1] == 0:
                print('There are no stones in that pocket.\nChoose another pocket.\n')
                continue
            
            game.update_board(player, server, room_id)
            return move                
        except ValueError:
            print("That is not a valid move, please try again.")


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
    print("----------------------------")


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
    print("----------------------------")


"""
For UDP Invite
"""
async def udp_listener():
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', config.UDP_PORT))
    sock.setblocking(False)
    print(f"[UDP] Listening on port {config.UDP_PORT} for invites...")

    while True:
        data, addr = await loop.sock_recvfrom(sock, 1024)
        msg = data.decode().strip()
        if msg.startswith("INVITE"):
            sender_ip = addr[0]
            print(f"[UDP] Received invitation from {sender_ip}")
            response = input("Accept invite? (yes/no): ").strip().lower()
            if response == "yes":
                await loop.sock_sendto(b"ACCEPT", addr)
            else:
                await loop.sock_sendto(b"DECLINE", addr)


async def udp_discover_players():
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    print("[UDP] Scanning for available players...")
    await loop.sock_sendto(b"DISCOVER", ('255.255.255.255', config.UDP_PORT))

    found = []
    try:
        while True:
            data, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 1024), timeout=3)
            msg = data.decode().strip()
            if msg.startswith("AVAILABLE"):
                found.append(addr[0])
                print(f"Found player at {addr[0]}")
    except asyncio.TimeoutError:
        pass

    print(f"[UDP] Discovery complete. Found: {found}")
    return found

async def send_udp_invite(target_username):
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    print(f"[UDP] Searching for {target_username}...")
    await loop.sock_sendto(b"DISCOVER", ('255.255.255.255', config.UDP_PORT))

    found_ip = None
    try:
        while True:
            data, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 1024), timeout=3)
            msg = data.decode().strip()
            if msg.startswith("AVAILABLE"):
                found_ip = addr[0]
                print(f"[UDP] Found {target_username} at {found_ip}")
                break
    except asyncio.TimeoutError:
        print("[UDP] Discovery timeout. No player found.")
        return

    if found_ip:
        print(f"[UDP] Sending invitation to {found_ip}:{config.UDP_PORT}")
        await loop.sock_sendto(b"INVITE", (found_ip, config.UDP_PORT))
        print(f"[UDP] Invitation sent to {target_username}.")


async def main():
    server_ip = input(f"Input server IP（Default：{config.HOST}）：").strip()
    server_ip = server_ip if server_ip else config.HOST
    server_port_input = input(f"Input server port（Default：{config.PORT}）：").strip()
    try:
        server_port = int(server_port_input) if server_port_input else config.PORT
    except ValueError:
        print("Invalid port, using default port 15000.")
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