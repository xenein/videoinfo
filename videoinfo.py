import json
import logging
import os
import re
from enum import Enum
from logging.config import dictConfig
from typing import Any
from urllib.parse import urlparse, parse_qs

import requests
import sentry_sdk
import waitress
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template

load_dotenv()

if dsn := os.environ.get("sentry_dsn"):
    sentry_sdk.init(dsn=dsn, send_default_pii=True)

yt_key = os.environ.get("yt_key")


dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["wsgi"]},
    }
)

Host = Enum(
    "Host",
    [
        ("YOUTUBE", 1),
        ("ARD", 2),
        ("ZDF", 3),
        ("VIMEO", 4),
        ("MEDIACCCDE", 5),
        ("TWITCH", 6),
        ("ARTE", 7),
        ("BELLTOWER", 8),
        ("VOLKSVERPETZER", 9),
    ],
)

app = Flask(__name__)


def normalize_link(video_link: str) -> tuple[str, Any] | None:
    if "youtube" in video_link.replace(".", ""):
        video_id = ""
        parsed = urlparse(video_link)
        qs = parse_qs(parsed.query)
        if "youtube.com/watch" in video_link:
            video_id = qs.get("v")[0]
        elif "youtu.be" in video_link:
            video_id = parsed.path[1:]
        else:
            video_id = video_link

        return f"https://www.youtube.com/watch?v={video_id}", Host.YOUTUBE
    elif "zdf" in video_link:
        return video_link, Host.ZDF
    elif "ard" in video_link:
        return video_link, Host.ARD
    elif "vimeo" in video_link:
        return video_link, Host.VIMEO
    elif "media.ccc.de" in video_link:
        return video_link.split("#")[0], Host.MEDIACCCDE
    elif "twitch.tv/video" in video_link:
        return video_link.split("?")[0], Host.TWITCH
    elif "arte.tv" in video_link:
        return video_link.split("?")[0], Host.ARTE
    elif "belltower.news/" in video_link:
        return video_link.split("?")[0], Host.BELLTOWER
    elif "volksverpetzer.de/" in video_link:
        return video_link.split("?")[0], Host.VOLKSVERPETZER
    return None


def fetch_video_soup(video_url: str):
    r = requests.get(
        video_url,
        headers={
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:136.0) Gecko/20100101 Firefox/136.0"
        },
    )
    app.logger.info(f"fetched {video_url}, status code: {r.status_code}")
    return BeautifulSoup(r.text, "html.parser")


def get_video_dict(soup: BeautifulSoup, host: Host) -> dict:
    if host == Host.MEDIACCCDE:
        authors = [
            sieved.get("content") for sieved in soup.select("meta[property='author']")
        ]

        path = soup.select("meta[property='og:url']").get("content")

        return dict(
            title=soup.select_one("meta[property='og:title']").get("content"),
            url=f"https://media.ccc.de{path}",
            year=soup.select_one("meta[property='og:video:release_date']")
            .get("content")
            .split("-")[0],
            channel=", ".join(authors),
        )


def get_ard_dict(video_url: str) -> dict:
    ard_parsed = urlparse(video_url)
    ard_video_id = ard_parsed.path.split("/")[-1]
    r = requests.get(
        f"https://api.ardmediathek.de/page-gateway/pages/ard/item/{ard_video_id}?embedded=false&mcV6=true"
    ).json()

    channel = "ARD"
    if "tracking" in r.keys() and "atiCustomVars" in r["tracking"].keys():
        channel = r["tracking"]["atiCustomVars"].get("channel")

    year = ""
    if (
        "widgets" in r.keys()
        and len(r["widgets"]) > 0
        and "broadcastedOn" in r["widgets"][0].keys()
    ):
        year = r.get("widgets")[0].get("broadcastedOn").split("-")[0]

    return dict(
        title=r.get("title"),
        url=f"https://www.ardmediathek.de/video/{ard_video_id}",
        channel=channel,
        year=year,
    )


def get_vimeo_dict(video_url: str) -> dict:
    vimeo_parsed = urlparse(video_url)
    vimeo_video_id = vimeo_parsed.path.split("/")[-1]
    r = requests.get(
        f"https://vimeo.com/api/oembed.json?url=https://vimeo.com/{vimeo_video_id}"
    ).json()
    return dict(
        title=r.get("title"),
        url=f"https://www.vimeo.com/{vimeo_video_id}",
        channel=r.get("author_name"),
        year=r.get("upload_date").split("-")[0],
    )


def get_arte_dict(video_url: str) -> dict:
    compiled_regex = re.compile(r"videos/(?P<arte_id>[\w-]+)/")
    match = compiled_regex.search(video_url)
    if not match:
        app.logger.info("no arte video id found")
    else:
        app.logger.info("found arte video id")
        arte_id = match.group("arte_id")

        r = requests.get(f"https://api.arte.tv/api/player/v2/config/de/{arte_id}")
        j = r.json()

        data = j.get("data").get("attributes")

        channel = data.get("provider")
        url = data.get("metadata").get("link").get("url")
        year = data.get("rights").get("begin")[:4]
        title = data.get("metadata").get("title")
        if subtitle := data.get("metadata").get("subtitle"):
            title = f"{title} – {subtitle}"
        return dict(title=title, year=year, channel=channel, url=url)


def extract_youtube_id(video_url: str) -> str:
    video_id = ""
    parsed = urlparse(video_url)
    qs = parse_qs(parsed.query)
    if "youtube.com/watch" in video_url:
        video_id = qs.get("v")[0]
    elif "youtu.be" in video_url:
        video_id = parsed.path[1:]

    return video_id


def get_youtube_dict(video_url: str) -> dict:
    yt_id = extract_youtube_id(video_url)

    r = requests.get(
        "https://youtube.googleapis.com/youtube/v3/videos?part=snippet%2CcontentDetails&id="
        + str(yt_id)
        + "&key="
        + str(yt_key)
    )

    j = r.json()

    video_id = j.get("items")[0].get("id")
    video_data = j.get("items")[0].get("snippet")

    return dict(
        title=video_data.get("title"),
        url="https://youtube.com/watch?v=" + video_id,
        year=video_data.get("publishedAt")[:4],
        channel=video_data.get("channelTitle"),
    )


def get_zdf_key(zdf_source: str) -> str:
    compiled_regex = re.compile(r"apiToken\\\":\\\"(\w+)\\\"")
    match = compiled_regex.search(zdf_source)
    if match:
        app.logger.info("extracted zdf api-token")
        return match.group(1)
    else:
        app.logger.info("unable to extract zdf api-token, falling back")
        return "ahBaeMeekaiy5ohsai4bee4ki6Oopoi5quailieb"


def get_zdf_dict(video_url: str) -> dict:
    r = requests.get(video_url)
    soup = BeautifulSoup(r.text, "html.parser")
    canonical_url = soup.select_one("link[rel='canonical']").get("href")
    canonical_id = urlparse(canonical_url).path.split("/")[-1]
    api_key = get_zdf_key(r.text)

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:136.0) Gecko/20100101 Firefox/136.0",
        "Content-Type": "application/json",
        "Referer": "https://www.zdf.de",
        "Origin": "https://www.zdf.de",
        "Priority": "u=4",
        "TE": "Trailers",
        "Api-Auth": f"Bearer {api_key}",
    }

    payload = {
        "operationName": "VideoByCanonical",
        "query": """
            query VideoByCanonical($canonical: String!) {
                videoByCanonical(canonical: $canonical) {
                title
                editorialDate
                sharingUrl
                }
            }
        """,
        "variables": {"canonical": f"{canonical_id}"},
    }

    graph = requests.post(
        "https://api.zdf.de/graphql", headers=headers, json=payload
    ).json()

    metadata = graph.get("data").get("videoByCanonical")

    return dict(
        title=metadata.get("title"),
        year=metadata.get("editorialDate")[:4],
        channel="ZDF",
        url=metadata.get("sharingUrl"),
    )


def get_twitch_dict(video_url: str) -> dict:
    r = requests.get(video_url)
    soup = BeautifulSoup(r.text, "html.parser")
    # ld = json.loads(soup.select_one("script[type='jd+json']").text)
    # ld = ld.get("@graph")[0]
    return dict(
        title=soup.select_one("meta[property='og:title']")
        .get("content")
        .rsplit("-", maxsplit=1)[0]
        .strip(),
        channel=soup.select_one("meta[property='og:description']")
        .get("content")
        .split(" ")[0],
        year=soup.select_one("meta[property='og:video:release_date']")
        .get("content")
        .split("-")[0],
        url=soup.select_one("link[rel='canonical']").get("href"),
    )


def get_belltower_dict(video_url: str) -> dict:
    r = requests.get(video_url)
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.select_one("meta[property='og:title']").get("content")
    year = (
        soup.select_one("meta[property='article:published_time']")
        .get("content")
        .split("-")[0]
    )
    url = soup.select_one("link[rel='canonical']").get("href")
    channel = soup.select_one("meta[property='og:site_name']").get("content")

    try:
        ld = soup.select_one("[type='application/ld+json']").text
        j = json.loads(ld)
        channel = f'{j.get("@graph")[-1].get("author").get("name")} für {channel}'
    except AttributeError:
        pass

    return dict(
        title=title,
        year=year,
        url=url,
        channel=channel,
    )


def get_volksverpetzer_dict(video_url: str) -> dict:
    r = requests.get(video_url)
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.select_one("meta[property='og:title']").get("content")
    url = soup.select_one("link[rel='canonical']").get("href")
    year = (
        soup.select_one("meta[property='article:published_time']")
        .get("content")
        .split("-")[0]
    )
    channel = soup.select_one("meta[property='og:site_name']").get("content")
    if author := soup.select_one("meta[name='author']").get("content"):
        channel = f"{author} für {channel}"

    return dict(
        title=title,
        year=year,
        url=url,
        channel=channel,
    )


def build_video_dict(link: str) -> dict:
    guess_link, host = normalize_link(link)
    if host == Host.ARD:
        video_dict = get_ard_dict(link)
    elif host == Host.VIMEO:
        video_dict = get_vimeo_dict(link)
    elif host == Host.YOUTUBE:
        video_dict = get_youtube_dict(link)
    elif host == Host.ZDF:
        video_dict = get_zdf_dict(link)
    elif host == Host.TWITCH:
        video_dict = get_twitch_dict(link)
    elif host == Host.ARTE:
        video_dict = get_arte_dict(link)
    elif host == Host.BELLTOWER:
        video_dict = get_belltower_dict(link)
    elif host == Host.VOLKSVERPETZER:
        video_dict = get_volksverpetzer_dict(link)
    else:
        soup = fetch_video_soup(guess_link)
        video_dict = get_video_dict(soup, host)
    return video_dict


@app.route("/")
def index():
    link = request.args.get("link")
    if link:
        app.logger.info(f"trying {link}")
        video_dict = build_video_dict(link)
        return jsonify(video_dict)
    else:
        return render_template("index.html")


@app.route("/compact")
def compact():
    link = request.args.get("link")
    if link:
        video_dict = build_video_dict(link)
        return f'© {video_dict.get("year")} | {video_dict.get("channel")} | {video_dict.get("url")}'


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    waitress.serve(app, listen="*:56565")
