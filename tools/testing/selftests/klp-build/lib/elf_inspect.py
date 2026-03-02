# SPDX-License-Identifier: GPL-2.0
"""ELF inspection utilities for klp-build test verification.

Provides helpers to inspect livepatch .ko modules and vmlinux for:
- .klp.rela.* section presence (livepatch structure)
- ThinLTO .llvm.<hash> suffixed symbols
- Symbol binding (LOCAL vs GLOBAL)
- Data structure dumping via pahole + readelf (struct field inspection)
"""

import os
import re
import struct as _struct
import subprocess
import tempfile


def get_elf_sections(path):
    """Return list of section names from an ELF file."""
    try:
        result = subprocess.run(
            ["readelf", "-S", "-W", path],
            capture_output=True, text=True, errors="replace", timeout=30,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    sections = []
    for line in result.stdout.splitlines():
        m = re.match(r"\s*\[\s*\d+\]\s+(\S+)", line)
        if m and m.group(1) != "NULL":
            sections.append(m.group(1))
    return sections


def get_klp_rela_sections(ko_path):
    """Return list of .klp.rela.* section names from a livepatch .ko."""
    return [s for s in get_elf_sections(ko_path) if s.startswith(".klp.rela.")]


def nm_grep(obj_path, pattern, timeout=120):
    """
    Run nm on obj_path and grep for pattern. Returns matching lines.

    Uses a shell pipe for efficiency on large files like vmlinux.
    """
    try:
        result = subprocess.run(
            ["sh", "-c", f"nm '{obj_path}' | grep -E '{pattern}'"],
            capture_output=True, text=True, errors="replace", timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def find_llvm_suffixed(obj_path, base_name):
    """
    Find ThinLTO-promoted symbols matching base_name.llvm.<digits>.

    Returns list of (full_name, nm_type) tuples.
    nm_type: 'T'=global text, 't'=local text, etc.
    """
    lines = nm_grep(obj_path, rf"{re.escape(base_name)}\.llvm\.")
    results = []
    pat = re.compile(re.escape(base_name) + r"\.llvm\.\d+")
    for line in lines:
        parts = line.split()
        if len(parts) >= 3:
            addr, nm_type, name = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            nm_type, name = parts[0], parts[1]
        else:
            continue
        if pat.search(name):
            results.append((name, nm_type))
    return results


def get_symbol_nm_type(obj_path, symbol_name):
    """
    Return the nm type character for a symbol ('T'=global, 't'=local, etc).
    Returns None if not found.
    """
    lines = nm_grep(obj_path, rf"\b{re.escape(symbol_name)}\b")
    for line in lines:
        parts = line.split()
        if len(parts) >= 3 and parts[2] == symbol_name:
            return parts[1]
        elif len(parts) == 2 and parts[1] == symbol_name:
            return parts[0]
    return None


def is_thinlto_config(config_path):
    """Check if kernel .config has CONFIG_LTO_CLANG_THIN=y."""
    if not os.path.isfile(config_path):
        return False
    try:
        with open(config_path, "r") as f:
            for line in f:
                if line.strip() == "CONFIG_LTO_CLANG_THIN=y":
                    return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# Data structure inspection via pahole + readelf
#
# Combines pahole (struct layout from DWARF), objcopy (raw section bytes),
# and readelf (relocations, string tables) to produce a complete picture of
# data structure instances in ELF sections.
#
# For fields with inline values (scalars, char arrays), the raw bytes are
# decoded directly.  For pointer fields resolved by relocations (.ko files
# are relocatable objects), the relocation target symbol is resolved, and
# string pointers into .rodata are further resolved to their string content.
# ---------------------------------------------------------------------------


def get_struct_layout(elf_path, struct_name):
    """Parse struct field layout from pahole -C.

    Returns (struct_size, fields) where fields is a list of dicts::

        [{"name": str, "offset": int, "size": int,
          "type": str, "is_pointer": bool}, ...]

    Returns (None, []) if pahole cannot parse the struct.
    """
    try:
        result = subprocess.run(
            ["pahole", "-C", struct_name, elf_path],
            capture_output=True, text=True, errors="replace", timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, []

    if not result.stdout.strip():
        return None, []

    struct_size = None
    fields = []
    in_struct = False
    depth = 0

    for line in result.stdout.splitlines():
        if re.match(rf"struct {re.escape(struct_name)}\s*\{{", line):
            in_struct = True
            depth = 1
            continue
        if not in_struct:
            continue

        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break
        if depth != 1:
            continue

        size_m = re.search(r"/\* size: (\d+)", line)
        if size_m:
            struct_size = int(size_m.group(1))
            continue

        # Match: TYPE FIELD; /* offset size */
        # Also handles bitfields (offset:bitoff) and arrays (FIELD[N]).
        comment_m = re.search(
            r"/\*\s+(\d+)(?::\s*\d+)?\s+(\d+)\s*\*/", line
        )
        if not comment_m:
            continue
        field_offset = int(comment_m.group(1))
        field_size = int(comment_m.group(2))

        decl = line[: comment_m.start()].strip()
        if not decl.endswith(";"):
            continue
        decl = decl.rstrip(";").strip()

        name_m = re.search(r"(\w+)(\[\d+\])?\s*$", decl)
        if not name_m:
            continue
        field_name = name_m.group(1)
        type_str = decl[: name_m.start()].strip()
        is_pointer = "*" in type_str

        fields.append({
            "name": field_name,
            "offset": field_offset,
            "size": field_size,
            "type": type_str,
            "is_pointer": is_pointer,
        })

    return struct_size, fields


def get_section_info(elf_path, section_name):
    """Return (section_size, entry_size) in bytes from readelf -S.

    Returns (None, None) if the section is not found.
    """
    try:
        result = subprocess.run(
            ["readelf", "-S", "-W", elf_path],
            capture_output=True, text=True, errors="replace", timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, None

    for line in result.stdout.splitlines():
        m = re.match(
            r"\s*\[\s*\d+\]\s+(\S+)\s+\S+\s+\S+\s+\S+\s+(\S+)\s+(\S+)",
            line,
        )
        if m and m.group(1) == section_name:
            try:
                return int(m.group(2), 16), int(m.group(3), 16)
            except ValueError:
                return None, None

    return None, None


def extract_section_bytes(elf_path, section_name):
    """Extract raw bytes of a section using objcopy.

    Returns bytes on success, empty bytes on failure.
    """
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["objcopy", "-O", "binary",
             f"--only-section={section_name}",
             elf_path, tmp_path],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            return b""
        with open(tmp_path, "rb") as f:
            return f.read()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return b""
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def get_section_relocations(elf_path, section_name):
    """Parse relocations targeting *section_name*.

    Reads the ``.rela<section_name>`` relocation section via readelf -r.

    Returns ``{byte_offset: {"symbol": str, "addend": int}}``.
    """
    rela_name = f".rela{section_name}"
    try:
        result = subprocess.run(
            ["readelf", "-r", "-W", elf_path],
            capture_output=True, text=True, errors="replace", timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    relocs = {}
    in_section = False

    for line in result.stdout.splitlines():
        if f"'{rela_name}'" in line:
            in_section = True
            continue
        if in_section and line.startswith("Relocation section"):
            break
        if not in_section:
            continue
        if line.strip().startswith("Offset") or not line.strip():
            continue

        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            offset = int(parts[0], 16)
        except ValueError:
            continue

        # Everything from column 5 onward: "sym_name + addend"
        tail = " ".join(parts[4:])
        tail = re.sub(r"\[\.\.\.\]", "", tail)

        add_m = re.search(r"\s+([+-])\s+([0-9a-fA-F]+)\s*$", tail)
        if add_m:
            sign = 1 if add_m.group(1) == "+" else -1
            addend = sign * int(add_m.group(2), 16)
            symbol = tail[: add_m.start()].strip()
        else:
            symbol = tail.strip()
            addend = 0

        relocs[offset] = {"symbol": symbol, "addend": addend}

    return relocs


def get_string_table(elf_path, section=".rodata"):
    """Parse string constants from a section via readelf -p.

    Returns ``{byte_offset: string_value}``.
    """
    try:
        result = subprocess.run(
            ["readelf", "-p", section, elf_path],
            capture_output=True, text=True, errors="replace", timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    strings = {}
    for line in result.stdout.splitlines():
        m = re.match(r"\s+\[\s*([0-9a-fA-F]+)\]\s+(.*)", line)
        if m:
            strings[int(m.group(1), 16)] = m.group(2)
    return strings


def _read_scalar(data, size):
    """Unpack a little-endian unsigned integer from *data*."""
    if size == 8 and len(data) >= 8:
        return _struct.unpack_from("<Q", data)[0]
    if size == 4 and len(data) >= 4:
        return _struct.unpack_from("<I", data)[0]
    if size == 2 and len(data) >= 2:
        return _struct.unpack_from("<H", data)[0]
    if size == 1 and len(data) >= 1:
        return data[0]
    return data


def find_type_source(ko_path, struct_name, kernel_root=None):
    """Find an ELF file that has DWARF info for *struct_name*.

    Tries *ko_path* first (works for GCC-built modules).  If the type
    is not found (common with ThinLTO/Clang .ko files whose DWARF is
    garbled), falls back to ``kernel_root/vmlinux``.

    Returns the path to use as ``type_source``, or None if neither works.
    """
    size, _ = get_struct_layout(ko_path, struct_name)
    if size is not None:
        return None  # ko_path itself works, no override needed

    if kernel_root:
        vmlinux = os.path.join(kernel_root, "vmlinux")
        if os.path.isfile(vmlinux):
            size, _ = get_struct_layout(vmlinux, struct_name)
            if size is not None:
                return vmlinux
    return None


def dump_struct_from_section(elf_path, section_name, struct_name,
                             type_source=None):
    """Build a complete picture of struct instances in an ELF section.

    Combines:

    * ``pahole``  -- struct field layout (names, offsets, sizes, types)
    * ``objcopy`` -- raw section bytes (inline scalar/array values)
    * ``readelf -r`` -- relocations (pointer targets)
    * ``readelf -p`` -- string table (resolve string pointer targets)

    Args:
        elf_path: path to the ELF file containing the section data
        section_name: name of the section to inspect
        struct_name: struct type name for pahole layout
        type_source: optional alternate ELF to read struct layout from
            (useful when elf_path lacks DWARF, e.g. ThinLTO .ko modules
            whose debug info is garbled; pass vmlinux instead)

    Returns a list of instance dicts, one per struct entry::

        [
          {                              # instance 0
            "old_name": {
              "offset": 0, "size": 8, "type": "const char *",
              "is_pointer": True,
              "value": 0,                # raw bytes (0 = reloc-resolved)
              "reloc": {"symbol": ".rodata", "addend": 0x58},
              "resolved": "klp_test_function",
            },
            "new_func": { ... },
            ...
          },
          ...
        ]

    The ``resolved`` key holds the best human-readable representation:

    * Pointer with .rodata reloc  -> the target string
    * Pointer with other reloc    -> ``"symbol"`` or ``"symbol+0xN"``
    * Inline scalar               -> the integer value
    * Inline byte blob            -> the decoded string or hex

    Returns None if the struct or section cannot be parsed.
    Returns an empty list if the section exists but is empty.
    """
    layout_elf = type_source or elf_path
    struct_size, fields = get_struct_layout(layout_elf, struct_name)
    if struct_size is None and type_source is None:
        return None
    if struct_size is None:
        return None

    sec_size, ent_size = get_section_info(elf_path, section_name)
    if sec_size is None or sec_size == 0:
        return []

    raw = extract_section_bytes(elf_path, section_name)
    if not raw:
        return []

    relocs = get_section_relocations(elf_path, section_name)
    strings = get_string_table(elf_path)

    if ent_size and ent_size > 0:
        entry_sz = ent_size
    elif sec_size % struct_size == 0:
        entry_sz = struct_size
    else:
        # Section uses a compact prefix of the struct (e.g. .init.klp_funcs
        # only contains old_name/new_func/old_sympos, not the full 152-byte
        # klp_func).  Find the largest field-boundary size that evenly
        # divides sec_size.
        boundaries = sorted({f["offset"] + f["size"] for f in fields},
                            reverse=True)
        entry_sz = sec_size
        for b in boundaries:
            if b <= sec_size and sec_size % b == 0:
                entry_sz = b
                break

    num_entries = len(raw) // entry_sz if entry_sz > 0 else 0
    instances = []

    def _is_zero(v):
        if isinstance(v, (bytes, bytearray)):
            return not any(v)
        return v == 0

    for i in range(num_entries):
        base = i * entry_sz
        instance = {}

        for field in fields:
            f_off = field["offset"]
            f_size = field["size"]
            if f_off + f_size > entry_sz:
                continue

            abs_off = base + f_off
            chunk = raw[abs_off: abs_off + f_size]
            raw_val = _read_scalar(chunk, f_size)

            finfo = {
                "offset": f_off,
                "size": f_size,
                "type": field["type"],
                "is_pointer": field["is_pointer"],
                "value": raw_val,
                "reloc": None,
                "resolved": None,
            }

            if abs_off in relocs:
                rel = relocs[abs_off]
                finfo["reloc"] = rel
                sym, addend = rel["symbol"], rel["addend"]
                if sym == ".rodata" and addend in strings:
                    finfo["resolved"] = strings[addend]
                elif addend:
                    finfo["resolved"] = f"{sym}+0x{addend:x}"
                else:
                    finfo["resolved"] = sym
            elif isinstance(raw_val, (bytes, bytearray)):
                try:
                    s = raw_val.rstrip(b"\x00").decode("utf-8")
                    if s and all(
                        c.isprintable() or c in "\n\t" for c in s
                    ):
                        finfo["resolved"] = s
                    else:
                        finfo["resolved"] = raw_val.hex()
                except UnicodeDecodeError:
                    finfo["resolved"] = raw_val.hex()
            else:
                finfo["resolved"] = raw_val

            instance[field["name"]] = finfo

        # Kernel arrays (klp_object[], klp_func[], etc.) are terminated by
        # an all-zero sentinel entry.  Stop when every field in the entry
        # is zero-valued with no relocation.
        if all(_is_zero(f["value"]) and f["reloc"] is None
               for f in instance.values()):
            break

        instances.append(instance)

    return instances


def format_struct_dump(instances, struct_name, indent=0,
                       skip_fields=None, skip_byte_counts=False):
    """Format struct instances as human-readable text lines.

    Args:
        instances: list of instance dicts from dump_struct_from_section()
        struct_name: struct type name for the header
        indent: extra leading spaces for all output lines
        skip_fields: set of field names to omit from output
        skip_byte_counts: if True, suppress "(N bytes)" on blob fields

    Returns a list of strings suitable for appending to test results.
    """
    if not instances:
        return [f"{' ' * indent}{struct_name}: (no instances)"]

    pad = " " * indent
    skip = skip_fields or set()
    lines = []

    for i, inst in enumerate(instances):
        lines.append(f"{pad}{struct_name}[{i}]:")
        for fname, finfo in inst.items():
            if fname in skip:
                continue
            resolved = finfo.get("resolved")
            reloc = finfo.get("reloc")
            val = finfo["value"]
            is_ptr = finfo.get("is_pointer", False)

            if reloc:
                sym = reloc["symbol"]
                addend = reloc["addend"]
                target = f"{sym}+0x{addend:x}" if addend else sym
                if resolved and resolved != target:
                    lines.append(
                        f'{pad}  .{fname} = "{resolved}"  '
                        f"[-> {target}]"
                    )
                else:
                    lines.append(f"{pad}  .{fname} -> {target}")
            elif is_ptr and val == 0:
                hint = " (vmlinux)" if fname == "name" else ""
                lines.append(f"{pad}  .{fname} = NULL{hint}")
            elif isinstance(val, (bytes, bytearray)):
                if all(b == 0 for b in val):
                    suffix = "" if skip_byte_counts else \
                        f"  ({len(val)} bytes)"
                    lines.append(f"{pad}  .{fname} = {{0}}{suffix}")
                else:
                    suffix = "" if skip_byte_counts else \
                        f"  ({len(val)} bytes)"
                    lines.append(f"{pad}  .{fname} = {resolved}{suffix}")
            elif isinstance(val, int):
                if val == 0:
                    lines.append(f"{pad}  .{fname} = 0")
                else:
                    lines.append(f"{pad}  .{fname} = 0x{val:x} ({val})")
            elif isinstance(val, str):
                lines.append(f'{pad}  .{fname} = "{val}"')
            else:
                lines.append(f"{pad}  .{fname} = {resolved}")

    return lines


def pahole_dump_section(elf_path, section_name, struct_name):
    """Try pahole's stdin-based pretty-printing on a section.

    Uses the pattern from pahole commits d8079c6, a83313f, 6fb98aa::

        objcopy -O binary --only-section=<section> <elf> <tmpfile>
        pahole -C <struct> <elf> < <tmpfile>

    When the section contains full-size struct entries, pahole produces
    C designated-initializer output with inline values resolved (scalars,
    char arrays).  Pointer fields in relocatable objects show as 0.

    Returns the pretty-printed text as a string, or None if pahole
    cannot produce output (e.g. section smaller than struct size).
    """
    raw = extract_section_bytes(elf_path, section_name)
    if not raw:
        return None

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["pahole", "-C", struct_name, elf_path],
            stdin=open(tmp_path, "rb"),
            capture_output=True, text=True, errors="replace", timeout=30,
        )
        out = result.stdout.strip()
        # pahole prints the struct definition first, then any prettified
        # instances.  If stdin data was consumed, there will be "{" lines
        # after the closing "};".
        end_idx = out.find("};")
        if end_idx < 0:
            return None
        after = out[end_idx + 2:].strip()
        return after if after else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
