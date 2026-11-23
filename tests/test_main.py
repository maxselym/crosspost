from crosspost import main


def test_main(capsys):
    main()

    captured = capsys.readouterr()

    assert captured.out == "Hello from crosspost!\n"
    assert captured.err == ""
