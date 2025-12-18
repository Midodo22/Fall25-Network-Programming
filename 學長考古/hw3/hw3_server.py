import socket
import threading
from queue import Queue
import traceback
import csv
import os
import time
users = {}
online_users = {}
online_connect = {}
room = {}
users_ip = {}
user_game_port = {}
invite_user = {}
broadcast_queue = Queue()
USER_FILE = "users.csv"
def is_game_in_csv(game_name, csv_file="games.csv"):
    with open(csv_file, mode="r") as file:
            reader = csv.reader(file)
            next(reader)  # Skip the header row
            # Check each row for the game name
            for row in reader:
                if row[0] == game_name:
                    return True
    return False  # Game not found
def read_user_games(current_user, csv_file="games.csv"):
    # Header for the table
    header = (
        "----------------------------------------------------------\n"
        "| Game        | Developer    | Introduction             |\n"
        "----------------------------------------------------------"
    )
    rows = []
    
    try:
        # Open and read the CSV file
        with open(csv_file, mode="r") as file:
            reader = csv.reader(file)
            next(reader)  # Skip the header row
            
            for row in reader:
                game_name, developer, introduction = row
                if developer == current_user:  # Filter by current user
                    # Format the row with proper spacing
                    rows.append(f"| {game_name:<10} | {developer:<12} | {introduction:<25} |")
        
        if rows:
            # Combine header and rows
            table = f"{header}\n" + "\n".join(rows) + "\n----------------------------------------------------------"
        else:
            table = f"No games found for developer '{current_user}'."
            
    except FileNotFoundError:
        table = "Game database not found. No games have been published yet."
    
    return table

def read_game_csv(csv_file="games.csv"):
    # Header for the table
    header = (
        "----------------------------------------------------------\n"
        "| Game        | Developer    | Introduction             |\n"
        "----------------------------------------------------------"
    )
    rows = []
    
    try:
        # Open and read the CSV file
        with open(csv_file, mode="r") as file:
            reader = csv.reader(file)
            next(reader)  # Skip the header row
            
            for row in reader:
                game_name, developer, introduction = row
                # Format the row with proper spacing
                rows.append(f"| {game_name:<10} | {developer:<12} | {introduction:<25} |")
        
        if rows:
            # Combine header and rows
            table = f"{header}\n" + "\n".join(rows) + "\n----------------------------------------------------------"
        else:
            table = "No games found in the database."
            
    except FileNotFoundError:
        table = "Game database not found. No games have been published yet."
    
    return table

def save_game_info_to_csv(game_name, developer, introduction, csv_file="games.csv",overwrite = False):
    if overwrite:
        # Read all existing rows
        updated_rows = []
        game_exists = False

        if os.path.isfile(csv_file):
            with open(csv_file, mode="r", newline="") as file:
                reader = csv.reader(file)
                header = next(reader)  # Skip the header
                updated_rows.append(header)

                for row in reader:
                    # Update the matching game entry
                    if row[0] == game_name:
                        updated_rows.append([game_name, developer, introduction])
                        game_exists = True
                    else:
                        updated_rows.append(row)

        # If game doesn't exist, append the new game entry
        if not game_exists:
            updated_rows.append([game_name, developer, introduction])

        # Write the updated rows back to the file
        with open(csv_file, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerows(updated_rows)

    else:
        # Append the new game entry (default behavior)
        file_exists = os.path.isfile(csv_file)
        with open(csv_file, mode="a", newline="") as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(["Game Name", "Developer", "Introduction"])
            writer.writerow([game_name, developer, introduction])

def delete_invitation_by_room(name, room_name):
    # Check if the user has any invitations
    if name not in invite_user or not invite_user[name]:
        return f" no invitations to delete."

    # Filter the invitations to exclude those with the specified room_name
    original_count = len(invite_user[name])
    invite_user[name] = [inv for inv in invite_user[name] if inv[1] != room_name]

    # Check if any invitations were deleted
    if len(invite_user[name]) < original_count:
        return f"Invitation(s) for room '{room_name}' successfully deleted."
    else:
        return f"No invitations found for room '{room_name}'."

def get_user_invitations(current_user):
    if current_user not in invite_user:
        return f"have no invitations."

    header = (
        "----------------------------------------------------------\n"
        "| Invitor          | Room Name     | Message          |\n"
        "----------------------------------------------------------"
    )
    rows = []

    for invitation in invite_user[current_user]:
        invitor, room_name, msg = invitation
        rows.append(f"| {invitor:<16} | {room_name:<13} | {msg:<16} |")

    table = f"{header}\n" + "\n".join(rows) + "\n----------------------------------------------------------"
    return table


# Function to load users from the CSV file (if it exists)
def load_users():
    global users
    try:
        with open(USER_FILE, mode="r", newline="") as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) == 2:  # Ensure valid rows
                    username, password = row
                    users[username] = password
    except FileNotFoundError:
        # If the file doesn't exist, start with an empty dictionary
        print(f"[Info] {USER_FILE} not found. Starting with no users.")

# Function to save a new user into the CSV file
def save_user(username, password):
    users[username] = password
    with open(USER_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([username, password])
    print(f"[Success] User '{username}' registered successfully.")
    return True

def get_room_details(room_name):
    if room_name in room:  # Check if the room exists
        details = room[room_name]
        header = (
            "-----------------------------------------------------------------------------\n"
            "| Room Name   | Game      | Type      | Host       | Players       | Count |\n"
            "-----------------------------------------------------------------------------"
        )
        players = ", ".join(details[5])  # Convert the player list to a string
        host = details[5][0] if details[5] else "None"  # Get the host or set to "None" if the list is empty
        player_count = details[4]  # Number of players
        row = (
            f"| {details[0]:<11} | {details[1]:<9} | {details[2]:<9} | {host:<10} | {players:<13} | {player_count:<5} |"
        )
        table = f"{header}\n{row}\n-------------------------------------------------------------------------"
        return table
    else:
        return f"Room '{room_name}' does not exist."



def prepare_room_table():
    if not room:  # Check if the room dictionary is empty
        return "Currently, no public rooms are available."
    
    header = (
        "-----------------------------------------------------------------------------\n"
        "| Room Name   | Game      | Type      | Host       | Players       | Count |\n"
        "-----------------------------------------------------------------------------"
    )
    rows = []
    
    for room_name, details in room.items():
        # Extract room details
        game = details[1]
        rtype = details[2]
        players = ", ".join(details[5])  # Convert the player list to a string
        host = details[5][0] if details[5] else "None"  # Get the host or set to "None" if the list is empty
        player_count = details[4]  # Number of players
        # Format each row
        rows.append(
            f"| {room_name:<11} | {game:<9} | {rtype:<9} | {host:<10} | {players:<13} | {player_count:<5} |"
        )
    
    # Combine the header and rows
    table = f"{header}\n" + "\n".join(rows) + "\n-----------------------------------------------------------------------------"
    return table





def find_player_room(player_name):
    for room_name, details in room.items():
        if player_name in details[5]:  
            return room_name
    return None  

def check_room_exists_p(room_name):
    if (
        room_name in room and
        room[room_name][3] == "waiting" and
        int(room[room_name][4]) == 1 
    ):
        return True
    return False

def check_room_exists(room_name):
    if (
        room_name in room and
        room[room_name][3] == "waiting" and
        room[room_name][2] == "public" and
        int(room[room_name][4]) == 1 
    ):
        return True
    return False

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
    

    public_rooms = {room_name: info for room_name, info in room.items() if info[2] == "public"}

    if public_rooms:
        room_info = "\n".join([
            f"    {info[0]} - {info[1]} - {info[2]} - {info[3]} - {info[4]} participants - Hosted by {info[5][0]}" 
            for room_name, info in public_rooms.items()
        ])
        room_msg = f"Public Rooms:\n{room_info}"
    else:
        room_msg = "Currently, no public rooms are available."
    
    msg = f"{online_msg}\n"
    return msg

def broadcast():
    global broadcast_queue
    while True:
        message, origin_user = broadcast_queue.get()
        for username, client_socket in online_connect.items():
            if username != origin_user and online_users[username] == "idle":  
                try:
                    client_socket.sendall(message.encode())
                except Exception as e:
                    print(f"Error sending message to {username}: {e}")
                    continue

def handle_room(conn, current_user):
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


def handle_login(conn):
    global broadcast_queue
    print(f"ip: {conn.getpeername()[0]} port: {conn.getpeername()[1]} connect")
    current_user = None
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
                    online_connect[username] = conn
                    save_user(username, password)
                    broadcast_queue.put((f"{username} has joined the lobby.",username))
                    current_user = username
                    users_ip[current_user] = conn.getpeername()[0]
                    print(f"user: {current_user} ip: {users_ip[current_user]} port: {conn.getpeername()[1]}")

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
                        online_connect[username] = conn
                        conn.send("valid".encode()) 
                        broadcast_queue.put((f"{username} has joined the lobby.",username))
                        current_user = username
                        users_ip[current_user] = conn.getpeername()[0]
                        print(f"user: {current_user} ip: {users_ip[current_user]} port: {conn.getpeername()[1]}")
                    else:
                        conn.send("invalid_password".encode()) 
            elif data == 'b':
                print(f"ip: {conn.getpeername()[0]} port: {conn.getpeername()[1]} disconnect")
                break
            elif data == 'ls':
                info = list_info(current_user)
                info = info + prepare_room_table()
                conn.send(info.encode())
            elif data == 'o':
                del online_users[current_user]
                del online_connect[current_user]
                print(f"user: {current_user} ip: {users_ip[current_user]} port: {conn.getpeername()[1]} logout")
            elif data.startswith("c"):
                online_users[current_user] = 'creating room'
                data = conn.recv(1024).decode()
                if(data != 'no'):
                    parts = data.split(' ')
                    game_and_rtype = [parts[0], parts[1]]
                    room_name = parts[2]
                    game = game_and_rtype[0] 
                    rtype = 'public' if game_and_rtype[1] == '1' else 'private'
                    num_people = str(1)
                    exists= check_room_exists(room_name)
                    if(exists == False):
                        game_exist = is_game_in_csv(game)
                        if(game_exist == True):
                            room[room_name] = [room_name, game, rtype, 'waiting',num_people,[current_user]]
                            online_users[current_user] = 'in room'
                            if(rtype == 'public'):
                                conn.send("ok".encode())
                                data = conn.recv(1024).decode()
                                user_game_port[room_name] = data
                                broadcast_queue.put((f"{username} has created a room.",username))
                            else:
                                conn.send("ok".encode())
                                data = conn.recv(1024).decode()
                                user_game_port[room_name] = data
                        else:
                            online_users[current_user] = 'idle'
                            conn.send("gnexist".encode())
                    else:
                        online_users[current_user] = 'idle'
                        conn.send("exist".encode())
                else:
                    online_users[current_user] = 'idle'
            elif data.startswith("j"):
                parts = data.split(' ', 1)
                room_name = parts[1]
                exists = check_room_exists(room_name)
                if(exists == False):
                    conn.send("nan".encode())
                else:
                    online_users[current_user] = 'in room'
                    game = room[room_name][1]
                    rtype = room[room_name][2]
                    num_people = int(room[room_name][4])
                    online_connect[room[room_name][5][0]].send("update".encode())
                    player = room[room_name][5]
                    player.append(current_user)
                    room[room_name] = [room_name, game, rtype, 'waiting',str(num_people+1),player]
                    conn.send("ok".encode())
            elif data.startswith("p"):
                parts = data.split(' ', 1)
                room_name = parts[1]
                exists = check_room_exists_p(room_name)
                if(exists == False):
                    conn.send("nan".encode())
                else:
                    online_users[current_user] = 'in room'
                    game = room[room_name][1]
                    rtype = room[room_name][2]
                    num_people = int(room[room_name][4])
                    online_connect[room[room_name][5][0]].send("update".encode())
                    player = room[room_name][5]
                    player.append(current_user)
                    room[room_name] = [room_name, game, rtype, 'waiting',str(num_people+1),player]
                    conn.send("ok".encode())
                    invite_user[current_user] = [inv for inv in invite_user[current_user] if inv[1] != room_name]
            elif data.startswith("d"):
                parts = data.split(' ', 1)
                room_name = parts[1]
                msg = delete_invitation_by_room(current_user,room_name)
                conn.send(msg.encode())
                    
            elif data == 'inv':
                msg = get_user_invitations(current_user)
                conn.send(msg.encode())
            elif data == 'lidle':
                info = list_idle_info(current_user)
                conn.send(info.encode())
            elif data.startswith("r1"):
                parts = data.split(' ')
                name = parts[1]
                selfname = parts[2]
                room_name = find_player_room(selfname)
                msg = parts[3]
                if name in online_users and online_users[name] == 'idle':
                    sendmsg = f'you have an invitation from {current_user}'
                    online_connect[name].send(sendmsg.encode())
                    if name not in invite_user:
                        invite_user[name] = []
                    for invitation in invite_user[name]:
                        if invitation[0] == current_user and invitation[1] == room_name:
                            conn.send('already'.encode())
                            continue
                    invite_user[name].append([current_user,room_name,msg])
                    conn.send('ok'.encode())
                else:
                    conn.send('no'.encode())
            elif data.startswith("r2"):
                room_name = find_player_room(current_user)
                if(room[room_name][4] == '1'):
                    conn.send('no'.encode())
                else:
                    game = room[room_name][1]
                    other = room[room_name][5][1]
                    port = user_game_port[room_name] 
                    online_users[current_user] = 'in game'
                    online_users[other] = 'in game'
                    room[room_name] = [room_name, game, room[room_name][2], 'in game' ,room[room_name][4], room[room_name][5]]
                    ip = users_ip[current_user]
                    data = f"{ip} {port} {game}"
                    conn.send(data.encode())
                    info = f"start {ip} {port} {game}"
                    online_connect[other].send(info.encode())
            elif data.startswith("r3"):
                online_users[current_user] = 'idle'
                room_name = find_player_room(current_user)
                if(int(room[room_name][4]) == 1):
                    del room[room_name]
                    conn.send("ok".encode())
                else:
                    game = room[room_name][1]
                    rtype = room[room_name][2]
                    num_player = int(room[room_name][4])-1
                    player = room[room_name][5]
                    player.remove(current_user)
                    room[room_name] = [room_name, game, rtype, 'waiting' ,str(num_player), player]
                    conn.send("ok".encode())
                    online_connect[player[0]].send("update".encode())
            elif data.startswith("rlist"):
                room_name = find_player_room(current_user)
                msg = get_room_details(room_name)
                conn.send(msg.encode())

            elif data.startswith("gamep"):
                metadata = conn.recv(1024).decode()
                game_name, game_intro = metadata.split('|', 1)
                file_path = f"game_folder/{game_name}.py"

                # Check if the game exists and who the developer is
                game_exists = False
                is_developer = False
                if os.path.isfile("games.csv"):
                    with open("games.csv", mode="r") as csvfile:
                        reader = csv.reader(csvfile)
                        next(reader)  # Skip the header
                        for row in reader:
                            existing_game_name, existing_developer, _ = row
                            if existing_game_name == game_name:
                                game_exists = True
                                if existing_developer == current_user:
                                    is_developer = True
                                break
                if game_exists:
                    if is_developer:
                        conn.send(b'ok')
                        with open(file_path, 'wb') as file:
                            while True:
                                data = conn.recv(4096)
                                if data == b'EOF':
                                    break
                                file.write(data)
                        save_game_info_to_csv(game_name, current_user, game_intro, overwrite=True)
                        conn.send(f"Game updated successfully!".encode())
                        print(f"Game '{game_name}' updated by developer '{current_user}'.")
                    else:
                        conn.send(b'nan')
                        print(f"Unauthorized attempt to overwrite game '{game_name}' by '{current_user}'.")
                else:
                    conn.send(b'ok')
                    with open(file_path, 'wb') as file:
                        while True:
                            data = conn.recv(4096)
                            if data == b'EOF':
                                break
                            file.write(data)
                    save_game_info_to_csv(game_name, current_user, game_intro, overwrite=False)
                    conn.send(f"Game published successfully!".encode())
                    print(f"Game '{game_name}' published by '{current_user}' with intro: {game_intro}")

            elif data.startswith("lgame"):
                data = read_game_csv()
                conn.send(data.encode())
            elif data.startswith("lmgame"):
                data = read_user_games(current_user)
                conn.send(data.encode())
            elif data == "getgame":
                user_room = None
                for room_name, details in room.items():
                    if current_user in details[5]:  # Assuming the players list is at index 5
                        user_room = room_name
                        break

                # Get the game name for the room
                game_name = room[user_room][1]  # Assuming game name is at index 1
                game_file_path = os.path.join('game_folder', f"{game_name}.py")

                # Send the game file
                conn.send(game_name.encode()) 
                with open(game_file_path, "rb") as file:
                    while (chunk := file.read(4096)):
                        conn.send(chunk)
                time.sleep(0.5)
                conn.send(b'EOF')  # End of file transfer signal
                print(f"Sent game '{game_name}' to {current_user}.")

            elif data.startswith('t'):
                _, chat = data.split(' ',1)
                room_name = find_player_room(current_user)
                player = room[room_name][5]
                num_player = int(room[room_name][4])
                if(num_player == 1):
                    continue
                else:
                    if(player[0] == current_user):
                        p2 = player[1]
                        chat = f'{current_user}: {chat}'
                        online_connect[p2].send(chat.encode())
                    else:
                        p2 = player[0]
                        chat = f'{current_user}: {chat}'
                        online_connect[p2].send(chat.encode())
            elif data.startswith('gamec'):
                _, game = data.split(' ',1)
                room_name = find_player_room(current_user)
                game_exist = is_game_in_csv(game)
                if(game_exist == True):
                    room[room_name] = [room_name, game, room[room_name][2], 'waiting',room[room_name][4],room[room_name][5]]
                    conn.send("ok".encode())
                    other = room[room_name][5][1]
                    online_connect[other].send('gamec'.encode())
                else:
                    conn.send("gnexist".encode())
            elif data.startswith('fgame'):
                room_name = find_player_room(current_user)
                game = room[room_name][1]
                other = room[room_name][5][1]
                port = user_game_port[room_name] 
                online_users[current_user] = 'in room'
                online_users[other] = 'in room'
                room[room_name] = [room_name, game, room[room_name][2], 'waiting' ,room[room_name][4], room[room_name][5]]
        except Exception as e:
            print(f"[Error] Handling client error: {e}")
            traceback.print_exc()  # Print the full traceback
            break

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        server.bind(("140.113.235.151", 26699))
        server.listen()
        print("[Server started] Waiting for connections...")
    except socket.error as e:
        print(f"[Error] Failed to start server: {e}")
        return  # Exit the function if the server fails to start
    load_users()
    threading.Thread(target=broadcast, daemon=True).start()
    while True:
        try:
            conn, _ = server.accept()
            thread = threading.Thread(target=handle_login, args=(conn,))
            thread.start()
        except Exception as e:
            print(f"[Error] Accepting connection failed: {e}")

start_server()