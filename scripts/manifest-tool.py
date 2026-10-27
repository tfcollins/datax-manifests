#!/usr/bin/env python3
"""Manifest and target inspection tool for datax-manifests.

Extracts structured target schemas, variables, inheritance, dependencies,
and documentation comments in machine-readable JSON format for AI agents
and programmatic tooling.
"""

import argparse
import json
from pathlib import Path
import re
import sys

try:
    import yaml
except ImportError:
    yaml = None


def find_repo_root(start_path=None):
    """Find repository root containing targets/."""
    current = Path(start_path or Path.cwd()).resolve()
    while current != current.parent:
        if (current / "targets").is_dir():
            return current
        current = current.parent
    if (Path(__file__).resolve().parent.parent / "targets").is_dir():
        return Path(__file__).resolve().parent.parent
    return None


def extract_variable_comments(sdk_path):
    """Extract doc comments preceding variables in sdk.yml."""
    if not sdk_path.exists():
        return {}
    comments = {}
    current_comment = []
    in_variables = False
    indent_level = None

    with open(sdk_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                current_comment = []
                continue

            if stripped.startswith("variables:"):
                in_variables = True
                current_comment = []
                continue

            if in_variables:
                # Check if we left variables section
                if not line.startswith(" ") and not line.startswith("\t"):
                    in_variables = False
                    current_comment = []
                    continue

                if stripped.startswith("#"):
                    comment_text = stripped.lstrip("#").strip()
                    if comment_text:
                        current_comment.append(comment_text)
                    continue

                # Look for variable declaration: VAR_NAME: value
                match = re.match(r"^\s*([A-Za-z0-9_]+)\s*:", line)
                if match:
                    var_name = match.group(1)
                    if current_comment:
                        comments[var_name] = " ".join(current_comment)
                        current_comment = []
                else:
                    current_comment = []

    return comments


def parse_yaml_file(path):
    """Parse YAML file using PyYAML or a fallback parser."""
    if not path.exists():
        return {}
    if yaml is not None:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    # Minimal fallback parser if pyyaml is missing
    data = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and ":" in line:
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip().strip("\"'")
    return data


def get_target_description(target_dir):
    """Extract a short description from targets/<name>/README.md."""
    readme = target_dir / "README.md"
    if not readme.exists():
        return ""
    lines = readme.read_text(encoding="utf-8").splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # First non-header non-empty line
        return line
    return ""


def get_target_info(repo_root, target_name):
    """Load and resolve full schema for a target, handling extends: hierarchy."""
    target_dir = repo_root / "targets" / target_name
    if not target_dir.is_dir():
        return None

    sdk_file = target_dir / "sdk.yml"
    sdk_data = parse_yaml_file(sdk_file)
    comments = extract_variable_comments(sdk_file)
    desc = get_target_description(target_dir)

    extends_name = sdk_data.get("extends")
    parent_info = None
    if extends_name:
        parent_info = get_target_info(repo_root, extends_name)

    # Resolve variables: parent vars first, then overlay, then target's own
    resolved_vars = {}
    if parent_info:
        for vname, vmeta in parent_info.get("variables", {}).items():
            resolved_vars[vname] = dict(vmeta)

    # Process overlay if present
    overlay = sdk_data.get("overlay", {})
    overlay_vars_set = overlay.get("variables", {}).get("set", {})
    for vname, val in overlay_vars_set.items():
        if vname in resolved_vars:
            resolved_vars[vname]["default"] = str(val) if val is not None else ""
        else:
            resolved_vars[vname] = {"default": str(val) if val is not None else "", "description": ""}

    # Add/override target's own variables
    target_vars = sdk_data.get("variables", {}) or {}
    for vname, val in target_vars.items():
        default_val = str(val) if val is not None else ""
        doc = comments.get(vname, resolved_vars.get(vname, {}).get("description", ""))
        resolved_vars[vname] = {"default": default_val, "description": doc}

    # Gits
    gits = []
    if parent_info:
        gits.extend(parent_info.get("gits", []))
    for git_item in sdk_data.get("gits", []) or []:
        # If already exists in parent gits, replace or append
        gits = [g for g in gits if g.get("name") != git_item.get("name")]
        gits.append({
            "name": git_item.get("name"),
            "url": git_item.get("url"),
            "commit": git_item.get("commit"),
            "build": git_item.get("build", []),
        })

    # OS dependencies
    os_deps = parse_yaml_file(target_dir / "os-dependencies.yml")

    return {
        "name": target_name,
        "description": desc,
        "extends": extends_name,
        "variables": resolved_vars,
        "gits": gits,
        "os_dependencies": os_deps,
        "makefile_include": sdk_data.get("makefile_include", []),
        "copy_files": sdk_data.get("copy_files", []),
    }


def list_all_targets(repo_root):
    """List all available targets in targets/."""
    targets_dir = repo_root / "targets"
    if not targets_dir.is_dir():
        return []
    targets = []
    for d in sorted(targets_dir.iterdir()):
        if d.is_dir() and (d / "sdk.yml").exists():
            desc = get_target_description(d)
            sdk = parse_yaml_file(d / "sdk.yml")
            targets.append({
                "name": d.name,
                "description": desc,
                "extends": sdk.get("extends"),
            })
    return targets


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Analog Devices manifest and target configuration inspector",
        epilog="Use --json to output structured JSON suitable for AI agents and scripts.",
    )
    parser.add_argument("--repo-root", type=Path, help="Path to datax-manifests root")
    parser.add_argument("-t", "--target", help="Specific target to inspect (e.g. hdl, adi-linux)")
    parser.add_argument("-l", "--list-targets", action="store_true", help="List all available targets")
    parser.add_argument("--all", action="store_true", help="Dump full configuration of all targets")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args(argv)

    repo_root = args.repo_root or find_repo_root()
    if not repo_root:
        sys.stderr.write("Error: Could not locate datax-manifests repository root.\n")
        return 1

    if args.list_targets or (not args.target and not args.all):
        targets = list_all_targets(repo_root)
        if args.json:
            print(json.dumps(targets, indent=2))
        else:
            print(f"Available targets from {repo_root}:")
            for t in targets:
                ext = f" (extends: {t['extends']})" if t['extends'] else ""
                print(f"  - {t['name']}{ext}: {t['description']}")
        return 0

    if args.target:
        info = get_target_info(repo_root, args.target)
        if not info:
            sys.stderr.write(f"Error: Target '{args.target}' not found in {repo_root}/targets\n")
            return 1
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print(f"Target: {info['name']}")
            if info['extends']:
                print(f"Extends: {info['extends']}")
            if info['description']:
                print(f"Description: {info['description']}\n")
            print("Variables:")
            for vname, vdata in sorted(info['variables'].items()):
                print(f"  {vname} = {vdata['default']}")
                if vdata['description']:
                    print(f"    # {vdata['description']}")
        return 0

    if args.all:
        all_info = {}
        for t in list_all_targets(repo_root):
            all_info[t["name"]] = get_target_info(repo_root, t["name"])
        if args.json:
            print(json.dumps(all_info, indent=2))
        else:
            for name, info in sorted(all_info.items()):
                print(f"=== Target: {name} ===")
                print(f"Description: {info['description']}")
                print(f"Variables: {', '.join(info['variables'].keys())}\n")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
