// SPDX-License-Identifier: MIT
//! BrailleSense U2 factory downloader and U2 Open diagnostic client.
//!
//! It uses libusb directly because the U2 recovery identity (0547:2720) is a
//! vendor-specific bulk interface, not CDC ACM. The `probe-shell` command
//! talks to a separately flashed U2 Open U-Boot build over vendor control USB.

use std::{env, ffi::c_void, fs, path::Path, ptr, thread, time::{Duration, Instant}};
mod ram;
mod carrier;

const VID: u16 = 0x0547;
const PID: u16 = 0x2720;
const INTERFACE: i32 = 0;
const EP_OUT: u8 = 0x02;
const EP_IN: u8 = 0x81;
// USBDown.exe writes the little-endian literal 0x44555441: ASCII "ATUD".
const AUTH: &[u8; 4] = b"ATUD";
const PROBE_VID: u16 = 0x1d50;
const PROBE_PID: u16 = 0x6152;

fn probe_shell(ctx: &UsbContext, command: Option<&str>) -> Result<(), String> {
    if command.is_some_and(|c| c.is_empty() || c.len() > 63 || c.as_bytes().contains(&0)) {
        return Err("shell command must contain 1..63 non-NUL bytes".into());
    }
    let mut list = ptr::null();
    let count = unsafe { libusb_get_device_list(ctx.0, &mut list) };
    if count < 0 { return Err(format!("enumerate USB devices: {}", error_name(count as i32))); }
    let mut matches = Vec::new();
    for index in 0..count as usize {
        let candidate = unsafe { *list.add(index) };
        let mut d = DeviceDescriptor::default();
        if unsafe { libusb_get_device_descriptor(candidate, &mut d) } == 0 &&
            (d.id_vendor, d.id_product) == (PROBE_VID, PROBE_PID) {
            matches.push(candidate);
        }
    }
    let mut handle = ptr::null_mut();
    let rc = if matches.len() == 1 { unsafe { libusb_open(matches[0], &mut handle) } } else { -4 };
    unsafe { libusb_free_device_list(list, 1) };
    if rc != 0 { return Err(format!("need exactly one U2 probe (found {}): {}", matches.len(), error_name(rc))); }
    let result = (|| {
        if let Some(command) = command {
        let mut bytes = command.as_bytes().to_vec();
        let n = unsafe { libusb_control_transfer(handle, 0x40, 0x52, 0x3255, 0x4f50,
            bytes.as_mut_ptr(), bytes.len() as u16, 5000) };
        if n != bytes.len() as i32 {
            return Err(format!("send command: {} ({n}/{})", if n < 0 { error_name(n) } else { "short transfer".into() }, bytes.len()));
        }
        }
        let started = Instant::now();
        let status = loop {
            let mut status = [0u8; 12];
            let n = unsafe { libusb_control_transfer(handle, 0xc0, 0x53, 0, 0,
                status.as_mut_ptr(), 12, 60000) };
            if n < 0 { return Err(format!("command status: {}", error_name(n))); }
            if n != 12 || &status[..4] != b"U2CS" {
                return Err(format!("unexpected command status: {:02x?}", &status[..n as usize]));
            }
            if status[4] == 3 { break status; }
            if started.elapsed() > Duration::from_secs(180) { return Err("command still running after 180 seconds; use probe-result, do not retry blindly".into()); }
            thread::sleep(Duration::from_millis(100));
        };
        let size = u16::from_le_bytes([status[8], status[9]]) as usize;
        if size > 4096 { return Err("invalid output size".into()); }
        let mut output = Vec::with_capacity(size);
        while output.len() < size {
            // The S3C EP0 driver mishandles an exact 64-byte data stage.
            let mut slice = [0u8; 63];
            let wanted = (size - output.len()).min(slice.len());
            let n = unsafe { libusb_control_transfer(handle, 0xc0, 0x54,
                output.len() as u16, 0, slice.as_mut_ptr(), wanted as u16, 3000) };
            if n <= 0 { return Err(format!("read command output: {}", if n < 0 { error_name(n) } else { "empty reply".into() })); }
            output.extend_from_slice(&slice[..n as usize]);
        }
        print!("{}", String::from_utf8_lossy(&output));
        if status[5] != 0 { return Err("U-Boot output truncated".into()); }
        let rc = i16::from_le_bytes([status[6], status[7]]);
        if rc != 0 { return Err(format!("U-Boot command failed: {rc}")); }
        Ok(())
    })();
    unsafe { libusb_close(handle) };
    result
}

#[repr(C)]
struct Context(c_void);
#[repr(C)]
struct Device(c_void);
#[repr(C)]
struct Handle(c_void);

#[repr(C)]
#[derive(Default)]
struct DeviceDescriptor {
    b_length: u8,
    b_descriptor_type: u8,
    bcd_usb: u16,
    b_device_class: u8,
    b_device_sub_class: u8,
    b_device_protocol: u8,
    b_max_packet_size0: u8,
    id_vendor: u16,
    id_product: u16,
    bcd_device: u16,
    i_manufacturer: u8,
    i_product: u8,
    i_serial_number: u8,
    b_num_configurations: u8,
}

unsafe extern "C" {
    fn libusb_init(ctx: *mut *mut Context) -> i32;
    fn libusb_exit(ctx: *mut Context);
    fn libusb_get_device_list(ctx: *mut Context, list: *mut *const *mut Device) -> isize;
    fn libusb_free_device_list(list: *const *mut Device, unref_devices: i32);
    fn libusb_ref_device(device: *mut Device) -> *mut Device;
    fn libusb_unref_device(device: *mut Device);
    fn libusb_get_device_descriptor(device: *mut Device, descriptor: *mut DeviceDescriptor) -> i32;
    fn libusb_get_bus_number(device: *mut Device) -> u8;
    fn libusb_get_device_address(device: *mut Device) -> u8;
    fn libusb_open(device: *mut Device, handle: *mut *mut Handle) -> i32;
    fn libusb_close(handle: *mut Handle);
    fn libusb_set_auto_detach_kernel_driver(handle: *mut Handle, enable: i32) -> i32;
    fn libusb_claim_interface(handle: *mut Handle, interface_number: i32) -> i32;
    fn libusb_release_interface(handle: *mut Handle, interface_number: i32) -> i32;
    fn libusb_bulk_transfer(
        handle: *mut Handle,
        endpoint: u8,
        data: *mut u8,
        length: i32,
        transferred: *mut i32,
        timeout_ms: u32,
    ) -> i32;
    fn libusb_control_transfer(handle: *mut Handle, request_type: u8,
        request: u8, value: u16, index: u16, data: *mut u8,
        length: u16, timeout_ms: u32) -> i32;
    fn libusb_error_name(code: i32) -> *const i8;
}

fn wait_probe(ctx: &UsbContext, timeout: Option<Duration>) -> Result<(), String> {
    println!("Waiting for OpenH432 U-Boot USB shell...");
    let started = Instant::now();
    loop {
        if let Some(device) = boot_device(ctx)? {
            if !device.recovery {
                let revision = timed_probe_info(ctx, device)?;
                println!("U-Boot shell found; protocol revision {revision}");
                return Ok(());
            }
        }
        if timeout.is_some_and(|limit| started.elapsed() >= limit) {
            return Err("timed out waiting for U-Boot shell".into());
        }
        thread::sleep(Duration::from_millis(200));
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct BootDevice { bus: u8, address: u8, recovery: bool }

// Owned identity only: never retain a libusb device after freeing its list.
fn boot_device(ctx: &UsbContext) -> Result<Option<BootDevice>, String> {
    let mut list = ptr::null();
    let count = unsafe { libusb_get_device_list(ctx.0, &mut list) };
    if count < 0 { return Err(format!("enumerate USB: {}", error_name(count as i32))); }
    let mut matches = Vec::new();
    for i in 0..count as usize {
        let device = unsafe { *list.add(i) };
        let mut d = DeviceDescriptor::default();
        if unsafe { libusb_get_device_descriptor(device, &mut d) } != 0 { continue; }
        if (d.id_vendor, d.id_product) == (PROBE_VID, PROBE_PID) ||
            (d.id_vendor, d.id_product) == (VID, PID) {
            matches.push(BootDevice {
                bus: unsafe { libusb_get_bus_number(device) },
                address: unsafe { libusb_get_device_address(device) },
                recovery: d.id_vendor == VID,
            });
        }
    }
    unsafe { libusb_free_device_list(list, 1) };
    match matches.len() {
        0 => Ok(None), 1 => Ok(Some(matches[0])),
        _ => Err("multiple U2 devices detected; connect only the one being timed".into()),
    }
}

fn timed_probe_info(ctx: &UsbContext, expected: BootDevice) -> Result<u8, String> {
    let mut list = ptr::null();
    let count = unsafe { libusb_get_device_list(ctx.0, &mut list) };
    if count < 0 { return Err(format!("enumerate USB: {}", error_name(count as i32))); }
    let mut handle = ptr::null_mut();
    let mut rc = -4;
    for i in 0..count as usize {
        let device = unsafe { *list.add(i) };
        if unsafe { libusb_get_bus_number(device) } == expected.bus &&
            unsafe { libusb_get_device_address(device) } == expected.address {
            rc = unsafe { libusb_open(device, &mut handle) };
            break;
        }
    }
    unsafe { libusb_free_device_list(list, 1) };
    if rc != 0 { return Err(format!("open fresh probe: {}", error_name(rc))); }
    let mut info = [0u8; 12];
    let n = unsafe { libusb_control_transfer(handle, 0xc0, 0x51, 0, 0,
        info.as_mut_ptr(), 12, 1000) };
    unsafe { libusb_close(handle) };
    if n != 12 || &info[..7] != b"U2PROBE" {
        return Err(format!("fresh probe not ready: GET_INFO returned {n}"));
    }
    Ok(info[7])
}

fn fresh_boot_device(original: BootDevice, current: BootDevice) -> Result<(), String> {
    if current.recovery { return Err("factory recovery appeared; this is not a plain-Reset boot".into()); }
    if current == original { return Err("old USB identity reappeared; cannot confirm a fresh boot".into()); }
    Ok(())
}

fn time_boot(ctx: &UsbContext, timeout: Duration) -> Result<(), String> {
    let original = boot_device(ctx)?.ok_or("start time-boot while the U2 shell is connected")?;
    if original.recovery { return Err("start time-boot from the U2 shell, not factory recovery".into()); }
    let old_revision = timed_probe_info(ctx, original)?;
    println!("Boot timer armed on bus {:03}/device {:03}, revision {}. Press plain Reset.",
        original.bus, original.address, old_revision);
    println!("Read-only monitor: no reset, flash, or register-write command is sent.");
    let armed = Instant::now();
    let disconnected = loop {
        match boot_device(ctx)? {
            None => break Instant::now(),
            Some(now) if now == original => {},
            Some(_) => return Err("USB changed without an observed disconnect; rerun the timer".into()),
        }
        if armed.elapsed() >= timeout { return Err("timed out waiting for Reset/disconnect".into()); }
        thread::sleep(Duration::from_millis(20));
    };
    println!("USB disconnect observed; timing fresh enumeration and shell readiness...");
    let mut enumerated = None;
    let mut last_error = String::new();
    loop {
        if disconnected.elapsed() >= timeout {
            return Err(format!("boot timed out after {:.3}s; {}", disconnected.elapsed().as_secs_f64(), last_error));
        }
        if let Some(device) = boot_device(ctx)? {
            fresh_boot_device(original, device)?;
            let enum_elapsed = *enumerated.get_or_insert(disconnected.elapsed());
            match timed_probe_info(ctx, device) {
                Ok(revision) => {
                    let info_elapsed = disconnected.elapsed();
                    // An actual read-only command proves the shell works, not just EP0.
                    probe_shell(ctx, Some("version"))?;
                    let shell_elapsed = disconnected.elapsed();
                    println!("Boot time: USB enumerated {:.3}s; GET_INFO {:.3}s; working shell {:.3}s.",
                        enum_elapsed.as_secs_f64(), info_elapsed.as_secs_f64(), shell_elapsed.as_secs_f64());
                    println!("Fresh bus {:03}/device {:03}, revision {}. Host monotonic time since observed USB disconnect; 20ms polling plus USB/host scheduling latency. Not a CPU-entry timestamp.",
                        device.bus, device.address, revision);
                    return Ok(());
                },
                Err(error) => last_error = error,
            }
        }
        thread::sleep(Duration::from_millis(20));
    }
}

#[cfg(test)]
mod boot_timing_tests {
    use super::*;
    const OLD: BootDevice = BootDevice { bus: 3, address: 12, recovery: false };
    #[test] fn old_endpoint_is_not_a_boot() { assert!(fresh_boot_device(OLD, OLD).is_err()); }
    #[test] fn recovery_is_not_a_plain_boot() {
        assert!(fresh_boot_device(OLD, BootDevice { address: 13, recovery: true, ..OLD }).is_err());
    }
    #[test] fn fresh_probe_is_accepted() {
        assert!(fresh_boot_device(OLD, BootDevice { address: 13, ..OLD }).is_ok());
    }
}

fn error_name(code: i32) -> String {
    unsafe {
        let name = libusb_error_name(code);
        if name.is_null() { return format!("libusb error {code}"); }
        std::ffi::CStr::from_ptr(name).to_string_lossy().into_owned()
    }
}

struct UsbContext(*mut Context);
impl Drop for UsbContext { fn drop(&mut self) { unsafe { libusb_exit(self.0) } } }

fn context() -> Result<UsbContext, String> {
    let mut value = ptr::null_mut();
    let rc = unsafe { libusb_init(&mut value) };
    if rc != 0 { Err(format!("libusb_init: {}", error_name(rc))) } else { Ok(UsbContext(value)) }
}

const NOT_FOUND: &str = "no U2 recovery device (0547:2720) found";
struct DeviceRef(*mut Device);
impl Drop for DeviceRef {
    fn drop(&mut self) { unsafe { libusb_unref_device(self.0) } }
}

fn find_u2(ctx: &UsbContext, announce: bool) -> Result<DeviceRef, String> {
    let mut list = ptr::null();
    let count = unsafe { libusb_get_device_list(ctx.0, &mut list) };
    if count < 0 { return Err(format!("enumerate USB: {}", error_name(count as i32))); }
    let mut matches = Vec::new();
    for i in 0..count as usize {
        let device = unsafe { *list.add(i) };
        let mut d = DeviceDescriptor::default();
        if unsafe { libusb_get_device_descriptor(device, &mut d) } == 0
            && (d.id_vendor, d.id_product) == (VID, PID) { matches.push(device); }
    }
    let result = match matches.as_slice() {
        [] => Err(NOT_FOUND.into()),
        [device] => {
            if announce {
                println!("U2 recovery: bus {:03}, device {:03}",
                    unsafe { libusb_get_bus_number(*device) },
                    unsafe { libusb_get_device_address(*device) });
            }
            Ok(DeviceRef(unsafe { libusb_ref_device(*device) }))
        },
        _ => Err("multiple recovery devices found; connect exactly one U2".into()),
    };
    unsafe { libusb_free_device_list(list, 1) };
    result
}

fn recovery_present(ctx: &UsbContext) -> Result<bool, String> {
    match find_u2(ctx, false) {
        Ok(_) => Ok(true),
        Err(e) if e == NOT_FOUND => Ok(false),
        Err(e) => Err(e),
    }
}

fn auth(ctx: &UsbContext) -> Result<(), String> {
    let device = find_u2(ctx, true)?;
    let mut handle = ptr::null_mut();
    let rc = unsafe { libusb_open(device.0, &mut handle) };
    if rc != 0 { return Err(format!("libusb_open: {}", error_name(rc))); }
    let result = (|| {
        // This detaches only a bound kernel interface for this process and the
        // driver is reattached when the handle closes. The observed interface
        // is normally unbound because cdc_subset rejects it.
        let _ = unsafe { libusb_set_auto_detach_kernel_driver(handle, 1) };
        let rc = unsafe { libusb_claim_interface(handle, INTERFACE) };
        if rc != 0 { return Err(format!("claim interface 0: {}", error_name(rc))); }
        let mut sent = 0;
        let rc = unsafe { libusb_bulk_transfer(handle, EP_OUT, AUTH.as_ptr() as *mut u8, 4, &mut sent, 1_000) };
        if rc != 0 || sent != 4 { return Err(format!("bulk OUT ATUD: {} ({} bytes)", error_name(rc), sent)); }
        let mut reply = [0u8; 4];
        let mut received = 0;
        let rc = unsafe { libusb_bulk_transfer(handle, EP_IN, reply.as_mut_ptr(), 4, &mut received, 3_000) };
        if rc != 0 { return Err(format!("bulk IN reply: {}", error_name(rc))); }
        println!("EBOOT reply ({} bytes): {:02x?}", received, &reply[..received as usize]);
        if reply == *b"OKUD" { println!("Verified: ATUD -> OKUD. No flash command was sent."); Ok(()) }
        else { Err("unexpected reply; no flash command was sent".into()) }
    })();
    unsafe { libusb_release_interface(handle, INTERFACE); libusb_close(handle); }
    result
}

fn version(ctx: &UsbContext) -> Result<(), String> {
    let device = find_u2(ctx, true)?;
    let mut handle = ptr::null_mut();
    let rc = unsafe { libusb_open(device.0, &mut handle) };
    if rc != 0 { return Err(format!("libusb_open: {}", error_name(rc))); }
    let result = (|| {
        let _ = unsafe { libusb_set_auto_detach_kernel_driver(handle, 1) };
        let rc = unsafe { libusb_claim_interface(handle, INTERFACE) };
        if rc != 0 { return Err(format!("claim interface 0: {}", error_name(rc))); }
        let exchange = |out: &[u8], in_size: usize, label: &str| -> Result<Vec<u8>, String> {
            let mut sent = 0;
            let rc = unsafe { libusb_bulk_transfer(handle, EP_OUT, out.as_ptr() as *mut u8, out.len() as i32, &mut sent, 1_000) };
            if rc != 0 || sent != out.len() as i32 { return Err(format!("bulk OUT {label}: {} ({} bytes)", error_name(rc), sent)); }
            let mut reply = vec![0u8; in_size];
            let mut received = 0;
            let rc = unsafe { libusb_bulk_transfer(handle, EP_IN, reply.as_mut_ptr(), in_size as i32, &mut received, 3_000) };
            if rc != 0 { return Err(format!("bulk IN {label}: {}", error_name(rc))); }
            reply.truncate(received as usize);
            Ok(reply)
        };
        let hello = exchange(AUTH, 4, "ATUD")?;
        if hello.as_slice() != b"OKUD" { return Err(format!("ATUD returned {:02x?}", hello)); }
        // Dragin V1.25 command 0x0d: a 2048-byte record, with the little-endian
        // command word followed by zeroes.  The vendor transport routine reads
        // a four-byte command acknowledgement, then its caller reads the four
        // bytes displayed as the boot version.
        let mut command = [0u8; 0x800];
        command[..4].copy_from_slice(&13u32.to_le_bytes());
        let acknowledgement = exchange(&command, 4, "EBOOT version request acknowledgement")?;
        let mut version = vec![0u8; 4];
        let mut received = 0;
        let rc = unsafe {
            libusb_bulk_transfer(handle, EP_IN, version.as_mut_ptr(), version.len() as i32,
                &mut received, 3_000)
        };
        if rc != 0 { return Err(format!("read EBOOT version: {}", error_name(rc))); }
        if received != 4 { return Err(format!("read EBOOT version: expected 4 bytes, got {received}")); }
        println!("Version-request acknowledgement: {:02x?}", acknowledgement);
        println!("EBOOT version bytes: {:02x?}", version);
        if version.len() == 4 {
            if version.iter().all(u8::is_ascii_graphic) {
                println!("EBOOT version (ASCII): {}", String::from_utf8_lossy(&version));
            } else {
                println!("EBOOT version (raw): {}.{}.{}.{}", version[0], version[1], version[2], version[3]);
            }
        }
        println!("No erase, download, image transfer, or flash command was sent.");
        Ok(())
    })();
    unsafe { libusb_release_interface(handle, INTERFACE); libusb_close(handle); }
    result
}

fn validate_os_image(path: &Path) -> Result<Vec<u8>, String> {
    use std::io::Read;
    let file = fs::File::open(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let mut image = Vec::new();
    file.take((carrier::MAX_IMAGE + 1) as u64).read_to_end(&mut image)
        .map_err(|e| e.to_string())?;
    carrier::validate(&image)?;
    println!("Validated OpenH432 CE carrier: {} bytes. Compatibility check, not authentication.", image.len());
    Ok(image)
}

fn bulk_out(handle: *mut Handle, bytes: &[u8], label: &str) -> Result<(), String> {
    let mut done = 0;
    let rc = unsafe { libusb_bulk_transfer(handle, EP_OUT, bytes.as_ptr() as *mut u8,
        bytes.len() as i32, &mut done, 5000) };
    if rc != 0 || done != bytes.len() as i32 {
        return Err(format!("{label}: {} ({done}/{} bytes)", error_name(rc), bytes.len()));
    }
    Ok(())
}

fn bulk_in4(handle: *mut Handle, label: &str, timeout_ms: u32) -> Result<[u8; 4], String> {
    let mut bytes = [0u8; 4];
    let mut done = 0;
    let rc = unsafe { libusb_bulk_transfer(handle, EP_IN, bytes.as_mut_ptr(), 4, &mut done, timeout_ms) };
    if rc != 0 || done != 4 { return Err(format!("{label}: {} ({done}/4 bytes)", error_name(rc))); }
    Ok(bytes)
}

fn record(command: u32, address: u32, length: u32, value: u32, payload: &[u8]) -> [u8; 2048] {
    assert!(payload.len() <= 0x7f0);
    let mut bytes = [0u8; 2048];
    for (i, word) in [command, address, length, value].iter().enumerate() {
        bytes[i * 4..i * 4 + 4].copy_from_slice(&word.to_le_bytes());
    }
    bytes[16..16 + payload.len()].copy_from_slice(payload);
    bytes
}

fn commit_staged(handle: *mut Handle, image_bytes: usize) -> Result<(), String> {
    let blocks = image_bytes.div_ceil(0x40000) as u32;
    bulk_out(handle, &record(4, 0x8020_0000, blocks, 0x8020_0000, &[]), "commit OS")?;
    let ack = bulk_in4(handle, "commit acknowledgement", 60000)?;
    if ack != [0; 4] { return Err(format!("unexpected commit reply: {ack:02x?}")); }
    let reported = u32::from_le_bytes(bulk_in4(handle, "NAND block count", 30000)?);
    println!("EBOOT reports {reported} NAND blocks to program");
    if reported == 0 || reported > 512 { return Err(format!("implausible NAND block count: {reported}")); }
    for index in 0..reported {
        let ack = bulk_in4(handle, "NAND block progress", 30000)?;
        if &ack != b"OKUP" { return Err(format!("NAND block {index}: unexpected reply {ack:02x?}")); }
        println!("programmed block {}/{}", index + 1, reported);
    }
    Ok(())
}

fn transfer_os(ctx: &UsbContext, path: &Path, commit: bool) -> Result<(), String> {
    let image = validate_os_image(path)?;
    let device = find_u2(ctx, true)?;
    let mut handle = ptr::null_mut();
    let rc = unsafe { libusb_open(device.0, &mut handle) };
    if rc != 0 { return Err(format!("open recovery device: {}", error_name(rc))); }
    let result = (|| {
        let _ = unsafe { libusb_set_auto_detach_kernel_driver(handle, 1) };
        let rc = unsafe { libusb_claim_interface(handle, INTERFACE) };
        if rc != 0 { return Err(format!("claim interface: {}", error_name(rc))); }
        bulk_out(handle, AUTH, "ATUD")?;
        if &bulk_in4(handle, "OKUD", 3000)? != b"OKUD" { return Err("EBOOT did not reply OKUD".into()); }
        // Official USBDown.exe OS route: select OS (1), staging address
        // 0x80200000, then 2032-byte data chunks with additive checksums.
        let chunks = image.len().div_ceil(0x7f0) as u32;
        bulk_out(handle, &record(7, 1, chunks, 0, &[]), "select OS")?;
        let select_reply = bulk_in4(handle, "select OS acknowledgement", 3000)?;
        if select_reply != [0; 4] { return Err(format!("unexpected select reply: {select_reply:02x?}")); }
        for (index, chunk) in image.chunks(0x7f0).enumerate() {
            let address = 0x8020_0000u32 + (index * 0x7f0) as u32;
            let sum = chunk.iter().fold(0u32, |n, b| n.wrapping_add(*b as u32));
            bulk_out(handle, &record(1, address, chunk.len() as u32, sum, chunk), "OS chunk")?;
            let got = u32::from_le_bytes(bulk_in4(handle, "OS chunk checksum", 5000)?);
            if got != sum { return Err(format!("chunk {index}: expected checksum {sum:08x}, got {got:08x}")); }
            if index % 16 == 0 { println!("staged {}/{} bytes", (index * 0x7f0 + chunk.len()), image.len()); }
        }
        println!("All {} image bytes acknowledged in RAM.", image.len());
        if !commit { return Ok(()); }
        commit_staged(handle, image.len())
    })();
    unsafe { libusb_release_interface(handle, INTERFACE); libusb_close(handle); }
    result
}

fn wait_transfer_os(ctx: &UsbContext, path: &Path, commit: bool,
                    timeout: Option<Duration>) -> Result<(), String> {
    // Validate before waiting so an invalid image cannot trigger an upload.
    validate_os_image(path)?;
    println!("Waiting for U2 recovery USB 0547:2720 (Previous + Reset)...");
    let started = Instant::now();
    loop {
        if recovery_present(ctx)? {
            return transfer_os(ctx, path, commit);
        }
        if timeout.is_some_and(|limit| started.elapsed() >= limit) {
            return Err("timed out waiting for U2 recovery USB".into());
        }
        thread::sleep(Duration::from_millis(200));
    }
}

fn wait_auth(ctx: &UsbContext, timeout: Option<Duration>) -> Result<(), String> {
    println!("Waiting for U2 recovery USB 0547:2720 (Previous + Reset)...");
    let started = Instant::now();
    loop {
        if recovery_present(ctx)? { return auth(ctx); }
        if timeout.is_some_and(|limit| started.elapsed() >= limit) {
            return Err("timed out waiting for U2 recovery USB".into());
        }
        thread::sleep(Duration::from_millis(200));
    }
}

fn wait_version(ctx: &UsbContext, timeout: Option<Duration>) -> Result<(), String> {
    println!("Waiting for U2 recovery USB 0547:2720 (Previous + Reset)...");
    let started = Instant::now();
    loop {
        if recovery_present(ctx)? { return version(ctx); }
        if timeout.is_some_and(|limit| started.elapsed() >= limit) {
            return Err("timed out waiting for U2 recovery USB".into());
        }
        thread::sleep(Duration::from_millis(200));
    }
}

const HELP: &str = "OpenH432 USB tools (Linux host)
Usage: openh432-usb COMMAND [ARGUMENTS]

Offline:
  check-carrier IMAGE                 Validate a BSP CE carrier without USB

Diagnostics (no NAND writes):
  list | auth | version
  wait-auth [SECONDS] | wait-version [SECONDS] | wait-probe [SECONDS]
  time-boot [SECONDS]                 Time plain Reset from a U-Boot shell

Development operations:
  stage-os IMAGE | wait-stage-os IMAGE [SECONDS]
                                      Stage carrier in RAM, NOT execute it
  flash-os IMAGE --confirm-replace-ce
  wait-flash-os IMAGE [SECONDS] --confirm-replace-ce
                                      Replace CE NK slot; read installation guide
  probe-shell 'COMMAND'               Privileged U-Boot command (180s bound)
  probe-result                        Read existing result; send no command
  ram-stage-loader FILE | ram-launch-loader FILE
  ram-upload kernel|dtb|initramfs FILE | ram-status | ram-boot

Waits default to 120 seconds. Connect exactly one device.
Flashing is not a backup or readback verification. There is no restore
or general provisioning command. See docs/installation.md.
";

fn timeout(args: &[String]) -> Result<Duration, String> {
    match args {
        [] => Ok(Duration::from_secs(120)),
        [s] => s.parse::<u64>().ok().filter(|n| *n > 0)
            .map(Duration::from_secs).ok_or("timeout must be positive whole seconds".into()),
        _ => Err("unexpected extra arguments".into()),
    }
}

fn flash_args(args: &[String], wait: bool) -> Result<(String, Duration), String> {
    let mut values = args.to_vec();
    if values.last().map(String::as_str) != Some("--confirm-replace-ce") {
        return Err("NAND write refused: append --confirm-replace-ce after reviewing docs/installation.md".into());
    }
    values.pop();
    let path = values.first().ok_or("missing carrier path")?.clone();
    if !wait && values.len() != 1 { return Err("unexpected flash arguments".into()); }
    Ok((path, timeout(&values[1..])?))
}

fn run_cli(command: &str, args: Vec<String>) -> Result<(), String> {
    match command {
        "check-carrier" => {
            if args.len() != 1 { return Err("check-carrier requires one image path".into()); }
            validate_os_image(Path::new(&args[0]))?;
            Ok(())
        },
        "flash-os" | "wait-flash-os" => {
            let wait = command.starts_with("wait-");
            let (path, limit) = flash_args(&args, wait)?;
            validate_os_image(Path::new(&path))?;
            println!("CONFIRMED: replace CE NK slot. Acknowledgements are not readback verification.");
            let ctx = context()?;
            if wait { wait_transfer_os(&ctx, Path::new(&path), true, Some(limit)) }
            else { transfer_os(&ctx, Path::new(&path), true) }
        },
        "stage-os" | "wait-stage-os" => {
            if args.is_empty() || (command == "stage-os" && args.len() != 1) {
                return Err("stage-os requires a carrier (waiting form accepts timeout)".into());
            }
            let limit = timeout(&args[1..])?;
            validate_os_image(Path::new(&args[0]))?;
            let ctx = context()?;
            if command.starts_with("wait-") {
                wait_transfer_os(&ctx, Path::new(&args[0]), false, Some(limit))
            } else { transfer_os(&ctx, Path::new(&args[0]), false) }
        },
        "probe-shell" => {
            if args.len() != 1 { return Err("supply one quoted U-Boot command".into()); }
            probe_shell(&context()?, Some(&args[0]))
        },
        "probe-result" => {
            if !args.is_empty() { return Err("probe-result takes no arguments".into()); }
            probe_shell(&context()?, None)
        },
        "list" | "auth" | "version" => {
            if !args.is_empty() { return Err("unexpected extra arguments".into()); }
            let ctx = context()?;
            match command {
                "list" => find_u2(&ctx, true).map(|_| ()),
                "auth" => auth(&ctx), _ => version(&ctx),
            }
        },
        "wait-auth" | "wait-version" | "wait-probe" | "time-boot" => {
            let limit = timeout(&args)?;
            let ctx = context()?;
            match command {
                "wait-auth" => wait_auth(&ctx, Some(limit)),
                "wait-version" => wait_version(&ctx, Some(limit)),
                "wait-probe" => wait_probe(&ctx, Some(limit)),
                _ => time_boot(&ctx, limit),
            }
        },
        name if name.starts_with("ram-") => ram::dispatch(&context()?, name, args),
        _ => Err("unknown command; use --help".into()),
    }
}

fn main() {
    let mut args = env::args().skip(1);
    let command = args.next().unwrap_or_else(|| "--help".into());
    if ["--help", "help", "-h"].contains(&command.as_str()) { print!("{HELP}"); return; }
    if let Err(error) = run_cli(&command, args.collect()) {
        eprintln!("Error: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod cli_tests {
    use super::*;
    #[test] fn write_requires_confirmation() {
        assert!(flash_args(&["image".into()], false).is_err());
        assert!(flash_args(&["image".into(), "--confirm-replace-ce".into()], false).is_ok());
        assert!(flash_args(&["image".into(), "oops".into(), "--confirm-replace-ce".into()], false).is_err());
    }
    #[test] fn timeouts_are_strict() {
        assert_eq!(timeout(&[]).unwrap(), Duration::from_secs(120));
        for v in ["0", "-1", "oops"] { assert!(timeout(&[v.into()]).is_err()); }
        assert!(timeout(&["1".into(), "2".into()]).is_err());
    }
}
