from std.sys.info import simd_width_of


comptime U8Ptr = UnsafePointer[UInt8, AnyOrigin[mut=True]]
comptime U32Ptr = UnsafePointer[UInt32, AnyOrigin[mut=True]]
comptime I32Ptr = UnsafePointer[Int32, AnyOrigin[mut=True]]
comptime I64Ptr = UnsafePointer[Int64, AnyOrigin[mut=True]]
comptime W = simd_width_of[DType.float64]()


def utf8_size(codepoint: Int) -> Int:
    if codepoint <= 0x7F:
        return 1
    if codepoint <= 0x7FF:
        return 2
    if codepoint <= 0xFFFF:
        return 3
    return 4


def write_utf8(dst: U8Ptr, position: Int, codepoint: Int) -> Int:
    if codepoint <= 0x7F:
        dst.store(position, UInt8(codepoint))
        return position + 1
    if codepoint <= 0x7FF:
        dst.store(position, UInt8(0xC0 | (codepoint >> 6)))
        dst.store(position + 1, UInt8(0x80 | (codepoint & 0x3F)))
        return position + 2
    if codepoint <= 0xFFFF:
        dst.store(position, UInt8(0xE0 | (codepoint >> 12)))
        dst.store(position + 1, UInt8(0x80 | ((codepoint >> 6) & 0x3F)))
        dst.store(position + 2, UInt8(0x80 | (codepoint & 0x3F)))
        return position + 3
    dst.store(position, UInt8(0xF0 | (codepoint >> 18)))
    dst.store(position + 1, UInt8(0x80 | ((codepoint >> 12) & 0x3F)))
    dst.store(position + 2, UInt8(0x80 | ((codepoint >> 6) & 0x3F)))
    dst.store(position + 3, UInt8(0x80 | (codepoint & 0x3F)))
    return position + 4


def copy_bytes(
    dst: U8Ptr,
    dst_position: Int,
    source: U8Ptr,
    source_position: Int,
    length: Int,
):
    if length == 1:
        dst.store(dst_position, source.load(source_position))
        return
    if length == 2:
        dst.store(dst_position, source.load(source_position))
        dst.store(dst_position + 1, source.load(source_position + 1))
        return
    if length == 3:
        dst.store(dst_position, source.load(source_position))
        dst.store(dst_position + 1, source.load(source_position + 1))
        dst.store(dst_position + 2, source.load(source_position + 2))
        return

    var index = 0
    while index + W <= length:
        var values = source.load[width=W](source_position + index)
        dst.store(dst_position + index, values)
        index += W
    while index < length:
        dst.store(dst_position + index, source.load(source_position + index))
        index += 1


def measure_ignore_range(
    codepoints: U32Ptr,
    offsets: I32Ptr,
    lengths: U8Ptr,
    table_size: Int,
    start: Int,
    end: Int,
    surrogate_found: I64Ptr,
) -> Int:
    var total = 0
    var index = start
    surrogate_found.store(0, 0)

    while index + W <= end:
        var values = codepoints.load[width=W](index)
        var ascii_mask = values.lt(0x80)
        var ascii_sizes = ascii_mask.select(
            SIMD[DType.uint32, W](1),
            SIMD[DType.uint32, W](0),
        )
        total += Int(ascii_sizes.reduce_add())
        if ascii_mask.reduce_and():
            index += W
            continue
        for lane in range(W):
            var codepoint = Int(values[lane])
            if (
                codepoint >= 0x80
                and codepoint < table_size
                and offsets.load(codepoint) >= 0
            ):
                total += Int(lengths.load(codepoint))
        if (values.ge(0xD800) & values.le(0xDFFF)).reduce_or():
            surrogate_found.store(0, 1)
        index += W

    while index < end:
        var codepoint = Int(codepoints.load(index))
        if codepoint < 0x80:
            total += 1
        elif codepoint < table_size and offsets.load(codepoint) >= 0:
            total += Int(lengths.load(codepoint))
        if codepoint >= 0xD800 and codepoint <= 0xDFFF:
            surrogate_found.store(0, 1)
        index += 1
    return total


@export("mud_measure")
def mud_measure(
    codepoints_addr: Int,
    count: Int,
    offsets_addr: Int,
    lengths_addr: Int,
    table_size: Int,
    mode: Int,
    replacement_length: Int,
    surrogate_found_addr: Int,
) abi("C") -> Int:
    if (
        count < 0
        or table_size < 0
        or replacement_length < 0
        or codepoints_addr == 0
        or offsets_addr == 0
        or lengths_addr == 0
        or surrogate_found_addr == 0
    ):
        return -1
    var codepoints = U32Ptr(unsafe_from_address=codepoints_addr)
    var offsets = I32Ptr(unsafe_from_address=offsets_addr)
    var lengths = U8Ptr(unsafe_from_address=lengths_addr)
    var surrogate_found = I64Ptr(unsafe_from_address=surrogate_found_addr)
    var total = 0
    surrogate_found.store(0, 0)

    if mode == 0:
        return measure_ignore_range(
            codepoints,
            offsets,
            lengths,
            table_size,
            0,
            count,
            surrogate_found,
        )

    for index in range(count):
        var codepoint = Int(codepoints.load(index))
        if codepoint >= 0xD800 and codepoint <= 0xDFFF:
            surrogate_found.store(0, 1)
        if codepoint < 0x80:
            total += 1
        elif codepoint < table_size and offsets.load(codepoint) >= 0:
            total += Int(lengths.load(codepoint))
        elif mode == 1:
            total += replacement_length
        elif mode == 2:
            total += utf8_size(codepoint)
        elif mode == 3:
            return -(index + 1)
        elif mode == 4:
            return -(count + index + 1)
    return total


def transliterate_range(
    codepoints: U32Ptr,
    offsets: I32Ptr,
    lengths: U8Ptr,
    table: U8Ptr,
    dst: U8Ptr,
    table_size: Int,
    mode: Int,
    replacement: U8Ptr,
    replacement_length: Int,
    start: Int,
    end: Int,
    start_position: Int,
    dst_capacity: Int,
) -> Int:
    var position = start_position
    var index = start

    while index + W <= end:
        var codepoint = Int(codepoints.load(index))
        if codepoint < 0x80:
            var values = codepoints.load[width=W](index)
            if values.lt(0x80).reduce_and():
                if position > dst_capacity - W:
                    return -1
                dst.store(position, values.cast[DType.uint8]())
                position += W
                index += W
                continue

            if position >= dst_capacity:
                return -1
            dst.store(position, UInt8(codepoint))
            position += 1
            index += 1
            continue

        if codepoint < table_size:
            var offset = Int(offsets.load(codepoint))
            if offset >= 0:
                var length = Int(lengths.load(codepoint))
                if length > dst_capacity - position:
                    return -1
                copy_bytes(dst, position, table, offset, length)
                position += length
                index += 1
                continue

        if mode == 1:
            if replacement_length > dst_capacity - position:
                return -1
            copy_bytes(dst, position, replacement, 0, replacement_length)
            position += replacement_length
        elif mode == 2:
            if utf8_size(codepoint) > dst_capacity - position:
                return -1
            position = write_utf8(dst, position, codepoint)
        elif mode == 3:
            return -(index + 1)
        index += 1

    while index < end:
        var codepoint = Int(codepoints.load(index))
        if codepoint < 0x80:
            if position >= dst_capacity:
                return -1
            dst.store(position, UInt8(codepoint))
            position += 1
            index += 1
            continue

        if codepoint < table_size:
            var offset = Int(offsets.load(codepoint))
            if offset >= 0:
                var length = Int(lengths.load(codepoint))
                if length > dst_capacity - position:
                    return -1
                copy_bytes(dst, position, table, offset, length)
                position += length
                index += 1
                continue

        if mode == 1:
            if replacement_length > dst_capacity - position:
                return -1
            copy_bytes(dst, position, replacement, 0, replacement_length)
            position += replacement_length
        elif mode == 2:
            if utf8_size(codepoint) > dst_capacity - position:
                return -1
            position = write_utf8(dst, position, codepoint)
        elif mode == 3:
            return -(index + 1)
        index += 1
    return position


@export("mud_transliterate")
def mud_transliterate(
    codepoints_addr: Int,
    count: Int,
    offsets_addr: Int,
    lengths_addr: Int,
    table_addr: Int,
    table_size: Int,
    mode: Int,
    replacement_addr: Int,
    replacement_length: Int,
    dst_addr: Int,
    dst_capacity: Int,
) abi("C") -> Int:
    if (
        count < 0
        or table_size < 0
        or replacement_length < 0
        or dst_capacity < 0
        or codepoints_addr == 0
        or offsets_addr == 0
        or lengths_addr == 0
        or table_addr == 0
        or replacement_addr == 0
        or dst_addr == 0
    ):
        return -1
    var codepoints = U32Ptr(unsafe_from_address=codepoints_addr)
    var offsets = I32Ptr(unsafe_from_address=offsets_addr)
    var lengths = U8Ptr(unsafe_from_address=lengths_addr)
    var table = U8Ptr(unsafe_from_address=table_addr)
    var replacement = U8Ptr(unsafe_from_address=replacement_addr)
    var dst = U8Ptr(unsafe_from_address=dst_addr)
    return transliterate_range(
        codepoints,
        offsets,
        lengths,
        table,
        dst,
        table_size,
        mode,
        replacement,
        replacement_length,
        0,
        count,
        0,
        dst_capacity,
    )
