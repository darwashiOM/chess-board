import unittest

from chessboard_app.lichess_client import LichessClient


class FakeResponse:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class LichessClientTest(unittest.TestCase):
    def test_validate_token_sends_bearer_auth_and_returns_username(self):
        transport = FakeTransport([FakeResponse(data={"username": "player1"})])
        client = LichessClient("secret", transport=transport)

        username = client.validate_token()

        self.assertEqual(username, "player1")
        method, url, kwargs = transport.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://lichess.org/api/account")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")

    def test_validate_token_rejects_bad_token(self):
        transport = FakeTransport([FakeResponse(status_code=401, text="Unauthorized")])
        client = LichessClient("bad", transport=transport)

        with self.assertRaises(PermissionError):
            client.validate_token()

    def test_make_move_posts_board_api_move(self):
        transport = FakeTransport([FakeResponse(data={"ok": True})])
        client = LichessClient("secret", transport=transport)

        client.make_move("game123", "e2e4")

        method, url, kwargs = transport.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://lichess.org/api/board/game/game123/move/e2e4")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")

    def test_active_games_uses_account_playing_endpoint(self):
        transport = FakeTransport([FakeResponse(data={"nowPlaying": [{"gameId": "abc"}]})])
        client = LichessClient("secret", transport=transport)

        games = client.active_games()

        self.assertEqual(games, [{"gameId": "abc"}])
        self.assertEqual(transport.calls[0][1], "https://lichess.org/api/account/playing")

    def test_game_controls_use_board_api_paths(self):
        transport = FakeTransport([FakeResponse(), FakeResponse(), FakeResponse()])
        client = LichessClient("secret", transport=transport)

        client.resign("game1")
        client.abort("game1")
        client.handle_draw("game1", accept=True)

        self.assertEqual(transport.calls[0][1], "https://lichess.org/api/board/game/game1/resign")
        self.assertEqual(transport.calls[1][1], "https://lichess.org/api/board/game/game1/abort")
        self.assertEqual(transport.calls[2][1], "https://lichess.org/api/board/game/game1/draw/yes")


if __name__ == "__main__":
    unittest.main()
