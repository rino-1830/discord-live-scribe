# Discord Live Scribe

![license](https://img.shields.io/badge/license-MIT-green)

## 概要

Discord のボイスチャンネルで **日本語音声** をリアルタイム文字起こしし、指定テキストチャンネルへ字幕として投稿するボットです。ローカル GPU と Kotoba‑Whisper v2（INT8）を使用します。  
字幕は `ユーザー名「内容」` の形式で投稿されます。
本リポジトリでは環境変数を `.env` で管理します。`.env.example` をコピーして `.env` を作成し、必要に応じて編集してください。各変数の役割はファイル内のコメントを参照してください。

## コマンド

| コマンド                 | 概要                                                                       |
| ------------------------ | -------------------------------------------------------------------------- |
| `/dls set-tc`            | このコマンドを実行したテキストチャンネル（TC）を字幕表示先に設定する。     |
| `/dls start` or `/dls s` | コマンド実行者がいるボイスチャンネル（VC）に参加して文字起こしを開始する。 |
| `/dls stop` or `/dls ss` | ボイスチャンネルから退出して文字起こしを停止する。                         |

## アーキテクチャ

![architecture](assets/architecture.svg)

```text
[Discord VC] —— Opus —→ [Voice Bot] —— PCM + meta —→ [Redis Streams (audio)] —— batch pull —→ [STT Worker (GPU)] —— Text —→ [Discord TC]
```

Discord VC から受信した Opus 音声を Voice Bot が即時に PCM 16 kHz へ変換し、Silero-VAD で無音区切り（最大 30 s／無音 2 s）を付けたチャンク＋メタデータ（user_id）を Redis Streams audio に書き込みます。これにより収集（Bot）と処理（Worker）を疎結合に保ち、Bot が落ちても音声が失われません。  
GPU 側の STT Worker は XREADGROUP でチャンクをバッチ取得し、Kotoba-Whisper v2（INT8, faster-whisper）で高速一括推論後、user_id 別にキュー分離されてた各ユーザーの発話は完全に非同期で処理され、Discord TC へ送信します。  
Redis Streams が順序保証と再配布を担い、1 GPU でも複数 Worker を水平展開できるため、低遅延かつスケーラブルなリアルタイム日本語文字起こしを実現します。

## 実行方法

`.env` を用意したら、次のコマンドでボットを起動できます。

```bash
python -m src.main
```

## ライセンス

本リポジトリは MIT License で配布されます。詳細は LICENSE ファイルを参照してください。
