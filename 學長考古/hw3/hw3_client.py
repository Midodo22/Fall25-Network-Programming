import threading
import socket
import time
import random
import select
import sys
import os
import importlib.util
import re
def game_manage(client,username):
    while True:
        print('(1) list my game\n(2) publish game \n(3) back to lobby')
        read_sockets, _, _ = select.select([sys.stdin,client], [], [])
        for sock in read_sockets:
                if sock == sys.stdin:
                    command = input()
                    if command == '1':
                        client.send('lmgame'.encode())
                        data = client.recv(4096).decode()
                        print(data)
                    elif command == '2':
                        # Publish game
                        game_name = input("Enter the name of the game (ignore .py): ").strip()
                        game_intro = input("Enter the introduction of the game: ").strip()
                        file_path = f"game_upload/{game_name}.py"
                        
                        if not os.path.exists(file_path):
                            print("Game file does not exist in 'game_upload' folder.")
                            continue
                        
                        try:
                            # Notify the server that we are publishing a game
                            client.send('gamep'.encode())
                            time.sleep(0.5)
                            client.sendall(f"{game_name}|{game_intro}".encode())
                            data = client.recv(4096).decode()
                            if(data == 'nan'):
                                print('game have been upload by others')
                            else:
                                with open(file_path, 'rb') as file:
                                    while chunk := file.read(4096):
                                        client.sendall(chunk)

                                # Indicate end of file
                                time.sleep(0.5)
                                client.sendall(b'EOF')
                                data = client.recv(4096).decode()
                                print(data)
                        except Exception as e:
                            print(f"Error publishing the game: {e}")
                    elif command == '3':
                        return
                    elif(command == ''):
                        continue
                    else:
                        print('Invalid command.')
                elif sock == client:
                    data = client.recv(1024).decode()
                    print(data)
def invited_manage(client,username):
    client.send('inv'.encode())
    data = client.recv(4096).decode()
    print(data)
    while True:
        print('(1) list requests\n(2) accept request \n(3) delete request\n(4) back to lobby')
        read_sockets, _, _ = select.select([sys.stdin,client], [], [])
        for sock in read_sockets:
                if sock == sys.stdin:
                    command = input()
                    if command == '1':
                        client.send('inv'.encode())
                        data = client.recv(4096).decode()
                        print(data)
                    elif command == '2':
                        name = input("room name: ")
                        if(name != "" or " " in name):
                            command = f"p {name}"
                            client.send(command.encode())
                            data = client.recv(1024).decode()
                            if(data == "nan"):
                                print('room not exist or not idle or full')
                                return
                            else:
                                print("join successful!")
                                client_room(client,"other",username)
                        else:
                            print('Invalid name. Room name can not be null or contain space.')
                        return
                    elif command == '3':
                        name = input("room name: ")
                        if(name != "" or " " in name):
                            command = f"d {name}"
                            client.send(command.encode())
                            data = client.recv(1024).decode()
                            print(data)
                        else:
                            print('Invalid name. Room name can not be null or contain space.')
                    elif command == '4':
                        return
                    elif(command == ''):
                        continue
                    else:
                        print('Invalid command.')
                elif sock == client:
                    data = client.recv(1024).decode()
                    print(data)

def request_game_from_server(client_socket, game_download_folder="game_download"):
    try:
        client_socket.send("getgame".encode())
        game_name = client_socket.recv(1024).decode()
        game_name = game_name + '.py'
        # Prepare to receive the game file
        os.makedirs(game_download_folder, exist_ok=True)
        game_file_path = os.path.join(game_download_folder, game_name)

        with open(game_file_path, "wb") as file:
            while True:
                data = client_socket.recv(4096)
                if data == b'EOF':
                    break
                file.write(data)

        print(f"Game received and saved to {game_file_path}.")
    except Exception as e:
        print(f"Error requesting game: {e}")

def load_and_play_game(game_name, connection, player_symbol):
    game_file_path = os.path.join("game_download", f"{game_name}.py")
    if not os.path.exists(game_file_path):
        print(f"Game file '{game_name}.py' not found in 'game_download' folder.")
        return
    
    spec = importlib.util.spec_from_file_location(game_name, game_file_path)
    game_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(game_module)
    
    if not hasattr(game_module, "handle_game"):
        print(f"The game '{game_name}' does not have a 'handle_game' function.")
        return

    print(f"Starting the game: {game_name}")
    result = game_module.handle_game(connection, player_symbol)
    
    if result == "W":
        print("Congratulations! You won!")
    elif result == "L":
        print("You lost. Better luck next time!")


def client_room(client, role, username):
    request_game_from_server(client)
    while True:
        if(role == "host"):
            client.send('rlist'.encode())
            data = client.recv(4096).decode()
            print(data)
            print('(1) invite other\n(2) start game \n(3) use format (t msg) to chat\n(4) change game\n(5) leave')
            read_sockets, _, _ = select.select([sys.stdin,client], [], [])
            for sock in read_sockets:
                if sock == sys.stdin:
                    command = input()
                    if command == '1':
                        print('choose which player you want to invite')
                        client.send('lidle'.encode())
                        data = client.recv(1024).decode()
                        print(data)
                        invitation = input("Invited user name: ")
                        while invitation == "":
                            print('username cannot be empty.')
                            invitation = input("Invited user name: ")
                        msg = input('invite message: ')
                        while msg == "":
                            print('message cannot be empty.')
                            msg = input('invite message: ')
                        invitation = 'r1 ' + invitation + ' ' + username + ' '+msg
                        client.send(invitation.encode())
                        data = client.recv(1024).decode()
                        if(data == 'ok'):
                            print('invitation sended')
                        elif data == 'already':
                            print('already sent the invitation')
                        else:
                            print(f"User is either not online or not idle.")
                    elif command == '2':
                        client.send('r2'.encode())
                        data = client.recv(1024).decode()
                        if(data == 'no'):
                            print('the room is not full')
                        else:
                            ip, port,game = data.split(' ')
                            port = int(port)
                            game_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            game_socket.bind((ip, port))
                            game_socket.listen(1)
                            conn, addr = game_socket.accept()
                            result = load_and_play_game(game,conn,'O')
                            time.sleep(0.5)
                            conn.close()
                            game_socket.close()
                            client.send('fgame'.encode())
                    elif command == '5':
                        client.send('r3'.encode())
                        data = client.recv(1024).decode()
                        if(data == 'ok'):
                            return
                    elif command.startswith('t'):
                        pattern = r"^t .+"
                        if re.match(pattern, command):
                            client.send(command.encode())
                            _, chat = command.split(' ',1)
                            msg = f'{username}: {chat}'
                            print(msg)
                        else:
                            print("Invalid chat format")
                    elif command == '4':
                        choice = input("enter the game name you want to play: ")
                        data = f'gamec {choice}'
                        client.send(data.encode())
                        data = client.recv(1024).decode()
                        if(data == 'ok'):
                            request_game_from_server(client)
                        else:
                            print('game not exist')
                    elif(command == ''):
                        continue
                    else:
                        print('Invalid command.')
                elif sock == client:
                        data = client.recv(1024).decode()
                        if(data == 'update'):
                            continue
                        print(data)
        else:
            client.send('rlist'.encode())
            data = client.recv(4096).decode()
            print(data)
            print('waiting host to start. press \'1\' to leave or use format (t msg) to chat')
            read_sockets, _, _ = select.select([sys.stdin,client], [], [])
            for sock in read_sockets:
                if sock == sys.stdin:
                    command = input()
                    if command == '1':
                        client.send('r3'.encode())
                        data = client.recv(1024).decode()
                        if(data == 'ok'):
                            return
                    elif command.startswith('t'):
                        pattern = r"^t .+"
                        if re.match(pattern, command):
                            client.send(command.encode())
                            _, chat = command.split(' ',1)
                            msg = f'{username}: {chat}'
                            print(msg)
                        else:
                            print("Invalid chat format")
                    elif(command == ''):
                        continue
                    else:
                        print('Invalid command.')
                elif sock == client:
                        data = client.recv(1024).decode()
                        if(data == 'update'):
                            role = 'host'
                            continue
                        if(data.startswith('start')):
                            _, ip, port,game = data.split(' ')
                            port = int(port)
                            game_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            game_socket.connect((ip, port))
                            result = load_and_play_game(game,game_socket,'X')
                            game_socket.close()
                        elif data.startswith('gamec'):
                            request_game_from_server(client)
                        else:
                            print(data)


def client_lobby(client, username):
    try:
        print("Welcome to lobby")
        command = 'ls'
        client.send(command.encode())
        data = client.recv(1024).decode()
        print(data)
        while True:
            print("(1) list online user and room\n(2) create room\n(3) join room\n(4) invitation management\n(5) list game\n(6) game management\n(7) leave")
            read_sockets, _, _ = select.select([sys.stdin,client], [], [])
            for sock in read_sockets:
                if sock == sys.stdin:
                    command = input()
                    if command == '1':
                        client.send('ls'.encode())
                        data = client.recv(1024).decode()
                        print(data)
                    elif command == '7':
                        client.send('o'.encode())
                        close_thread = True
                        print("Logged out successfully.")

                        return
                    elif command == '2':
                        client.send('c'.encode())
                        name = input("room name: ")
                        if(name != "" or " " in name):
                            choice = input("enter the game name you want to play: ")
                            rtype = input("1. public\n2. private\nwhat is the room type 1 or 2?: ")
                            if rtype in ["1", "2"]:
                                command = f"{choice} {rtype} {name}"
                                client.send(command.encode())
                                data = client.recv(1024).decode()
                                if(data == "ok"):
                                    game_port = 0
                                    while(int(game_port) < 10000 or int(game_port) > 65535) :
                                        print("port should be larger than 10000, smaller than 65535 and must be a number")
                                        game_port = input("game port: ")
                                        if (not game_port.isdigit()):
                                            game_port = 0    
                                    client.send(game_port.encode())
                                    print("Room created.")
                                    role = "host"
                                    client_room(client,role, username)
                                elif data == 'gnexist':
                                    print("game not exsit.")
                                elif data == 'exist':
                                    print("Room name already exsit.")
                            else:
                                client.send('no'.encode())
                                print('Invalid choice for room type.')
                        else:
                            client.send('no'.encode())
                            print('Invalid name. Room name can not be null or contain space.')
                    elif command == '3':
                        name = input("room name: ")
                        if(name != "" or " " in name):
                            command = f"j {name}"
                            client.send(command.encode())
                            data = client.recv(1024).decode()
                            if(data == "nan"):
                                print('room not exist or not idle or full or private')
                                continue
                            else:
                                print("join successful!")
                                client_room(client,"other",username)
                        else:
                            print('Invalid name. Room name can not be null or contain space.')
                    elif command == '4':
                        invited_manage(client,username)
                    elif command == '5':
                        client.send('lgame'.encode())
                        data = client.recv(1024).decode()
                        print(data)
                    elif command == '6':
                        game_manage(client,username)
                    else:
                        print('Invalid command.')
                elif sock == client:
                    data = client.recv(1024).decode()
                    print(data)
    except (ConnectionResetError, ConnectionAbortedError):
        print("[Error] Disconnected from the lobby server.")
    except (KeyboardInterrupt):
        client.send('byby'.encode())
    except Exception as e:
        print(f"[Error] {e}")


def start_client():
    global close_thread
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(("140.113.235.151", 26699))
        print("Connected to the game lobby server.")
    except socket.error as e:
        print(f"[Connection Error] Unable to connect to the server: {e}")
        return 

    while True:
        try:
            print("Please register (r) or log in (l) or leave (b): ")
            command = input()
            if(command == ''):
                continue
            client.send(command.encode())
            if command == "r":
                data = client.recv(1024).decode()
                if data == "exists":
                    print("Username already exists. Please try again.")
                elif data == "username:":
                    username = input("Enter username: ")
                    while username == "":
                            print('username cannot be empty.')
                            username = input("Enter username: ")
                    client.send(username.encode())
                    data = client.recv(1024).decode()
                    if data == "exists":
                        print("Username already exists. Please try again.")
                    elif data == "password:":
                        password = input("Enter password: ")
                        while password == "":
                            print('Password cannot be empty.')
                            password = input("Enter password: ")
                        client.send(password.encode())
                        data = client.recv(1024).decode()
                        if data == "registered":
                            print("Registration successful!")
                            close_thread = False
                            client_lobby(client, username)
                        else:
                            print("Registration failed.")
            
            elif command == "l":
                data = client.recv(1024).decode()
                if data == "username:":
                    username = input("Enter username: ")
                    while username == "":
                            print('username cannot be empty.')
                            username = input("Enter username: ")
                    client.send(username.encode())
                    data = client.recv(1024).decode()
                    if data == "password:":
                        password = input("Enter password: ")
                        while password == "":
                            print('Password cannot be empty.')
                            password = input("Enter password: ")
                        client.send(password.encode())
                        data = client.recv(1024).decode()
                        if data == "valid":
                            print("Login successful! Welcome to the lobby.")
                            client_lobby(client, username)
                        elif data == "invalid_password":
                            print("Incorrect password. Please try again.")
                    elif data == "no_user":
                        print("User does not exist or user already in lobby. Please register first.")
                else:
                    print("Login failed.")
            elif command == "b":
                client.send(command.encode())
                print("bye")
                break
            else:
                print("Invalid command. Please choose 'r' for register or 'l' for login.")
        
        except (ConnectionResetError, ConnectionAbortedError):
            print("Disconnected server error.")
            break
        except (KeyboardInterrupt):
            client.send('b'.encode())
            break
        except socket.error as e:
            print("Disconnected server error.")
            break
        except Exception as e:
            print(f"[Unexpected Error] {e}")
            break
    client.close()
    print("[Client closed] Connection to server has ended.")

start_client()
