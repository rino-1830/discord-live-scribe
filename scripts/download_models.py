"""
download_models.py
Discord-Live-Scribe で必要な STT / VAD モデルをローカルにキャッシュするスクリプト
Python ≥3.9 / pip install huggingface_hub torch を前提
"""

import argparse
import shutil
import sys
from pathlib import Path


# ------------------------------------------------------------
# region Kotoba-Whisper v2.0 (CTranslate2)
def fetch_kotoba(dest: Path):
    from huggingface_hub import snapshot_download

    repo_id = "kotoba-tech/kotoba-whisper-v2.0-faster"
    print(f"▶ Downloading {repo_id} …")
    snapshot_download(
        repo_id,
        local_dir=dest / "kotoba-whisper-v2.0-faster",
        local_dir_use_symlinks=False,
        resume_download=True,
    )


# endregion
# ------------------------------------------------------------
# region Silero-VAD v5 (.jit)
def fetch_silero(dest: Path):
    import torch

    print("▶ Downloading Silero-VAD (jit) …")
    _ = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        trust_repo=True,
        force_reload=False,
    )
    hub_dir = Path(torch.hub.get_dir())
    jit_file = next(hub_dir.rglob("silero_vad.jit"), None)
    if jit_file is None:
        sys.exit("❌ silero_vad.jit が見つかりませんでした")
    shutil.copy2(jit_file, dest / "silero_vad.jit")
    print(f"  ✓ {jit_file.name} → {dest}")


# endregion
# ------------------------------------------------------------
# region メイン処理
def main():
    parser = argparse.ArgumentParser(
        description="Download Kotoba-Whisper & Silero-VAD models"
    )
    default_dir = Path(__file__).resolve().parent.parent / "models"
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_dir,
        help=f"保存先ディレクトリ（デフォルト: {default_dir}）",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    fetch_kotoba(args.output)
    fetch_silero(args.output)

    print(f"\n✅ All models saved under: {args.output.resolve()}")


# endregion

if __name__ == "__main__":
    main()
