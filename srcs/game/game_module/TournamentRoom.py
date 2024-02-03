from typing import List, Dict
import asyncio
import time
import threading

from socketio import AsyncServer

from .BaseRoom import BaseRoom
from blockchain.executeContract import record_transaction


class TournamentRoom(BaseRoom):
    """
    유저 네 명이 토너먼트 핑퐁 게임을 할 수 있는 게임방 인스턴스 정의

    BaseRoom 객체를 상속받는다
    """
    def __init__(self, sio: AsyncServer, player: List[str], room_name: str, mode: str) -> None:
        super().__init__(sio, player, room_name, mode, "/tournament")
        self._winner: List[str] = []  # 이긴 플레이어의 sid
        self._winner_side: str = ""  # 직전 판에 이긴 플레이어의 방향
        self._round: int = 0  # 현재 라운드 수
        self._tournament_log: List[Dict] = []

    async def _new_game(self) -> None:
        """
        새 게임 시작
        """
        # 초기화 작업 여기서 시행
        self._round += 1
        # 출전 플레이어 설정
        if self._round == 1:
            self._left_player, self._right_player = self._player[:2]
        elif self._round == 2:
            self._left_player, self._right_player = self._player[2:]
        elif self._round == 3:
            self._left_player, self._right_player = self._winner[:2]
        self._score[self._left_player] = 0
        self._score[self._right_player] = 0
        self._bar_loc_left, self._bar_loc_right = 0, 0
        self._ball_loc.zero()
        self._reset_ball_velocity()
        await asyncio.sleep(0.5)
        self._stay_state = False
        isError = await self._state_updata_loop()
        await self._game_end("normal" if not isError else "opponentLeft")

    async def _get_score(self, player) -> bool:
        """
        player가 점수를 얻은 경우

        parameter
        * player: 점수를 획득한 플레이어 (sid)

        True가 리턴된 경우 게임을 종료
        False인 경우 게임 속행
        """
        self._stay_time = time.time()
        self._stay_state = True
        self._score[player] += 1
        score_data = {
            "leftUserScore": self._score[self._left_player],
            "rightUserScore": self._score[self._right_player]
        }
        end_game = False
        if self._score[player] >= self.ENDSCORE:
            end_game = True
            left_session = await self._server.get_session(self._left_player, namespace="/tournament")
            right_session = await self._server.get_session(self._right_player, namespace="/tournament")
            if self._score[self._left_player] > self._score[self._right_player]:
                self._winner.append(self._left_player)
                self._winner_side = "left"
                self._tournament_log.append({
                    "game_id": self._round,
                    "winner": {
                        "name": left_session["intraId"],
                        "score": self._score[self._left_player],
                        },
                    "loser": {
                        "name": right_session["intraId"],
                        "score": self._score[self._right_player],
                        },
                })
            else:
                self._winner.append(self._right_player)
                self._winner_side = "right"
                self._tournament_log.append({
                    "game_id": self._round,
                    "winner": {
                        "name": right_session["intraId"],
                        "score": self._score[self._right_player],
                        },
                    "loser": {
                        "name": left_session["intraId"],
                        "score": self._score[self._left_player],
                        },
                })
        await self._server.emit(
            "updateGameScore", score_data, room=self._room_name, namespace=self._namespace
        )
        self._ball_loc.zero()
        self._reset_ball_velocity()
        return end_game

    async def _game_end(self, end_reason: str) -> None:
        """
        게임(라운드)이 종료되었을 경우 해당 함수 호출

        parameter
        * end_reason: 종료 사유

        normal: 정상 종료
        opponentLeft: 상대가 나감
        """
        if self._game_expire is True:
            return
        send_info = {
            "round": self._round,
            "reason": end_reason,
            "winnerSide": self._winner_side
        }
        self._game_start = False
        for player_sid in self._ready:
            self._ready[player_sid] = False
        await self._server.emit(
            "endGame", send_info, room=self._room_name, namespace=self._namespace
        )
        # 토너먼트 전체 종료. 전체 종료의 경우, 연결을 끊고 방을 닫는다.
        if self._round == 3 or end_reason == "opponentLeft":
            self._game_expire = True
            if self._tournament_log and len(self._tournament_log) == 3:
                self._tournament_log.append(int(time.time()))
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, record_transaction, self._tournament_log.copy())
            await self._server.close_room(self._room_name, namespace=self._namespace)
            for player in self._player:
                await self._server.disconnect(player, namespace=self._namespace)
