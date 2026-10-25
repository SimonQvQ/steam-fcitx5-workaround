# SPDX-License-Identifier: LGPL-2.1-or-later
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import steam_fcitx5 as app


class LauncherTests(unittest.TestCase):
    def test_all_desktop_actions_keep_their_arguments(self):
        source = ("[Desktop Entry]\nName=Steam\nType=Application\n"
                  "Exec=/usr/bin/steam %U\nActions=Friends;\n"
                  "[Desktop Action Friends]\nName=Friends\n"
                  "Exec=/usr/bin/steam steam://open/friends\n")
        result = app.render_desktop(source, Path("/tmp/user space/start-steam.sh"))
        self.assertIn('Exec="/tmp/user space/start-steam.sh" %U', result)
        self.assertIn('Exec="/tmp/user space/start-steam.sh" steam://open/friends', result)

    def test_unexpected_exec_is_not_silently_rewritten(self):
        with self.assertRaises(RuntimeError):
            app.render_desktop("Exec=env SOME_CUSTOM=value steam %U\n",
                               Path("/tmp/start-steam.sh"))

    def test_only_helper_receives_input_overrides(self):
        with tempfile.TemporaryDirectory(prefix="steam input test ") as temporary:
            base = Path(temporary)
            real = base / "real runtime"
            real.mkdir()
            app.atomic_write(real / "_v2-entry-point",
                             '#!/bin/sh\nset -eu\n[ "$1" = -- ] && shift\nexec "$@"\n',
                             0o755)
            prefix = base / "private modules"
            prefix.mkdir()
            wrapper = base / "entry"
            app.atomic_write(wrapper, app.runtime_script(real, prefix), 0o755)
            expression = ("import os,json; print(json.dumps({k:os.environ.get(k) "
                          "for k in ['GTK_IM_MODULE','GTK_IM_MODULE_FILE',"
                          "'FCITX_ENABLE_SYNC_MODE']}))")
            body = "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -c " + (
                shlex.quote(expression)) + "\n"
            environment = dict(os.environ)
            for key in ("GTK_IM_MODULE", "GTK_IM_MODULE_FILE", "FCITX_ENABLE_SYNC_MODE"):
                environment.pop(key, None)
            outputs = {}
            for name in ("steamwebhelper_sniper_wrap.sh", "ordinary-child.sh"):
                child = base / name
                app.atomic_write(child, body, 0o755)
                outputs[name] = json.loads(subprocess.check_output(
                    [str(wrapper), "--", str(child)], text=True, env=environment))
            helper = outputs["steamwebhelper_sniper_wrap.sh"]
            self.assertEqual(helper["GTK_IM_MODULE"], "fcitx")
            self.assertEqual(helper["GTK_IM_MODULE_FILE"], str(prefix / "immodules.cache"))
            self.assertEqual(helper["FCITX_ENABLE_SYNC_MODE"], "1")
            self.assertEqual(outputs["ordinary-child.sh"],
                             {key: None for key in helper})


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="steam-fcitx5-install-")
        self.base = Path(self.temporary.name)
        self.prefix = self.base / "private"
        self.desktop = self.base / "applications" / "steam.desktop"
        self.source = self.base / "system.desktop"
        self.source.write_text("[Desktop Entry]\nName=Steam\nType=Application\n"
                               "Exec=/usr/bin/steam %U\n")
        self.steam = self.base / "Steam"
        runtime = self.steam / "steamrt64/pv-runtime/steam-runtime-steamrt"
        runtime.mkdir(parents=True)
        for name in ("_v2-entry-point", "run"):
            app.atomic_write(runtime / name, "#!/bin/sh\nexit 0\n", 0o755)
        for name in ("bin", "pressure-vessel"):
            (runtime / name).mkdir()
        artifacts = self.base / "artifacts"
        artifacts.mkdir()
        for name in app.LIBRARIES:
            (artifacts / name).write_bytes(b"unit test placeholder")
        self.args = SimpleNamespace(
            prefix=self.prefix, desktop_target=self.desktop,
            steam_root=self.steam, steam_binary=shutil.which("true"),
            desktop_source=self.source, replace_desktop=False, skip_build=True)
        self.artifact_patch = patch.object(app, "ARTIFACTS", artifacts)
        self.query_patch = patch.object(app.subprocess, "check_output",
                                        return_value="# fake GTK cache\n")
        self.artifact_patch.start()
        self.query_patch.start()

    def tearDown(self):
        self.query_patch.stop()
        self.artifact_patch.stop()
        self.temporary.cleanup()

    def install(self):
        with contextlib.redirect_stdout(io.StringIO()):
            app.install(self.args)

    def uninstall(self):
        with contextlib.redirect_stdout(io.StringIO()):
            app.uninstall(self.args)

    def test_clean_install_uninstall_restores_system_fallback(self):
        self.install()
        self.assertTrue(self.desktop.exists())
        self.assertTrue((self.prefix / "manifest.json").exists())
        self.uninstall()
        self.assertFalse(self.desktop.exists())
        self.assertFalse(self.prefix.exists())

    def test_reinstall_preserves_the_original_desktop_backup(self):
        self.desktop.parent.mkdir()
        original = "# Existing custom Steam entry\n" + self.source.read_text()
        self.desktop.write_text(original)
        self.args.replace_desktop = True
        self.install()
        self.install()
        self.uninstall()
        self.assertEqual(self.desktop.read_text(), original)

    def test_existing_user_entry_requires_explicit_replace(self):
        self.desktop.parent.mkdir()
        self.desktop.write_text(self.source.read_text())
        with self.assertRaises(RuntimeError):
            self.install()
        self.assertFalse(self.prefix.exists())

    def test_uninstall_keeps_newer_user_edits(self):
        self.install()
        newer = self.desktop.read_text() + "# User's later edit\n"
        self.desktop.write_text(newer)
        with self.assertRaises(RuntimeError):
            self.uninstall()
        self.assertEqual(self.desktop.read_text(), newer)
        self.assertTrue(self.prefix.exists())


if __name__ == "__main__":
    unittest.main()
