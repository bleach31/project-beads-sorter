"""メインエントリーポイント."""

import os

import uvicorn


def main():
    """アプリケーションのメインエントリーポイント."""
    uvicorn.run(
        "beads_sorter.web:app",
        host=os.getenv("BEADS_SORTER_HOST", "0.0.0.0"),
        port=int(os.getenv("BEADS_SORTER_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
