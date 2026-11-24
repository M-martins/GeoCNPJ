from fastapi import Request


def get_services(request: Request):
    return request.app.state.services


def get_settings(request: Request):
    return request.app.state.settings
