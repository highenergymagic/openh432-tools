#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Capture raw NAND+OOB through the exact RAM USB console. Read-only on NAND.
Keep captured data private. Framed base64, remote SHA256, gzip CRC and exact size
must all pass; interrupted captures are kept with a .partial suffix.
"""
import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import select
import shlex
import termios
import time

spec=importlib.util.spec_from_file_location("console",Path(__file__).with_name("watch-console.py"))
console=importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)


REGIONS={
 "raw":("u2-nand-raw-readonly",0,512<<20),
 "boot":("factory-boot",0,4<<20),
 "scratch":("nand-scratch",0x1fee0000,131072),
 "ubi":("linux-ubi",4<<20,507<<20),
 "tail":("bbt-reserved",511<<20,1<<20),
}

def capture(fd,start,length,path,timeout,region="raw"):
    name,base,size=REGIONS[region]
    token=secrets.token_hex(12)
    tag=("U2D_"+token).encode()
    # A private tmpfs directory; no writes to MTD or persistent filesystems.
    shell=f"""set -eu
dev=
for entry in /sys/class/mtd/mtd[0-9]*; do
 test -f "$entry/name" || continue
 if test "$(cat "$entry/name")" = {name}; then
  test -z "$dev"
  dev=/dev/$(basename "$entry")
  test "$(cat "$entry/size")" = {size}
  test "$(cat "$entry/writesize")" = 2048
  test "$(cat "$entry/oobsize")" = 64
 fi
done
test -n "$dev"
dumpdir=$(mktemp -d /tmp/u2-nand-XXXXXX)
trap 'rm -f "$dumpdir/raw" "$dumpdir/raw.gz"; rmdir "$dumpdir"' EXIT
nanddump -q -n -o --bb=dumpbad -s {start-base} -l {length} -f "$dumpdir/raw" "$dev"
test "$(stat -c %s "$dumpdir/raw")" = {length//2048*2112}
gzip -n "$dumpdir/raw"
printf '\\n{token}_HASH '
sha256sum "$dumpdir/raw.gz"
base64 -w 64 "$dumpdir/raw.gz" | sed 's/^/U2D_{token} /'
"""
    command="sh -c "+shlex.quote(shell)+f"; printf '\\n{token}_END=%s\\n' \"$?\"\n"
    deadline=time.monotonic()+timeout
    console.write_all(fd,command.encode(),deadline)
    digest=None
    buf=b""
    partial=path.with_suffix(path.suffix+".partial")
    h=hashlib.sha256()
    with os.fdopen(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
        while time.monotonic()<deadline:
            if not select.select([fd],[],[],0.1)[0]:
                continue
            data=os.read(fd,65536)
            if not data:
                raise RuntimeError("console disconnected")
            buf+=data
            while b"\n" in buf:
                line,buf=buf.split(b"\n",1)
                line=line.rstrip(b"\r")
                if line.startswith(tag+b" "):
                    block=base64.b64decode(line[len(tag)+1:],validate=True)
                    out.write(block)
                    h.update(block)
                elif line.startswith((token+"_HASH ").encode()):
                    digest=line.split()[1].decode()
                elif line.startswith((token+"_END=").encode()):
                    if line!=(token+"_END=0").encode():
                        raise RuntimeError(line.decode())
                    out.flush()
                    if not digest or h.hexdigest()!=digest:
                        raise RuntimeError("remote/host SHA256 mismatch")
                    with gzip.open(partial,"rb") as gz:
                        raw=gz.read(length//2048*2112+1)
                    if len(raw)!=length//2048*2112:
                        raise RuntimeError("unexpected raw+OOB size")
                    if path.exists():
                        raise FileExistsError(path)
                    os.link(partial, path)  # Atomic no-clobber publication on the same filesystem.
                    partial.unlink()
                    return {"offset":start,"length":length,"raw_oob_bytes":len(raw),
                            "gzip_sha256":digest,
                            "raw_oob_sha256":hashlib.sha256(raw).hexdigest()}
        raise TimeoutError("NAND slice timed out")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--region",choices=REGIONS,default="raw")
    p.add_argument("--start",type=lambda x:int(x,0))
    p.add_argument("--length",type=lambda x:int(x,0))
    p.add_argument("--chunk",type=lambda x:int(x,0),default=4<<20)
    p.add_argument("--timeout",type=int,default=180)
    a=p.parse_args()
    _,base,size=REGIONS[a.region]
    if a.start is None: a.start=base
    if a.length is None: a.length=size
    if (a.start<base or a.length<=0 or a.start+a.length>base+size or
        a.start%131072 or a.length%131072 or
        a.chunk<131072 or a.chunk>16<<20 or a.chunk%131072):
        p.error("bounded eraseblock-aligned NAND range required")
    if a.timeout <= 0: p.error("timeout must be positive")
    a.output.mkdir(parents=True,exist_ok=True,mode=0o700)
    dev=console.find_console()
    if not dev:
        raise RuntimeError("exact OpenH432-RAM console absent")
    fd=os.open(dev,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
    attrs=termios.tcgetattr(fd)
    attrs[0]=attrs[1]=attrs[3]=0
    attrs[2]=termios.CS8|termios.CREAD|termios.CLOCAL
    attrs[4]=attrs[5]=termios.B115200
    attrs[6][termios.VMIN]=attrs[6][termios.VTIME]=0
    termios.tcsetattr(fd,termios.TCSANOW,attrs)
    try:
        for start in range(a.start,a.start+a.length,a.chunk):
            length=min(a.chunk,a.start+a.length-start)
            file=a.output/f"{start:08x}.raw.gz"
            # Never assume an existing partial/evidence file is verified.
            if file.exists() or file.with_suffix(".json").exists() or file.with_suffix(file.suffix+".partial").exists():
                raise FileExistsError(file)
            t=time.monotonic()
            result=capture(fd,start,length,file,a.timeout,a.region)
            with os.fdopen(os.open(file.with_suffix(".json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
                json.dump(result,stream,indent=2)
                stream.write("\n")
            print(f"{start:08x}: {length} data bytes + OOB verified in "
                  f"{time.monotonic()-t:.2f}s, gzip={file.stat().st_size}",flush=True)
    finally:
        os.close(fd)


if __name__=="__main__":
    main()
