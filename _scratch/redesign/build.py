#!/usr/bin/env python3
"""Assemble each concept: title + fonts + css + app root + embedded data + js.
No doctype/html/head/body: the Artifact tool adds the skeleton. A standalone
copy (with the skeleton) is also written for local screenshots."""
import json, sys, os
B = '/tmp/fleet/build'
data = open('/tmp/fleet/concept-data.json').read().replace('</', '<\\/')
common_css = open(f'{B}/common.css').read()
common_js = open(f'{B}/common.js').read()
CONCEPTS = {
    'a': ('The Queue', 'Public+Sans:wght@400;600;700&family=JetBrains+Mono:wght@400;600', '🗂️'),
    'b': ('The Evidence Matrix', 'Atkinson+Hyperlegible:wght@400;700&family=DM+Mono:wght@400;500', '▦'),
    'd': ('The Evidence Matrix, with Schedule', 'Atkinson+Hyperlegible:wght@400;700&family=DM+Mono:wght@400;500', '▦'),
    'c': ('The Client Brief', 'Newsreader:opsz,wght@6..72,500;6..72,600&family=Source+Sans+3:wght@400;600;700', '📋'),
}
for key in (sys.argv[1:] or CONCEPTS):
    title, fonts, _ = CONCEPTS[key]
    css = open(f'{B}/{key}.css').read()
    js = open(f'{B}/{key}.js').read()
    body = f"""<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={fonts}&display=swap">
<style>
{common_css}
{css}
</style>
<div id="app"></div>
<script type="application/json" id="fleet-data">{data}</script>
<script>
{common_js}
</script>
<script>
{js}
</script>
"""
    open(f'/tmp/fleet/out/concept-{key}.html', 'w').write(body)
    open(f'/tmp/fleet/out/standalone-{key}.html', 'w').write('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>' + body + '</body></html>')
    print(key, os.path.getsize(f'/tmp/fleet/out/concept-{key}.html'))
