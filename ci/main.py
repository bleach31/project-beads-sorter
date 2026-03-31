"""Dagger CI/CD パイプライン.

ドキュメント生成パイプラインを定義する。

Usage:
    dagger run python ci/main.py build-docs
    dagger run python ci/main.py lint
    dagger run python ci/main.py test
    dagger run python ci/main.py all
"""

import sys

import anyio
import dagger


async def build_docs(client: dagger.Client) -> str:
    """Sphinxドキュメントをビルドする."""
    src = client.host().directory(".", exclude=[".venv", "__pycache__", "docs/_build"])

    container = (
        client.container()
        .from_("python:3.12-slim")
        .with_directory("/work", src)
        .with_workdir("/work")
        .with_exec(["pip", "install", "sphinx", "sphinx-needs", "shibuya", "myst-parser"])
        .with_exec(
            ["sphinx-build", "-b", "html", "docs", "docs/_build/html"]
        )
    )

    # ビルド結果をエクスポート
    await container.directory("/work/docs/_build/html").export("docs/_build/html")

    return "docs build completed"


async def lint(client: dagger.Client) -> str:
    """Ruff によるリント実行."""
    src = client.host().directory(".", exclude=[".venv", "__pycache__", "docs/_build"])

    container = (
        client.container()
        .from_("python:3.12-slim")
        .with_directory("/work", src)
        .with_workdir("/work")
        .with_exec(["pip", "install", "ruff"])
        .with_exec(["ruff", "check", "impl/src", "tests"])
    )

    output = await container.stdout()
    return f"lint completed: {output}"


async def test(client: dagger.Client) -> str:
    """pytest によるテスト実行."""
    src = client.host().directory(".", exclude=[".venv", "__pycache__", "docs/_build"])

    container = (
        client.container()
        .from_("python:3.12-slim")
        .with_directory("/work", src)
        .with_workdir("/work")
        .with_exec(["pip", "install", "pytest", "pytest-cov"])
        .with_exec(["pip", "install", "-e", "."])
        .with_exec(["pytest", "tests/", "-v"])
    )

    output = await container.stdout()
    return f"test completed: {output}"


async def main():
    """メインエントリーポイント."""
    command = sys.argv[1] if len(sys.argv) > 1 else "all"

    async with dagger.Connection() as client:
        if command == "build-docs":
            result = await build_docs(client)
            print(result)
        elif command == "lint":
            result = await lint(client)
            print(result)
        elif command == "test":
            result = await test(client)
            print(result)
        elif command == "all":
            print(await lint(client))
            print(await test(client))
            print(await build_docs(client))
        else:
            print(f"Unknown command: {command}")
            print("Available: build-docs, lint, test, all")
            sys.exit(1)


if __name__ == "__main__":
    anyio.run(main)
