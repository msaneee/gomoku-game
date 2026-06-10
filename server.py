#!/usr/bin/env python3
import asyncio
import websockets
from collections import deque

# Game constants
BOARD_SIZE = 10
WIN_CONDITION = 5

# Server state
waiting_players = deque()
games = []

class GameRoom:
    def __init__(self, player1, player2):
        self.player1 = player1
        self.player2 = player2
        self.board = [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.current_turn = "BLACK"
        self.game_active = True
        
        self.player1.color = "BLACK"
        self.player2.color = "WHITE"
        
        # Send start messages
        asyncio.create_task(self._safe_send(self.player1.websocket, f"START|BLACK|Your turn|{self.player2.name}"))
        asyncio.create_task(self._safe_send(self.player2.websocket, f"START|WHITE|Waiting|{self.player1.name}"))
        
        print(f"Game started: {self.player1.name} (BLACK) vs {self.player2.name} (WHITE)")
    
    async def _safe_send(self, websocket, message):
        """Safely send a message without crashing"""
        try:
            await websocket.send(message)
            return True
        except Exception as e:
            print(f"Failed to send message: {e}")
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
            await self._safe_send(player.websocket, "ERROR|Position already occupied")
            return False
        
        stone = 1 if player.color == "BLACK" else 2
        self.board[row][col] = stone
        
        move_msg = f"MOVE|{player.color}|{row}|{col}"
        await self._safe_send(self.player1.websocket, move_msg)
        await self._safe_send(self.player2.websocket, move_msg)
        
        print(f"{player.name} placed {player.color} at ({row},{col})")
        
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
        
        # Diagonal (\)
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
        
        # Diagonal (/)
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
        """Handle a player leaving - sends quit message to BOTH players"""
        if not self.game_active:
            return
            
        self.game_active = False
        
        # Determine the message
        if is_quit:
            quit_message = f"{player.name} has quit the game"
        else:
            quit_message = f"{player.name} disconnected"
        
        # Format: QUIT|quitter_name|message_for_display
        full_message = f"QUIT|{player.name}|{quit_message}"
        
        print(f"\n*** PLAYER QUIT EVENT ***")
        print(f"Quitter: {player.name}")
        print(f"Message: {full_message}")
        
        # Send to the other player
        other = self.player2 if player == self.player1 else self.player1
        if other:
            await self._safe_send(other.websocket, full_message)
            print(f"✓ Sent quit message to: {other.name}")
        
        # Send to the quitting player
        await self._safe_send(player.websocket, full_message)
        print(f"✓ Sent quit message to: {player.name} (the quitter)")
        
        await asyncio.sleep(0.1)
        print(f"*** Game ended: {quit_message} ***\n")


class Player:
    def __init__(self, websocket, name):
        self.websocket = websocket
        self.name = name
        self.color = None
        self.game = None


async def handle_client(websocket):
    """Handle a new client connection"""
    player = None
    
    try:
        # Wait for player name
        name = await websocket.recv()
        name = name.strip()
        
        if not name or len(name) > 20:
            await websocket.send("ERROR|Invalid name")
            return
        
        player = Player(websocket, name)
        await websocket.send(f"CONNECTED|Welcome {name}")
        print(f"{name} connected")
        
        # Add to waiting queue
        waiting_players.append(player)
        await websocket.send("WAITING|Searching for opponent...")
        
        # Try to match players
        await try_match_players()
        
        # Handle incoming messages
        async for message in websocket:
            if message == "QUIT":
                print(f"{player.name} sent QUIT command")
                if player.game:
                    await player.game.remove_player(player, is_quit=True)
                    if player.game in games:
                        games.remove(player.game)
                if player in waiting_players:
                    waiting_players.remove(player)
                break
            
            if message.startswith("MOVE|"):
                parts = message.split("|")
                row = int(parts[1])
                col = int(parts[2])
                
                if player.game:
                    await player.game.make_move(player, row, col)
    
    except websockets.exceptions.ConnectionClosed:
        print(f"Client disconnected unexpectedly: {player.name if player else 'unknown'}")
        if player:
            if player.game:
                await player.game.remove_player(player, is_quit=False)
                if player.game in games:
                    games.remove(player.game)
            if player in waiting_players:
                waiting_players.remove(player)
    except Exception as e:
        print(f"Error in handle_client: {e}")
    finally:
        if player and player in waiting_players:
            waiting_players.remove(player)


async def try_match_players():
    """Match waiting players into games"""
    while len(waiting_players) >= 2:
        player1 = waiting_players.popleft()
        player2 = waiting_players.popleft()
        
        game = GameRoom(player1, player2)
        games.append(game)
        
        player1.game = game
        player2.game = game


async def main():
    """Start the WebSocket server"""
    host = "localhost"
    port = 8080
    
    print(f"=== GoMoKu Python Server ===")
    print(f"Listening on {host}:{port}")
    print("Waiting for players...\n")
    
    async with websockets.serve(handle_client, host, port):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())