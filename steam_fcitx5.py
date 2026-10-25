#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build and manage a user-local Fcitx5 GTK workaround for native Steam."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor" / "fcitx5-gtk"
BUILD = ROOT / ".build"
ARTIFACTS = BUILD / "artifacts"
PROJECT_ID = "steam-fcitx5-workaround"
VERSION_FLAGS = [
    "-DGLIB_VERSION_MIN_REQUIRED=GLIB_VERSION_2_66",
    "-DGLIB_VERSION_MAX_ALLOWED=GLIB_VERSION_2_66",
]
LIBRARIES = ("im-fcitx5.so", "libFcitx5GClient.so.2")


def run(command, **kwargs):
    return subprocess.run([str(v) for v in command], check=True, **kwargs)


def package_flags(kind, *packages):
    return shlex.split(subprocess.check_output(
        ["pkg-config", kind, *packages], text=True))


def atomic_write(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".steam-fcitx5-", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_sources():
    entries = json.loads((ROOT / "vendor" / "SHA256SUMS.json").read_text())
    for relative, digest in entries.items():
        if hashlib.sha256((VENDOR / relative).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Vendor source checksum mismatch: {relative}")


def build():
    if platform.machine() not in ("x86_64", "amd64"):
        raise RuntimeError("Only x86-64 Linux has been tested.")
    for command in ("gcc", "g++", "pkg-config", "patch", "gtk-query-immodules-3.0"):
        if shutil.which(command) is None:
            raise RuntimeError(f"Missing build dependency: {command}")
    verify_sources()
    BUILD.mkdir(exist_ok=True)
    source = BUILD / "sources"
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(VENDOR, source, symlinks=True)
    run(["patch", "--batch", "--forward", "-p1", "-i",
         ROOT / "patches" / "glib-2.66.patch"], cwd=source)
    objects = BUILD / "objects"
    objects.mkdir(exist_ok=True)
    ARTIFACTS.mkdir(exist_ok=True)
    atomic_write(objects / "config.h",
        '#define LOCALEDIR "/usr/share/locale"\n'
        '#define NO_SNOOPER_APPS ".*chrome.*,.*chromium.*,firefox.*,Do.*"\n'
        '#define NO_PREEDIT_APPS "gvim.*"\n'
        '#define SYNC_MODE_APPS "firefox.*"\n'
        "#define ENABLE_SNOOPER\n#define _ENABLE_SNOOPER 1\n")
    marshallers = (source / "gtk-common" / "marshall.list").read_text().splitlines()
    atomic_write(objects / "marshall.h", "#include <glib-object.h>\n" + "".join(
        "#define fcitx_marshall_" + item.replace(":", "__").replace(",", "_")
        + " g_cclosure_marshal_generic\n" for item in marshallers if item))
    # GLib's generic marshaller avoids a glib-genmarshal build-time dependency.
    run(["gcc", "-shared", "-fPIC", "-O2", *VERSION_FLAGS,
         "-I" + str(objects), source / "fcitx-gclient" / "fcitxgclient.c",
         source / "fcitx-gclient" / "fcitxgwatcher.c",
         "-Wl,-soname,libFcitx5GClient.so.2", "-o",
         ARTIFACTS / "libFcitx5GClient.so.2",
         *package_flags("--cflags", "gio-2.0", "gobject-2.0"),
         *package_flags("--libs", "gio-2.0", "gobject-2.0")])
    common = ["-fPIC", "-O2", *VERSION_FLAGS, "-I" + str(objects),
              "-I" + str(source),
              *package_flags("--cflags", "gtk+-3.0", "gio-unix-2.0",
                             "xkbcommon", "x11")]
    names = ("fcitxim.c", "fcitximcontext.cpp", "fcitxtheme.cpp", "utils.cpp",
             "inputwindow.cpp", "gtk3inputwindow.cpp")

    def compile_one(name):
        output = objects / (name + ".o")
        compiler = ["gcc"] if name.endswith(".c") else [
            "g++", "-std=c++17", "-fno-exceptions"]
        run([*compiler, *common, "-c", source / "gtk3" / name, "-o", output])
        return output

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(compile_one, names))
    run(["g++", "-shared", "-o", ARTIFACTS / "im-fcitx5.so", *outputs,
         ARTIFACTS / "libFcitx5GClient.so.2", "-Wl,-rpath,$ORIGIN",
         *package_flags("--libs", "gtk+-3.0", "gio-unix-2.0", "xkbcommon", "x11")])
    print(f"Built Fcitx5 GTK 5.1.7 with GLib 2.66 API selection: {ARTIFACTS}")


def discover_steam_root(explicit=None):
    candidates = ([Path(explicit).expanduser()] if explicit else [
        Path.home() / ".steam" / "root",
        Path.home() / ".local" / "share" / "Steam",
    ])
    for path in candidates:
        runtime = path / "steamrt64/pv-runtime/steam-runtime-steamrt"
        if all((runtime / name).exists() for name in (
                "_v2-entry-point", "run", "bin", "pressure-vessel")):
            return path.resolve()
    raise RuntimeError("Native Steam Runtime 3c was not found. Start/update "
                       "native Steam once, or pass --steam-root.")


def runtime_script(real_runtime, prefix):
    real = shlex.quote(str(real_runtime / "_v2-entry-point"))
    cache = shlex.quote(str(prefix / "immodules.cache"))
    return (
        "#!/bin/sh\nset -eu\n"
        "# Only the Steam browser/chat launcher receives input overrides.\n"
        "command_path=${2-}\n"
        'if [ "${1-}" = "--" ] && '
        '[ "${command_path##*/}" = "steamwebhelper_sniper_wrap.sh" ]; then\n'
        "    shift\n"
        f"    exec {real} -- /usr/bin/env GTK_IM_MODULE=fcitx "
        f"GTK_IM_MODULE_FILE={cache} FCITX_ENABLE_SYNC_MODE=1 \"$@\"\n"
        "fi\n"
        f'exec {real} "$@"\n'
    )


def start_script(prefix, steam_binary):
    return ("#!/bin/sh\nset -eu\n"
            f"export STEAM_RUNTIME_STEAMRT={shlex.quote(str(prefix / 'runtime'))}\n"
            f'exec {shlex.quote(str(steam_binary))} "$@"\n')


def desktop_quote(path):
    value = str(path)
    if any(c in value for c in ("\n", "\r", "\0")):
        raise RuntimeError("Desktop entry paths cannot contain line breaks or NUL.")
    value = value.replace("%", "%%")
    for char in ("\\", '"', "`", "$"):
        value = value.replace(char, "\\" + char)
    return '"' + value + '"'


def render_desktop(source, launcher):
    count = 0
    result = []
    for line in source.splitlines(keepends=True):
        if line.startswith("Exec="):
            command = line[5:].rstrip("\r\n")
            words = shlex.split(command)
            if not words or Path(words[0]).name != "steam":
                raise RuntimeError(f"Unsupported Steam desktop Exec: {command}")
            match = re.match(r'^(?:"[^"]*"|[^\s]+)(.*)$', command)
            line = "Exec=" + desktop_quote(launcher) + match.group(1) + "\n"
            count += 1
        result.append(line)
    if count == 0:
        raise RuntimeError("No Steam Exec lines found in the desktop source.")
    return "".join(result)


def read_manifest(prefix):
    path = prefix / "manifest.json"
    if not path.exists():
        return None
    manifest = json.loads(path.read_text())
    if manifest.get("project") != PROJECT_ID:
        raise RuntimeError("The prefix belongs to another application.")
    return manifest


def install(args):
    prefix = args.prefix.expanduser().absolute()
    target = args.desktop_target.expanduser().absolute()
    if prefix == Path.home() or prefix == Path("/") or prefix == ROOT:
        raise RuntimeError("Choose a dedicated installation prefix.")
    manifest = read_manifest(prefix)
    if prefix.exists() and manifest is None and any(prefix.iterdir()):
        raise RuntimeError("Installation prefix is not managed by this project.")
    if manifest:
        if manifest["desktop_target"] != str(target):
            raise RuntimeError("A previous install uses a different desktop target.")
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != (
                manifest["installed_desktop_sha256"]):
            raise RuntimeError("The local desktop entry changed since install; "
                               "refusing to replace it.")
    elif target.exists() and not args.replace_desktop:
        raise RuntimeError("A local Steam desktop entry already exists. Review it "
                           "first; --replace-desktop backs it up before replacing it.")
    steam_root = discover_steam_root(args.steam_root)
    real_runtime = steam_root / "steamrt64/pv-runtime/steam-runtime-steamrt"
    executable = Path(args.steam_binary)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f"Steam executable was not found: {executable}")
    desktop = render_desktop(args.desktop_source.read_text(),
                             prefix / "start-steam.sh")
    if not args.skip_build:
        build()
    if not all((ARTIFACTS / name).is_file() for name in LIBRARIES):
        raise RuntimeError("No build artifacts. Run build first.")
    prefix.mkdir(parents=True, exist_ok=True)
    # The original desktop backup survives repeat installs.
    previous = manifest.get("previous_desktop") if manifest else None
    if manifest is None and target.exists():
        previous = "desktop-before.install"
        shutil.copy2(target, prefix / previous)
    for name in LIBRARIES:
        temporary = prefix / (name + ".new")
        shutil.copy2(ARTIFACTS / name, temporary)
        os.replace(temporary, prefix / name)
    cache = subprocess.check_output(
        ["gtk-query-immodules-3.0", str(prefix / "im-fcitx5.so")], text=True)
    atomic_write(prefix / "immodules.cache", cache)
    proxy = prefix / "runtime"
    proxy.mkdir(exist_ok=True)
    for item in real_runtime.iterdir():
        if item.name == "_v2-entry-point":
            continue
        link = proxy / item.name
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            raise RuntimeError(f"Unexpected file in runtime proxy: {link}")
        link.symlink_to(item, target_is_directory=item.is_dir())
    atomic_write(proxy / "_v2-entry-point",
                 runtime_script(real_runtime, prefix), 0o755)
    atomic_write(prefix / "start-steam.sh",
                 start_script(prefix, executable), 0o755)
    for file in (proxy / "_v2-entry-point", prefix / "start-steam.sh"):
        run(["sh", "-n", file])
    # Validate before changing the live desktop entry.
    candidate = prefix / "candidate.desktop"
    atomic_write(candidate, desktop)
    if shutil.which("desktop-file-validate"):
        run(["desktop-file-validate", candidate], stdout=subprocess.DEVNULL)
    candidate.unlink()
    next_manifest = {
        "project": PROJECT_ID,
        "upstream_version": "5.1.7",
        "steam_root": str(steam_root),
        "real_runtime": str(real_runtime),
        "desktop_target": str(target),
        "previous_desktop": previous,
        "installed_desktop_sha256": hashlib.sha256(desktop.encode()).hexdigest(),
    }
    atomic_write(prefix / "manifest.json",
                 json.dumps(next_manifest, indent=2) + "\n")
    atomic_write(target, desktop)
    print(f"Installed menu launcher: {target}")
    print(f"Private input modules: {prefix}")
    print("Steam was not restarted. Fully exit Steam, then open it from the app menu.")


def uninstall(args):
    prefix = args.prefix.expanduser().absolute()
    manifest = read_manifest(prefix)
    if manifest is None:
        raise RuntimeError("No managed installation was found at this prefix.")
    target = Path(manifest["desktop_target"])
    if target.exists():
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != manifest["installed_desktop_sha256"]:
            raise RuntimeError("The Steam desktop entry has been edited; refusing "
                               "to overwrite your newer changes.")
    previous = manifest["previous_desktop"]
    if previous:
        atomic_write(target, (prefix / previous).read_text())
        print("Restored the previous local Steam desktop entry.")
    else:
        target.unlink(missing_ok=True)
        print("Removed the local desktop override; the system entry is available.")
    if prefix == Path.home() or prefix == Path("/") or prefix == ROOT:
        raise RuntimeError("Refusing to remove an unsafe prefix.")
    shutil.rmtree(prefix)
    print("Removed the private installation. The source checkout/build cache remain.")
    print("Fully exit and reopen Steam to stop using an already loaded module.")


def running_helpers():
    records = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / "comm").read_text().strip() != "steamwebhelper":
                continue
            arguments = (process / "cmdline").read_bytes().split(b"\0")
            if any(v.startswith(b"--type=") for v in arguments):
                continue
            environment = dict(v.split(b"=", 1) for v in
                               (process / "environ").read_bytes().split(b"\0")
                               if b"=" in v)
            selected = {key.decode(): environment.get(key, b"").decode(
                errors="replace") for key in (
                    b"GTK_IM_MODULE", b"GTK_IM_MODULE_FILE",
                    b"FCITX_ENABLE_SYNC_MODE")}
            mappings = sorted({line.split()[-1] for line in
                               (process / "maps").read_text().splitlines()
                               if any(name in line for name in LIBRARIES)})
            records.append({"pid": int(process.name), "settings": selected,
                            "loaded_input_libraries": mappings})
        except (OSError, ValueError):
            continue
    return records


def doctor(args):
    prefix = args.prefix.expanduser().absolute()
    manifest = read_manifest(prefix)
    print("Installation:", "present" if manifest else "not found")
    print(json.dumps(running_helpers(), ensure_ascii=False, indent=2))
    if not args.runtime_test:
        return
    if manifest is None:
        raise RuntimeError("Install into this prefix before running --runtime-test.")
    # Keep the probe under the shared home path; container /tmp may be private.
    with tempfile.TemporaryDirectory(prefix=".doctor-", dir=prefix) as temporary:
        directory = Path(temporary)
        probe = directory / "context-probe"
        run(["gcc", "-O2", *VERSION_FLAGS, ROOT / "tools/context-probe.c",
             "-o", probe, *package_flags("--cflags", "gtk+-3.0"),
             *package_flags("--libs", "gtk+-3.0")])
        helper = directory / "steamwebhelper_sniper_wrap.sh"
        atomic_write(helper, "#!/bin/sh\nexec " + shlex.quote(str(probe)) + "\n",
                     0o755)
        command = [prefix / "runtime/_v2-entry-point", "--", helper]
        environment = dict(os.environ, GDK_BACKEND="x11")
        run(command, env=environment)
    print("A successful probe verifies module loading, not every Steam chat key path.")


def parser():
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="Build private GTK3 modules from vendored source")
    install_parser = commands.add_parser("install", help="Install a user-local menu override")
    for command in (install_parser,
                    commands.add_parser("uninstall", help="Restore the launcher and remove modules"),
                    commands.add_parser("doctor", help="Inspect the current module settings")):
        command.add_argument("--prefix", type=Path,
                             default=data / PROJECT_ID)
    install_parser.add_argument("--steam-root", type=Path)
    install_parser.add_argument("--steam-binary", default=(
        "/usr/bin/steam" if Path("/usr/bin/steam").exists() else "/usr/games/steam"))
    install_parser.add_argument("--desktop-source", type=Path,
                                default=Path("/usr/share/applications/steam.desktop"))
    install_parser.add_argument("--desktop-target", type=Path,
                                default=data / "applications/steam.desktop")
    install_parser.add_argument("--replace-desktop", action="store_true")
    install_parser.add_argument("--skip-build", action="store_true")
    commands.choices["doctor"].add_argument("--runtime-test", action="store_true")
    return root


def main():
    args = parser().parse_args()
    try:
        if args.command == "build":
            build()
        elif args.command == "install":
            install(args)
        elif args.command == "uninstall":
            uninstall(args)
        elif args.command == "doctor":
            doctor(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
