"""Rewrite README-relative links to the Sphinx pages that include those READMEs.

The target pages are ``{include}``s of ``targets/<name>/README.md``, whose
links are written for GitHub: ``../<other>/README.md`` from a target README,
``targets/<name>/README.md`` from the top-level README. Map both onto the
``targets/<name>`` documents (keeping any ``#fragment``), and ``LICENSE`` onto
the GitHub blob, so the rendered site has no dead anchors.
"""
import re

from docutils import nodes
from sphinx.addnodes import pending_xref

TARGET_README = re.compile(r"^(?:\.\./|targets/)([A-Za-z0-9_-]+)/README\.md(#.*)?$")
REPO_BLOB = "https://github.com/tfcollins/datax-manifests/blob/main/"


def rewrite(app, doctree):
    for node in list(doctree.findall(nodes.reference)):
        uri = node.get("refuri") or ""
        m = TARGET_README.match(uri)
        if m:
            target, fragment = m.group(1), m.group(2) or ""
            xref = pending_xref(
                "", refdomain="std", reftype="doc", reftarget=f"/targets/{target}",
                refexplicit=True, refwarn=True,
            )
            xref += nodes.inline("", "", *node.children, classes=["xref", "std", "std-doc"])
            if fragment:
                xref["refanchor"] = fragment
            node.replace_self(xref)
        elif uri == "LICENSE":
            node["refuri"] = REPO_BLOB + "LICENSE"
        elif uri.startswith("#../") or uri.startswith("#targets/"):
            # a GitHub-relative link that myst already demoted to a local anchor
            node["refuri"] = uri[1:]


def setup(app):
    app.connect("doctree-read", rewrite)
    return {"version": "1", "parallel_read_safe": True}
