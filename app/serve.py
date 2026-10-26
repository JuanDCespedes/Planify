import os

from waitress import serve

from planify import create_app


app = create_app()


if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
