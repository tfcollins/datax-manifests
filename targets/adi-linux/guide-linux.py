#!/usr/bin/env python3
"""Side-effect-free selection UI; all artifact policy stays in build-kernel.py."""
import argparse
import importlib.util
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
            print("Available: " + "\n - ".join(choices) if choices else f"Default: {default}")
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


def ask_dts(release, platform, dts, hdl_project):
    """Step 2b: pick a devicetree from the boot-pairings CSV, or none."""
    rows, path, fallback = kernel.load_pairings(release)
    choices = [r["DTS"] for r in kernel.find_dts(rows, platform=platform, hdl_project=hdl_project or None)]
    if not choices:
        print(f"No {platform} devicetrees in {path.name}" + (f" for {hdl_project}" if hdl_project else "") + "; kernel only.")
        return ""
    if fallback:
        print(f"(no boot_pairings_{release.lower()}.csv; choices come from {path.name})")
    default = dts if dts in choices else "none"
    return ask("[Step 2b/6] Select devicetree (or none or ? for list)", default, str, ["none"] + choices).replace("none", "")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analog Devices Linux Guided Build Wizard (adi-linux)",
        epilog="No arguments: wizard on a TTY, help otherwise. Use --interactive for scripted input. q/cancel or EOF cancels without building.")
    parser.add_argument("-i", "--interactive", action="store_true")
    parser.add_argument("-l", "--list", action="store_true", help="list supported release/platform combinations offline")
    parser.add_argument("--release", choices=kernel.RELEASES, default="2023_R2")
    parser.add_argument("--platform", choices=kernel.TARGETS, default="zynq")
    parser.add_argument("--dts", default="", help="devicetree to build with the kernel (empty: kernel only)")
    parser.add_argument("--hdl-project", default="", help="HDL project to look the devicetree up from")
    parser.add_argument("-j", "--jobs", default="4")
    parser.add_argument("--output", help="default: artifacts/RELEASE/PLATFORM")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="print commands only; never download/build/verify")
    action.add_argument("--build", action="store_true", help="explicitly execute the helper (may download/build)")
    action.add_argument("--verify", action="store_true", help="offline artifact verification only")
    args = parser.parse_args(argv)
    if args.list:
        for release, source in kernel.RELEASES.items():
            for platform in kernel.TARGETS:
                print(f"{release} / {platform} ({source['ref']})")
        return 0
    interactive = args.interactive or (not any((args.dry_run, args.build, args.verify)) and sys.stdin.isatty())
    if not interactive and not any((args.dry_run, args.build, args.verify)):
        parser.print_help()
        return 0
    try:
        if interactive:
            print("Analog Devices Linux Guided Build Wizard (adi-linux)")
            print("Type ? or list for choices; q/cancel to cancel. Enter accepts defaults.")
            args.release = ask("[Step 1/6] Select Linux release", args.release, str, kernel.RELEASES)
            args.platform = ask("[Step 2/6] Select platform", args.platform, str, kernel.TARGETS)
            args.dts = ask_dts(args.release, args.platform, args.dts, args.hdl_project)
            args.jobs = ask("[Step 3/6] Parallel make jobs", args.jobs, jobs)
        if args.dts or args.hdl_project:
            args.dts = kernel.resolve_dts(args.release, args.platform, args.dts or None, args.hdl_project or None)
        default_output = f"artifacts/{args.release}/{args.platform}"
        if interactive:
            args.output = ask("[Step 4/6] Build output directory" + (f" (+ /{args.dts})" if args.dts else ""),
                              args.output or default_output, output)
        args.jobs = jobs(args.jobs)
        args.output = output(args.output or default_output)
        command = [sys.executable, str(HELPER), "--release", args.release, "--platform", args.platform,
                   "--jobs", args.jobs, "--output", args.output]
        if args.dts:
            command += ["--dts", args.dts]
        print("[Step 5/6] Build Configuration Summary")
        print(f"Release: {args.release} ({kernel.RELEASES[args.release]['ref']}); Platform: {args.platform}; Jobs: {args.jobs}")
        print(f"Devicetree: {args.dts or '(none, kernel only)'}"
              + (f"; artifacts in {args.output}/{args.dts}" if args.dts else ""))
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
