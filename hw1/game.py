from config import server_data as server

# Set initial board setup
class board:
    def __init__(self):
        self.BP1 = [4, 4, 4, 4, 4, 4, 0]
        self.BP2 = [4, 4, 4, 4, 4, 4, 0]
        self.P1InPlay = sum(self.BP1[:6])
        self.P2InPlay = sum(self.BP2[:6])
    
    def serialize(self):
        return {
            "BP1": self.BP1,
            "BP2": self.BP2,
            "P1InPlay": self.P1InPlay,
            "P2InPlay": self.P2InPlay
        }

    # Rebuild board from dict
    @classmethod
    def deserialize(cls, data):
        b = cls()
        b.BP1 = data["BP1"]
        b.BP2 = data["BP2"]
        b.P1InPlay = data["P1InPlay"]
        b.P2InPlay = data["P2InPlay"]
        return b

# serialize_board: takes a board object, returns dict
def serialize_board(board_obj):
    return board_obj.serialize()

# deserialize_board: takes dict, returns board object
def deserialize_board(board_dict):
    return board.board.deserialize(board_dict)

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
    extra_turn = False
    
    if(player == 'Host'):
        # Host is P1
        Stones = BP1[move - 1]
        if Stones + move < 7:
            BP1[move - 1] = 0
            for i in range(move, Stones + move):
                BP1[i] = BP1[i] + 1
            if (BP1[i] == 1) and (i != 6):
                BP1[i] = BP1[i]+BP2[5-i]
                BP2[5-i] = 0
                extra_turn = True
        elif Stones + move == 7:
            BP1[move - 1] = 0
            for i in range(move, Stones + move):
                BP1[i] = BP1[i] + 1
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
    else:
        if Stones + move < 7:
            BP2[move - 1] = 0
            for i in range(move, Stones + move):
                BP2[i] = BP2[i] + 1
            if (BP2[i] == 1) and (i != 6):
                BP2[i] = BP2[i] + BP1[5-i]
                BP1[5-i] = 0
                extra_turn = True
        elif Stones + move == 7:
            BP2[move - 1] = 0
            for i in range(move, Stones + move):
                BP2[i] = BP2[i] + 1
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
    
    board.P2InPlay = sum(board.BP2[:6])
    board.P1InPlay = sum(board.BP1[:6])
    print_board(room_id)
    
    return extra_turn
    
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
