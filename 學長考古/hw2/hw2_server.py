import socket
import threading

flag = 0
users = {}
online_users = {}
room = {}
users_ip = {}
user_game_port = {}
invited_user = {}
def check_room_exists(room_name):
    for user, details in room.items():
        if details[0] == room_name and details[3] == "waiting" and details[2] == "public": 
            return True, [user,details]
    return False, None

def list_idle_info(current_user):
    other_players = {username: status for username, status in online_users.items() if username != current_user and status == "idle"}
    
    if other_players:
        online_players_info = "\n".join([f"    {username} - {status}" for username, status in other_players.items()])
        online_msg = f"Online players:\n{online_players_info}"
    else:
        online_msg = "Currently, no players are online."
    
    msg = f"{online_msg}"
    return msg

def list_info(current_user):
    other_players = {username: status for username, status in online_users.items() if username != current_user}
    
    if other_players:
        online_players_info = "\n".join([f"    {username} - {status}" for username, status in other_players.items()])
        online_msg = f"Online players:\n{online_players_info}"
    else:
        online_msg = "Currently, no players are online."
    

    public_rooms = {username: info for username, info in room.items() if info[2] == "public"}

    if public_rooms:
        room_info = "\n".join([f"    {info[0]} - {username} - {info[1]} - {info[2]} - {info[3]}" 
                               for username, info in public_rooms.items()])
        room_msg = f"Public Rooms:\n{room_info}"
    else:
        room_msg = "Currently, no public rooms are available."
    
    msg = f"{online_msg}\n{room_msg}"
    return msg

def handle_room_public(conn, current_user):
    try:
        origin_room = room[current_user]
        uip = users_ip[current_user]
        uport = user_game_port[current_user]
        game = room[current_user][1]
        info = f"{uip} {uport} {game}"
        conn.send(info.encode())
        while True:
            if(room[current_user] != origin_room ):
                conn.send("start".encode())
                break
        online_users[current_user] = "in game"
        data = conn.recv(1024).decode()
        if(data == "end"):
            online_users[current_user] = "idle"
            del room[current_user]

    except Exception:
        del invited_user[data]
        del room[current_user]
        del online_users[current_user]

def handle_room_private(conn, current_user):
    try:
        uip = users_ip[current_user]
        uport = user_game_port[current_user]
        game = room[current_user][1]
        info = f"{uip} {uport} {game}"
        conn.send(info.encode())
        while True:
            data = conn.recv(1024).decode()
            if(data == "i"):
                info = list_idle_info(current_user)
                conn.send(info.encode())
                data = conn.recv(1024).decode()
                if data in online_users and online_users[data] == 'idle':
                    invited_user[data] = [current_user, '0']
                    conn.send("ok".encode())
                    origin_invitation = invited_user[data][1]
                    while True:
                        if(origin_invitation != invited_user[data][1]):
                            if(invited_user[data][1] == '1'):
                                del invited_user[data]
                                conn.send("a".encode())
                                online_users[current_user] = "in game"
                                room[current_user][3] = 'in game'
                                data = conn.recv(1024).decode()
                                if(data == "end"):
                                    online_users[current_user] = "idle"
                                    del room[current_user]
                                    return
                            else:
                                del invited_user[data]
                                conn.send("r".encode())
                                break
                else:
                    conn.send("nan".encode())
    except Exception:
        del invited_user[data]
        del room[current_user]
        del online_users[current_user]

def handle_join(conn, current_user, user):
    try:
        online_users[current_user] = 'in game'
        uip = users_ip[user]
        uport = user_game_port[user]
        game = room[user][1]
        info = f"{uip} {uport} {game}"
        print(info)
        conn.send(info.encode())
        data = conn.recv(1024).decode()
        if(data == "end"):
            online_users[current_user] = "idle"
            del room[user]
    
    except Exception:
        del online_users[current_user]


def handle_inv(conn,current_user):
    while True:
        data = conn.recv(1024).decode()
        if data.startswith("i"):
            if current_user in invited_user:
                inviter = invited_user[current_user][0]
                msg = "yes " + inviter
                conn.send(msg.encode())
                data = conn.recv(1024).decode()
                if(data == 'a'):
                    invited_user[current_user][1] = "1"
                    handle_join(conn, current_user, inviter)
                else:
                    invited_user[current_user][1] = "2"
                    continue
            else:
                conn.send("nan".encode())

def handle_lobby(conn, current_user):
    global flag
    try:
        users_ip[current_user] = conn.getpeername()[0]
        info = list_info(current_user)
        print(f"user: {current_user} ip: {users_ip[current_user]} port: {conn.getpeername()[1]}")
        conn.send(info.encode())
        while True:
            data = conn.recv(1024).decode()
            if data == 'ls':
                info = list_info(current_user)
                conn.send(info.encode())
            elif data == 'o':
                del online_users[current_user]
                print(f"user: {current_user} ip: {users_ip[current_user]} port: {conn.getpeername()[1]} logout")
                if current_user in room:
                    del room[current_user]
                return
            elif data.startswith("c"):
                online_users[current_user] = 'creating room'
                data = conn.recv(1024).decode()
                if(data != 'no'):
                    parts = data.split(' ', 1)
                    game_and_rtype = parts[0]
                    room_name = parts[1]
                    choice = game_and_rtype[0] 
                    rtype = 'public' if game_and_rtype[1] == '1' else 'private'

                    game = 'Gomoku' if choice == '1' else 'Fishing'
                    exists, r_info = check_room_exists(room_name)
                    if(exists == False):
                        room[current_user] = [room_name, game, rtype, 'waiting']
                        online_users[current_user] = 'in room'
                        if(rtype == 'public'):
                            conn.send("ok".encode())
                            data = conn.recv(1024).decode()
                            user_game_port[current_user] = data
                            handle_room_public(conn, current_user)
                        else:
                            conn.send("ok".encode())
                            data = conn.recv(1024).decode()
                            user_game_port[current_user] = data
                            handle_room_private(conn, current_user)
                    else:
                        online_users[current_user] = 'idle'
                        conn.send("exist".encode())
                else:
                    online_users[current_user] = 'idle'
            elif data.startswith("j"):
                parts = data.split(' ', 1)
                room_name = parts[1]
                exists, r_info = check_room_exists(room_name)
                if(exists == False):
                    conn.send("nan".encode())
                else:
                    room_name = r_info[1][0]
                    game = r_info[1][1]
                    rtype = r_info[1][2]
                    room[r_info[0]] = [room_name, game, rtype, 'in game']
                    conn.send("ok".encode())
                    handle_join(conn, current_user, r_info[0])
            elif data == 'byby':
                del online_users[current_user]
                print(f"user: {current_user} ip: {users_ip[current_user]} port: {conn.getpeername()[1]} logout")
                print(f"ip: {users_ip[current_user]} port: {conn.getpeername()[1]} disconnect")
                flag =1
                if current_user in room:
                    del room[current_user]
                return
    except (ConnectionResetError, ConnectionAbortedError):
        print(f"[Disconnection] {current_user} disconnected unexpectedly.")
    finally:
        # Ensure cleanup of disconnected clients
        if current_user in online_users:
            del online_users[current_user]
        if current_user in room:
            del room[current_user]
        print(f"[Cleanup] {current_user} has been removed from online users and rooms.")

def handle_login(conn):
    print(f"ip: {conn.getpeername()[0]} port: {conn.getpeername()[1]} connect")
    while True:
        try:
            data = conn.recv(1024).decode()
            if data == "r":
                conn.send("username:".encode())
                username = conn.recv(1024).decode()
                
                if username in users:
                    conn.send("exists".encode())
                else:
                    conn.send("password:".encode())
                    password = conn.recv(1024).decode()
                    if password == "":
                        continue
                    users[username] = password
                    conn.send("registered".encode())  
                    online_users[username] = "idle"
                    handle_lobby(conn, username)

            elif data == "l":
                conn.send("username:".encode())
                username = conn.recv(1024).decode()

                if (username not in users) or (username in online_users):
                    conn.send("no_user".encode()) 
                else:
                    conn.send("password:".encode())
                    password = conn.recv(1024).decode()

                    if users[username] == password:
                        online_users[username] = "idle"
                        conn.send("valid".encode()) 
                        handle_lobby(conn, username)
                    else:
                        conn.send("invalid_password".encode())  
            elif data == 'b':
                print(f"ip: {conn.getpeername()[0]} port: {conn.getpeername()[1]} disconnect")
                break
            elif data.startswith("i"):
                parts = data.split(' ', 1)
                username = parts[1]
                conn.send("ack".encode())
                handle_inv(conn,username)
            else:
                conn.send("invalid_command".encode())
                
        except Exception as e:
            if(flag == 1):
                break
            else:
                print(f"[Error_login] {e}")
                break

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        server.bind(("140.113.235.151", 26699))
        server.listen()
        print("[Server started] Waiting for connections...")
    except socket.error as e:
        print(f"[Error] Failed to start server: {e}")
        return 

    while True:
        try:
            conn, _ = server.accept()
            thread = threading.Thread(target=handle_login, args=(conn,))
            thread.start()
        except Exception as e:
            print(f"[Error] Accepting connection failed: {e}")

start_server()
