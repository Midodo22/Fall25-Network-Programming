import unittest

import games.tetris as tetris


class TetrisLogicTests(unittest.TestCase):
    def test_line_clear_scoring(self):
        game = tetris.SimpleTetris(width=4, height=4, seed=42)
        game.field[0] = [1, 1, 1, 1]
        game._clear_lines()
        self.assertEqual(game.lines, 1)
        self.assertEqual(game.score, 100)
        self.assertTrue(all(cell == 0 for cell in game.field[-1]))

    def test_hold_and_spawn_logic(self):
        game = tetris.SimpleTetris(width=4, height=4, seed=99)
        original_shape = game.piece.shape
        game.hold()
        self.assertEqual(game.hold_piece, original_shape)
        self.assertNotEqual(game.piece.shape, original_shape)
        game.hold()
        self.assertIsNotNone(game.hold_piece)


if __name__ == "__main__":
    unittest.main()
