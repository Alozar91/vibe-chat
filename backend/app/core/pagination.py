from app.core.errors import bad_request


def parse_pagination(limit: int | None, offset: int | None, default: int = 50, max_limit: int = 100) -> tuple[int, int]:
    limit = default if limit is None else limit
    offset = 0 if offset is None else offset
    if limit < 1 or limit > max_limit:
        raise bad_request("limit вне диапазона 1..100", {"limit": limit})
    if offset < 0:
        raise bad_request("offset не может быть отрицательным")
    return limit, offset
