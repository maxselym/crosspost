import argparse
from pathlib import Path

import yt_dlp

# Корень проекта: C:\Dev\crosspost
# Пример использования:
# uv run python -m crosspost.vk.download_sample_video "https://vkvideo.ru/video-227892646_456239081"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOWNLOAD_DIR = PROJECT_ROOT / "media" / "vk"


def download_video(url: str) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "outtmpl": str(DOWNLOAD_DIR / "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "overwrites": False,
    }

    print("VK video download test")
    print("=" * 40)
    print(f"URL: {url}")
    print(f"Destination: {DOWNLOAD_DIR}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # pyright: ignore[reportArgumentType]
            info = ydl.extract_info(url, download=True)

            if info is None:
                raise RuntimeError("yt-dlp returned no video information")

            print("\nDownload completed")
            print(f"Title: {info.get('title', 'Unknown')}")
            print(f"Video ID: {info.get('id', 'Unknown')}")
            print(f"Format: {info.get('ext', 'Unknown')}")

            filepath = Path(ydl.prepare_filename(info))
            if filepath.exists():
                print(f"File: {filepath}")
                print(f"Size: {filepath.stat().st_size / (1024 * 1024):.2f} MB")
            else:
                print(f"File not found at expected path: {filepath}")

    except Exception as exc:
        print(f"\nDownload failed: {type(exc).__name__}: {exc}")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Download a VK video into media/vk/")
    parser.add_argument("url", help="VK video URL")

    args = parser.parse_args()
    download_video(args.url)


if __name__ == "__main__":
    main()
