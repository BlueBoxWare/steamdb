#!/usr/bin/env python3

import argparse
import json
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, DefaultDict, NamedTuple
from urllib.parse import ParseResult, urlparse

STATE_FILE_NAME = "state"

APPLIST_URL = "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/games_appid.json"
APPINFO_URL = "https://store.steampowered.com/api/appdetails?l=english&appids="

SLEEP = 2
BACKOFF = [5, 20, 60, 120]
BUCKETS: list[int] = [100, 500, 1000, 2000, 5000, 10000, 50000, 100000]

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
]


class State(NamedTuple):
    timestamp: int
    count: int
    error: bool = False
    removed: bool = False


state: dict[int, State] = {}
known_ids: set[int] = set()

##
## Helpers
##
def progress(msg: str):
    if not args.quiet:
        print(msg)


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
    print(" ", end="")


def save():
    progress("Saving.")

    for file_id, games in fetched.items():
        js = {}
        file = Path(args.datadir, str(file_id))
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

    with open(state_file, "w") as f:
        for id, data in sorted(state.items()):
            f.write(f"{id},{data.timestamp},{data.count},{1 if data.error else 0}\n")


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
    if u.netloc == "cdn.akamai.steamstatic.com" and "=" in u.query:
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


def convert_date(d: str) -> str:
    try:
        date = datetime.strptime(d, "%b %d, %Y")
        postfix = date.strftime("%b, %Y")
        return f"{date.day} {postfix}"
    except:
        return d


##
## Command line arguments
##
parser = argparse.ArgumentParser(prog="fetch.py")
parser.add_argument("datadir", help="data directory")
parser.add_argument("number", help="number of apps to fetch", type=int)
parser.add_argument("--new", help="new apps only", action="store_true")
parser.add_argument("--file", help="load list of apps from <file>", metavar="<file>")
parser.add_argument("--stats", help="print stats only", action="store_true")
parser.add_argument("-b", "--batch", help="batch size", type=int)
parser.add_argument("-q", "--quiet", help="don't report progress", action="store_true")
args = parser.parse_args()

##
## Main
##
state_file = Path(args.datadir, STATE_FILE_NAME)

# Load state
try:
    with open(state_file) as f:
        for line in f:
            id, stamp, count, error = line[:-1].split(",")
            state[int(id)] = State(int(stamp), count=int(count), error=error == "1")
            known_ids.add(int(id))
except FileNotFoundError:
    pass


# Get apps
if args.file:
    with open(args.file) as f:
        json_obj = json.load(f)
else:
    req = request(APPLIST_URL)
    with urllib.request.urlopen(req) as resp:
        json_obj = json.loads(resp.read())

new_item_count = 0
ids = set()

# Handle both old Steam API format (dict) and new GitHub list format (list)
apps_source = json_obj
if isinstance(json_obj, dict) and "applist" in json_obj:
    apps_source = json_obj["applist"]["apps"]

for app in apps_source:
    id = int(app["appid"])
    ids.add(id)
    if id not in known_ids:
        state[id] = State(0, 0)
        known_ids.add(id)
        new_item_count = new_item_count + 1
progress(f"{new_item_count} new items added to queue.")

removed_item_count = 0
for id, data in list(state.items()):
    if not id in ids:
        removed_item_count = removed_item_count + 1
        state[id] = State(
            data.timestamp, count=data.count, error=data.error, removed=True
        )
progress(f"{removed_item_count} removed from queue.")

# Stats
if not args.quiet:
    unseen_items = len([i for i in state.values() if i.timestamp == 0])
    progress(f"{unseen_items} unfetched items in queue.")
    progress(f"{len(state) - unseen_items} fetched items in queue.")

if args.stats:
    sys.exit(0)

# Create queue
queue: list[int] = [
    id for id in state.keys() if state[id].count == 0 and not state[id].removed
]

if args.number and len(queue) > args.number:
    queue = queue[: args.number]

elif not args.new:

    BUCKETS.insert(0, 0)
    items_per_bucket = (args.number - len(queue)) // len(BUCKETS)
    ids = sorted(
        [id for id in state.keys() if state[id].count > 0 and not state[id].removed],
        reverse=True,
    )
    BUCKETS.append(len(ids))
    for i in range(0, len(BUCKETS) - 1):
        bucket = ids[BUCKETS[i] : BUCKETS[i + 1]]
        to_add = sorted(bucket, key=lambda id: state[id].timestamp)[:items_per_bucket]
        queue.extend(to_add)

# Start
batch_count = 0
fetched: DefaultDict[int, dict[int, Any]] = defaultdict(dict)

for game_id in queue:
    batch_count = batch_count + 1

    if args.batch and batch_count > args.batch:
        save()
        batch_count = 0
        sleep(SLEEP)

    full_url = APPINFO_URL + str(game_id)
    req = request(full_url)
    timestamp = int(datetime.now().timestamp())
    data_file = Path(args.datadir, str(game_id))

    retry = 0
    response = None
    while retry < len(BACKOFF):
        try:
            response = urllib.request.urlopen(req)
            break
        except Exception as e:
            progress(f"Network error fetching {game_id}")
            sleep(BACKOFF[retry])
            retry = retry + 1
            if retry >= len(BACKOFF):
                progress("Too many network failures. Aborting.\n")
                save()
                raise e

    if not response:
        sys.exit(1)

    response_text = response.read()
    if not response_text:
        progress(f"Empty response for {game_id}.")
        response_text = "{}"
    json_obj = json.loads(response_text)
    try:
        data = json_obj[str(game_id)]["data"]
    except KeyError as e:
        progress(f"E: {game_id}. ")
        state[game_id] = State(timestamp, state[game_id].count + 1, error=True)
        sleep(SLEEP)
        continue

    for d in DELETE:
        if d in data:
            del data[d]
    if "package_groups" in data:
        for p in data["package_groups"]:
            if "subs" in p:
                del p["subs"]
    if "achievements" in data:
        if "highlighted" in data["achievements"]:
            del data["achievements"]["highlighted"]
    if "release_date" in data:
        if "date" in data["release_date"]:
            data["release_date"]["date"] = convert_date(data["release_date"]["date"])
    compact(data, "categories")
    compact(data, "genres")
    data = transform(data, urlrewrite)

    file = game_id // 3000
    fetched[file][game_id] = data

    prefix = "U" if state[game_id].timestamp > 0 else "N"
    old_time = ""
    if state[game_id].timestamp > 0:
        old_time = (
            "("
            + datetime.utcfromtimestamp(state[game_id].timestamp)
            .replace(tzinfo=timezone.utc)
            .astimezone(tz=None)
            .strftime("%-d %b")
            + ")"
        )
    progress(f"{prefix}: {data['name']} ({game_id}) {old_time}")

    state[game_id] = State(timestamp, state[game_id].count + 1)

    sleep(SLEEP)

save()
