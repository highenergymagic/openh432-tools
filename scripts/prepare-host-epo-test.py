#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepare a bounded RAM-only diagnostic shell script; never accesses hardware."""
import argparse
import hashlib
import importlib.util
import operator
from functools import reduce
from pathlib import Path
import struct
import time

spec=importlib.util.spec_from_file_location("epo",Path(__file__).with_name("inspect-epo.py"))
epo=importlib.util.module_from_spec(spec)
spec.loader.exec_module(epo)

def sentence(body):
    raw=body.encode("ascii")
    return "$"+body+"*"+format(reduce(operator.xor,raw,0),"02X")

def packets(data, gps_hour):
    meta=epo.inspect(data)
    first=meta["first_gps_hour"]
    if not first <= gps_hour < meta["end_gps_hour_exclusive"]:
        raise ValueError("EPO does not cover requested GPS hour")
    for offset in range(0,len(data),72):
        words=struct.unpack("<18I",data[offset:offset+72])
        if reduce(operator.xor,words[:-1],0)!=words[-1]:
            raise ValueError("EPO record XOR mismatch")
    index=(gps_hour-first)//6
    result=[]
    for sat in range(1,33):
        start=index*2304+(sat-1)*72
        record=data[start:start+72]
        if record[3]==0:
            continue  # Omit uncertain/unavailable records; never fabricate them.
        words=struct.unpack("<18I",record)
        body="PMTK721,"+format(sat,"X")+","+",".join(format(w,"X") for w in words)
        result.append(sentence(body))
    if not result:
        raise ValueError("No nonzero-ID satellite records in current set")
    return first+index*6,result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("file",type=Path)
    p.add_argument("--sha256",required=True)
    p.add_argument("--gps-utc-offset",required=True,type=int)
    p.add_argument("--one-record",action="store_true")
    p.add_argument("--utc",action="store_true",help="Inject target UTC only with recent systemd time-sync marker")
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    if not 0 <= a.gps_utc_offset <= 60:
        p.error("Invalid explicit GPS/UTC offset")
    with a.file.open("rb") as stream:
        data=stream.read(276481)
    if hashlib.sha256(data).hexdigest()!=a.sha256:
        p.error("Input SHA256 mismatch")
    now=int(time.time())
    hour=(now-315964800+a.gps_utc_offset)//3600
    start,frames=packets(data,hour)
    if a.one_record:
        frames=frames[:1]
    begin=start*3600+315964800-a.gps_utc_offset
    end=begin+21600
    shell="""#!/bin/sh
set -eu
test -e /sys/firmware/devicetree/base/hims,gps-query-test
test "$(cat /sys/class/ubi/ubi0/ro_mode)" = 1
test "$(cat /proc/sys/kernel/tainted)" = 0
! pidof gpsd >/dev/null
tty=
for candidate in /sys/class/tty/ttySAC*; do
    case "$(readlink -f "$candidate")" in
        */e2900400.serial/*) test -z "$tty"; tty=$(basename "$candidate");;
    esac
done
test -n "$tty"
! grep -q "console=$tty" /proc/cmdline
now=$(date +%s)
"""
    shell+=f'test "$now" -ge {begin}\ntest "$now" -lt {min(end-60,now+300)}\n'
    shell+='''stty -F "/dev/$tty" 9600 raw -echo -ixon -ixoff -crtscts clocal cread cs8 -parenb -cstopb -hupcl
work=$(mktemp -d /run/h432b-host-epo.XXXXXX)
timeout 45 cat "/dev/$tty" > "$work/nmea.raw" &
reader=$!
trap 'kill "$reader" 2>/dev/null || true' EXIT
sleep 1
kill -0 "$reader"
'''
    if a.utc:
        shell+='''test -e /run/systemd/timesync/synchronized
systemctl is-active --quiet systemd-timesyncd
age=$(( $(date +%s) - $(stat -c %Y /run/systemd/timesync/synchronized) ))
test "$age" -ge 0
test "$age" -lt 3600
body=$(date -u '+PMTK740,%Y,%m,%d,%H,%M,%S')
checksum=$(printf '%s' "$body" | od -An -tu1 | awk '
function bxor(a,b, r,p) {
    r=0; p=1
    while (a || b) {
        if ((a%2)!=(b%2)) r+=p
        a=int(a/2); b=int(b/2); p*=2
    }
    return r
}
{ for (i=1;i<=NF;i++) c=bxor(c,$i) }
END { printf "%02X",c }')
printf '$%s*%s\\r\\n' "$body" "$checksum" > "/dev/$tty"
sleep 1
'''
    for frame in frames:
        shell+=f"printf '%s\\r\\n' '{frame}' > \"/dev/$tty\"\nsleep 1\n"
    shell+='''status=0
wait "$reader" || status=$?
test "$status" = 0 || test "$status" = 124
echo GPS_CAPTURE_BEGIN
cat "$work/nmea.raw"
printf '\\nGPS_CAPTURE_END\\n'
test "$(cat /proc/sys/kernel/tainted)" = 0
echo GPS_HOST_EPO_TRANSPORT_COMPLETED
'''
    with a.output.open("x") as out:
        out.write(shell)
    print(f"Prepared {len(frames)} RAM aiding packets, GPS set hour {start}; no hardware opened.")

if __name__=="__main__":
    main()
