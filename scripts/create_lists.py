#!/usr/bin/env python3

import argparse
import os
import json
from pathlib import Path

parser = argparse.ArgumentParser(
    prog="create_lists.py",
)
parser.add_argument("datadir", help="data directory")
parser.add_argument("outputdir", help="dir where the lists should be placed")
args = parser.parse_args()

demos = set()
cards = set()
achievements = set()

for filename in os.listdir(args.datadir):
    if filename.isdigit():
        with open(Path(args.datadir, filename)) as f:
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

with open(Path(args.outputdir, "demos"), 'w') as f:
    for id in sorted(demos):
        f.write(f"{id}\n")
with open(Path(args.outputdir, "cards"), 'w') as f:
    for id in sorted(cards):
        f.write(f"{id}\n")
with open(Path(args.outputdir, "achievements"), 'w') as f:
    for id in sorted(achievements):
        f.write(f"{id}\n")
