"""Publish generated API assets from this repo. Run with --site DIR --backend DIR."""
import argparse
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--site', type=Path, required=True)
p.add_argument('--backend', type=Path, required=True)
a = p.parse_args()
r = Path(__file__).resolve().parents[1]
for source, destination in [
    (r / 'skills/justcaptions/assets/styles.json', a.site / 'styles.json'),
    (r / 'skills/justcaptions/assets/styles.json', a.backend / 'functions/_shared/justcaptions-styles.json'),
    (r / 'remote/mcp.mjs', a.backend / 'functions/_shared/justcaptions-mcp.js'),
    (r / 'remote/openapi.json', a.site / 'openapi.json'),
    (r / 'remote/openapi.json', a.backend / 'functions/_shared/justcaptions-openapi.json'),
]:
    shutil.copyfile(source, destination)
    print(destination)
