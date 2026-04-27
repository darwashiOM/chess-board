from __future__ import annotations

from typing import Any
from urllib import parse
from urllib import request as urllib_request
from urllib.error import HTTPError


class UrllibTransport:
    def request(self, method: str, url: str, **kwargs: Any):
        headers = kwargs.get("headers", {})
        body = None
        if "data" in kwargs:
            body = parse.urlencode(kwargs["data"]).encode("utf-8")
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                **headers,
            }
        req = urllib_request.Request(url, data=body, method=method, headers=headers)
        try:
            response = urllib_request.urlopen(req, timeout=kwargs.get("timeout", 10))
        except HTTPError as exc:
            return UrllibResponse(exc.code, exc.read().decode("utf-8"))
        return UrllibResponse(response.status, response.read().decode("utf-8"))


class UrllibResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def json(self):
        import json

        return json.loads(self.text)


class LichessClient:
    def __init__(
        self,
        token: str,
        transport: Any | None = None,
        base_url: str = "https://lichess.org",
    ):
        self.token = token
        self.transport = transport or UrllibTransport()
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, data: dict[str, Any] | None = None):
        response = self.transport.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            data=data,
            timeout=10,
        )
        if response.status_code == 401:
            raise PermissionError("Lichess token was rejected")
        if response.status_code == 429:
            raise RuntimeError("Lichess rate limit reached")
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"Lichess request failed: {response.status_code} {response.text}")
        return response

    def validate_token(self) -> str:
        response = self._request("GET", "/api/account")
        data = response.json()
        username = data.get("username")
        if not username:
            raise RuntimeError("Lichess account response did not include a username")
        return username

    def make_move(self, game_id: str, uci: str) -> None:
        self._request("POST", f"/api/board/game/{game_id}/move/{uci}")

    def active_games(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/api/account/playing")
        return response.json().get("nowPlaying", [])

    def resign(self, game_id: str) -> None:
        self._request("POST", f"/api/board/game/{game_id}/resign")

    def abort(self, game_id: str) -> None:
        self._request("POST", f"/api/board/game/{game_id}/abort")

    def handle_draw(self, game_id: str, accept: bool) -> None:
        answer = "yes" if accept else "no"
        self._request("POST", f"/api/board/game/{game_id}/draw/{answer}")

    def challenge_friend(
        self,
        username: str,
        *,
        clock_limit: int,
        increment: int,
        rated: bool = False,
        color: str = "random",
        variant: str = "standard",
    ) -> dict[str, Any]:
        response = self._request("POST", f"/api/challenge/{username}", data={
            "clock.limit": clock_limit,
            "clock.increment": increment,
            "rated": _bool(rated),
            "color": color,
            "variant": variant,
        })
        return response.json()

    def challenge_ai(
        self,
        *,
        level: int,
        clock_limit: int,
        increment: int,
        color: str = "random",
        variant: str = "standard",
    ) -> dict[str, Any]:
        response = self._request("POST", "/api/challenge/ai", data={
            "level": level,
            "clock.limit": clock_limit,
            "clock.increment": increment,
            "color": color,
            "variant": variant,
        })
        return response.json()

    def create_seek(
        self,
        *,
        time_minutes: int,
        increment: int,
        rated: bool = False,
        color: str = "random",
        variant: str = "standard",
    ) -> dict[str, Any]:
        response = self._request("POST", "/api/board/seek", data={
            "time": time_minutes,
            "increment": increment,
            "rated": _bool(rated),
            "color": color,
            "variant": variant,
        })
        data = response.json()
        return data or {"ok": True}

    def open_challenge(
        self,
        *,
        clock_limit: int,
        increment: int,
        rated: bool = False,
        name: str = "ChessBoard",
        variant: str = "standard",
    ) -> dict[str, Any]:
        response = self._request("POST", "/api/challenge/open", data={
            "clock.limit": clock_limit,
            "clock.increment": increment,
            "rated": _bool(rated),
            "name": name,
            "variant": variant,
        })
        return response.json()

    def next_puzzle(self, difficulty: str | None = None) -> dict[str, Any]:
        path = "/api/puzzle/next"
        if difficulty:
            path = f"{path}?{parse.urlencode({'difficulty': difficulty})}"
        return self._request("GET", path).json()

    def daily_puzzle(self) -> dict[str, Any]:
        return self._request("GET", "/api/puzzle/daily").json()


def _bool(value: bool) -> str:
    return "true" if value else "false"
