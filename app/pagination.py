from dataclasses import dataclass
from math import ceil
from urllib.parse import urlencode


ALLOWED_PAGE_SIZES = (25, 50, 100)


@dataclass(frozen=True)
class Pagination:
    page: int
    page_size: int
    total: int
    total_pages: int
    offset: int
    start: int
    end: int
    pages: tuple[int, ...]
    previous_url: str | None
    next_url: str | None
    page_urls: tuple[tuple[int, str], ...]
    size_urls: tuple[tuple[int, str], ...]


def build_pagination(
    *, total: int, page: int, page_size: int, path: str,
    params: dict[str, object] | None = None,
) -> Pagination:
    page_size = page_size if page_size in ALLOWED_PAGE_SIZES else 25
    total_pages = max(1, ceil(total / page_size))
    page = min(max(1, page), total_pages)
    offset = (page - 1) * page_size
    base = {
        key: value for key, value in (params or {}).items()
        if value not in (None, "", "all")
    }

    def url(target_page: int, target_size: int = page_size) -> str:
        query = {**base, "page": target_page, "page_size": target_size}
        return f"{path}?{urlencode(query)}"

    first_page = max(1, page - 2)
    last_page = min(total_pages, page + 2)
    pages = tuple(range(first_page, last_page + 1))
    return Pagination(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        offset=offset,
        start=offset + 1 if total else 0,
        end=min(offset + page_size, total),
        pages=pages,
        previous_url=url(page - 1) if page > 1 else None,
        next_url=url(page + 1) if page < total_pages else None,
        page_urls=tuple((number, url(number)) for number in pages),
        size_urls=tuple((size, url(1, size)) for size in ALLOWED_PAGE_SIZES),
    )
