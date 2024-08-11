import asyncio
import random
from pathlib import Path
from pprint import pprint
from typing import Any, Collection, Dict, List, Optional

from autolink import linkify
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .downloader import Downloader
from .store import Store
from .utils import format_duration, format_thousand, plain2html

APP = FastAPI()
CWD = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(CWD / "templates"))

STORE = Store()
DOWNLOADER = Downloader()

APP.mount("/static", StaticFiles(directory=str(CWD / "static")), name="static")


async def entries(
        request: Request,
        page_title: str,
        field_query: str,
        ytdl_query: str,
        page: int = 1,
        result_count: int = 12,
        exclude_ids: Collection[str] = (),
        embedded: bool = False,
        downloader: Downloader = DOWNLOADER,
):
    wanted = result_count * page
    entries = (await downloader.search(ytdl_query))["entries"]
    entries = [e for e in entries if e["id"] not in exclude_ids]
    entries = entries[wanted - result_count:wanted]

    for entry in entries:
        entry.update({
            "preview_url": f"/preview?video_id={entry['id']}",
            "watch_url": f"/watch?v={entry['id']}",
            "human_duration": format_duration(entry.get("duration") or 0),
            "human_views": format_thousand(entry.get("view_count") or 0),
            "seen_class": "seen" if entry["id"] in STORE.seen else "",
        })

    prev_url = \
        request.url.include_query_params(page=page - 1) if page > 1 else ""

    params = {
        "request": request,
        "page_title": page_title,
        "field_query": field_query,
        "entries": entries,
        "page_num": page,
        "prev_url": prev_url,
        "next_url": request.url.include_query_params(page=page + 1),
        "embedded": embedded,
    }
    return TEMPLATES.TemplateResponse("results.html.jinja", params)


# Old version of the home function
@APP.get("/", response_class=HTMLResponse)
async def home(request: Request, page: int = 1, embedded: bool = False):
    terms = STORE.recommendations_query(4 * 3)
    groups = [terms[i:i + 3] for i in range(0, len(terms), 3)]
    print(groups)

    results = await asyncio.gather(*[
        entries(
            request=request,
            page_title="CTube",
            field_query="",
            ytdl_query=f"ytsearch{12 * page}:{' '.join(group)}",
            page=page,
            embedded=embedded,
        ) for group in groups
    ])

    videos: List[Dict[str, Any]] = []

    for result in results:
        if result.context["entries"]:
            videos += random.sample(result.context["entries"], k=3)

    for res in results[1:]:
        results[0].context["entries"] += res.context["entries"]

    prev_url = \
        request.url.include_query_params(page=page - 1) if page > 1 else ""

    params = {
        "request": request,
        "page_title": "CTube",
        "field_query": "",
        "entries": videos,
        "page_num": page,
        "prev_url": prev_url,
        "next_url": request.url.include_query_params(page=page + 1),
        "embedded": embedded,
    }
    return TEMPLATES.TemplateResponse("results.html.jinja", params)


# New version of the home function
@APP.get("/", response_class=HTMLResponse)
async def home(request: Request, page: int = 1, embedded: bool = False):
    try:
        terms = STORE.recommendations_query(4 * 3)
        if not terms:
            # If no recommendations are available, use a default search query
            return await results(request, "popular videos", page, embedded=embedded)

        groups = [terms[i:i + 3] for i in range(0, len(terms), 3)]
        print(groups)

        results = await asyncio.gather(*[
            entries(
                request=request,
                page_title="CTube",
                field_query="",
                ytdl_query=f"ytsearch{12 * page}:{' '.join(group)}",
                page=page,
                embedded=embedded,
            ) for group in groups
        ])

        videos: List[Dict[str, Any]] = []

        for result in results:
            if result.context["entries"]:
                videos += random.sample(result.context["entries"], k=min(3, len(result.context["entries"])))

        for res in results[1:]:
            results[0].context["entries"] += res.context["entries"]

        prev_url = request.url.include_query_params(page=page - 1) if page > 1 else ""

        params = {
            "request": request,
            "page_title": "CTube",
            "field_query": "",
            "entries": videos,
            "page_num": page,
            "prev_url": prev_url,
            "next_url": request.url.include_query_params(page=page + 1),
            "embedded": embedded,
        }
        return TEMPLATES.TemplateResponse("results.html.jinja", params)
    except Exception as e:
        print(f"Error in home route: {str(e)}")
        # Fallback to a default search if an error occurs
        return await results(request, "trending videos", page, embedded=embedded)


@APP.get("/results", response_class=HTMLResponse)
async def results(
        request: Request,
        search_query: str,
        page: int = 1,
        exclude_id: Optional[str] = None,
        embedded: bool = False,
):
    if not search_query:
        return await home(request)

    wanted = 12 * page
    total = wanted + (1 if exclude_id else 0)

    return await entries(
        request=request,
        page_title=search_query,
        field_query=search_query,
        ytdl_query=f"ytsearch{total}:{search_query}",
        page=page,
        exclude_ids=[exclude_id] if exclude_id else [],
        embedded=embedded,
    )


@APP.get("/search", response_class=HTMLResponse)
async def search(
        request: Request,
        q: str,
        page: int = 1,
        exclude_id: Optional[str] = None,
        embedded: bool = False,
):
    return await results(request, q, page, exclude_id, embedded)


@APP.get("/channel/{channel_id}", response_class=HTMLResponse)
@APP.get("/channel/{channel_id}/videos", response_class=HTMLResponse)
@APP.get("/user/{channel_id}", response_class=HTMLResponse)
@APP.get("/user/{channel_id}/videos", response_class=HTMLResponse)
async def channel(
        request: Request,
        channel_id: str,
        page: int = 1,
        exclude_id: Optional[str] = None,
        embedded: bool = False,
):
    kind = "channel" if "/channel/" in str(request.url) else "user"

    return await entries(
        request=request,
        page_title=channel_id,
        field_query="",
        ytdl_query=f"https://youtube.com/{kind}/{channel_id}/videos",
        page=page,
        exclude_ids=[exclude_id] if exclude_id else [],
        embedded=embedded,
        downloader=Downloader(playlistend=page * 12),
    )


@APP.get("/preview", response_class=HTMLResponse)
async def preview(request: Request, video_id: str):
    info = await DOWNLOADER.video_info(video_id)
    params = {
        **info,
        "request": request,
        "seen_class": "seen" if info["id"] in STORE.seen else "",
    }
    return TEMPLATES.TemplateResponse("preview.html.jinja", params)


@APP.get("/watch", response_class=HTMLResponse)
async def watch(request: Request, v: str):
    video_id = v
    info = await DOWNLOADER.video_info(video_id)
    await STORE.record_seen(info)

    # Get the best quality video URL
    video_url = next((f['url'] for f in info['formats'] if f.get('vcodec') != 'none' and f.get('acodec') != 'none'), None)

    if not video_url:
        raise HTTPException(status_code=404, detail="No suitable video format found")

    params = {
        **info,
        "request": request,
        "video_url": video_url  # Add the video URL to the template parameters
    }
    return TEMPLATES.TemplateResponse("watch.html.jinja", params)

@APP.get("/comments", response_class=HTMLResponse)
async def comments(request: Request, video_id: str, page: int = 1):
    comments, reached_end = await DOWNLOADER.comments(video_id, page)

    for i, comment in enumerate(comments):
        comments[i].update({
            "is_reply": "." in comment["cid"],
            "html_text": linkify(plain2html(comment["text"])),
            "channel_url": "/channel/%s" % comment["channel"],
        })

    prev_url = \
        request.url.include_query_params(page=page - 1) if page > 1 else ""

    next_url = \
        "" if reached_end else request.url.include_query_params(page=page + 1)

    params = {
        "request": request,
        "comments": comments,
        "page_num": page,
        "prev_url": prev_url,
        "next_url": next_url,
    }

    return TEMPLATES.TemplateResponse("comments.html.jinja", params)
