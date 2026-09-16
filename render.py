#!/usr/bin/env python3
"""Render data/build.json into dist/ static HTML."""
import json
import os
import shutil
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
build = json.load(open("data/build.json"))

if os.path.exists("dist"):
    shutil.rmtree("dist")
os.makedirs("dist")

ctx = {"generated": build["generated"][:10], "churn": build["churn"], "badge": None}
index = env.get_template("index.html").render(ballots=build["ballots"], **ctx)
open("dist/index.html", "w").write(index)

ballot_tpl = env.get_template("ballot.html")
for b in build["ballots"]:
    html = ballot_tpl.render(ballot=b, churn=build["churn"].get(b["id"]), generated=ctx["generated"])
    open(f"dist/{b['id']}.html", "w").write(html)
    print(f"dist/{b['id']}.html")

print("dist/index.html — done")
