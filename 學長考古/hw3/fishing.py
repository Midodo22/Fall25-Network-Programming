import socket
import random
board_fish_SIZE_FISH = 8
NUM_FISH = 7

board_fish = [[' ' for _ in range(board_fish_SIZE_FISH)] for _ in range(board_fish_SIZE_FISH)]
fish_positions = set()

player_positions = {'X': (0, 0), 'O': (board_fish_SIZE_FISH - 1, board_fish_SIZE_FISH - 1)}
board_fish[0][0] = 'X'
board_fish[board_fish_SIZE_FISH - 1][board_fish_SIZE_FISH - 1] = 'O'

scores = {'X': 0, 'O': 0}

def print_board_fish():
    print("    " + "   ".join(f"{i+1:2}" for i in range(board_fish_SIZE_FISH)))
    print("  " + "-" * (board_fish_SIZE_FISH * 5 - 1)+ "----")
    for i, row in enumerate(board_fish):
        print(f"{i+1:2} | " + ' | '.join(f"{cell:2}" for cell in row) + " |")
        print("  " + "-" * (board_fish_SIZE_FISH * 5 - 1)+ "----")

def is_valid_move(x, y):
    return 0 <= x < board_fish_SIZE_FISH and 0 <= y < board_fish_SIZE_FISH and board_fish[x][y] not in {'X', 'O'}

def move_player(player, direction):
    px, py = player_positions[player]
    new_x, new_y = px, py
    if direction == 'w': new_x -= 1 
    elif direction == 'a': new_y -= 1 
    elif direction == 's': new_x += 1 
    elif direction == 'd': new_y += 1

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
    if not fish_positions:
        tcp_socket.send(b'non') 
    else:
        fish_data = " ".join(f"{x} {y}" for x, y in fish_positions)
        tcp_socket.send(fish_data.encode())

def receive_fish_positions(tcp_socket):
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

def handle_game(tcp_socket, player):
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
            
            if player == 'X':
                fish_positions = move_fish()
                send_fish_positions(tcp_socket)
                ack = tcp_socket.recv(1024).decode()
            else:
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