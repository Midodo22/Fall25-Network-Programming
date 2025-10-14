import asyncio
import json
import sys
import logging
import utils as ut
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

# store logged-in username here when client logs in
USERNAME = None

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
For server (TCP lobby)
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
                        # server sends: READY_TO_INVITE <target_username> <room_id>
                        if len(parts) >= 3:
                            target_username = parts[1]
                            room_id = parts[2]
                            print(f"\n[INFO] You can now invite {target_username} via UDP for room {room_id}.")
                            # pass writer so UDP listener on other side can respond with TCP ACCEPT/DECLINE
                            await send_udp_invite(target_username, room_id, writer)

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
                    elif update_type == "room_status" or update_type == "public_rooms":
                        room_id = message_json.get("room_id")
                        updated_status = message_json.get("status")
                        print(f"\nRoom {room_id} status updated as {updated_status}")
                elif status == "p2p_info":
                    # p2p info from server; start the peer-to-peer game
                    peer_info["role"] = message_json.get("role")
                    peer_info["peer_ip"] = message_json.get("peer_ip")
                    peer_info["peer_port"] = message_json.get("peer_port")
                    peer_info["own_port"] = message_json.get("own_port")
                    
                    logging.debug(f"Role: {peer_info['role']} waiting for peer: {peer_info['peer_ip']} waiting for port: {peer_info['peer_port']}, self port: {peer_info['own_port']}")
                    print(f"Role: {peer_info['role']} waiting for peer: {peer_info['peer_ip']} waiting for port: {peer_info['peer_port']}, self port: {peer_info['own_port']}")
                    # room_id isn't included here; server's message flow pairs players after JOIN/ACCEPT
                    # We don't have the room_id here in p2p_info; game functions expect room_id.
                    # But the server sends p2p_info after room status change to In Game - both clients should already have the room id locally if needed.
                    # In our earlier logic READY_TO_INVITE provided room_id; when JOIN_ROOM returns JOIN_ROOM_SUCCESS we get room id then.
                    # For simplicity, we will start the P2P game with the room id if available in message; otherwise, use a best effort variable.
                    room_id = message_json.get("room_id")
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
    global USERNAME
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
                # store username locally
                USERNAME = params[0]
                await ut.send_command(writer, "LOGIN", params)

            elif command == "LOGOUT":
                if not logged_in.value:
                    print("You aren't logged in.")
                    continue
                await ut.send_command(writer, "LOGOUT", [])
                USERNAME = None

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
                    # present options
                    print("[UDP] Found players:")
                    for i, p in enumerate(players):
                        print(f"{i}: {p[0]} @ {p[1]}:{p[2]}")
                    target = players[0]  # pick first by default
                    target_ip = target[1]
                    target_port = target[2]
                    print(f"[UDP] Sending invite test to {target_ip}:{target_port}")
                    loop = asyncio.get_event_loop()
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.setblocking(False)
                    await loop.sock_sendto(b"INVITE_TEST", (target_ip, target_port))
                    sock.close()
                else:
                    print("No players found.")

            else:
                print("Invalid command, input 'help' to see list of available commands.")
        except KeyboardInterrupt:
            print("Exiting...")
            logging.info("User chose to leave client via keyboard interrupt.")
            if logged_in.value:
                await ut.send_command(writer, "LOGOUT", [])
            game_in_progress.value = False
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
            break
        except Exception as e:
            print(f"Error when sending command: {e}")
            logging.error(f"Error when sending command: {e}")
            game_in_progress.value = False
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
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
        try:
            await ut.send_command(writer, "GAME_OVER", [])
        except Exception:
            pass


async def start_game_as_host(own_port, room_id):
    # create a handler that passes room_id to the game client handler
    from functools import partial
    handler = partial(handle_game_client, room_id=room_id)

    server_obj = await asyncio.start_server(handler, '0.0.0.0', own_port)
    logging.info(f"Waiting for client to connect to {own_port} as game server...")
    print(f"Waiting for client to connect to {own_port} as game server...")
    
    global server_close_event
    server_close_event = asyncio.Event()

    async def stop_server():
        await server_close_event.wait()
        server_obj.close()
        await server_obj.wait_closed()
        print("Game server is closed.")

    async with server_obj:
        await asyncio.gather(server_obj.serve_forever(), stop_server())


async def handle_game_client(reader, writer, room_id):
    try:
        print("Client has connected.")
        await game_loop(reader, writer, "Host", room_id)
    except Exception as e:
        logging.error(f"Server error: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass


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
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass


async def game_loop(reader, writer, role, room_id):
    my_move = None
    opponent_move = None
    game_over = False

    while not game_over:
        if role == "Host":
            # Host move
            my_move = await get_move("Host", room_id)
            await ut.send_message(writer, json.dumps({"move": my_move}) + '\n')
            print("Waiting for opponent to choose pocket...")
            data = await reader.read(1024)
            if not data:
                print("Opponent has disconnected.")
                game_over = True
                break
            try:
                message = json.loads(data.decode())
                opponent_move = message.get("move")
                if not await check_move(opponent_move, room_id):
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
                if not await check_move(opponent_move, room_id):
                    print("Received invalid move.")
                    continue
            except json.JSONDecodeError:
                print("Received invalid message.")
                continue
            my_move = await get_move("Client", room_id)
            await ut.send_message(writer, json.dumps({"move": my_move}) + '\n')

        if game.det_game_over(room_id):
            game_over = True
            # signal host server to close
            try:
                server_close_event.set()
            except Exception:
                pass
            game.det_winner(room_id)
        else:
            game.update_board(role if role == "Host" else "Client", my_move, room_id)


async def check_move(input_move, room_id):
    try:
        move = int(input_move)
        cur_board = server.rooms[room_id]['board']
        if move < 1 or move > 6 or cur_board.BP1[move - 1] == 0:
            return False
        return True
    except:
        return False


async def get_move(player, room_id):
    while True:
        game.print_board(room_id)
        user_input = await get_user_input(f"{player}, which pocket do you want to move? ")
        try:
            move = int(user_input)
            cur_board = server.rooms[room_id]['board']
            if move < 1 or move > 6:
                print("Index out of range, please choose another pocket.")
                continue
            if cur_board.BP1[move - 1] == 0:
                print('There are no stones in that pocket.\nChoose another pocket.\n')
                continue
            
            # call update_board with the move; game.update_board handles host/client logic
            game.update_board(player, move, room_id)
            return move                
        except ValueError:
            print("That is not a valid move, please try again.")


"""
For broadcast / discovery
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
For UDP Invite / Discovery
Protocol:
 - DISCOVER -> responders reply: AVAILABLE <username>
 - INVITE <room_id> <from_username> -> receiver prompts user; sends back via UDP ACCEPT <room_id> or DECLINE <room_id>
 - Additionally, when receiver ACCEPTs/DECLINEs, they send TCP ACCEPT_INVITE/DECLINE_INVITE to the lobby server so server can pair / notify.
"""
async def udp_listener(writer):
    # bind to UDP_PORT and listen for DISCOVER/INVITE messages
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind(('0.0.0.0', config.UDP_PORT))
    except Exception as e:
        print(f"[UDP] Failed to bind UDP port {config.UDP_PORT}: {e}")
        return

    sock.setblocking(False)
    print(f"[UDP] Listening on port {config.UDP_PORT} for invites and discovery...")

    while True:
        try:
            data, addr = await loop.sock_recvfrom(sock, 1024)
            msg = data.decode().strip()
            # DISCOVER -> reply with AVAILABLE <username>
            if msg.startswith("DISCOVER"):
                # reply with username so discoverer knows who is available
                uname = USERNAME if USERNAME else "UNKNOWN"
                resp = f"AVAILABLE {uname}"
                await loop.sock_sendto(sock, resp.encode(), addr)
                print(f"[UDP] Received DISCOVER from {addr}, replied AVAILABLE {uname}")
            elif msg.startswith("INVITE"):
                # INVITE <room_id> <from_username>
                parts = msg.split()
                if len(parts) >= 3:
                    _, room_id, inviter = parts[:3]
                else:
                    print(f"[UDP] Malformed INVITE from {addr}: {msg}")
                    continue
                sender_ip = addr[0]
                print(f"[UDP] Received invitation from {inviter} ({sender_ip}) for room {room_id}")
                response = input("Accept invite? (yes/no): ").strip().lower()
                if response == "yes":
                    # notify inviter directly by UDP (optional) and inform lobby server via TCP
                    await loop.sock_sendto(sock, f"ACCEPT {room_id}".encode(), addr)
                    # also inform lobby server via TCP so server can do pairing
                    await ut.send_command(writer, "ACCEPT_INVITE", [room_id])
                else:
                    await loop.sock_sendto(sock, f"DECLINE {room_id}".encode(), addr)
                    # inform lobby server so inviter can be notified
                    await ut.send_command(writer, "DECLINE_INVITE", [inviter, room_id])
                    print("You have declined the invite.")
            elif msg.startswith("AVAILABLE"):
                # some other client broadcasted AVAILABLE; ignore here (handled by discoverer)
                continue
            elif msg.startswith("ACCEPT") or msg.startswith("DECLINE"):
                # Used for direct notify of invite result (optional)
                # format: ACCEPT <room_id> or DECLINE <room_id>
                parts = msg.split()
                if len(parts) >= 2:
                    act = parts[0]
                    room_id = parts[1]
                    print(f"[UDP] {act} received for room {room_id} from {addr[0]}")
                continue
            else:
                # treat as unknown UDP message
                print(f"[UDP] Unknown message from {addr}: {msg}")
        except Exception as e:
            # avoid crashing listener on transient errors
            await asyncio.sleep(0.1)
            continue


async def udp_discover_players(timeout=3):
    """
    Broadcast DISCOVER across UDP_BROADCAST_RANGE and collect AVAILABLE <username> replies.
    Returns list of tuples: (username, ip, port)
    """
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)

    print("[UDP] Scanning for available players...")
    # send DISCOVER to all ports in range
    for p in config.UDP_BROADCAST_RANGE:
        try:
            await loop.sock_sendto(sock, b"DISCOVER", ('255.255.255.255', p))
        except Exception:
            # ignore send errors (multiple interfaces may drop broadcast)
            pass

    found = []
    start = loop.time()
    try:
        while loop.time() - start < timeout:
            try:
                data, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 1024), timeout=timeout - (loop.time() - start))
                msg = data.decode().strip()
                if msg.startswith("AVAILABLE"):
                    parts = msg.split()
                    uname = parts[1] if len(parts) >= 2 else "UNKNOWN"
                    found.append((uname, addr[0], addr[1]))
                    print(f"Found player {uname} at {addr[0]}:{addr[1]}")
            except asyncio.TimeoutError:
                break
            except Exception:
                await asyncio.sleep(0.05)
                continue
    finally:
        sock.close()

    print(f"[UDP] Discovery complete. Found: {found}")
    return found


async def send_udp_invite(target_username, room_id, writer):
    """
    Find the target username via discovery, then send INVITE <room_id> <from_username> to that player's IP:port.
    """
    if not USERNAME:
        print("[UDP] You must be logged in before sending invites.")
        return

    loop = asyncio.get_event_loop()
    # send DISCOVER and look for AVAILABLE replies, then pick one matching target_username
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)

    print(f"[UDP] Searching for {target_username}...")
    for p in config.UDP_BROADCAST_RANGE:
        try:
            await loop.sock_sendto(sock, b"DISCOVER", ('255.255.255.255', p))
        except Exception:
            pass

    found_ip = None
    found_port = None
    try:
        start = loop.time()
        while loop.time() - start < 3:
            try:
                data, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 1024), timeout=3 - (loop.time() - start))
            except asyncio.TimeoutError:
                break
            if not data:
                continue
            msg = data.decode().strip()
            if msg.startswith("AVAILABLE"):
                parts = msg.split()
                uname = parts[1] if len(parts) >= 2 else None
                if uname == target_username:
                    found_ip = addr[0]
                    found_port = addr[1]
                    print(f"[UDP] Found {target_username} at {found_ip}:{found_port}")
                    break
    except Exception as e:
        logging.error(f"Error during UDP discovery: {e}")
    finally:
        sock.close()

    if not found_ip:
        print("[UDP] Discovery timeout. No player found.")
        return

    # send INVITE <room_id> <from_username> to found_ip:found_port
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_sock.setblocking(False)
    invite_msg = f"INVITE {room_id} {USERNAME}"
    try:
        await loop.sock_sendto(send_sock, invite_msg.encode(), (found_ip, found_port))
        print(f"[UDP] Invitation sent to {target_username} @ {found_ip}:{found_port}")
    except Exception as e:
        print(f"[UDP] Failed to send invite: {e}")
    finally:
        send_sock.close()


async def main():
    global USERNAME
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

    # start UDP listener (needs writer to notify server on ACCEPT/DECLINE)
    udp_task = asyncio.create_task(udp_listener(writer))
    server_task = asyncio.create_task(handle_server_messages(reader, writer, game_in_progress, logged_in))
    user_task = asyncio.create_task(handle_user_input(writer, game_in_progress, logged_in))

    print("\nAvailable commands: ")
    for cmd in COMMANDS:
        print(cmd)
    print("")

    # keep alive until tasks end
    done, pending = await asyncio.wait([udp_task, server_task, user_task], return_when=asyncio.FIRST_COMPLETED)

    # cancel remaining
    for t in pending:
        t.cancel()
    try:
        await asyncio.gather(*pending, return_exceptions=True)
    except:
        pass

    print("Client end closed.")
    logging.info("Client end closed.")
    try:
        writer.close()
        await writer.wait_closed()
    except:
        pass
    sys.exit()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Client end terminated with error: {e}")
        logging.error(f"Client end terminated with error: {e}")
