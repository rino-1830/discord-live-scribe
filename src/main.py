"""Discordボットを起動し音声を収集するエントリポイント。

本モジュールは以下の責務を持つ。

* `.env` ファイルから環境変数を読み込む。
* Discord ボットを起動する。
* 受信した音声を PCM へ変換して Redis Streams に書き込む。
* Redis Streams を監視する STT ワーカーを起動し、音声を文字起こしする。
"""

from __future__ import annotations

import asyncio
import importlib
import os
from types import ModuleType
from typing import Any, Dict, Optional

import discord
import redis.asyncio as redis
from discord.ext import commands
from dotenv import load_dotenv
from redis.exceptions import ConnectionError

sinks_module: ModuleType | None
try:
    sinks_module = importlib.import_module("discord.sinks")
except Exception:  # pragma: no cover - 環境依存のためテスト除外
    sinks_module = None

RawDataSink: type[Any]
if sinks_module is not None:
    RawDataSink = sinks_module.RawData  # type: ignore[assignment]
else:

    class _RawDataSink:
        """discord.sinks が利用できない環境向けの簡易 Sink 基底クラス。"""

        def __init__(self) -> None:
            """内部状態を初期化する。"""

            self.audio_data = {}

        def cleanup(self) -> None:  # pragma: no cover - 実装はダミー
            """後処理を行うためのダミーメソッド。"""

            return None

    RawDataSink = _RawDataSink


class RedisAudioStream:
    """Redis Streams を利用した音声チャンク管理クラス。"""

    def __init__(self, redis_client: redis.Redis[bytes], stream_name: str) -> None:
        """インスタンスを生成する。

        Args:
            redis_client: Redis 接続オブジェクト。
            stream_name: 使用するストリーム名。
        """

        self.redis: redis.Redis[bytes] = redis_client
        self.stream_name = stream_name

    async def write(self, user_id: int, pcm: bytes) -> None:
        """音声チャンクを Redis Streams へ書き込む。

        Args:
            user_id: 発話者のユーザー ID。
            pcm: 16bit PCM 音声データ。
        """

        fields: Dict[str, bytes] = {
            "user_id": str(user_id).encode(),
            "pcm": pcm,
        }
        await self.redis.xadd(self.stream_name, fields)

    async def read(self, last_id: str = "0-0") -> tuple[str, Optional[Dict[str, Any]]]:
        """Redis Streams からデータを取得する。

        Args:
            last_id: 最後に読み取ったメッセージ ID。

        Returns:
            次のメッセージ ID とその内容。新しいメッセージがない場合は ``None`` を返す。
        """

        response = await self.redis.xread(
            {self.stream_name: last_id}, block=1000, count=1
        )
        if not response:
            return last_id, None
        _, messages = response[0]
        message_id, fields = messages[0]
        data = {k.decode(): v for k, v in fields.items()}
        return message_id, data


class PCMStreamSink(RawDataSink):
    """受信音声をリアルタイムで Redis に転送する Sink。"""

    def __init__(self, stream: RedisAudioStream) -> None:
        """インスタンスを生成する。

        Args:
            stream: 書き込み対象の :class:`RedisAudioStream` インスタンス。
        """

        super().__init__()
        self.stream = stream

    async def write(self, data, user: discord.User) -> None:  # type: ignore[override]
        """Discord からの音声フレームを受信する度に呼び出される。

        Args:
            data: 受信した音声データ。Opus から PCM へ変換済み。
            user: 音声の送信者。
        """

        await self.stream.write(user.id, data.pcm)  # type: ignore[attr-defined]


class STTWorker:
    """Redis Streams を監視して音声を文字起こしするワーカー。"""

    def __init__(self, stream: RedisAudioStream) -> None:
        """インスタンスを生成する。

        Args:
            stream: 音声チャンクを読み出す :class:`RedisAudioStream`。
        """

        self.stream = stream

    async def transcribe(self, pcm: bytes) -> str:
        """PCM データを文字列へ変換する。

        実際には Faster-Whisper などによる推論を行うが、ここではデータ長を
        利用したダミーの結果を返す。

        Args:
            pcm: 16bit PCM 音声データ。

        Returns:
            文字起こし結果の文字列。
        """

        return f"{len(pcm)}バイトの音声"

    async def run(self) -> None:
        """無限ループでストリームを読み取り、逐次文字起こしを行う。"""

        last_id = "0-0"
        while True:
            last_id, data = await self.stream.read(last_id)
            if data is None:
                await asyncio.sleep(0.1)
                continue
            pcm: bytes = data["pcm"]
            user_id = data["user_id"]
            text = await self.transcribe(pcm)
            print(f"{user_id}: {text}")


class VoiceBot(commands.Bot):
    """Discord 上で音声を収集するボットクラス。"""

    def __init__(self, audio_stream: RedisAudioStream) -> None:
        """インスタンスを生成する。

        Args:
            audio_stream: 音声チャンクを書き込む :class:`RedisAudioStream`。
        """

        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix="/", intents=intents)
        self.audio_stream = audio_stream

    async def on_ready(self) -> None:  # type: ignore[override]
        """ログイン完了時に呼び出される。"""

        print("Bot にログインしました")

    async def join_and_record(self, channel: discord.VoiceChannel) -> None:
        """指定ボイスチャンネルへ参加し録音を開始する。

        Args:
            channel: 参加するボイスチャンネル。
        """

        voice = await channel.connect()
        if not hasattr(voice, "start_recording"):
            raise RuntimeError("この環境の discord.py では録音機能が提供されていません")
        sink = PCMStreamSink(self.audio_stream)
        voice.start_recording(sink, self._after_recording)  # type: ignore[attr-defined]

    async def _after_recording(self, sink: PCMStreamSink) -> None:
        """録音終了時の後処理を行う。

        Args:
            sink: 使用していた :class:`PCMStreamSink`。
        """

        for user, audio in sink.audio_data.items():
            pcm = b"".join(chunk.pcm for chunk in audio)
            await self.audio_stream.write(user.id, pcm)


async def main() -> None:
    """Discord ボットと STT ワーカーを起動する。

    `.env` から環境変数を読み込み、Redis への接続確認後にボットと
    ワーカーを起動する。

    Raises:
        RuntimeError: ``BOT_TOKEN`` または Redis 接続に問題がある場合。
    """

    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token is None:
        raise RuntimeError("DISCORD_BOT_TOKEN が設定されていません")

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_client: redis.Redis[bytes] = redis.from_url(redis_url, decode_responses=False)

    try:
        await redis_client.ping()
    except ConnectionError as exc:
        raise RuntimeError(
            "Redis サーバーに接続できません。REDIS_URL とサーバーの起動状態を確認してください。"
        ) from exc

    audio_stream = RedisAudioStream(redis_client, "audio")
    bot = VoiceBot(audio_stream)

    worker = STTWorker(audio_stream)
    asyncio.create_task(worker.run())

    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
