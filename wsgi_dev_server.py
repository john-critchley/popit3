#!/usr/bin/env python3
from wsgiref.simple_server import make_server

from job_api import application


def main(host: str = "127.0.0.1", port: int = 8051) -> None:
    with make_server(host, port, application) as httpd:
        print(f"Serving WSGI job_api on http://{host}:{port} ...")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down WSGI dev server.")


if __name__ == "__main__":
    main()
