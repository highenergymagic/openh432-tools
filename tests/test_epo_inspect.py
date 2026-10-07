# SPDX-License-Identifier: MIT
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location("epo",Path(__file__).resolve().parents[1]/"scripts/inspect-epo.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def sample():
    return b"".join((400000+6*(i//32)).to_bytes(3,"little")+bytes([i%32+1])+bytes(68) for i in range(64))

class EpoTests(unittest.TestCase):
    def test_shape(self):
        r=module.inspect(sample())
        self.assertEqual(r["sets"],2)
        self.assertEqual(r["end_gps_hour_exclusive"],400012)
        self.assertFalse(r["upload_qualified"])
    def test_lengths(self):
        for data in (b"",sample()[:-1],bytes(276481)):
            with self.assertRaises(ValueError): module.inspect(data)
    def test_time(self):
        b=bytearray(sample()); b[72]^=1
        with self.assertRaises(ValueError): module.inspect(b)
    def test_satellite(self):
        b=bytearray(sample()); b[3]=33
        with self.assertRaises(ValueError): module.inspect(b)
    def test_zero_id_not_qualified(self):
        b=bytearray(sample()); b[3]=0
        self.assertEqual(module.inspect(b)["zero_id_records"],1)
        self.assertFalse(module.inspect(b)["upload_qualified"])

if __name__=="__main__":
    unittest.main()
