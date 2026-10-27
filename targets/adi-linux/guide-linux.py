#!/usr/bin/env python3
"""Side-effect-free selection UI; all artifact policy stays in build-kernel.py."""
import argparse
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys

HELPER = Path(__file__).resolve().with_name("build-kernel.py")
spec = importlib.util.spec_from_file_location("kernel", HELPER)
assert spec is not None and spec.loader is not None
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)


def jobs(value):
    if not value.isascii() or not value.isdecimal() or int(value) < 1:
        raise ValueError("jobs must be a positive integer")
    return str(int(value))


def output(value):
    if not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError("output must be a nonempty path without control characters")
    return value


def ask(label, default, validate, choices=None):
    while True:
        value = input(f"{label} [{default}] > ").strip()
        if value.lower() in ("q", "quit", "cancel"):
            raise EOFError
        if value in ("?", "list"):
            print("Available: " + ", ".join(choices) if choices else f"Default: {default}")
            continue
        value = value or default
        if choices and value.isdecimal() and 1 <= int(value) <= len(choices):
            value = list(choices)[int(value) - 1]
        try:
            if choices and value not in choices:
                raise ValueError("choose " + ", ".join(choices))
            return validate(value)
        except ValueError as exc:
            print(f"Invalid selection: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analog Devices Linux Guided Build Wizard (adi-linux)",
        epilog="No arguments: wizard on a TTY, help otherwise. Use --interactive for scripted input. q/cancel or EOF cancels without building.")
    parser.add_argument("-i", "--interactive", action="store_true")
    parser.add_argument("-l", "--list", action="store_true", help="list supported release/platform combinations offline")
    parser.add_argument("--release", choices=kernel.RELEASES, default="2023_R2")
    parser.add_argument("--platform", choices=kernel.TARGETS, default="zynq")
    parser.add_argument("-j", "--jobs", default="4")
    parser.add_argument("--output", help="default: artifacts/RELEASE/PLATFORM")
    parser.add_argument("--json", action="store_true", help="output structured JSON (offline, machine-readable)")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="print commands only; never download/build/verify")
    action.add_argument("--build", action="store_true", help="explicitly execute the helper (may download/build)")
    action.add_argument("--verify", action="store_true", help="offline artifact verification only")
    args = parser.parse_args(argv)
    if args.list:
        if args.json:
            items = []
            for release, source in kernel.RELEASES.items():
                for platform in kernel.TARGETS:
                    target_spec = kernel.TARGETS[platform]
                    items.append({
                        "release": release,
                        "platform": platform,
                        "ref": source["ref"],
                        "arch": target_spec["arch"],
                        "defconfig": target_spec["defconfig"],
                        "output_format": target_spec["output"],
                        "image": target_spec["image"],
                    })
            print(json.dumps(items, indent=2))
        else:
            for release, source in kernel.RELEASES.items():
                for platform in kernel.TARGETS:
                    print(f"{release} / {platform} ({source['ref']})")
        return 0
    interactive = args.interactive or (not any((args.dry_run, args.build, args.verify, args.json)) and sys.stdin.isatty())
    if not interactive and not any((args.dry_run, args.build, args.verify, args.json)):
        parser.print_help()
        return 0
    try:
        if interactive:
            print("Analog Devices Linux Guided Build Wizard (adi-linux)")
            print("Type ? or list for choices; q/cancel to cancel. Enter accepts defaults.")
            args.release = ask("[Step 1/5] Select Linux release", args.release, str, kernel.RELEASES)
            args.platform = ask("[Step 2/5] Select platform", args.platform, str, kernel.TARGETS)
            args.jobs = ask("[Step 3/5] Parallel make jobs", args.jobs, jobs)
            args.output = ask("[Step 4/5] Build output directory", args.output or f"artifacts/{args.release}/{args.platform}", output)
        args.jobs = jobs(args.jobs)
        args.output = output(args.output or f"artifacts/{args.release}/{args.platform}")
        command = [sys.executable, str(HELPER), "--release", args.release, "--platform", args.platform,
                   "--jobs", args.jobs, "--output", args.output]
        if args.json:
            cfg = {
                "target": "adi-linux",
                "release": args.release,
                "platform": args.platform,
                "ref": kernel.RELEASES[args.release]["ref"],
                "arch": kernel.TARGETS[args.platform]["arch"],
                "defconfig": kernel.TARGETS[args.platform]["defconfig"],
                "output_dir": args.output,
                "output_format": kernel.TARGETS[args.platform]["output"],
                "jobs": int(args.jobs),
                "provenance": kernel.provenance(args.platform, args.release),
                "commands": {
                    "build": shlex.join(command),
                    "verify": shlex.join(command + ["--verify"]),
                },
            }
            print(json.dumps(cfg, indent=2))
            return 0
        print("[Step 5/5] Build Configuration Summary")
        print(f"Release: {args.release} ({kernel.RELEASES[args.release]['ref']}); Platform: {args.platform}; Jobs: {args.jobs}")
        print("Build command: " + shlex.join(command))
        print("Verify command: " + shlex.join(command + ["--verify"]))
        if args.dry_run:
            print("[DRY-RUN] No commands executed.")
            return 0
        if interactive:
            choice = ask("Verify existing artifacts or start build? (build/verify/no)", "no", str,
                         ("build", "verify", "no"))
            if choice == "no":
                raise EOFError
            args.verify = choice == "verify"
        return subprocess.run(command + (["--verify"] if args.verify else []), check=False).returncode
    except (EOFError, KeyboardInterrupt):
        print("\nBuild cancelled. No further commands executed.")
        return 0
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
