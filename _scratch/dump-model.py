#!/usr/bin/env python3
"""Scratch: dump the renderer's FULL model (every site fact, components, email rulings)
so the redesign concepts are built from the same object the page draws from.
Read-only; does not touch the renderer."""
import importlib.util, json, os, sys, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rd", os.path.join(HERE, "..", "scripts", "render-dashboard.py"))
rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)
m = rd.build_model("./history", "./data/fleet-inventory.json", datetime.date.today())
def dflt(o):
    if isinstance(o, (set, tuple)): return sorted(o) if isinstance(o, set) else list(o)
    if isinstance(o, (datetime.date, datetime.datetime)): return o.isoformat()
    return str(o)
out = {}
for k, v in m.items():
    try:
        json.dumps(v, default=dflt); out[k] = v
    except Exception as e:
        out[k] = "UNSERIALISABLE: %s" % e
with open("_scratch/fleet-model-full.json", "w") as fh:
    json.dump(out, fh, indent=1, default=dflt)
print(sorted(m.keys()))
print(os.path.getsize("_scratch/fleet-model-full.json"))
