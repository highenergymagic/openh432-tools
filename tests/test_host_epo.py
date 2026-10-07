# SPDX-License-Identifier: MIT
import importlib.util
import operator
from functools import reduce
from pathlib import Path
import struct
import unittest
spec=importlib.util.spec_from_file_location("hostepo",Path(__file__).resolve().parents[1]/"scripts/prepare-host-epo-test.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
def sample():
    result=b""
    for sat in range(1,33):
        words=[400000|(sat<<24)]+[0]*16
        words.append(reduce(operator.xor,words,0))
        result+=struct.pack("<18I",*words)
    return result
class HostEpoTests(unittest.TestCase):
    def test_sentence(self):
        self.assertEqual(m.sentence("PMTK607"),"$PMTK607*33")
    def test_current(self):
        start,packets=m.packets(sample(),400001)
        self.assertEqual(start,400000)
        self.assertEqual(len(packets),32)
        self.assertTrue(packets[15].startswith("$PMTK721,10,"))
    def test_outside(self):
        for hour in (399999,400006):
            with self.assertRaises(ValueError): m.packets(sample(),hour)
    def test_corrupt(self):
        b=bytearray(sample()); b[8]^=1
        with self.assertRaises(ValueError): m.packets(b,400000)
    def test_zero_omitted(self):
        b=bytearray(sample())
        words=list(struct.unpack("<18I",b[:72])); words[0]&=0xffffff
        words[-1]=reduce(operator.xor,words[:-1],0)
        b[:72]=struct.pack("<18I",*words)
        self.assertEqual(len(m.packets(b,400000)[1]),31)
if __name__=="__main__":
    unittest.main()
