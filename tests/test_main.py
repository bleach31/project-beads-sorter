"""メインモジュールのテスト."""

from beads_sorter.main import main


def test_main(monkeypatch):
    """main関数の基本テスト."""
    invocation = {}

    def fake_run(app, **options):
        invocation["app"] = app
        invocation["options"] = options

    monkeypatch.setattr("beads_sorter.main.uvicorn.run", fake_run)

    main()

    assert invocation == {
        "app": "beads_sorter.web:app",
        "options": {"host": "0.0.0.0", "port": 8000},
    }
