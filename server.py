#!/usr/bin/env python3
import asyncio
import websockets
from collections import deque
import os

# Game constants
BOARD_SIZE = 10
WIN_CONDITION = 5

# Server state
waiting_players = deque()
games = []
active_players = {}

# Get port from environment variable (Render sets this)
PORT = int(os.environ.get('PORT', 8080))


class GameRoom:
    def __init__(self, player1, player2):
        self.player1 = player1
        self.player2 = player2
        self.board = [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.current_turn = "BLACK"
        self.game_active = True
        self.game_id = f"game_{id(self)}"
        
        self.player1.color = "BLACK"
        self.player2.color = "WHITE"
        
        self.player1.game = self
        self.player2.game = self
        
        active_players[self.player1.player_id] = self.player1
        active_players[self.player2.player_id] = self.player2
        
        asyncio.create_task(self._safe_send(self.player1.websocket, f"START|BLACK|Your turn|{self.player2.name}"))
        asyncio.create_task(self._safe_send(self.player2.websocket, f"START|WHITE|Waiting|{self.player1.name}"))
        
        print(f"Game started: {self.player1.name} (BLACK) vs {self.player2.name} (WHITE)")
    
    async def _safe_send(self, websocket, message):
        try:
            await websocket.send(message)
            return True
        except Exception as e:
            print(f"Failed to send: {e}")
            return False
    
    async def make_move(self, player, row, col):
        if not self.game_active:
            await self._safe_send(player.websocket, "ERROR|Game already ended")
            return False
        
        if player.color != self.current_turn:
            await self._safe_send(player.websocket, "ERROR|Not your turn")
            return False
        
        if row < 0 or row >= BOARD_SIZE or col < 0 or col >= BOARD_SIZE:
            await self._safe_send(player.websocket, "ERROR|Invalid position")
            return False
        
        if self.board[row][col] != 0:
            await self._safe_send(player.websocket, "ERROR|Position occupied")
            return False
        
        stone = 1 if player.color == "BLACK" else 2
        self.board[row][col] = stone
        
        move_msg = f"MOVE|{player.color}|{row}|{col}"
        await self._safe_send(self.player1.websocket, move_msg)
        await self._safe_send(self.player2.websocket, move_msg)
        
        print(f"{player.name} placed at ({row},{col})")
        
        if self.check_win(row, col, stone):
            self.game_active = False
            win_msg = f"WIN|{player.color}|{player.name} wins!"
            await self._safe_send(self.player1.websocket, win_msg)
            await self._safe_send(self.player2.websocket, win_msg)
            print(f"{player.name} wins!")
            return True
        
        if self.is_draw():
            self.game_active = False
            draw_msg = "DRAW|Game ended in a draw!"
            await self._safe_send(self.player1.websocket, draw_msg)
            await self._safe_send(self.player2.websocket, draw_msg)
            print("Game ended in a draw!")
            return True
        
        self.current_turn = "WHITE" if self.current_turn == "BLACK" else "BLACK"
        turn_msg = f"TURN|{self.current_turn}"
        await self._safe_send(self.player1.websocket, turn_msg)
        await self._safe_send(self.player2.websocket, turn_msg)
        
        return True
    
    def check_win(self, row, col, stone):
        # Horizontal
        count = 1
        c = col - 1
        while c >= 0 and self.board[row][c] == stone:
            count += 1
            c -= 1
        c = col + 1
        while c < BOARD_SIZE and self.board[row][c] == stone:
            count += 1
            c += 1
        if count >= WIN_CONDITION:
            return True
        
        # Vertical
        count = 1
        r = row - 1
        while r >= 0 and self.board[r][col] == stone:
            count += 1
            r -= 1
        r = row + 1
        while r < BOARD_SIZE and self.board[r][col] == stone:
            count += 1
            r += 1
        if count >= WIN_CONDITION:
            return True
        
        # Diagonal
        count = 1
        r, c = row - 1, col - 1
        while r >= 0 and c >= 0 and self.board[r][c] == stone:
            count += 1
            r -= 1
            c -= 1
        r, c = row + 1, col + 1
        while r < BOARD_SIZE and c < BOARD_SIZE and self.board[r][c] == stone:
            count += 1
            r += 1
            c += 1
        if count >= WIN_CONDITION:
            return True
        
        # Diagonal
        count = 1
        r, c = row - 1, col + 1
        while r >= 0 and c < BOARD_SIZE and self.board[r][c] == stone:
            count += 1
            r -= 1
            c += 1
        r, c = row + 1, col - 1
        while r < BOARD_SIZE and c >= 0 and self.board[r][c] == stone:
            count += 1
            r += 1
            c -= 1
        if count >= WIN_CONDITION:
            return True
        
        return False
    
    def is_draw(self):
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                if self.board[row][col] == 0:
                    return False
        return True
    
    async def remove_player(self, player, is_quit=False):
        if not self.game_active:
            return
            
        self.game_active = False
        
        if is_quit:
            message = f"QUIT|{player.name}|{player.name} quit the game"
        else:
            message = f"QUIT|{player.name}|{player.name} disconnected"
        
        other = self.player2 if player == self.player1 else self.player1
        if other:
            await self._safe_send(other.websocket, message)
        
        if player.player_id in active_players:
            del active_players[player.player_id]
        if other and other.player_id in active_players:
            del active_players[other.player_id]
        
        if self in games:
            games.remove(self)


class Player:
    def __init__(self, websocket, name, player_id=None):
        self.websocket = websocket
        self.name = name
        self.player_id = player_id or f"player_{id(self)}"
        self.color = None
        self.game = None


async def handle_client(websocket):
    """Handle WebSocket connection"""
    player = None
    
    try:
        # Wait for player name
        name = await websocket.recv()
        name = name.strip()
        
        print(f"New connection: {name}")
        
        if not name or len(name) > 20:
            await websocket.send("ERROR|Invalid name")
            return
        
        player = Player(websocket, name)
        await websocket.send(f"CONNECTED|Welcome {name}")
        
        # Add to waiting queue
        waiting_players.append(player)
        await websocket.send("WAITING|Searching for opponent...")
        print(f"{name} added to queue. Queue size: {len(waiting_players)}")
        
        # Try to match players
        await try_match_players()
        
        # Handle incoming messages
        async for message in websocket:
            print(f"Message from {name}: {message}")
            
            if message == "QUIT":
                print(f"{name} quit")
                if player.game:
                    await player.game.remove_player(player, is_quit=True)
                if player in waiting_players:
                    waiting_players.remove(player)
                break
            
            if message.startswith("MOVE|"):
                parts = message.split("|")
                row = int(parts[1])
                col = int(parts[2])
                if player.game:
                    await player.game.make_move(player, row, col)
                else:
                    await player.websocket.send("ERROR|No active game")
    
    except websockets.exceptions.ConnectionClosed:
        print(f"Connection closed: {player.name if player else 'unknown'}")
        if player and player.game:
            await player.game.remove_player(player, is_quit=False)
        if player and player in waiting_players:
            waiting_players.remove(player)
    except Exception as e:
        print(f"Error: {e}")


async def try_match_players():
    """Match waiting players"""
    while len(waiting_players) >= 2:
        player1 = waiting_players.popleft()
        player2 = waiting_players.popleft()
        
        game = GameRoom(player1, player2)
        games.append(game)
        
        print(f"✓ Match found: {player1.name} vs {player2.name}")
        print(f"Active games: {len(games)}")


async def main():
    print(f"=== GoMoKu Python Server ===")
    print(f"Starting WebSocket server on port {PORT}")
    print(f"Waiting for players...\n")
    
    # Start the server
    async with websockets.serve(handle_client, "0.0.0.0", PORT):
        print(f"Server running on ws://0.0.0.0:{PORT}")
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())