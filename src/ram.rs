// SPDX-License-Identifier: MIT
//! RAM-only Linux bring-up. Never sends factory/NAND protocol commands.
use super::*;

const ADDRESSES: [u32; 3] = [0x42000000, 0x44000000, 0x44400000];
const LIMITS: [usize; 3] = [32 << 20, 1 << 20, 16 << 20];
const LOADER: u32 = 0x46000000;

pub fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = !0u32;
    for &byte in bytes {
        crc ^= byte as u32;
        for _ in 0..8 { crc = (crc >> 1) ^ (0xedb88320 & 0u32.wrapping_sub(crc & 1)); }
    }
    !crc
}

struct Probe(*mut Handle);
impl Drop for Probe {
    fn drop(&mut self) { unsafe { libusb_release_interface(self.0, 0); libusb_close(self.0); } }
}
impl Probe {
    fn open(ctx: &UsbContext) -> Result<Self, String> {
        let mut list = ptr::null();
        let count = unsafe { libusb_get_device_list(ctx.0, &mut list) };
        if count < 0 { return Err(error_name(count as i32)); }
        let mut matches = Vec::new();
        for i in 0..count as usize {
            let device = unsafe { *list.add(i) };
            let mut d = DeviceDescriptor::default();
            if unsafe { libusb_get_device_descriptor(device, &mut d) } == 0 &&
                (d.id_vendor, d.id_product) == (PROBE_VID, PROBE_PID) { matches.push(device); }
        }
        let mut handle = ptr::null_mut();
        let rc = if matches.len() == 1 { unsafe { libusb_open(matches[0], &mut handle) } } else { -4 };
        unsafe { libusb_free_device_list(list, 1); }
        if rc != 0 { return Err(format!("need exactly one U2 shell (found {}): {}", matches.len(), error_name(rc))); }
        let rc = unsafe { libusb_claim_interface(handle, 0) };
        if rc != 0 { unsafe { libusb_close(handle); } return Err(format!("claim U2: {}", error_name(rc))); }
        Ok(Self(handle))
    }
    fn revision(&self) -> Result<u8, String> {
        let mut data = [0; 12];
        self.control(0xc0, 0x51, 0, 0, &mut data)?;
        if &data[..7] != b"U2PROBE" { return Err("wrong USB firmware signature".into()); }
        Ok(data[7])
    }
    fn control(&self, kind: u8, req: u8, value: u16, index: u16, data: &mut [u8]) -> Result<(), String> {
        let n = unsafe { libusb_control_transfer(self.0, kind, req, value, index,
            data.as_mut_ptr(), data.len() as u16, 10000) };
        if n != data.len() as i32 { return Err(format!("USB request {req:02x}: {n}/{} ({})", data.len(), error_name(n))); }
        Ok(())
    }
    fn send_command(&self, command: &str) -> Result<(), String> {
        if command.is_empty() || command.len() > 63 || command.contains('\0') { return Err("bad shell command".into()); }
        self.control(0x40, 0x52, 0x3255, 0x4f50, &mut command.as_bytes().to_vec())
    }
    fn shell(&self, command: &str) -> Result<String, String> {
        self.send_command(command)?;
        let deadline = Instant::now() + Duration::from_secs(30);
        let status = loop {
            let mut s = [0; 12];
            self.control(0xc0, 0x53, 0, 0, &mut s)?;
            if &s[..4] != b"U2CS" { return Err("bad shell status".into()); }
            if s[4] == 3 { break s; }
            if Instant::now() > deadline { return Err("shell timeout".into()); }
            thread::sleep(Duration::from_millis(1));
        };
        let size = u16::from_le_bytes([status[8], status[9]]) as usize;
        if size > 4096 || status[5] != 0 { return Err("invalid/truncated shell output".into()); }
        let mut output = vec![0; size];
        for (i, slice) in output.chunks_mut(63).enumerate() { self.control(0xc0, 0x54, (i*63) as u16, 0, slice)?; }
        let output = String::from_utf8_lossy(&output).into_owned();
        let rc = i16::from_le_bytes([status[6], status[7]]);
        if rc != 0 { return Err(format!("shell failed {rc}: {output}")); }
        Ok(output)
    }
    fn status(&self, id: usize) -> Result<RamStatus, String> {
        let mut b = [0; 24];
        self.control(0xc0, 0x57, 0, id as u16, &mut b)?;
        RamStatus::parse(&b, id)
    }
}

#[derive(Debug)]
struct RamStatus { state: u8, size: usize, received: usize, expected: u32, actual: u32 }
impl RamStatus {
    fn parse(b: &[u8], id: usize) -> Result<Self, String> {
        if b.len() != 24 || &b[..4] != b"U2RM" || b[5] as usize != id || b[4] > 4 {
            return Err("invalid RAM status".into());
        }
        let word = |n| u32::from_le_bytes(b[n..n+4].try_into().unwrap());
        Ok(Self { state:b[4], size:word(8) as usize, received:word(12) as usize, expected:word(16), actual:word(20) })
    }
    fn verified(&self, size: usize, crc: u32) -> bool {
        self.state == 3 && self.size == size && self.received == size && self.expected == crc && self.actual == crc
    }
}

fn read_slot(id: usize, path: &Path) -> Result<Vec<u8>, String> {
    let n = fs::metadata(path).map_err(|e| e.to_string())?.len();
    if id >= 3 || n == 0 || n > LIMITS[id] as u64 { return Err("file exceeds fixed RAM slot or is empty".into()); }
    let data = fs::read(path).map_err(|e| e.to_string())?;
    if data.is_empty() || data.len() > LIMITS[id] { return Err("file changed size while reading".into()); }
    Ok(data)
}

fn upload(p: &Probe, id: usize, data: &[u8]) -> Result<(), String> {
    if p.revision()? != 52 { return Err("RAM upload requires revision 52".into()); }
    let crc = crc32(data);
    let mut begin = Vec::from((data.len() as u32).to_le_bytes());
    begin.extend_from_slice(&crc.to_le_bytes());
    p.control(0x40, 0x55, 0x3255, id as u16, &mut begin)?;
    let start = Instant::now();
    for (i, bytes) in data.chunks(56).enumerate() {
        let mut packet = Vec::from(((i*56) as u32).to_le_bytes());
        packet.extend_from_slice(bytes);
        p.control(0x40, 0x56, 0x3255, id as u16, &mut packet)?;
        if i % 4096 == 0 { println!("RAM slot {id} at {:08x}: {}/{} bytes", ADDRESSES[id], i*56+bytes.len(), data.len()); }
    }
    p.control(0x40, 0x58, 0x3255, id as u16, &mut [])?;
    loop {
        let status = p.status(id)?;
        if status.verified(data.len(), crc) { break; }
        if status.state != 2 || start.elapsed() > Duration::from_secs(1800) { return Err(format!("RAM verify failed: {status:?}")); }
        thread::sleep(Duration::from_millis(10));
    }
    println!("Verified slot {id}: {} bytes, CRC32 {crc:08x}, {:.3}s. Not booted; no NAND writes.", data.len(), start.elapsed().as_secs_f64());
    Ok(())
}

fn loader_commands(data: &[u8]) -> Result<Vec<String>, String> {
    if data.len() < 68 || data.len() > 1 << 20 || data.len() % 4 != 0 || data[3] != 0xea ||
        u32::from_le_bytes(data[0x40..0x44].try_into().unwrap()) != LOADER {
        return Err("expected aligned ARM U-Boot binary linked at 46000000 (68B..1MiB)".into());
    }
    Ok(data.chunks(8).enumerate().map(|(i, pair)| {
        pair.chunks(4).enumerate().map(|(j, word)| format!("mw.l {:08x} {:08x}",
            LOADER + (i*8+j*4) as u32, u32::from_le_bytes(word.try_into().unwrap())))
            .collect::<Vec<_>>().join(";")
    }).collect())
}

fn stage_loader(p: &Probe, data: &[u8]) -> Result<(), String> {
    let commands = loader_commands(data)?;
    if p.revision()? != 51 { return Err("bootstrap requires known revision 51 shell".into()); }
    let started = Instant::now();
    for (i, command) in commands.iter().enumerate() {
        p.shell(command)?;
        if i % 1024 == 0 { println!("Loader RAM staging: {}/{} bytes", (i*8+8).min(data.len()), data.len()); }
    }
    let expected = crc32(data);
    let output = p.shell(&format!("crc32 {LOADER:08x} {:x}", data.len()))?;
    let got = output.split_whitespace().last().and_then(|s| u32::from_str_radix(s, 16).ok());
    if got != Some(expected) { return Err(format!("loader CRC mismatch: expected {expected:08x}, target {output}")); }
    println!("Loader staged and verified: {} bytes, CRC32 {expected:08x}, {:.3}s. NOT executed. NAND unchanged.", data.len(), started.elapsed().as_secs_f64());
    Ok(())
}

pub fn dispatch(ctx: &UsbContext, cmd: &str, args: Vec<String>) -> Result<(), String> {
    match (cmd, args.as_slice()) {
        ("ram-stage-loader", [file]) => {
            let data = read_slot(1, Path::new(file))?;
            stage_loader(&Probe::open(ctx)?, &data)
        },
        ("ram-launch-loader", [file]) => {
            let data = read_slot(1, Path::new(file))?;
            loader_commands(&data)?;
            let p = Probe::open(ctx)?;
            if p.revision()? != 51 { return Err("launch requires revision 51".into()); }
            let expected = crc32(&data);
            let output = p.shell(&format!("crc32 {LOADER:08x} {:x}", data.len()))?;
            if output.split_whitespace().last().and_then(|s| u32::from_str_radix(s,16).ok()) != Some(expected) {
                return Err("RAM loader CRC differs; stage this exact binary first".into());
            }
            p.send_command("go 46000000")?;
            println!("RAM loader launch requested. This is NOT confirmation of successful boot. Plain Reset boots the installed NAND image; do not assume it remains the bootstrap.");
            Ok(())
        },
        ("ram-upload", [slot, file]) => {
            let id = match slot.as_str() { "kernel" => 0, "dtb" => 1, "initramfs" => 2, _ => return Err("slot must be kernel, dtb or initramfs".into()) };
            let data = read_slot(id, Path::new(file))?;
            upload(&Probe::open(ctx)?, id, &data)
        },
        ("ram-status", []) => {
            let p = Probe::open(ctx)?;
            if p.revision()? != 52 { return Err("RAM status requires rev52".into()); }
            for i in 0..3 { println!("slot {i}: {:?}", p.status(i)?); }
            Ok(())
        },
        ("ram-boot", []) => {
            let p = Probe::open(ctx)?;
            if p.revision()? != 52 { return Err("RAM boot requires rev52".into()); }
            for i in 0..3 {
                let s = p.status(i)?;
                if s.size == 0 || s.size > LIMITS[i] || !s.verified(s.size, s.expected) { return Err(format!("slot {i} is not verified")); }
            }
            p.send_command("u2linux")?;
            println!("Linux handoff requested; kernel boot is not yet confirmed. No NAND writes.");
            Ok(())
        },
        _ => Err("usage: ram-stage-loader FILE | ram-launch-loader FILE | ram-upload kernel|dtb|initramfs FILE | ram-status | ram-boot".into())
    }
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn standard_crc() { assert_eq!(crc32(b"123456789"), 0xcbf43926); assert_eq!(crc32(b""),0); }
    #[test] fn loader_alignment_and_bounds() {
        assert!(loader_commands(&[0;64]).is_err());
        let mut b=vec![0;68]; b[3]=0xea; b[0x40..0x44].copy_from_slice(&LOADER.to_le_bytes());
        let c=loader_commands(&b).unwrap();
        assert_eq!(c.len(),9); assert!(c.iter().all(|s| s.len()<=63));
        assert_eq!(c.last().unwrap(),"mw.l 46000040 46000000");
        b.push(0); assert!(loader_commands(&b).is_err());
    }
    #[test] fn status_requires_all_fields() {
        let s=RamStatus {state:3,size:4,received:4,expected:7,actual:7};
        assert!(s.verified(4,7)); assert!(!s.verified(5,7)); assert!(!s.verified(4,8));
        assert!(RamStatus::parse(&[0;24],0).is_err());
    }
}
