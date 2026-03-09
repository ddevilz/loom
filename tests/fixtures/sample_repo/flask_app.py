from __future__ import annotations


class app:
    @staticmethod
    def route(path):
        def wrapper(fn):
            return fn

        return wrapper


@app.route("/login")
def login():
    return "login page"


@app.route("/logout")
def logout():
    return "logout page"


def helper():
    return "not a route"
