#!/usr/bin/env python3
import asyncio
import json
import websockets
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
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
        
        print(f"Game started [{self.game_id}]: {self.player1.name} (BLACK) vs {self.player2.name} (WHITE)")
    
    async def _safe_send(self, websocket, message):
        try:
            if websocket and hasattr(websocket, 'open') and websocket.open:
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
            await self._safe_send(player.websocket, "ERROR|Invalid position (0-9 only)")
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
            self._cleanup_sessions()
            return True
        
        if self.is_draw():
            self.game_active = False
            draw_msg = "DRAW|Game ended in a draw!"
            await self._safe_send(self.player1.websocket, draw_msg)
            await self._safe_send(self.player2.websocket, draw_msg)
            print("Game ended in a draw!")
            self._cleanup_sessions()
            return True
        
        self.current_turn = "WHITE" if self.current_turn == "BLACK" else "BLACK"
        turn_msg = f"TURN|{self.current_turn}"
        await self._safe_send(self.player1.websocket, turn_msg)
        await self._safe_send(self.player2.websocket, turn_msg)
        
        return True
    
    def check_win(self, row, col, stone):
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
    
    def _cleanup_sessions(self):
        if self.player1.player_id in active_players:
            del active_players[self.player1.player_id]
        if self.player2.player_id in active_players:
            del active_players[self.player2.player_id]
    
    async def end_game_for_player(self, player, is_quit=False):
        if not self.game_active:
            return
            
        self.game_active = False
        
        if is_quit:
            quit_message = f"{player.name} quit the game"
        else:
            quit_message = f"{player.name} closed the tab - game ended"
        
        full_message = f"QUIT|{player.name}|{quit_message}"
        
        print(f"\n*** GAME ENDED ***")
        print(f"Player: {player.name}")
        print(f"Reason: {quit_message}")
        
        other = self.player2 if player == self.player1 else self.player1
        if other and other.websocket:
            await self._safe_send(other.websocket, full_message)
            print(f"✓ Notified {other.name}")
        
        self._cleanup_sessions()
        
        if self in games:
            games.remove(self)
        
        print(f"*** Game removed. Active games: {len(games)} ***\n")


class Player:
    def __init__(self, websocket, name, player_id=None, session_id=None):
        self.websocket = websocket
        self.name = name
        self.player_id = player_id or f"player_{int(asyncio.get_event_loop().time() * 1000)}_{id(self)}"
        self.session_id = session_id or f"session_{int(asyncio.get_event_loop().time() * 1000)}"
        self.color = None
        self.game = None


async def handle_client(websocket, path=None):
    """Handle WebSocket client connections"""
    player = None
    session_id = f"session_{int(asyncio.get_event_loop().time() * 1000)}_{id(websocket)}"
    
    try:
        first_message = await websocket.recv()
        first_message = first_message.strip()
        
        print(f"New WebSocket connection - Session: {session_id}")
        print(f"First message: {first_message}")
        
        # Check for reconnect
        if first_message.startswith("RECONNECT|"):
            parts = first_message.split("|")
            if len(parts) >= 3:
                player_id = parts[1]
                old_session_id = parts[2]
                player_name = parts[3] if len(parts) > 3 else "Player"
                
                if player_id in active_players:
                    existing_player = active_players[player_id]
                    
                    if existing_player.session_id == old_session_id:
                        if existing_player.game and existing_player.game.game_active:
                            existing_player.websocket = websocket
                            existing_player.session_id = session_id
                            player = existing_player
                            active_players[player_id] = player
                            
                            await websocket.send(f"CONNECTED|Welcome back {player.name} - Game restored")
                            await asyncio.sleep(0.1)
                            
                            other_player = player.game.player2 if player.game.player1 == player else player.game.player1
                            await websocket.send(f"START|{player.color}|Continue game|{other_player.name}")
                            await asyncio.sleep(0.1)
                            
                            board = player.game.board
                            for row in range(BOARD_SIZE):
                                for col in range(BOARD_SIZE):
                                    if board[row][col] != 0:
                                        stone_color = "BLACK" if board[row][col] == 1 else "WHITE"
                                        await websocket.send(f"MOVE|{stone_color}|{row}|{col}")
                                        await asyncio.sleep(0.02)
                            
                            await websocket.send(f"TURN|{player.game.current_turn}")
                            await websocket.send("CONNECTED|Game restored! Continue playing.")
                        else:
                            player = Player(websocket, player_name, player_id, session_id)
                            active_players[player_id] = player
                            await websocket.send(f"CONNECTED|Welcome {player.name}")
                            await add_to_waiting(player)
                    else:
                        player = Player(websocket, player_name, player_id, session_id)
                        active_players[player_id] = player
                        await websocket.send(f"CONNECTED|Welcome {player.name}")
                        await add_to_waiting(player)
                else:
                    player = Player(websocket, player_name, player_id, session_id)
                    active_players[player_id] = player
                    await websocket.send(f"CONNECTED|Welcome {player.name}")
                    await add_to_waiting(player)
            else:
                name = first_message
                player = Player(websocket, name, None, session_id)
                await websocket.send(f"CONNECTED|Welcome {player.name}")
                await add_to_waiting(player)
        else:
            name = first_message
            if not name or len(name) > 20:
                await websocket.send("ERROR|Invalid name")
                return
            
            player = Player(websocket, name, None, session_id)
            await websocket.send(f"CONNECTED|Welcome {player.name}")
            await add_to_waiting(player)
        
        # Handle incoming messages
        async for message in websocket:
            if message == "QUIT":
                if player.game:
                    await player.game.end_game_for_player(player, is_quit=True)
                if player in waiting_players:
                    waiting_players.remove(player)
                if player.player_id in active_players:
                    del active_players[player.player_id]
                break
            
            if message == "PAGE_CLOSE":
                if player.game:
                    await player.game.end_game_for_player(player, is_quit=False)
                if player in waiting_players:
                    waiting_players.remove(player)
                if player.player_id in active_players:
                    del active_players[player.player_id]
                break
            
            if message.startswith("MOVE|"):
                parts = message.split("|")
                if len(parts) >= 3:
                    row = int(parts[1])
                    col = int(parts[2])
                    
                    if player.game:
                        await player.game.make_move(player, row, col)
                    else:
                        await player.websocket.send("ERROR|No active game")
    
    except websockets.exceptions.ConnectionClosed:
        print(f"Connection closed for: {player.name if player else 'unknown'}")
        if player and player.game and player.game.game_active:
            await player.game.end_game_for_player(player, is_quit=False)
        if player and player.player_id in active_players:
            del active_players[player.player_id]
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if player and not player.game and player in waiting_players:
            waiting_players.remove(player)


async def add_to_waiting(player):
    waiting_players.append(player)
    await player.websocket.send("WAITING|Searching for opponent...")
    print(f"{player.name} added to waiting queue. Queue size: {len(waiting_players)}")
    await try_match_players()


async def try_match_players():
    while len(waiting_players) >= 2:
        player1 = waiting_players.popleft()
        player2 = waiting_players.popleft()
        
        game = GameRoom(player1, player2)
        games.append(game)
        
        print(f"✓ Match found! {player1.name} vs {player2.name}")
        print(f"Active games: {len(games)}")


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks"""
    
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress health check logs
        if args[0] != 'HEAD / HTTP/1.1':
            print(f"Health check: {args}")
    
    def handle_one_request(self):
        try:
            super().handle_one_request()
        except Exception:
            pass


def run_health_server():
    """Run a simple HTTP server for health checks on a different port"""
    # Find an available port for health checks (Render uses PORT env var)
    health_port = int(os.environ.get('PORT', 8080)) + 1
    server = HTTPServer(('0.0.0.0', health_port), HealthCheckHandler)
    print(f"Health check server running on port {health_port}")
    server.serve_forever()


async def main():
    print(f"=== GoMoKu Python Server ===")
    print(f"WebSocket server will run on port {PORT}")
    print("Waiting for players...\n")
    
    # Start health check server in a separate thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    # Run WebSocket server
    async with websockets.serve(handle_client, "0.0.0.0", PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())