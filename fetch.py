#!/usr/bin/env python3

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import ParseResult, urlparse

STATE_FILE_NAME = "state"
GENRE_FILE_NAME = "genres"

APPLIST_URLS = {
    "games": "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/games_appid.json",
    "dlc": "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/dlc_appid.json",
    "software": "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/software_appid.json",
    "hardware": "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/hardware_appid.json",
    "videos": "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/videos_appid.json",
}
APPINFO_URL = "https://store.steampowered.com/api/appdetails?l=english&appids="
APPLIST_API_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/?"
CATEGORIES_URL = "https://store.steampowered.com/actions/ajaxgetstorecategories"

VALID_TYPES = ", ".join(APPLIST_URLS.keys())

BACKOFF = [5, 20, 60, 2 * 60, 10 * 60, 30 * 60]

DELETE = [
    "price_overview",
    "recommendations",
    "screenshots",
    "movies",
    "reviews",
    "detailed_description",
    "legal_notice",
    "about_the_game",
    "pc_requirements",
    "mac_requirements",
    "linux_requirements",
    "ratings",
]


def progress(msg: str, end: str | None = "\n"):
    if not args.quiet:
        print(msg, end=end, flush=True)


def error(msg: str):
    print(msg, file=sys.stderr)


def p(filename: str) -> Path:
    return Path(args.datadir, filename)


def request(url: str) -> urllib.request.Request:
    req = urllib.request.Request(url)
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    )
    return req


def sleep(secs: int):
    if args.quiet:
        sleep(secs)
        return
    for _ in range(0, secs):
        time.sleep(1)
        print(".", end="", flush=True)
    print()


def save():
    progress("Saving... ", end="")

    for file_id, games in fetched.items():
        js = {}
        file = p(str(file_id))
        try:
            with open(file) as f:
                js = json.load(f)
        except FileNotFoundError:
            pass
        for game_id, data in games.items():
            js[str(game_id)] = data
        with open(file, "w") as f:
            json.dump(js, f, indent=2)

    fetched.clear()

    with open(p(STATE_FILE_NAME), "w") as f:
        for id, timestamp in sorted(state.items()):
            f.write(f"{id},{timestamp}\n")

    progress("Done.")


def transform(js: Any, transformer: Callable[[str], str]) -> Any:
    if isinstance(js, dict):
        return {k: transform(v, transformer) for k, v in js.items()}
    elif isinstance(js, list):
        return [transform(x, transformer) for x in js]
    elif isinstance(js, str):
        return transformer(js)
    else:
        return js


def urlrewrite(url: str) -> str:
    u = urlparse(url)
    if u.netloc.endswith("akamai.steamstatic.com") and "=" in u.query:
        name, value = u.query.split("=")
        if name == "t" and value.isdigit():
            return ParseResult(u.scheme, u.netloc, u.path, u.params, "", "").geturl()
    return url


def compact(js: dict[str, Any], cat: str):
    ids = set()
    if cat in js:
        for c in js[cat]:
            ids.add(int(c["id"]))
        js[cat] = sorted(ids)


def process_genre(js: dict):
    if "genres" in js:
        for genre in js["genres"]:
            if genre["id"] not in genres:
                genres[genre["id"]] = genre["description"]


def delete(js: dict, keychain: list[str]):
    for key in keychain[:-1]:
        try:
            js = js[key]
        except:
            return
    js.pop(keychain[-1], None)


def time2str(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%-d %b %Y")


def create_lists():
    if not args.lists:
        return

    progress("Creating lists... ", end="")

    demos = set()
    cards = set()
    achievements = set()

    for filename in os.listdir(args.datadir):
        if filename.isdigit():
            with open(p(filename)) as f:
                js = json.load(f)
                for id, data in js.items():
                    gameid = int(id)
                    if data.get("demos", []):
                        demos.add(gameid)
                    cats = data.get("categories", [])
                    if 29 in cats:
                        cards.add(gameid)
                    if 22 in cats:
                        achievements.add(gameid)

    with open(p("demos"), "w") as f:
        for id in sorted(demos):
            f.write(f"{id}\n")
    with open(p("cards"), "w") as f:
        for id in sorted(cards):
            f.write(f"{id}\n")
    with open(p("achievements"), "w") as f:
        for id in sorted(achievements):
            f.write(f"{id}\n")
    with open(p(GENRE_FILE_NAME), "w") as f:
        for id in sorted(genres.keys(), key=int):
            f.write(f"{id}\t{genres[id]}\n")

    with urllib.request.urlopen(request(CATEGORIES_URL)) as resp:
        with open(p("categories"), "w") as f:
            json.dump(json.loads(resp.read()), f, indent=2)

    progress("Done.")


##
## Command line arguments
##
parser = argparse.ArgumentParser(prog="fetch.py")
parser.add_argument("datadir", help="data directory")
parser.add_argument(
    "--max", help="maximum number of apps to fetch (default: no limit)", type=int
)
parser.add_argument("--new", help="new apps only (default: false)", action="store_true")
parser.add_argument(
    "--types",
    help=f"comma-seperated list of types to include (available types: {VALID_TYPES}) (example: --types games,software) (default: include all types)",
)
parser.add_argument(
    "--api",
    metavar="APIKEY",
    help="use the Steam API to get the list of app IDs. APIKEY: your Steam API key (default: use https://github.com/jsnli/steamappidlist instead)",
)
parser.add_argument(
    "--lists", help="create lists after fetching (default: false)", action="store_true"
)
parser.add_argument(
    "--sleep",
    help="number of seconds to sleep between fetches (default: 3)",
    type=int,
    default=3,
)
parser.add_argument("--stats", help="print stats only", action="store_true")
parser.add_argument(
    "--batch",
    help="save data and state every <BATCH> fetches (default: 1000)",
    type=int,
    default=1000,
)
parser.add_argument(
    "-q", "--quiet", help="don't report progress, only errors", action="store_true"
)
args = parser.parse_args()

types_to_fetch: list[str] = list(APPLIST_URLS.keys())
if args.types:
    types_to_fetch = re.split(r"\s*,\s*", args.types.strip(", "))
    types_to_fetch = [t.lower() for t in types_to_fetch]
    for type in types_to_fetch:
        if type not in APPLIST_URLS:
            error(f"--types: Unknown type: '{type}'. Valid types: {VALID_TYPES}.")
            sys.exit(1)


##
## Main
##

state: dict[int, int] = defaultdict(int)  # id -> last fetch time
apps: dict[int, int] = {}  # id -> last changed time
genres: dict[str, str] = {}
new_apps: set[int] = set()
outdated_apps: set[int] = set()
queue: list[int] = []
removed_apps: int = 0
fetched: dict[int, dict[int, dict]] = defaultdict(dict)
nr_of_outdated_items: int = 0

Path(args.datadir).mkdir(parents=True, exist_ok=True)

# Load state
try:
    with open(p(STATE_FILE_NAME)) as f:
        for line in f:
            id, stamp = line[:-1].split(",")[0:2]
            state[int(id)] = int(stamp)
except FileNotFoundError:
    pass

try:
    with open(p(GENRE_FILE_NAME)) as f:
        for line in f:
            id, name = line[:-1].split("\t")
            genres[id] = name
except FileNotFoundError:
    pass


# Get apps
progress("Fetching app ids.", end="")
if args.api:
    base_url = APPLIST_API_URL + f"key={args.api}&max_results=50000"
    for type in types_to_fetch:
        base_url = base_url + f"&include_{type}=true"
    if "games" not in types_to_fetch:
        base_url = base_url + "&include_games=false"
    last_appid = None
    while True:
        url = base_url
        if last_appid:
            url = url + f"&last_appid={last_appid}"
        with urllib.request.urlopen(request(url)) as resp:
            if resp.status != 200:
                error(f"Error fetching app list from api. Response code {resp.status}")
                sys.exit(1)
            data = json.loads(resp.read())
            for item in data["response"]["apps"]:
                apps[item["appid"]] = item["last_modified"]
            if data["response"].get("have_more_results", False):
                last_appid = data["response"]["last_appid"]
            else:
                break
        progress(".", end="")
else:
    for url in [APPLIST_URLS[t] for t in types_to_fetch]:
        with urllib.request.urlopen(request(url)) as resp:
            for item in json.loads(resp.read()):
                apps[item["appid"]] = item["last_modified"]
progress(" Done.")

for id, stamp in apps.items():
    if id in state:
        if state[id] < apps[id]:
            outdated_apps.add(id)
    else:
        new_apps.add(id)

# Removed apps
for id in state.keys():
    if id not in apps:
        removed_apps = removed_apps + 1

# Stats
progress(f"New apps: {len(new_apps)}")
progress(f"Outdated apps: {len(outdated_apps)}")
progress(f"Removed apps: {removed_apps}")

# Queue
queue = sorted(new_apps)
if not args.new:
    queue = queue + sorted(
        outdated_apps, key=lambda id: apps[id] - state[id], reverse=True
    )

nr_of_outdated_items = len(queue)

if args.max:
    queue = queue[: args.max]

progress(f"Queue size: {len(queue)}")
if len(queue) < nr_of_outdated_items:
    progress(
        f"Outdated and new items left after this run: {nr_of_outdated_items - len(queue)}\n"
    )
else:
    progress("")

if args.stats:
    sys.exit(0)

batch_count = 0
error_count = 0

for index, id in enumerate(queue):
    batch_count = batch_count + 1

    if batch_count > args.batch:
        save()
        create_lists()
        batch_count = 1

    req = request(APPINFO_URL + str(id))
    timestamp = int(datetime.now().timestamp())

    retry = 0
    response = None
    while retry < len(BACKOFF):
        try:
            response = urllib.request.urlopen(req)
            break
        except Exception as e:
            progress(f"Error fetching {id}")
            sleep(BACKOFF[retry])
            retry = retry + 1
            if retry >= len(BACKOFF):
                error("Too many failures. Aborting.\n")
                save()
                raise e

    if not response:
        sys.exit(1)

    text = response.read()
    if not text:
        progress(f"Empty response for {id}.")
        response_text = "{}"
    json_obj = json.loads(text)
    try:
        data = json_obj[str(id)]["data"]
    except KeyError as e:
        progress(f"E: {id}", end="")
        state[id] = timestamp
        error_count = error_count + 1
        sleep(args.sleep)
        continue

    process_genre(data)

    for d in DELETE:
        data.pop(d, None)
    if "package_groups" in data:
        for pkg in data["package_groups"]:
            pkg.pop("subs", None)
            pkg.pop("selection_text")
    delete(data, ["achievements", "highlighted"])
    compact(data, "categories")
    compact(data, "genres")
    data = transform(data, urlrewrite)

    file = id // 3000
    fetched[file][id] = data

    prefix = "N"
    old_time = ""
    last_change = time2str(apps[id])
    last_fetch = ""
    if state[id] > 0:
        prefix = "U"
        last_fetch = ", last fetch: " + time2str(state[id])

    progress(
        f"{index}: {prefix}: {id}: {data['name']} (last change: {last_change}{last_fetch}) ",
        end="",
    )

    state[id] = timestamp

    sleep(args.sleep)

progress(f"\nErrors (region restricted items): {error_count}")
if len(queue) < nr_of_outdated_items:
    progress(f"Outdated and new items left: {nr_of_outdated_items - len(queue)}.")
else:
    progress("Nothing left to update.")
save()
create_lists()
