# Contributing

Thanks for considering a contribution to Media Downloader Bot! For significant
changes, please open an issue first to discuss what you'd like to change
before putting time into a pull request.

## Setting up a dev environment

```bash
git clone https://github.com/dmytrokurochkin/Media-Downloader-Bot.git
cd Media-Downloader-Bot

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Make sure `ffmpeg` is installed and available on `PATH`, and create a `.env`
file as described in the [README](README.md#-local-deployment).

## Running the tests

```bash
pytest
```

The test suite is also run automatically on every push and pull request to
`main` via the [Tests workflow](.github/workflows/tests.yml).

## Submitting a pull request

1. Fork the repository and create a branch off `main` for your change.
2. Keep the change focused - unrelated fixes or refactors should be their
   own PR.
3. Make sure `pytest` passes locally before opening the PR.
4. Describe what the change does and why in the PR description.

## Code style

There's no enforced linter/formatter yet - just try to match the style of
the surrounding code.
