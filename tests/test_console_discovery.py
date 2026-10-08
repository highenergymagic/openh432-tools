# SPDX-License-Identifier: MIT
import errno
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "console_discovery", Path(__file__).resolve().parents[1] /
    "scripts/watch-console.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class ConsoleDiscoveryTests(unittest.TestCase):
    def test_disappearing_usb_attributes_are_not_candidates(self):
        for error in (errno.ENOENT, errno.ENODEV, errno.EACCES):
            with self.subTest(error=error), \
                    patch.object(tool.glob, "glob", return_value=["/sys/class/tty/ttyACM0"]), \
                    patch.object(tool.Path, "resolve", return_value=Path("/usb/device")), \
                    patch.object(tool.Path, "read_text", side_effect=OSError(error, "test")):
                self.assertIsNone(tool.find_console())

    def test_other_io_errors_are_not_hidden(self):
        with patch.object(tool.glob, "glob", return_value=["/sys/class/tty/ttyACM0"]), \
                patch.object(tool.Path, "resolve", return_value=Path("/usb/device")), \
                patch.object(tool.Path, "read_text", side_effect=OSError(errno.EIO, "test")):
            with self.assertRaises(OSError):
                tool.find_console()


if __name__ == "__main__":
    unittest.main()
