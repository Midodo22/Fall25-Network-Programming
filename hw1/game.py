from config import server_data as server

# Set initial board setup
class board:
    def __init__(self):
        self.BP1 = [4, 4, 4, 4, 4, 4, 0]
        self.BP2 = [4, 4, 4, 4, 4, 4, 0]
        self.P1InPlay = sum(self.BP1[:6])
        self.P2InPlay = sum(self.BP2[:6])

#Print board. Second player section reversed to emulate mancala board from Player 1 view. Seperate single-value lists are capture pockets.
def print_board(room_id):
    board = server.rooms[room_id]['board']
    BP1 = board.BP1
    BP2 = board.BP2
    BP2.reverse()
    print("P1   1 2 3 4 5 6     ")
    print("  -----------------  ")
    print(f"    |{BP2[1]}|{BP2[2]}|{BP2[3]}|{BP2[4]}|{BP2[5]}|{BP2[6]}|    ")
    print(f" {BP2[0]}  -------------  {BP1[6]} ")
    print(f"    |{BP1[0]}|{BP1[1]}|{BP1[2]}|{BP1[3]}|{BP1[4]}|{BP1[5]}|    ")
    print(f"  -----------------  ")
    print("     6 5 4 3 2 1   P2")
    BP2.reverse()

def update_board(player, move, room_id):
    board = server.rooms[room_id]['board']
    BP1 = board.BP1
    BP2 = board.BP2
    
    if(player == 'Host'):
        # Host is P1
        while not det_game_over(room_id):
            Stones = BP1[move - 1]
            if Stones + move < 7:
                BP1[move - 1] = 0
                for i in range(move, Stones + move):
                    BP1[i] = BP1[i] + 1
                if (BP1[i] == 1) and (i != 6):
                    BP1[i] = BP1[i]+BP2[5-i]
                    BP2[5-i] = 0
                else:
                    break
            elif Stones + move == 7:
                BP1[move - 1] = 0
                for i in range(move, Stones + move):
                    BP1[i] = BP1[i] + 1
                break
            else:
                OFlow = Stones + move - 6

                for i in range(move, 7):
                    BP1[i] = BP1[i] + 1
                if OFlow < 7:
                    BP1[move - 1] = 0
                    for i in range(0, OFlow - 1):
                        BP2[i] = BP2[i] + 1
                # This handles overflow back into P1s pockets for large amount of seeds.
                else:
                    BP1[move - 1] = 0
                    for i in range(0, 6):
                        BP2[i] = BP2[i] + 1
                    for i in range(0, OFlow - 7):
                        BP1[i] = BP1[i] + 1
                    if (BP1[i] == 1) and (i != 6):
                        BP1[i] = BP1[i] + BP2[5-i]
                        BP2[5-i] = 0
                break
    else:
        while not det_game_over(room_id):
            if Stones + move < 7:
                BP2[move - 1] = 0
                for i in range(move, Stones + move):
                    BP2[i] = BP2[i] + 1
                if (BP2[i] == 1) and (i != 6):
                    BP2[i] = BP2[i] + BP1[5-i]
                    BP1[5-i] = 0
                else:
                    break
            elif Stones + move == 7:
                BP2[move - 1] = 0
                for i in range(move, Stones + move):
                    BP2[i] = BP2[i] + 1
                break
            else:
                print('OF')
                OFlow = Stones + move - 6
                for i in range(move, 7):
                    BP2[i] = BP2[i] + 1
                if OFlow < 7:
                    BP2[move - 1] = 0
                    for i in range(0, OFlow - 1):
                        BP1[i] = BP1[i] + 1

                else:
                    BP2[move - 1] = 0
                    for i in range(0, 6):
                        BP1[i] = BP1[i] + 1
                    for i in range(0, OFlow - 5):
                        BP2[i] = BP2[i] + 1
                    if (BP2[i] == 1) and (i != 6):
                        BP2[i] = BP2[i] + BP1[5-i]
                        BP1[5-i] = 0
                break
    
    board.P2InPlay = sum(board.BP2[:6])
    board.P1InPlay = sum(board.BP1[:6])
    print_board()
    
def det_game_over(room_id):
    board = server.rooms[room_id]['board']
    if (board.P1InPlay != 0) and (board.P2InPlay != 0):
        return False
    return True

def det_winner(room_id):
    board = server.rooms[room_id]['board']
    if board.BP1[6] > board.BP2[6]:
        print(f"Game over. \nHost scored {board.BP1[6]}, \nClient scored: {board.BP2[6]}.\nThe host won!")
    else:
        print(f"Game over. \nHost scored {board.BP1[6]}, \nClient scored: {board.BP2[6]}.\nThe client won!")
