# Configuration file for the Sphinx documentation builder.
#
# The target pages pull in each target's README.md verbatim (myst include),
# so the READMEs stay the single source of truth.

import datetime
import os
import sys

sys.path.append(os.path.abspath("./ext"))

# -- Project information -----------------------------------------------------

repository = "datax-manifests"
project = "datax-manifests"
year_now = datetime.datetime.now().year
copyright = f"{year_now}, Analog Devices, Inc"
author = "Travis Collins"

release = "main"
version = release

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_parser",
    "adi_doctools",
    "readme_links",
]

needs_extensions = {"adi_doctools": "0.4.21"}

myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3

templates_path = ["_templates"]
exclude_patterns = []

# README links such as ../hdl-boot/README.md are rewritten to doc pages by
# ext/readme_links.py; myst must not turn them into local anchors first.
myst_all_links_external = True

linkcheck_ignore = [
    r"https://wiki.analog.com.*",
    r"https://swdownloads.analog.com.*",
]

# -- External docs configuration ----------------------------------------------

interref_repos = ["doctools"]

# -- Options for HTML output -------------------------------------------------

html_theme = "cosmic"
html_static_path = ["_static"]
html_css_files = ["css/diagrams.css"]
