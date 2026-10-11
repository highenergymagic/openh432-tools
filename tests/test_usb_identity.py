# SPDX-License-Identifier: MIT
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'console_identity', Path(__file__).resolve().parents[1] /
    'scripts/watch-console.py')
console = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(console)


class UsbIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ports = []

    def add_console(self, index, serial='FM-H432B-MAC-021122334455',
                    product='Braille Sense U2 (Linux)',
                    manufacturer='Fractal Microsystems', vendor='0525',
                    pid='a4a7', interface='02', subclass='02'):
        device = self.root / 'usb' / f'1-{index}'
        child = device / f'1-{index}:1.0'
        child.mkdir(parents=True)
        for name, value in {'product': product, 'manufacturer': manufacturer,
                            'idVendor': vendor, 'idProduct': pid,
                            'serial': serial}.items():
            if value is not None:
                (device / name).write_text(value + '\n')
        (child / 'bInterfaceClass').write_text(interface + '\n')
        (child / 'bInterfaceSubClass').write_text(subclass + '\n')
        entry = self.root / 'class' / f'ttyACM{index}'
        entry.mkdir(parents=True)
        (entry / 'device').symlink_to(child)
        self.ports.append(str(entry))
        return f'/dev/ttyACM{index}'

    def find(self, serial=None):
        with patch.object(console.glob, 'glob', return_value=self.ports):
            return console.find_console(serial)

    def test_current_identity(self):
        expected = self.add_console(0)
        self.assertEqual(self.find(), expected)
        self.assertEqual(self.find('FM-H432B-MAC-021122334455'), expected)
        self.assertIsNone(self.find('FM-H432B-MAC-02AABBCCDDEE'))

    def test_missing_factory_identity_has_no_fabricated_serial(self):
        expected = self.add_console(0, serial=None)
        self.assertEqual(self.find(), expected)
        self.assertIsNone(self.find('H432-RAM-TEST'))

    def test_legacy_installed_image_remains_supported(self):
        expected = self.add_console(0, product='OpenH432-RAM',
                                    serial='H432-RAM-TEST', manufacturer='Linux')
        self.assertEqual(self.find(), expected)

    def test_wrong_device_or_interface_is_never_selected(self):
        for index, changes in enumerate(({'vendor': '1234'}, {'pid': '5678'},
                                        {'interface': 'ff'}, {'subclass': '01'},
                                        {'product': 'unrelated ACM'},
                                        {'manufacturer': 'unrelated'},
                                        {'serial': 'H432-RAM-TEST'},
                                        {'serial': 'FM-H432B-MAC-INVALID'})):
            self.add_console(index, **changes)
        self.assertIsNone(self.find())

    def test_ambiguity_and_explicit_selection(self):
        self.add_console(0)
        expected = self.add_console(1, serial='FM-H432B-MAC-02AABBCCDDEE')
        with self.assertRaises(RuntimeError):
            self.find()
        self.assertEqual(self.find('FM-H432B-MAC-02AABBCCDDEE'), expected)
        self.add_console(2, serial='FM-H432B-MAC-02AABBCCDDEE')
        with self.assertRaises(RuntimeError):
            self.find('FM-H432B-MAC-02AABBCCDDEE')


if __name__ == '__main__':
    unittest.main()
