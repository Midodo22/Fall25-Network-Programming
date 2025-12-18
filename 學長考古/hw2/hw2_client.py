import threading
import socket
import time
import random
invitation_received = False
invite_temp = ""
close_thread = False
BOARD_SIZE = 15

board = [[' ' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]

board_fish_SIZE_FISH = 8
NUM_FISH = 7

board_fish = [[' ' for _ in range(board_fish_SIZE_FISH)] for _ in range(board_fish_SIZE_FISH)]
fish_positions = set()

player_positions = {'X': (0, 0), 'O': (board_fish_SIZE_FISH - 1, board_fish_SIZE_FISH - 1)}
board_fish[0][0] = 'X'
board_fish[board_fish_SIZE_FISH - 1][board_fish_SIZE_FISH - 1] = 'O'

scores = {'X': 0, 'O': 0}

def print_board_fish():
    """Prints the board_fish to the console."""
    print("    " + "   ".join(f"{i+1:2}" for i in range(board_fish_SIZE_FISH)))
    print("  " + "-" * (board_fish_SIZE_FISH * 5 - 1)+ "----")
    for i, row in enumerate(board_fish):
        print(f"{i+1:2} | " + ' | '.join(f"{cell:2}" for cell in row) + " |")
        print("  " + "-" * (board_fish_SIZE_FISH * 5 - 1)+ "----")

def is_valid_move(x, y):
    return 0 <= x < board_fish_SIZE_FISH and 0 <= y < board_fish_SIZE_FISH and board_fish[x][y] not in {'X', 'O'}

def move_player(player, direction):
    """Move player based on 'w', 'a', 's', 'd' direction input."""
    px, py = player_positions[player]
    new_x, new_y = px, py
    if direction == 'w': new_x -= 1  # Up
    elif direction == 'a': new_y -= 1  # Left
    elif direction == 's': new_x += 1  # Down
    elif direction == 'd': new_y += 1  # Right

    if is_valid_move(new_x, new_y):
        board_fish[px][py] = ' '
        if (new_x, new_y) in fish_positions:
            scores[player] += 1
            fish_positions.remove((new_x, new_y))
        board_fish[new_x][new_y] = player
        player_positions[player] = (new_x, new_y)
        return True
    return False

def move_fish():
    """Randomly moves each fish one step in a random direction."""
    new_positions = set()
    for x, y in fish_positions:
        board_fish[x][y] = ' '
        dx, dy = random.choice([(-1, 0), (1, 0), (0, -1), (0, 1)])
        new_x, new_y = x + dx, y + dy
        if 0 <= new_x < board_fish_SIZE_FISH and 0 <= new_y < board_fish_SIZE_FISH and board_fish[new_x][new_y] == ' ':
            new_positions.add((new_x, new_y))
            board_fish[new_x][new_y] = 'F'
        else:
            new_positions.add((x, y))
            board_fish[x][y] = 'F'
    return new_positions

def send_fish_positions(tcp_socket):
    """Send the updated fish positions to the other player."""
    if not fish_positions:
        tcp_socket.send(b'non')  # Send an empty message for empty fish positions
    else:
        fish_data = " ".join(f"{x} {y}" for x, y in fish_positions)
        tcp_socket.send(fish_data.encode())

def receive_fish_positions(tcp_socket):
    """Receive the updated fish positions from the other player."""
    fish_data = tcp_socket.recv(1024).decode()
    if fish_data == "non":
        return set()
    fish_data = fish_data.split()
    new_fish_positions = set()
    for i in range(0, len(fish_data), 2):
        x, y = int(fish_data[i]), int(fish_data[i+1])
        new_fish_positions.add((x, y))
    return new_fish_positions

def check_winner():
    return scores['X'] + scores['O'] == NUM_FISH

def handle_fish_game(tcp_socket, player):
    global fish_positions
    global board_fish
    global player_positions
    global scores
    current_player = 'X'
    if player == 'X':
        for _ in range(NUM_FISH):
            while True:
                x, y = random.randint(0, board_fish_SIZE_FISH - 1), random.randint(0, board_fish_SIZE_FISH - 1)
                if board_fish[x][y] == ' ':
                    board_fish[x][y] = 'F'
                    fish_positions.add((x, y))
                    break
        send_fish_positions(tcp_socket)

    if player == 'O':
        fish_positions = receive_fish_positions(tcp_socket)
        for x, y in fish_positions:
                board_fish[x][y] = 'F'
    
    while True:
        try:
            print_board_fish()
            print(f"Your score: {scores[player]}")
            if(player == 'X'):
                print(f"opponent's score: {scores['O']}")
            else:
                print(f"opponent's score: {scores['X']}")
            if current_player == player:
                while True:
                    direction = input(f"Your move ({player}) [w/a/s/d]: ")
                    if len(direction) == 1 and direction in {'w', 'a', 's', 'd'}:
                        if move_player(player, direction):
                            break
                        else:
                            print("Invalid move. Try again.")
                    else:
                        print("Invalid input. Please enter a single character: 'w', 'a', 's', or 'd'.")
                tcp_socket.send(direction.encode())
                ack = tcp_socket.recv(1024).decode()

            else:
                print("Waiting for the other player's move...")
                direction = tcp_socket.recv(1024).decode()
                tcp_socket.send('ack'.encode())
                move_player(current_player, direction[0])
            
            # Player X moves the fish and sends new positions to Player O each round
            if player == 'X':
                fish_positions = move_fish()
                send_fish_positions(tcp_socket)
                ack = tcp_socket.recv(1024).decode()
            else:
                # Player O receives the updated fish positions and updates the board_fish
                for x, y in fish_positions:
                    if board_fish[x][y] == 'F':
                        board_fish[x][y] = ' '
                fish_positions = receive_fish_positions(tcp_socket)
                tcp_socket.send('ack'.encode())

                for x, y in fish_positions:
                    board_fish[x][y] = 'F'

            if check_winner():
                print_board_fish()
                board_fish = [[' ' for _ in range(board_fish_SIZE_FISH)] for _ in range(board_fish_SIZE_FISH)]
                fish_positions = set()

                player_positions = {'X': (0, 0), 'O': (board_fish_SIZE_FISH - 1, board_fish_SIZE_FISH - 1)}
                board_fish[0][0] = 'X'
                board_fish[board_fish_SIZE_FISH - 1][board_fish_SIZE_FISH - 1] = 'O'
                if(player == 'X'):
                    opp = 'O'
                else:
                    opp = 'X'
                if scores[player] > scores[opp]:
                    scores = {'X': 0, 'O': 0}
                    return 'W'
                else:
                    scores = {'X': 0, 'O': 0}
                    return 'L'

        
            current_player = 'O' if current_player == 'X' else 'X'
        except Exception:
            print("oppenent leave")
            return "W"


def print_board():
    print("     " + " | ".join(f"{i + 1:2}" for i in range(BOARD_SIZE)))
    print("   " + "-" * (BOARD_SIZE * 5 - 1))  # Divider for column labels
    for i, row in enumerate(board):
        # Print row label and the row itself
        print(f"{i + 1:2} | " + ' | '.join(f"{cell:2}" for cell in row))
        print("   " + "-" * (BOARD_SIZE * 5 - 1))  # Divider for rows


def is_winner(player):
    for i in range(BOARD_SIZE):
        for j in range(BOARD_SIZE):
            if (check_direction(i, j, player, 1, 0) or
                check_direction(i, j, player, 0, 1) or
                check_direction(i, j, player, 1, 1) or
                check_direction(i, j, player, 1, -1)):
                return True
    return False

def check_direction(x, y, player, dx, dy):
    count = 0
    for _ in range(5):
        if 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE and board[x][y] == player:
            count += 1
            x += dx
            y += dy
        else:
            break
    return count == 5

def handle_game(tcp_socket, player):
    try:
        now = 'X'
        global board
        while True:
            print_board()
            if now == player:
                while(1):
                    action = input(f"Your move ({player}): ")
                    if action.count(' ') == 1 and all(part.isdigit() for part in action.split()):
                        row, col = map(int, action.split())
                        if(col > 15 or row > 15 or col < 1 or row < 1):
                            print("invalid position")
                        else:
                            if(board[row-1][col-1] == 'X' or board[row-1][col-1] == 'O'):
                                print("position have been selected")
                            else:
                                if(player == 'X'):
                                    board[row-1][col-1] = '\u2716'
                                else:
                                    board[row-1][col-1] = '\u2B24'
                                print(row)
                                print(col)
                                break
                    else:
                        print("invalid input")
                print(f"{row} {col}")
                tcp_socket.send(f"{row} {col}".encode())
                if is_winner(player):
                    print_board()
                    board = [[' ' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
                    return "W"
            else:
                print("Waiting for the other player's move...")
                move = tcp_socket.recv(1024).decode()
                print(move)
                row, col = map(int, move.split())
                if(now == 'X'):
                    board[row-1][col-1] = '\u2716'
                else:
                    board[row-1][col-1] = '\u2B24'
                if is_winner(now):
                    print_board()
                    board = [[' ' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
                    return "L"

            if(now == 'O'):
                now = 'X' 
            else:
                now = 'O'
    except Exception:
        print("oppenent leave")
        return "W"

def client_room_private(client):
    data = client.recv(1024).decode()
    parts = data.split(' ')
    gip = parts[0]
    gport =  parts[1]
    game = parts[2]
    game_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    game_socket.bind((gip, int(gport)))
    game_socket.listen(1)
    while True:
        print("Using 'i' to invite others")
        command = input()
        if(command == 'i'):
                client.send(command.encode())
                data = client.recv(1024).decode()
                print(data)
                invitation = input("Invited user name: ")
                while invitation == "":
                            print('username cannot be empty.')
                            invitation = input("Invited user name: ")
                client.send(invitation.encode())
                data = client.recv(1024).decode()
                if(data == "ok"):
                    print("waiting for the result of invitation...")
                    data = client.recv(1024).decode()
                    if(data == "a"):
                        print("invitation is accepted")
                        new_tcp,addr =  game_socket.accept()
                        if(game == 'Gomoku'):
                            result = handle_game(new_tcp, 'X')
                        else:
                            result = handle_fish_game(new_tcp, 'X')
                        if(result == "W"):
                            print("You Win!!!")
                        else:
                            print("You Loss")
                        client.send("end".encode())
                        return
                    else:
                        print("invitation is rejected")
                        continue
                else:
                    print(f"User is either not online or not idle.")
        else:
            print("Invalid command")

def client_room_public(client):
    print("waiting for the other to join")
    data = client.recv(1024).decode()
    parts = data.split(' ')
    gip = parts[0]
    gport =  parts[1]
    game = parts[2]
    game_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    game_socket.bind((gip, int(gport)))
    game_socket.listen(1)
    data = client.recv(1024).decode()
    print(game)
    if data =="start":
        new_tcp,addr =  game_socket.accept()
        if(game == 'Gomoku'):
            result = handle_game(new_tcp, 'X')
        else:
            result = handle_fish_game(new_tcp, 'X')
        if(result == "W"):
            print("You Win!!!")
        else:
            print("You Loss")
        client.send("end".encode())
        return

def join_room(client):
    game_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    data = client.recv(1024).decode()
    parts = data.split(' ')
    gip =  parts[0]
    gport =  parts[1]
    game = parts[2]
    game_socket.connect((gip, int(gport)))
    if(game == 'Gomoku'):
        result =handle_game(game_socket, 'O')
    else:
        result =handle_fish_game(game_socket, 'O')
    game_socket.close()
    if(result == "W"):
        print("You Win!!!")
    else:
        print("You Loss")
    client.send("end".encode())
    return

def poll_invitation(client):
    global invitation_received
    global invite_temp
    while True:
        if(close_thread == True):
            break
        client.send("i".encode())
        data = client.recv(1024).decode()
        if(data.startswith('y')):
            parts = data.split(' ', 1)
            print(f"You have a new invitation from {parts[1]}")
            invitation_received = True
            invite_temp = "8972348927492"
            org = invite_temp
            print("the answer should be 'a' or 'r'\naccept or reject?")
            while org == invite_temp:
                continue
            while(invite_temp !="a" and invite_temp != "r"):
                invite_temp = input("the answer should be 'a' or 'r'\naccept or reject?\n")
            client.send(invite_temp.encode())
            if(invite_temp == "a"):
                join_room(client)
                invitation_received = False
            else:
                invitation_received = False
                continue
        else:
            continue

flag = 0
def client_lobby(client, username):
    global flag
    global invite_temp
    global close_thread
    inv_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    inv_socket.connect(("140.113.235.151", 26699))
    msg ="i " + username
    inv_socket.send(msg.encode())
    ack = inv_socket.recv(1024).decode()
    polling_thread = threading.Thread(target=poll_invitation, args=(inv_socket,))
    polling_thread.daemon = True
    polling_thread.start()
    
    try:
        data = client.recv(1024).decode()
        print(data)
        while True:
            command = input("Using 'ls' to show all online players and public room, 'o' to log out, 'c' to create room, 'j' to join the public room\n")
            if command == 'ls':
                client.send(command.encode())
                data = client.recv(1024).decode()
                print(data)
            elif command == 'o':
                client.send(command.encode())
                close_thread = True
                print("Logged out successfully.")

                return
            elif command == 'c':
                client.send(command.encode())
                name = input("room name: ")
                if(name != "" or " " in name):
                    choice = input("1. Gomoku\n2. Fishing\nwhich game do you want 1 or 2?: ")
                    if choice in ["1", "2"]:
                        rtype = input("1. public\n2. private\nwhat is the room type 1 or 2?: ")
                        if rtype in ["1", "2"]:
                            command = f"{choice}{rtype} {name}"
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
                                if(rtype == "1"):
                                    client_room_public(client)
                                else:
                                    client_room_private(client)
                            else:
                                client.send('no'.encode())
                                print("Room name already exsit.")
                        else:
                            client.send('no'.encode())
                            print('Invalid choice for room type.')
                    else:
                        client.send('no'.encode())
                        print('Invalid choice for game.')
                else:
                    client.send('no'.encode())
                    print('Invalid name. Room name can not be null or contain space.')
            elif command == 'j':
                name = input("room name: ")
                if(name != "" or " " in name):
                    command = f"j {name}"
                    client.send(command.encode())
                    data = client.recv(1024).decode()
                    if(data == "nan"):
                        print('room not exist or not idle')
                        continue
                    else:
                        print("join successful!")
                        join_room(client)
                else:
                    print('Invalid name. Room name can not be null or contain space.')
            elif command == 'a' or  command == 'r':
                invite_temp = command
                if(invitation_received == True):
                    while (1):
                        if(invitation_received != True):
                            break
                else:
                    print('Invalid command.')
            else:
                invite_temp = command
                if(invitation_received == True):
                    while (1):
                        if(invitation_received != True):
                            break
                    continue
                print('Invalid command.')
    except (ConnectionResetError, ConnectionAbortedError):
        print("[Error] Disconnected from the lobby server.")
    except (KeyboardInterrupt):
        client.send('byby'.encode())
        close_thread = True
        flag = 1
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
            if(flag == 1):
                break
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
                            close_thread = False
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
                data = client.recv(1024).decode()
        
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
