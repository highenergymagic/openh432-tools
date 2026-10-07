# SPDX-License-Identifier: MIT
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location("gps_capture",Path(__file__).resolve().parents[1]/"scripts/check-gps-capture.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def frame(body):
    check=0
    for char in body:
        check ^= char
    return b"$"+body+b"*"+format(check,"02X").encode()+b"\r\n"

class GpsCaptureTests(unittest.TestCase):
    def test_valid_void_and_fix(self):
        data=b"GPS_CAPTURE_BEGIN\n"+frame(b"GPRMC,,V,,,,,,,,,")+frame(b"GPGGA,,,,,,1,04,,,,,,")+b"GPS_CAPTURE_END"
        result=module.summarize(data)
        self.assertEqual(result["valid_sentences"],2)
        self.assertEqual(result["fix_indicating_sentences"],1)
        self.assertNotIn("coordinates",result)
    def test_bad_checksum(self):
        data=b"GPS_CAPTURE_BEGIN\n$GPRMC,,V*00\nGPS_CAPTURE_END"
        self.assertEqual(module.summarize(data)["invalid_checksums_or_ids"],1)
    def test_ignore_unframed_data(self):
        self.assertEqual(module.summarize(frame(b"GPRMC,,A"))["valid_sentences"],0)
    def test_truncated_sentence(self):
        data=b"GPS_CAPTURE_BEGIN\n$GPRMC,,V*\nGPS_CAPTURE_END"
        self.assertEqual(module.summarize(data)["valid_sentences"],0)

    def test_firmware_reply(self):
        body=b"PMTK705,AXN_TEST,0001,TEST,1.0"
        data=b"GPS_CAPTURE_BEGIN\n"+frame(body)+b"GPS_CAPTURE_END"
        result=module.summarize(data)
        self.assertEqual(result["firmware_releases"],[["AXN_TEST","0001","TEST","1.0"]])
        self.assertEqual(module.summarize(frame(body))["firmware_releases"],[])
    def test_corrupt_firmware_reply(self):
        data=b"GPS_CAPTURE_BEGIN\n$PMTK705,AXN_TEST*00\nGPS_CAPTURE_END"
        self.assertEqual(module.summarize(data)["firmware_releases"],[])
    def test_ack_and_echo_markers(self):
        data=b"echo GPS_CAPTURE_BEGIN\nignored\necho GPS_CAPTURE_END\n"
        data+=b"GPS_CAPTURE_BEGIN\n"+frame(b"PMTK001,721,3")+b"GPS_CAPTURE_END"
        result=module.summarize(data)
        self.assertEqual(result["capture_blocks"],1)
        self.assertEqual(result["command_ack_counts"],{"721:3":1})
if __name__=="__main__":
    unittest.main()
