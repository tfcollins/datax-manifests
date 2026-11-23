"""The agent skills in .claude/skills must only name make verbs and repo paths that exist.

Skills are read by agents as ground truth; a renamed make target or moved
script silently turns them into wrong instructions. Offline, no workspace.
"""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS = sorted((ROOT / ".claude/skills").glob("*/SKILL.md"))

# Targets every cim-generated Makefile has, plus the per-git targets cim
# derives from a gits: entry with its own build: (hdl-boot).
CIM_GENERATED = {"all", "sdk-envsetup", "sdk-build", "sdk-clean", "sdk-test", "sdk-flash",
                 "u-boot-xlnx", "arm-trusted-firmware"}


def make_verbs():
    verbs = set(CIM_GENERATED)
    for mk in (ROOT / "targets").glob("*/*.mk"):
        text = mk.read_text().replace("\\\n", " ")
        for line in text.splitlines():
            if line.startswith(".PHONY:"):
                verbs.update(line.split(":", 1)[1].split())
    return verbs


def workspace_paths():
    """copy_files destinations: paths that exist in a workspace, not the repo."""
    dests = set()
    for sdk in (ROOT / "targets").glob("*/sdk.yml"):
        for entry in yaml.safe_load(sdk.read_text()).get("copy_files") or []:
            dests.add(entry["dest"])
    return dests


def code_spans(text):
    """Inline `code` and fenced blocks: the parts agents copy and run."""
    fenced = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
    inline = re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S))
    return fenced + inline


class SkillTests(unittest.TestCase):
    def test_skills_exist(self):
        self.assertGreaterEqual(len(SKILLS), 5)

    def test_frontmatter(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = skill.read_text()
                self.assertTrue(text.startswith("---\n"))
                meta = yaml.safe_load(text.split("---\n")[1])
                self.assertEqual(meta["name"], skill.parent.name)
                self.assertRegex(meta["name"], r"^[a-z0-9-]+$")
                self.assertTrue(meta["description"].startswith("Use when"), meta["description"][:40])
                self.assertLessEqual(len(meta["description"]), 1024)

    def test_make_verbs_exist(self):
        verbs = make_verbs()
        for skill in SKILLS:
            for span in code_spans(skill.read_text()):
                for verb in re.findall(r"(?<!to )\bmake\s+(?:-[a-zA-Z]+\s+)*([a-z][a-z0-9-]*)(?![\w<*-])", span):
                    with self.subTest(skill=skill.parent.name, verb=verb):
                        self.assertIn(verb, verbs, f"`make {verb}` in {skill.parent.name} is not a target")

    def test_paths_exist(self):
        ws = workspace_paths()
        # placeholders (`tests/test_<target>.py`, `targets/*/…`, `{a,b}`) are not checked
        pattern = re.compile(r"(?<![\w/.~$-])((?:targets|scripts|tests|doc|\.claude)/[\w./-]*\w)(?![\w<*{-])")
        for skill in SKILLS:
            for span in code_spans(skill.read_text()):
                for path in pattern.findall(span):
                    with self.subTest(skill=skill.parent.name, path=path):
                        self.assertTrue((ROOT / path).exists() or path in ws,
                                        f"{path} named in {skill.parent.name} exists neither in the repo "
                                        "nor as a copy_files dest")
                for module in re.findall(r"\btests\.(test_\w+)", span):
                    with self.subTest(skill=skill.parent.name, module=module):
                        self.assertTrue((ROOT / "tests" / f"{module}.py").exists())

    def test_cross_references_resolve(self):
        names = {s.parent.name for s in SKILLS}
        for skill in SKILLS:
            for ref in re.findall(r"`([a-z]+(?:-[a-z]+)+)`", skill.read_text()):
                if ref.endswith(("-cim-targets", "-cim-target", "-cim-manifests", "-boot-bin", "-devicetree")):
                    with self.subTest(skill=skill.parent.name, ref=ref):
                        self.assertIn(ref, names)


if __name__ == "__main__":
    unittest.main()
