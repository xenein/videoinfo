import logging
import os
from enum import Enum
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

Host = Enum(
    "Host", [("YOUTUBE", 1), ("ARD", 2), ("ZDF", 3), ("VIMEO", 4), ("MEDIACCCDE", 5)]
)

app = Flask(__name__)


def normalize_link(video_link: str) -> tuple[str, Any] | None:
    video_link = video_link.strip().lower()
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


def fetch_video_soup(video_url: str):
    r = requests.get(video_url).text
    return BeautifulSoup(r, "html.parser")


def get_video_dict(soup: BeautifulSoup, host: Host) -> dict:
    if host == Host.YOUTUBE:
        return dict(
            title=soup.select_one("meta[property='og:title']").get("content"),
            url=soup.select_one("meta[property='og:url']").get("content"),
            year=soup.select_one("meta[itemprop='datePublished']")
            .get("content")
            .split("-")[0],
            channel=soup.select_one("link[itemprop='name']").get("content"),
        )
    elif host == Host.ZDF:
        return dict(
            title=soup.select_one("meta[property='og:title']").get("content"),
            url=soup.select_one("link[rel='canonical']").get("href"),
            year=soup.select_one("meta[name='zdf:publicationDate']")
            .get("content")
            .split("-")[0],
            channel="ZDF",
        )
    elif host == Host.MEDIACCCDE:
        authors = [
            sieved.get("content") for sieved in soup.select("meta[property='author']")
        ]

        # authors = map(
        #     lambda x: x.get("content"), soup.select("meta[property='og:author']")
        # )
        return dict(
            title=soup.select_one("meta[property='og:title']").get("content"),
            url=f"https://media.ccc.de{soup.select_one("meta[property='og:url']").get("content")}",
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


def build_video_dict(link: str) -> dict:
    guess_link, host = normalize_link(link)
    if host == Host.ARD:
        video_dict = get_ard_dict(link)
    elif host == Host.VIMEO:
        video_dict = get_vimeo_dict(link)
    else:
        soup = fetch_video_soup(guess_link)
        video_dict = get_video_dict(soup, host)
    return video_dict


@app.route("/")
def index():
    link = request.args.get("link")
    if link:
        video_dict = build_video_dict(link)
        return jsonify(video_dict)
    else:
        return render_template("index.html")


@app.route("/compact")
def compact():
    link = request.args.get("link")
    if link:
        video_dict = build_video_dict(link)
        return f"© {video_dict.get("year")} | {video_dict.get("channel")} | {video_dict.get("url")}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    waitress.serve(app, listen="*:56565")
    # video_url = "https://www.youtube.com/watch?v=l7Q-m-oiPeE"
    # video_soup = fetch_video_soup(guess_yt_link(video_url))
    #
    # title = video_soup.select_one("meta[property='og:title']").get("content")
    # url = video_soup.select_one("meta[property='og:url']").get("content")
    # year = video_soup.select_one("meta[itemprop='datePublished']").get("content").split("-")[0]
    # channel = video_soup.select_one("link[itemprop='name']").get("content")
    #
    # print(title)
    # print(url)
    # print(year)
    # print(channel)
